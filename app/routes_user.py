"""Signed-in routes: onboarding wizard, dashboard, feedback, click-through
logging, settings."""
from __future__ import annotations

import json
import os
import re
import threading

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app import db, openalex
from app.web import render, get_user, login_redirect

router = APIRouter()

MIN_SEEDS = 3
MIN_STATEMENT_CHARS = 40


def _user_flavors(user) -> list[dict]:
    """Structured topic entries saved during onboarding/settings."""
    try:
        return json.loads(user["interest_flavors_json"] or "[]")
    except (ValueError, TypeError):
        return []


def _user_negatives(user) -> list[str]:
    try:
        return json.loads(user["interest_negatives_json"] or "[]")
    except (ValueError, TypeError):
        return []


def _parse_flavor_forms(keys, descs, cores) -> list[dict]:
    """Parallel form arrays -> [{name, description, core}] (blank rows dropped)."""
    out = []
    for i, (name, desc) in enumerate(zip(keys, descs)):
        name, desc = name.strip()[:80], desc.strip()[:600]
        core = i < len(cores) and cores[i] == "1"
        if name or desc:
            out.append({"name": name, "description": desc, "core": core})
    return out


def _compose_profile_and_finish(con, user):
    """Synchronous, network-free part of finishing onboarding (deterministic:
    onboarding never blocks on an API). Structured fields compose the judge
    profile directly; a legacy user with only a paragraph still gets the
    fallback profile. Enrichment (concepts, embeddings, LLM flavor drafting
    for fallback profiles) happens in the background / nightly stage."""
    from pipeline.build_profile import structured_profile, bump_version
    prof = structured_profile(user["interest_statement"] or "",
                              _user_flavors(user), _user_negatives(user))
    existing = db.get_profile(con, user["id"])
    if not existing:
        db.save_profile(con, user["id"], prof, bump_version())
    else:
        changed = any(existing.get(k) != prof[k]
                      for k in ("core_statement", "flavors", "negatives"))
        if changed:
            existing.update({k: prof[k] for k in
                             ("core_statement", "flavors", "fit_rule", "negatives")})
            db.save_profile(con, user["id"], existing, bump_version())
    con.execute("UPDATE users SET onboarded_at=COALESCE(onboarded_at, ?) WHERE id=?",
                (db.now(), user["id"]))
    con.commit()


def _spawn_profile_build(uid: int):
    """Best-effort background enrichment (concepts, LLM flavors, embeddings).
    PROFILE_BUILD=off disables (tests); the nightly stage retries regardless."""
    if os.environ.get("PROFILE_BUILD", "thread") == "off":
        return

    def work():
        try:
            from pipeline.build_profile import build
            con = db.connect()
            try:
                user = db.get_user(con, uid)
                if user:
                    build(con, user)
            finally:
                con.close()
        except Exception:
            import logging
            logging.getLogger("papersradar.web").exception("bg profile build failed")

    threading.Thread(target=work, daemon=True).start()


# --- onboarding --------------------------------------------------------------

N_STEPS = 6                       # about, describe, topics, negatives, seeds, review
SEEDS_STEP = 5


def _onboarding_ctx(con, user, step: int, error: str = "", notice: str = "",
                    zotero_preview: bool = False):
    from app.routes_zotero import link_ctx
    seeds = con.execute("SELECT * FROM seeds WHERE user_id=? ORDER BY id",
                        (user["id"],)).fetchall()
    ctx = {"step": step, "n_steps": N_STEPS, "seeds": seeds, "min_seeds": MIN_SEEDS,
           "flavors": _user_flavors(user), "negatives": _user_negatives(user),
           "error": error, "notice": notice, "znext": f"/onboarding?step={step}"}
    ctx.update(link_ctx(con, user["id"],
                        want_preview=zotero_preview and step == SEEDS_STEP))
    return ctx


def _default_step(user, n_seeds: int) -> int:
    if not user["name"]:
        return 1
    if not user["interest_statement"]:
        return 2
    if not _user_flavors(user):
        return 3
    return SEEDS_STEP if n_seeds < MIN_SEEDS else N_STEPS


@router.get("/onboarding")
def onboarding(request: Request, step: int = 0, zerr: str = "", znotice: str = "",
               zpreview: str = "", welcome: str = ""):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        n = con.execute("SELECT COUNT(*) c FROM seeds WHERE user_id=?",
                        (user["id"],)).fetchone()["c"]
        step = step if 1 <= step <= N_STEPS else _default_step(user, n)
        notice = znotice
        if welcome == "1" and not notice:
            notice = ("You're signed in — you'll stay signed in on this device "
                      "for 90 days.")
        return render(request, "onboarding.html",
                      _onboarding_ctx(con, user, step, error=zerr, notice=notice,
                                      zotero_preview=zpreview == "1"))
    finally:
        con.close()


@router.post("/onboarding/about")
def onboarding_about(request: Request, name: str = Form(""),
                     frequency: str = Form("daily")):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        name = name.strip()[:120]
        if not name:
            return render(request, "onboarding.html",
                          _onboarding_ctx(con, user, 1, error="Please tell us your name."),
                          status_code=400)
        if frequency not in ("daily", "weekly", "none"):
            frequency = "daily"
        con.execute("UPDATE users SET name=?, frequency=? WHERE id=?",
                    (name, frequency, user["id"]))
        con.commit()
        return RedirectResponse("/onboarding?step=2", status_code=303)
    finally:
        con.close()


@router.post("/onboarding/interests")
def onboarding_interests(request: Request, statement: str = Form("")):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        statement = statement.strip()[:4000]
        if len(statement) < MIN_STATEMENT_CHARS:
            return render(request, "onboarding.html",
                          _onboarding_ctx(con, user, 2,
                                          error="A few sentences helps the judge a lot — "
                                                "please write at least a short paragraph."),
                          status_code=400)
        con.execute("UPDATE users SET interest_statement=? WHERE id=?",
                    (statement, user["id"]))
        con.commit()
        return RedirectResponse("/onboarding?step=3", status_code=303)
    finally:
        con.close()


@router.post("/onboarding/flavors")
def onboarding_flavors(request: Request,
                       flavor_key: list[str] = Form([]),
                       flavor_desc: list[str] = Form([]),
                       flavor_core: list[str] = Form([])):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        entries = _parse_flavor_forms(flavor_key, flavor_desc, flavor_core)
        complete = [e for e in entries if e["name"] and e["description"]]
        if not complete:
            con.execute("UPDATE users SET interest_flavors_json=? WHERE id=?",
                        (json.dumps(entries), user["id"]))
            con.commit()
            user = db.get_user(con, user["id"])
            return render(request, "onboarding.html",
                          _onboarding_ctx(con, user, 3,
                                          error="Add at least one topic with both a "
                                                "short name and a description."),
                          status_code=400)
        con.execute("UPDATE users SET interest_flavors_json=? WHERE id=?",
                    (json.dumps(complete), user["id"]))
        con.commit()
        return RedirectResponse("/onboarding?step=4", status_code=303)
    finally:
        con.close()


@router.post("/onboarding/negatives")
def onboarding_negatives(request: Request, negative: list[str] = Form([])):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        negs = [n.strip()[:300] for n in negative if n.strip()][:20]
        con.execute("UPDATE users SET interest_negatives_json=? WHERE id=?",
                    (json.dumps(negs), user["id"]))
        con.commit()
        return RedirectResponse(f"/onboarding?step={SEEDS_STEP}", status_code=303)
    finally:
        con.close()


def _add_seeds_from_text(con, user, text: str, source: str) -> tuple[int, list[str]]:
    """Resolve pasted DOIs/titles via OpenAlex; add hits, report misses."""
    added, misses = 0, []
    existing = {r["doi"] for r in con.execute(
        "SELECT doi FROM seeds WHERE user_id=?", (user["id"],)).fetchall() if r["doi"]}
    lines = [ln.strip() for ln in re.split(r"[\n;]+", text or "") if ln.strip()]
    for line in lines[:50]:
        rec = openalex.lookup(line)
        if not rec or not rec.get("title"):
            misses.append(line)
            continue
        if rec.get("doi") and rec["doi"] in existing:
            continue
        con.execute(
            "INSERT INTO seeds(user_id, doi, openalex_id, title, abstract, source, "
            "added_at) VALUES(?,?,?,?,?,?,?)",
            (user["id"], rec.get("doi", ""), rec.get("openalex_id", ""),
             rec["title"], rec.get("abstract", ""), source, db.now()))
        if rec.get("doi"):
            existing.add(rec["doi"])
        added += 1
    con.commit()
    return added, misses


@router.post("/onboarding/seeds")
def onboarding_seeds(request: Request, papers: str = Form("")):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        added, misses = _add_seeds_from_text(con, user, papers, "onboarding")
        notice = f"Added {added} paper{'s' if added != 1 else ''}." if added else ""
        error = ""
        if misses:
            error = ("Couldn't find: " + "; ".join(m[:80] for m in misses[:5])
                     + ". Try the DOI instead of the title.")
        return render(request, "onboarding.html",
                      _onboarding_ctx(con, user, SEEDS_STEP, error=error,
                                      notice=notice))
    finally:
        con.close()


@router.post("/onboarding/seeds/remove")
def onboarding_seed_remove(request: Request, seed_id: int = Form(...),
                           next: str = Form(f"/onboarding?step={SEEDS_STEP}")):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        con.execute("DELETE FROM seed_embeddings WHERE seed_id IN "
                    "(SELECT id FROM seeds WHERE id=? AND user_id=?)",
                    (seed_id, user["id"]))
        con.execute("DELETE FROM seeds WHERE id=? AND user_id=?",
                    (seed_id, user["id"]))
        con.commit()
        dest = next if next.startswith("/") else f"/onboarding?step={SEEDS_STEP}"
        return RedirectResponse(dest, status_code=303)
    finally:
        con.close()


@router.post("/onboarding/finish")
def onboarding_finish(request: Request):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        n = con.execute("SELECT COUNT(*) c FROM seeds WHERE user_id=?",
                        (user["id"],)).fetchone()["c"]
        if (not user["name"] or not user["interest_statement"]
                or not _user_flavors(user) or n < MIN_SEEDS):
            return render(request, "onboarding.html",
                          _onboarding_ctx(con, user, _default_step(user, n),
                                          error="A couple of steps still need attention "
                                                "before we can start your radar."),
                          status_code=400)
        _compose_profile_and_finish(con, user)
        _spawn_profile_build(user["id"])
        return RedirectResponse("/dashboard", status_code=303)
    finally:
        con.close()


# --- dashboard ---------------------------------------------------------------

@router.get("/dashboard")
def dashboard(request: Request, date: str = "", welcome: str = ""):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        if not user["onboarded_at"]:
            return RedirectResponse("/onboarding", status_code=303)
        dates = [r["date"] for r in con.execute(
            "SELECT DISTINCT date FROM briefing_items WHERE user_id=? "
            "ORDER BY date DESC LIMIT 60", (user["id"],)).fetchall()]
        sel = date if date in dates else (dates[0] if dates else "")
        items = []
        if sel:
            items = con.execute(
                "SELECT p.*, b.rank, b.fit AS b_fit, j.flavors_json, j.why, "
                "MAX(j.judged_at) AS _newest_judgment, "     # deterministic row pick
                "COALESCE(f.vote, '') AS vote "
                "FROM briefing_items b "
                "JOIN papers p ON p.id = b.paper_id "
                "LEFT JOIN judgments j ON j.paper_id = b.paper_id AND j.user_id = b.user_id "
                "LEFT JOIN feedback f ON f.paper_id = b.paper_id AND f.user_id = b.user_id "
                "WHERE b.user_id=? AND b.date=? "
                "GROUP BY p.id ORDER BY b.rank", (user["id"], sel)).fetchall()
        cards = []
        for r in items:
            cards.append({
                "id": r["id"], "title": r["title"], "venue": r["venue"],
                "date": r["pub_date"], "doi": r["doi"],
                "authors": ", ".join(json.loads(r["authors_json"] or "[]")[:8]),
                "fit": r["b_fit"],
                "flavors": [f.replace("_", " ")
                            for f in json.loads(r["flavors_json"] or "[]")],
                "why": r["why"] or "", "abstract": r["abstract"] or "",
                "vote": r["vote"],
            })
        n_seeds = con.execute("SELECT COUNT(*) c FROM seeds WHERE user_id=?",
                              (user["id"],)).fetchone()["c"]
        prof = db.get_profile(con, user["id"])
        return render(request, "dashboard.html", {
            "cards": cards, "dates": dates, "sel_date": sel,
            "n_seeds": n_seeds,
            "profile_ready": bool(prof and prof.get("retrieval_concepts")),
            "welcome": welcome == "1",
        })
    finally:
        con.close()


@router.post("/feedback")
def feedback(request: Request, paper_id: int = Form(...), vote: str = Form("")):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return JSONResponse({"error": "not signed in"}, status_code=401)
        if vote not in ("up", "down", ""):
            return JSONResponse({"error": "bad vote"}, status_code=400)
        paper = con.execute("SELECT title FROM papers WHERE id=?",
                            (paper_id,)).fetchone()
        if not paper:
            return JSONResponse({"error": "no such paper"}, status_code=404)
        con.execute(
            "INSERT INTO feedback(user_id, paper_id, vote, title, ts) VALUES(?,?,?,?,?) "
            "ON CONFLICT(user_id, paper_id) DO UPDATE SET vote=excluded.vote, "
            "ts=excluded.ts", (user["id"], paper_id, vote, paper["title"], db.now()))
        con.commit()
        return JSONResponse({"ok": True, "vote": vote})
    finally:
        con.close()


@router.get("/out/{paper_id}")
def out(request: Request, paper_id: int, ctx: str = "dashboard"):
    con = db.connect()
    try:
        user = get_user(request, con)
        paper = con.execute("SELECT doi, oa_url FROM papers WHERE id=?",
                            (paper_id,)).fetchone()
        if not paper:
            return RedirectResponse("/dashboard", status_code=303)
        if user:
            con.execute("INSERT INTO clicks(user_id, paper_id, ts, context) "
                        "VALUES(?,?,?,?)",
                        (user["id"], paper_id, db.now(),
                         ctx if ctx in ("dashboard", "email") else "dashboard"))
            con.commit()
        url = (f"https://doi.org/{paper['doi']}" if paper["doi"]
               else (paper["oa_url"] or "/dashboard"))
        return RedirectResponse(url, status_code=302)
    finally:
        con.close()


# --- settings ----------------------------------------------------------------

def _settings_ctx(con, user, error: str = "", notice: str = "",
                  zotero_preview: bool = False):
    from app.routes_zotero import link_ctx
    prof = db.get_profile(con, user["id"]) or {}
    seeds = con.execute("SELECT * FROM seeds WHERE user_id=? ORDER BY id",
                        (user["id"],)).fetchall()
    # Structured entries: prefer the user's own saved entries; legacy users
    # (pre-structured onboarding) see their profile's flavors/negatives, which
    # may include LLM-drafted ones — editing here adopts them as their own.
    flavors = _user_flavors(user) or [
        {"name": f["key"].replace("_", " "), "description": f["description"],
         "core": bool(f.get("core"))}
        for f in prof.get("flavors", [])
        if f.get("key") != "my_research_interests"]
    negatives = _user_negatives(user) or list(prof.get("negatives", []))
    ctx = {"prof": prof, "seeds": seeds, "flavors": flavors,
           "negatives": negatives,
           "error": error, "notice": notice, "znext": "/settings"}
    ctx.update(link_ctx(con, user["id"], want_preview=zotero_preview))
    return ctx


@router.get("/settings")
def settings(request: Request, zerr: str = "", znotice: str = "", zpreview: str = ""):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        return render(request, "settings.html",
                      _settings_ctx(con, user, error=zerr, notice=znotice,
                                    zotero_preview=zpreview == "1"))
    finally:
        con.close()


@router.post("/settings/account")
def settings_account(request: Request, name: str = Form(""),
                     frequency: str = Form("daily")):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        if frequency not in ("daily", "weekly", "none"):
            frequency = "daily"
        con.execute("UPDATE users SET name=?, frequency=? WHERE id=?",
                    (name.strip()[:120] or user["name"], frequency, user["id"]))
        con.commit()
        user = db.get_user(con, user["id"])
        request.state.user = user
        return render(request, "settings.html",
                      _settings_ctx(con, user, notice="Account settings saved."))
    finally:
        con.close()


@router.post("/settings/criteria")
def settings_criteria(request: Request, core_statement: str = Form(""),
                      fit_rule: str = Form(""),
                      flavor_key: list[str] = Form([]),
                      flavor_desc: list[str] = Form([]),
                      flavor_core: list[str] = Form([]),
                      negative: list[str] = Form([])):
    from pipeline.build_profile import bump_version, structured_profile
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        prof = db.get_profile(con, user["id"]) or {}
        core = core_statement.strip()[:4000]
        if len(core) < MIN_STATEMENT_CHARS:
            return render(request, "settings.html",
                          _settings_ctx(con, user,
                                        error="The core statement is what the judge reads "
                                              "first — please keep at least a short paragraph."),
                          status_code=400)
        entries = _parse_flavor_forms(flavor_key, flavor_desc, flavor_core)
        entries = [e for e in entries if e["name"] and e["description"]]
        if not entries:
            return render(request, "settings.html",
                          _settings_ctx(con, user,
                                        error="At least one topic is required "
                                              "(short name + description)."),
                          status_code=400)
        negs = [n.strip()[:300] for n in negative if n.strip()][:20]
        composed = structured_profile(core, entries, negs)
        prof.update({
            "core_statement": core,
            # a hand-written fit rule wins; otherwise the composed default
            "fit_rule": fit_rule.strip()[:2000] or composed["fit_rule"],
            "flavors": composed["flavors"],
            "negatives": composed["negatives"],
        })
        db.save_profile(con, user["id"], prof, bump_version())
        con.execute("UPDATE users SET interest_statement=?, "
                    "interest_flavors_json=?, interest_negatives_json=? WHERE id=?",
                    (core, json.dumps(entries), json.dumps(negs), user["id"]))
        con.commit()
        user = db.get_user(con, user["id"])
        request.state.user = user
        return render(request, "settings.html",
                      _settings_ctx(con, user,
                                    notice="Selection Criteria saved. Papers will be "
                                           "re-judged against the new wording on the "
                                           "next run."))
    finally:
        con.close()


@router.post("/settings/delete-account")
def settings_delete_account(request: Request, confirm: str = Form("")):
    """Self-serve full deletion: the user types DELETE to confirm; every row
    belonging to them is removed (see db.delete_user_cascade) and the session
    cookie is cleared."""
    from app.web import clear_session_cookie
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        if confirm.strip().upper() != "DELETE":
            return render(request, "settings.html",
                          _settings_ctx(con, user,
                                        error="To delete your account, type DELETE "
                                              "in the confirmation box."),
                          status_code=400)
        db.delete_user_cascade(con, user["id"])
        request.state.user = None
        resp = render(request, "account_deleted.html", {"user": None})
        clear_session_cookie(resp)
        return resp
    finally:
        con.close()


@router.post("/settings/seeds/add")
def settings_seeds_add(request: Request, papers: str = Form("")):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        added, misses = _add_seeds_from_text(con, user, papers, "settings")
        if added:
            _spawn_profile_build(user["id"])
        notice = f"Added {added} paper{'s' if added != 1 else ''}." if added else ""
        error = ("Couldn't find: " + "; ".join(m[:80] for m in misses[:5])
                 if misses else "")
        return render(request, "settings.html",
                      _settings_ctx(con, user, error=error, notice=notice))
    finally:
        con.close()
