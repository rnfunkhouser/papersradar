"""AI profile coach endpoints: seed-based autofill, draft suggestions, and
the vote-informed profile audit. Every endpoint is per-user rate-limited
(COACH_DAILY_LIMIT calls/day across ALL modes, tracked in coach_usage), and
every LLM call goes through pipeline.providers.chat — the same router, quota
counters, and admin-visible accounting as judging."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app import coach, db
from app.config import cfg_int
from app.web import get_user, login_redirect, render

router = APIRouter()
log = logging.getLogger("papersradar.coach")

BUDGET_MSG = ("The AI coach is rate-limited to a few calls per day — "
              "please try again tomorrow.")
UNAVAILABLE_MSG = ("The AI coach couldn't reach a language-model provider "
                   "just now — please try again in a few minutes.")


def _take_budget(con, uid: int) -> bool:
    """Reserve one coach call from the user's shared daily budget."""
    limit = cfg_int("COACH_DAILY_LIMIT")
    row = con.execute("SELECT count FROM coach_usage WHERE user_id=? AND date=?",
                      (uid, db.today())).fetchone()
    if row and row["count"] >= limit:
        return False
    con.execute(
        "INSERT INTO coach_usage(user_id, date, count) VALUES(?,?,1) "
        "ON CONFLICT(user_id, date) DO UPDATE SET count = count + 1",
        (uid, db.today()))
    con.commit()
    return True


def _chat(system: str, user_msg: str):
    from pipeline import providers
    return providers.chat(system, user_msg, temperature=coach.COACH_TEMPERATURE)


# --- a) seed-based autofill ---------------------------------------------------

@router.post("/coach/autofill")
def coach_autofill(request: Request):
    """Draft core statement + flavors + negatives from the user's seed papers.
    The draft is stored in coach_drafts and PREFILLS the structured editor —
    it is never saved as the profile without the user walking the editor
    steps themselves."""
    from app.routes_user import MIN_SEEDS, SEEDS_STEP, _onboarding_ctx
    from pipeline import providers
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        seeds = con.execute("SELECT title, abstract FROM seeds WHERE user_id=? "
                            "ORDER BY id", (user["id"],)).fetchall()
        if len(seeds) < MIN_SEEDS:
            return render(request, "onboarding.html",
                          _onboarding_ctx(con, user, SEEDS_STEP,
                                          error=f"Add at least {MIN_SEEDS} seed "
                                                "papers first — the draft is built "
                                                "from them."),
                          status_code=400)
        if not _take_budget(con, user["id"]):
            return render(request, "onboarding.html",
                          _onboarding_ctx(con, user, SEEDS_STEP, error=BUDGET_MSG),
                          status_code=429)
        try:
            text, _provider = _chat(coach.AUTOFILL_SYSTEM,
                                    coach.autofill_user_msg([dict(s) for s in seeds]))
        except providers.ProvidersUnavailable:
            return render(request, "onboarding.html",
                          _onboarding_ctx(con, user, SEEDS_STEP,
                                          error=UNAVAILABLE_MSG),
                          status_code=503)
        draft = coach.parse_autofill(text)
        if not draft:
            return render(request, "onboarding.html",
                          _onboarding_ctx(con, user, SEEDS_STEP,
                                          error="The draft came back malformed — "
                                                "please try once more."),
                          status_code=502)
        con.execute("INSERT INTO coach_drafts(user_id, draft_json, created_at) "
                    "VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                    "draft_json=excluded.draft_json, created_at=excluded.created_at",
                    (user["id"], json.dumps(draft, ensure_ascii=False), db.now()))
        con.commit()
        return RedirectResponse("/onboarding?step=2", status_code=303)
    finally:
        con.close()


# --- b) suggestions on the current draft --------------------------------------

@router.post("/coach/suggest")
def coach_suggest(request: Request, statement: str = Form(""),
                  flavor_key: list[str] = Form([]),
                  flavor_desc: list[str] = Form([]),
                  negative: list[str] = Form([])):
    """Coach the draft the user is LOOKING AT (fields posted from the open
    editor, saved or not). Returns JSON; the client renders it as dismissible
    suggestions beside the editor — nothing is applied automatically."""
    from pipeline import providers
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return JSONResponse({"error": "not signed in"}, status_code=401)
        if not _take_budget(con, user["id"]):
            return JSONResponse({"error": BUDGET_MSG}, status_code=429)
        flavors = [{"name": k.strip()[:80], "description": d.strip()[:600]}
                   for k, d in zip(flavor_key, flavor_desc) if k.strip() or d.strip()]
        negatives = [n.strip()[:300] for n in negative if n.strip()]
        # each editor step posts only its own fields; fall back to saved values
        # so the coach always sees the whole draft
        statement = statement.strip()[:4000] or (user["interest_statement"] or "")
        if not flavors:
            try:
                flavors = json.loads(user["interest_flavors_json"] or "[]")
            except (ValueError, TypeError):
                flavors = []
        if not negatives:
            try:
                negatives = json.loads(user["interest_negatives_json"] or "[]")
            except (ValueError, TypeError):
                negatives = []
        seed_titles = [r["title"] for r in con.execute(
            "SELECT title FROM seeds WHERE user_id=? ORDER BY id",
            (user["id"],)).fetchall()]
        try:
            text, _provider = _chat(
                coach.SUGGEST_SYSTEM,
                coach.suggest_user_msg(statement, flavors, negatives, seed_titles))
        except providers.ProvidersUnavailable:
            return JSONResponse({"error": UNAVAILABLE_MSG}, status_code=503)
        out = coach.parse_suggestions(text)
        if not out:
            return JSONResponse({"error": "The suggestions came back malformed — "
                                          "please try once more."}, status_code=502)
        return JSONResponse(out)
    finally:
        con.close()


# --- c) vote-informed audit ---------------------------------------------------

@router.post("/coach/audit")
def coach_audit(request: Request):
    """One LLM call over profile + seeds + vote evidence -> specific wording
    proposals (current -> suggested, motivating papers cited). Stored in
    profile_audits; the user applies edits manually in the criteria editor."""
    from app.routes_user import _settings_ctx
    from pipeline import providers
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        prof = db.get_profile(con, user["id"])
        evidence = coach.gather_audit_evidence(con, user["id"])
        min_votes = cfg_int("AUDIT_MIN_VOTES")
        if not prof or evidence["n_votes"] < min_votes:
            return render(request, "settings.html",
                          _settings_ctx(con, user,
                                        error=f"The audit unlocks at {min_votes} "
                                              f"votes ({evidence['n_votes']} so far) "
                                              "— votes are its evidence."),
                          status_code=400)
        if not _take_budget(con, user["id"]):
            return render(request, "settings.html",
                          _settings_ctx(con, user, error=BUDGET_MSG),
                          status_code=429)
        seed_titles = [r["title"] for r in con.execute(
            "SELECT title FROM seeds WHERE user_id=? ORDER BY id",
            (user["id"],)).fetchall()]
        prev_row = con.execute(
            "SELECT * FROM profile_audits WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (user["id"],)).fetchone()
        previous = None
        if prev_row:
            try:
                previous = {"created_at": prev_row["created_at"],
                            "proposals": json.loads(
                                prev_row["proposals_json"]).get("proposals", [])}
            except ValueError:
                pass
        try:
            text, provider = _chat(
                coach.AUDIT_SYSTEM,
                coach.audit_user_msg(prof, seed_titles, evidence, previous))
        except providers.ProvidersUnavailable:
            return render(request, "settings.html",
                          _settings_ctx(con, user, error=UNAVAILABLE_MSG),
                          status_code=503)
        result = coach.parse_audit(text)
        if not result:
            return render(request, "settings.html",
                          _settings_ctx(con, user,
                                        error="The audit came back malformed — "
                                              "please try once more."),
                          status_code=502)
        con.execute("INSERT INTO profile_audits(user_id, created_at, n_votes, "
                    "proposals_json, provider) VALUES(?,?,?,?,?)",
                    (user["id"], db.now(), evidence["n_votes"],
                     json.dumps(result, ensure_ascii=False), provider))
        con.commit()
        return render(request, "settings.html",
                      _settings_ctx(con, user,
                                    notice="Audit complete — proposals below. "
                                           "Apply the ones you agree with in the "
                                           "Selection Criteria editor."))
    finally:
        con.close()
