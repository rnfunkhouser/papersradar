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


def _fallback_profile_and_finish(con, user):
    """Synchronous, network-free part of finishing onboarding (deterministic:
    onboarding never blocks on an API). Enrichment happens in the background /
    nightly profiles stage."""
    from pipeline.build_profile import fallback_profile, bump_version
    if not db.get_profile(con, user["id"]):
        prof = fallback_profile(user["name"], user["interest_statement"] or "")
        db.save_profile(con, user["id"], prof, bump_version())
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

def _onboarding_ctx(con, user, step: int, error: str = "", notice: str = "",
                    zotero_preview: bool = False):
    from app.routes_zotero import link_ctx
    seeds = con.execute("SELECT * FROM seeds WHERE user_id=? ORDER BY id",
                        (user["id"],)).fetchall()
    ctx = {"step": step, "seeds": seeds, "min_seeds": MIN_SEEDS,
           "error": error, "notice": notice, "znext": f"/onboarding?step={step}"}
    ctx.update(link_ctx(con, user["id"],
                        want_preview=zotero_preview and step == 3))
    return ctx


def _default_step(user, n_seeds: int) -> int:
    if not user["name"]:
        return 1
    if not user["interest_statement"]:
        return 2
    return 3 if n_seeds < MIN_SEEDS else 4


@router.get("/onboarding")
def onboarding(request: Request, step: int = 0, zerr: str = "", znotice: str = "",
               zpreview: str = ""):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        n = con.execute("SELECT COUNT(*) c FROM seeds WHERE user_id=?",
                        (user["id"],)).fetchone()["c"]
        step = step if 1 <= step <= 4 else _default_step(user, n)
        return render(request, "onboarding.html",
                      _onboarding_ctx(con, user, step, error=zerr, notice=znotice,
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
                      _onboarding_ctx(con, user, 3, error=error, notice=notice))
    finally:
        con.close()


@router.post("/onboarding/seeds/remove")
def onboarding_seed_remove(request: Request, seed_id: int = Form(...),
                           next: str = Form("/onboarding?step=3")):
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
        dest = next if next.startswith("/") else "/onboarding?step=3"
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
        if not user["name"] or not user["interest_statement"] or n < MIN_SEEDS:
            return render(request, "onboarding.html",
                          _onboarding_ctx(con, user, _default_step(user, n),
                                          error="A couple of steps still need attention "
                                                "before we can start your radar."),
                          status_code=400)
        _fallback_profile_and_finish(con, user)
        _spawn_profile_build(user["id"])
        return RedirectResponse("/dashboard", status_code=303)
    finally:
        con.close()


# --- dashboard ---------------------------------------------------------------

@router.get("/dashboard")
def dashboard(request: Request, date: str = ""):
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
    flavors_text = "\n".join(f"{f['key']}: {f['description']}"
                             for f in prof.get("flavors", []))
    ctx = {"prof": prof, "seeds": seeds, "flavors_text": flavors_text,
           "negatives_text": "\n".join(prof.get("negatives", [])),
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
                      fit_rule: str = Form(""), flavors: str = Form(""),
                      negatives: str = Form("")):
    from pipeline.build_profile import bump_version
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
        flist = []
        for line in flavors.splitlines():
            if ":" not in line:
                continue
            key, _, desc = line.partition(":")
            key = re.sub(r"\W+", "_", key.strip().lower())[:40]
            if key and desc.strip():
                flist.append({"key": key, "description": desc.strip()[:600]})
        if not flist:
            return render(request, "settings.html",
                          _settings_ctx(con, user,
                                        error="At least one flavor is required "
                                              "(format: key: description)."),
                          status_code=400)
        prof.update({
            "core_statement": core,
            "fit_rule": fit_rule.strip()[:2000] or prof.get("fit_rule", ""),
            "flavors": flist,
            "negatives": [n.strip() for n in negatives.splitlines() if n.strip()][:20],
        })
        db.save_profile(con, user["id"], prof, bump_version())
        con.execute("UPDATE users SET interest_statement=? WHERE id=?",
                    (core, user["id"]))
        con.commit()
        return render(request, "settings.html",
                      _settings_ctx(con, user,
                                    notice="Selection Criteria saved. Papers will be "
                                           "re-judged against the new wording on the "
                                           "next run."))
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
