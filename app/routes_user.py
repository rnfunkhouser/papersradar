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
    from pipeline.build_profile import (CORE_FIT_SENTENCE, DEFAULT_FIT_RULE,
                                        bump_version, fallback_profile,
                                        structured_profile)
    prof = structured_profile(user["interest_statement"] or "",
                              _user_flavors(user), _user_negatives(user))
    existing = db.get_profile(con, user["id"])
    if not existing:
        db.save_profile(con, user["id"], prof, bump_version())
    else:
        changed = any(existing.get(k) != prof[k]
                      for k in ("core_statement", "flavors", "negatives"))
        if changed:
            # a fit_rule customized out-of-band (e.g. the owner's imported,
            # calibrated rubric) survives structured edits; only rules
            # matching a composed default stay in sync with the core flags
            defaults = {DEFAULT_FIT_RULE, DEFAULT_FIT_RULE + CORE_FIT_SENTENCE,
                        fallback_profile("", "")["fit_rule"]}
            keys = ("core_statement", "flavors", "negatives")
            if existing.get("fit_rule") in defaults:
                keys += ("fit_rule",)
            existing.update({k: prof[k] for k in keys})
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

# The wizard opens with an entry fork (step 0): "Start from my papers" adds
# seed papers FIRST and coach-drafts the interest editors from them; "Write it
# myself" keeps the interests-first order. Both are the SAME seven named steps
# — only the position of the seeds step differs — and they converge on the
# shared tail (about -> journals -> review).
SEQUENCES = {
    "papers": ["seeds", "describe", "topics", "negatives",
               "about", "journals", "review"],
    "manual": ["describe", "topics", "negatives", "seeds",
               "about", "journals", "review"],
}
STEP_TITLES = {
    "seeds": "Seed papers", "describe": "Describe your research",
    "topics": "Topics & intersections", "negatives": "Not interested",
    "about": "About you", "journals": "Priority journals",
    "review": "Review & launch",
}
N_STEPS = 7


def user_path(user) -> str:
    """'papers' | 'manual' | '' (fork not answered yet). Users who progressed
    before the fork existed continue under the manual (original) order."""
    try:
        p = user["onboarding_path"] or ""
    except (IndexError, KeyError):
        p = ""
    if p in SEQUENCES:
        return p
    if user["name"] or user["interest_statement"] or _user_flavors(user):
        return "manual"
    return ""


def step_num(user, slug: str) -> int:
    """1-based position of a named step in this user's sequence."""
    return SEQUENCES[user_path(user) or "manual"].index(slug) + 1


def _next_url(user, slug: str) -> str:
    return f"/onboarding?step={step_num(user, slug) + 1}"


def _coach_draft(con, uid: int) -> dict | None:
    row = con.execute("SELECT draft_json FROM coach_drafts WHERE user_id=?",
                      (uid,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["draft_json"])
    except ValueError:
        return None


def _onboarding_ctx(con, user, step: int, error: str = "", notice: str = "",
                    zotero_preview: bool = False):
    from app.config import cfg_int
    from app.routes_journals import user_priority_journals
    from app.routes_zotero import link_ctx
    seeds = con.execute("SELECT * FROM seeds WHERE user_id=? ORDER BY id",
                        (user["id"],)).fetchall()
    path = user_path(user)
    seq = SEQUENCES[path or "manual"]
    step_slug = seq[step - 1] if 1 <= step <= N_STEPS else ""
    ctx = {"step": step, "n_steps": N_STEPS, "seeds": seeds, "min_seeds": MIN_SEEDS,
           "path": path, "step_slug": step_slug,
           "step_titles": [STEP_TITLES[s] for s in seq],
           "default_briefing_size": cfg_int("BRIEFING_MAX_ITEMS"),
           "flavors": _user_flavors(user), "negatives": _user_negatives(user),
           "priority_journals": user_priority_journals(con, user["id"]),
           "coach_draft": _coach_draft(con, user["id"]),
           "draft_statement": "",
           "error": error, "notice": notice,
           "znext": f"/onboarding?step={step}",
           "jnext": f"/onboarding?step={seq.index('journals') + 1}"}
    # AI-drafted profile (coach autofill): PREFILL only — the draft becomes the
    # user's saved text exclusively when they submit each editor step.
    if ctx["coach_draft"]:
        d = ctx["coach_draft"]
        ctx["draft_statement"] = str(d.get("core_statement") or "")
        if not ctx["flavors"]:
            ctx["flavors"] = [{"name": str(f.get("name") or ""),
                               "description": str(f.get("description") or ""),
                               "core": False} for f in d.get("flavors") or []]
        if not ctx["negatives"]:
            ctx["negatives"] = [str(n) for n in d.get("negatives") or []]
    ctx.update(link_ctx(con, user["id"],
                        want_preview=zotero_preview and step_slug == "seeds"))
    return ctx


def _default_step(user, n_seeds: int) -> int:
    """First incomplete step in this user's sequence; 0 = the entry fork."""
    path = user_path(user)
    if not path:
        return 0
    missing = {"describe": not user["interest_statement"],
               "topics": not _user_flavors(user),
               "seeds": n_seeds < MIN_SEEDS,
               "about": not user["name"]}
    for i, slug in enumerate(SEQUENCES[path], 1):
        if missing.get(slug):
            return i
    return N_STEPS


@router.get("/onboarding")
def onboarding(request: Request, step: int = -1, zerr: str = "", znotice: str = "",
               zpreview: str = "", welcome: str = ""):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        n = con.execute("SELECT COUNT(*) c FROM seeds WHERE user_id=?",
                        (user["id"],)).fetchone()["c"]
        step = step if 0 <= step <= N_STEPS else _default_step(user, n)
        if step and not user_path(user):
            step = 0                        # numbered steps need a chosen path
        notice = znotice
        if welcome == "1" and not notice:
            notice = ("You're signed in — you'll stay signed in on this device "
                      "for 90 days.")
        return render(request, "onboarding.html",
                      _onboarding_ctx(con, user, step, error=zerr, notice=notice,
                                      zotero_preview=zpreview == "1"))
    finally:
        con.close()


@router.post("/onboarding/path")
def onboarding_path(request: Request, path: str = Form("")):
    """The entry fork: 'papers' (seeds first, drafted criteria) or 'manual'.
    Changeable — going Back to the fork and picking again just re-orders the
    remaining steps; nothing already entered is lost."""
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        if path not in SEQUENCES:
            path = "manual"
        con.execute("UPDATE users SET onboarding_path=? WHERE id=?",
                    (path, user["id"]))
        con.commit()
        return RedirectResponse("/onboarding?step=1", status_code=303)
    finally:
        con.close()


def _parse_briefing_size(raw: str):
    """'' -> None (global default); else clamp to the allowed 3-10 range."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return max(3, min(10, int(raw)))
    except ValueError:
        return None


def _set_geo_scope(con, user, on: bool) -> None:
    """Persist the Western-context flag. The soft half of the option lives in
    the judge PROMPT, so when the flag changes for a user who already has a
    judge profile, the profile version is bumped — cached verdicts from the
    other prompt must not mix, exactly like any other criteria edit."""
    if bool(user["western_context"]) == on:
        return
    con.execute("UPDATE users SET western_context=? WHERE id=?",
                (1 if on else 0, user["id"]))
    prof = db.get_profile(con, user["id"])
    if prof:
        from pipeline.build_profile import bump_version
        db.save_profile(con, user["id"], prof, bump_version())
    con.commit()


@router.post("/onboarding/about")
def onboarding_about(request: Request, name: str = Form(""),
                     frequency: str = Form("daily"),
                     briefing_size: str = Form(""),
                     western_context: str = Form("")):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        name = name.strip()[:120]
        if not name:
            return render(request, "onboarding.html",
                          _onboarding_ctx(con, user, step_num(user, "about"),
                                          error="Please tell us your name."),
                          status_code=400)
        if frequency not in ("daily", "weekly", "none"):
            frequency = "daily"
        con.execute("UPDATE users SET name=?, frequency=?, briefing_size=? WHERE id=?",
                    (name, frequency, _parse_briefing_size(briefing_size),
                     user["id"]))
        con.commit()
        _set_geo_scope(con, user, western_context == "1")
        return RedirectResponse(_next_url(user, "about"), status_code=303)
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
                          _onboarding_ctx(con, user, step_num(user, "describe"),
                                          error="A few sentences helps the judge a lot — "
                                                "please write at least a short paragraph."),
                          status_code=400)
        con.execute("UPDATE users SET interest_statement=? WHERE id=?",
                    (statement, user["id"]))
        con.commit()
        return RedirectResponse(_next_url(user, "describe"), status_code=303)
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
                          _onboarding_ctx(con, user, step_num(user, "topics"),
                                          error="Add at least one topic with both a "
                                                "short name and a description."),
                          status_code=400)
        con.execute("UPDATE users SET interest_flavors_json=? WHERE id=?",
                    (json.dumps(complete), user["id"]))
        con.commit()
        return RedirectResponse(_next_url(user, "topics"), status_code=303)
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
        return RedirectResponse(_next_url(user, "negatives"), status_code=303)
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
                      _onboarding_ctx(con, user, step_num(user, "seeds"),
                                      error=error, notice=notice))
    finally:
        con.close()


@router.post("/onboarding/seeds/remove")
def onboarding_seed_remove(request: Request, seed_id: int = Form(...),
                           next: str = Form("/onboarding")):
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
        dest = next if next.startswith("/") else "/onboarding"
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


# --- dashboard & archive -----------------------------------------------------

def _briefing_cards(con, uid: int, date: str = "", q: str = "",
                    limit: int = 200) -> list[dict]:
    """Card dicts for this user's briefed papers (dashboard day view, archive
    day view, archive search). `q` is a plain LIKE search over title, venue,
    authors and abstract — always scoped to the user's own briefing_items."""
    sql = ("SELECT p.*, b.date AS b_date, b.rank, b.fit AS b_fit, "
           "j.flavors_json, j.why, "
           "MAX(j.judged_at) AS _newest_judgment, "          # deterministic row pick
           "COALESCE(f.vote, '') AS vote, "
           "COALESCE(s.summary, '') AS gen_summary, "
           "COALESCE(s.grounded, 0) AS summary_grounded, "
           "COALESCE(pj.display_name, '') AS pj_name "
           "FROM briefing_items b "
           "JOIN papers p ON p.id = b.paper_id "
           "LEFT JOIN judgments j ON j.paper_id = b.paper_id AND j.user_id = b.user_id "
           "LEFT JOIN feedback f ON f.paper_id = b.paper_id AND f.user_id = b.user_id "
           "LEFT JOIN paper_summaries s ON s.paper_id = b.paper_id "
           "LEFT JOIN priority_journals pj ON pj.user_id = b.user_id "
           "     AND pj.source_id = p.source_id AND p.source_id != '' "
           "WHERE b.user_id=?")
    args: list = [uid]
    if date:
        sql += " AND b.date=?"
        args.append(date)
    if q:
        like = f"%{q}%"
        sql += (" AND (p.title LIKE ? OR p.venue LIKE ? "
                "OR p.authors_json LIKE ? OR p.abstract LIKE ?)")
        args += [like] * 4
    sql += " GROUP BY p.id ORDER BY b.date DESC, b.rank LIMIT ?"
    args.append(limit)
    cards = []
    for r in con.execute(sql, args).fetchall():
        cards.append({
            "id": r["id"], "title": r["title"], "venue": r["venue"],
            "date": r["pub_date"], "doi": r["doi"],
            "authors": ", ".join(json.loads(r["authors_json"] or "[]")[:8]),
            "fit": r["b_fit"], "briefing_date": r["b_date"],
            "flavors": [f.replace("_", " ")
                        for f in json.loads(r["flavors_json"] or "[]")],
            "why": r["why"] or "", "abstract": r["abstract"] or "",
            "summary": r["gen_summary"] or "",
            "summary_grounded": bool(r["summary_grounded"]),
            "vote": r["vote"],
            "priority_journal": r["pj_name"] or "",
        })
    return cards


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
        cards = _briefing_cards(con, user["id"], date=sel) if sel else []
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


@router.get("/archive")
def archive(request: Request, date: str = "", q: str = ""):
    """Every past briefing day for this user (date + pick count, grouped by
    month), a full card view per day, and a plain text search over the user's
    own archived items. Votes work on archived cards exactly as on the
    dashboard."""
    import datetime as dt
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        if not user["onboarded_at"]:
            return RedirectResponse("/onboarding", status_code=303)
        q = q.strip()[:120]
        day_rows = con.execute(
            "SELECT date, COUNT(*) n FROM briefing_items WHERE user_id=? "
            "GROUP BY date ORDER BY date DESC", (user["id"],)).fetchall()
        months: list[dict] = []
        for r in day_rows:
            month = r["date"][:7]
            if not months or months[-1]["key"] != month:
                try:
                    label = dt.date.fromisoformat(month + "-01").strftime("%B %Y")
                except ValueError:
                    label = month
                months.append({"key": month, "label": label, "days": []})
            try:
                weekday = dt.date.fromisoformat(r["date"]).strftime("%A")
            except ValueError:
                weekday = ""
            months[-1]["days"].append({"date": r["date"], "weekday": weekday,
                                       "n": r["n"]})
        sel = date if any(d["date"] == date for m in months
                          for d in m["days"]) else ""
        cards = []
        if q:
            cards = _briefing_cards(con, user["id"], q=q, limit=100)
        elif sel:
            cards = _briefing_cards(con, user["id"], date=sel)
        return render(request, "archive.html", {
            "months": months, "n_days": len(day_rows),
            "n_items": sum(r["n"] for r in day_rows),
            "sel_date": sel, "q": q, "cards": cards,
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


# Sources whose papers live on a preprint server: their DOIs are often not
# yet registered with Crossref when we link them (verified live: a fresh
# PsyArXiv DOI 404s on doi.org while its oa_url resolves), so prefer the
# hosting page and keep the DOI as fallback. Journal-published papers keep
# DOI-first. Mirrors pipeline.gather's source values ('arxiv' + OSF providers).
PREPRINT_SOURCES = {"arxiv", "socarxiv", "psyarxiv"}


def outbound_url(paper) -> str:
    doi_url = f"https://doi.org/{paper['doi']}" if paper["doi"] else ""
    oa = paper["oa_url"] or ""
    if (paper["source"] or "").lower() in PREPRINT_SOURCES:
        return oa or doi_url or "/dashboard"
    return doi_url or oa or "/dashboard"


@router.get("/out/{paper_id}")
def out(request: Request, paper_id: int, ctx: str = "dashboard"):
    con = db.connect()
    try:
        user = get_user(request, con)
        paper = con.execute("SELECT doi, oa_url, source FROM papers WHERE id=?",
                            (paper_id,)).fetchone()
        if not paper:
            return RedirectResponse("/dashboard", status_code=303)
        if user:
            con.execute("INSERT INTO clicks(user_id, paper_id, ts, context) "
                        "VALUES(?,?,?,?)",
                        (user["id"], paper_id, db.now(),
                         ctx if ctx in ("dashboard", "email") else "dashboard"))
            con.commit()
        return RedirectResponse(outbound_url(paper), status_code=302)
    finally:
        con.close()


@router.get("/more/{paper_id}")
def more(request: Request, paper_id: int):
    """Email 'Full summary on your dashboard' link: log the click under its
    own context, then land on the paper's card anchor."""
    con = db.connect()
    try:
        user = get_user(request, con)
        if user:
            con.execute("INSERT INTO clicks(user_id, paper_id, ts, context) "
                        "VALUES(?,?,?,'email-more')",
                        (user["id"], paper_id, db.now()))
            con.commit()
        return RedirectResponse(f"/dashboard#paper-{paper_id}", status_code=302)
    finally:
        con.close()


# --- settings ----------------------------------------------------------------

def _settings_ctx(con, user, error: str = "", notice: str = "",
                  zotero_preview: bool = False):
    from app.config import cfg_int
    from app.routes_journals import user_priority_journals
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
    n_votes = con.execute(
        "SELECT COUNT(*) c FROM feedback WHERE user_id=? AND vote != ''",
        (user["id"],)).fetchone()["c"]
    audits = con.execute(
        "SELECT * FROM profile_audits WHERE user_id=? ORDER BY id DESC LIMIT 5",
        (user["id"],)).fetchall()
    latest_audit = None
    if audits:
        try:
            parsed = json.loads(audits[0]["proposals_json"])
            latest_audit = {"created_at": audits[0]["created_at"],
                            "summary": parsed.get("summary", ""),
                            "proposals": parsed.get("proposals", [])}
        except ValueError:
            pass
    ctx = {"prof": prof, "seeds": seeds, "flavors": flavors,
           "negatives": negatives,
           "priority_journals": user_priority_journals(con, user["id"]),
           "n_votes": n_votes, "audit_min_votes": cfg_int("AUDIT_MIN_VOTES"),
           "audits": audits, "latest_audit": latest_audit,
           "default_briefing_size": cfg_int("BRIEFING_MAX_ITEMS"),
           "error": error, "notice": notice,
           "znext": "/settings", "jnext": "/settings"}
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
                     frequency: str = Form("daily"),
                     briefing_size: str = Form("")):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        if frequency not in ("daily", "weekly", "none"):
            frequency = "daily"
        con.execute("UPDATE users SET name=?, frequency=?, briefing_size=? WHERE id=?",
                    (name.strip()[:120] or user["name"], frequency,
                     _parse_briefing_size(briefing_size), user["id"]))
        con.commit()
        user = db.get_user(con, user["id"])
        request.state.user = user
        return render(request, "settings.html",
                      _settings_ctx(con, user, notice="Account settings saved."))
    finally:
        con.close()


@router.post("/settings/scope")
def settings_scope(request: Request, western_context: str = Form("")):
    """Western-context toggle — same behavior as from onboarding: if the flag
    changes, the judge prompt changes, so the profile version bumps and the
    current window is re-judged on the next run."""
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        changed = bool(user["western_context"]) != (western_context == "1")
        _set_geo_scope(con, user, western_context == "1")
        user = db.get_user(con, user["id"])
        request.state.user = user
        notice = "Scope saved."
        if changed:
            notice = ("Scope saved. Papers will be re-judged under the new "
                      "scope on the next run.")
        return render(request, "settings.html",
                      _settings_ctx(con, user, notice=notice))
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
