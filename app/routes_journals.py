"""Priority journals: autocomplete against the OpenAlex sources API, plus
add/remove of a user's priority list. Papers from these journals are always
gathered and get guaranteed judge slots when close enough to the user's
interests (PRIORITY_JOURNAL_MIN_REL_PCTL — see
analysis/priority_journal_threshold.md)."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app import db, openalex
from app.web import get_user, login_redirect

router = APIRouter()

MAX_PRIORITY_JOURNALS = 25


def user_priority_journals(con, uid: int) -> list:
    return con.execute(
        "SELECT * FROM priority_journals WHERE user_id=? ORDER BY added_at, source_id",
        (uid,)).fetchall()


@router.get("/journals/search")
def journals_search(request: Request, q: str = ""):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return JSONResponse({"error": "not signed in"}, status_code=401)
        results = openalex.search_sources(q)
        # remember every source we've shown (country_code powers the
        # Western-context venue filter)
        for src in results:
            if src.get("id"):
                db.upsert_source(con, src)
        con.commit()
        mine = {r["source_id"] for r in user_priority_journals(con, user["id"])}
        return JSONResponse({"results": [
            {**src, "selected": src["id"] in mine} for src in results if src.get("id")]})
    finally:
        con.close()


@router.post("/journals/add")
def journals_add(request: Request, source_id: str = Form(...),
                 display_name: str = Form(""), country_code: str = Form(""),
                 next: str = Form("/settings")):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        source_id = source_id.strip()[:40]
        if not source_id.startswith("S"):
            return JSONResponse({"error": "bad source id"}, status_code=400)
        n = con.execute("SELECT COUNT(*) c FROM priority_journals WHERE user_id=?",
                        (user["id"],)).fetchone()["c"]
        if n >= MAX_PRIORITY_JOURNALS:
            return JSONResponse({"error": f"limit of {MAX_PRIORITY_JOURNALS} "
                                          "priority journals reached"}, status_code=400)
        display_name = openalex.clean_text(display_name.strip()[:200])
        country_code = country_code.strip().upper()[:2]
        con.execute(
            "INSERT OR IGNORE INTO priority_journals(user_id, source_id, "
            "display_name, country_code, added_at) VALUES(?,?,?,?,?)",
            (user["id"], source_id, display_name, country_code, db.now()))
        db.upsert_source(con, {"id": source_id, "display_name": display_name,
                               "country_code": country_code, "type": ""})
        con.commit()
        dest = next if next.startswith("/") else "/settings"
        return RedirectResponse(dest, status_code=303)
    finally:
        con.close()


@router.post("/journals/remove")
def journals_remove(request: Request, source_id: str = Form(...),
                    next: str = Form("/settings")):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        con.execute("DELETE FROM priority_journals WHERE user_id=? AND source_id=?",
                    (user["id"], source_id.strip()))
        con.commit()
        dest = next if next.startswith("/") else "/settings"
        return RedirectResponse(dest, status_code=303)
    finally:
        con.close()
