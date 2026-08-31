"""Owner/admin surface: users, pipeline runs, provider quotas, errors,
dev-mode login links."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app import db
from app.config import smtp_configured
from app.web import render, get_user, login_redirect

router = APIRouter()

PROVIDER_CAPS = {"groq": 1000, "gemini": 250, "cerebras": 14400, "openrouter": 50}


def _require_admin(request: Request, con):
    user = get_user(request, con)
    if not user:
        return None, login_redirect()
    if not user["is_admin"]:
        return None, RedirectResponse("/dashboard", status_code=303)
    return user, None


@router.get("/admin")
def admin(request: Request):
    con = db.connect()
    try:
        user, redirect = _require_admin(request, con)
        if redirect:
            return redirect
        users = con.execute(
            "SELECT u.*, "
            "(SELECT COUNT(*) FROM seeds s WHERE s.user_id=u.id) AS n_seeds, "
            "(SELECT COUNT(*) FROM judgments j WHERE j.user_id=u.id) AS n_judged, "
            "(SELECT MAX(date) FROM briefing_items b WHERE b.user_id=u.id) AS last_briefing "
            "FROM users u ORDER BY u.id").fetchall()
        runs = con.execute(
            "SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT 25").fetchall()
        usage = con.execute(
            "SELECT * FROM provider_usage WHERE date=? ORDER BY provider",
            (db.today(),)).fetchall()
        errors = con.execute(
            "SELECT * FROM pipeline_runs WHERE status='error' "
            "ORDER BY id DESC LIMIT 10").fetchall()
        n_papers = con.execute("SELECT COUNT(*) c FROM papers").fetchone()["c"]
        n_vectors = con.execute("SELECT COUNT(*) c FROM paper_embeddings").fetchone()["c"]
        podcast_episodes = con.execute(
            "SELECT e.*, u.email FROM podcast_episodes e "
            "JOIN users u ON u.id = e.user_id "
            "ORDER BY e.date DESC, u.email, e.engine LIMIT 14").fetchall()
        return render(request, "admin.html", {
            "users": users, "runs": runs, "usage": usage, "errors": errors,
            "caps": PROVIDER_CAPS, "n_papers": n_papers, "n_vectors": n_vectors,
            "podcast_episodes": podcast_episodes,
            "dev_mode": not smtp_configured(),
        })
    finally:
        con.close()


@router.get("/admin/dev-links")
def dev_links(request: Request):
    con = db.connect()
    try:
        user, redirect = _require_admin(request, con)
        if redirect:
            return redirect
        links = con.execute(
            "SELECT email, dev_link, created_at, expires_at FROM auth_tokens "
            "WHERE dev_link IS NOT NULL AND used_at IS NULL AND expires_at > ? "
            "ORDER BY created_at DESC LIMIT 25",
            (dt.datetime.now().isoformat(),)).fetchall()
        return render(request, "dev_links.html",
                      {"links": links, "dev_mode": not smtp_configured()})
    finally:
        con.close()
