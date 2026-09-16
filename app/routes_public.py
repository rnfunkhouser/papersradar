# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public routes: landing, magic-link login, about-scores explainer."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import auth, db, mailer
from app.web import (render, get_user, set_session_cookie, clear_session_cookie,
                     client_ip)

router = APIRouter()
log = logging.getLogger("papersradar.auth")


@router.get("/")
def landing(request: Request):
    con = db.connect()
    try:
        get_user(request, con)
        return render(request, "landing.html")
    finally:
        con.close()


@router.get("/login")
def login_form(request: Request):
    return render(request, "login.html", {"error": None, "email": ""})


@router.post("/login")
def login_submit(request: Request, email: str = Form("")):
    email = email.strip().lower()
    if not auth.valid_email(email):
        return render(request, "login.html",
                      {"error": "That doesn't look like an email address.",
                       "email": email}, status_code=400)
    con = db.connect()
    try:
        try:
            auth.check_rate_limit(con, email, client_ip(request))
        except auth.RateLimited as e:
            return render(request, "login.html", {"error": str(e), "email": email},
                          status_code=429)
        token, url = auth.issue_token(con, email)
        sent = mailer.send_magic_link(email, url)
        if not sent:
            log.info("DEV-MODE magic link for %s: %s", email, url)
        return render(request, "login_sent.html", {"email": email, "sent": sent})
    finally:
        con.close()


@router.get("/auth/{token}")
def auth_click(request: Request, token: str):
    con = db.connect()
    try:
        email = auth.redeem_token(con, token)
        if not email:
            return render(request, "login.html",
                          {"error": "That sign-in link is invalid or expired — "
                                    "request a fresh one.", "email": ""},
                          status_code=400)
        user = db.ensure_user(con, email)
        # welcome=1 surfaces the "signed in for 90 days on this device" note once
        dest = "/dashboard?welcome=1" if user["onboarded_at"] else "/onboarding?welcome=1"
        resp = RedirectResponse(dest, status_code=303)
        set_session_cookie(resp, user["id"])
        return resp
    finally:
        con.close()


@router.get("/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    clear_session_cookie(resp)
    return resp


@router.get("/about-scores")
def about_scores(request: Request):
    con = db.connect()
    try:
        get_user(request, con)
        return render(request, "about_scores.html")
    finally:
        con.close()


@router.get("/about")
def about(request: Request):
    con = db.connect()
    try:
        get_user(request, con)
        return render(request, "about.html")
    finally:
        con.close()


@router.get("/privacy")
def privacy(request: Request):
    con = db.connect()
    try:
        get_user(request, con)
        return render(request, "privacy.html")
    finally:
        con.close()


@router.get("/unsubscribe/{token}")
def unsubscribe(request: Request, token: str):
    """One-click unsubscribe from briefing-email footers: a signed token
    switches the account to dashboard-only — no login needed, idempotent,
    and it can only ever turn email OFF."""
    con = db.connect()
    try:
        get_user(request, con)
        uid = auth.read_unsubscribe_token(token)
        user = db.get_user(con, uid) if uid is not None else None
        if not user:
            return render(request, "unsubscribed.html", {"ok": False},
                          status_code=400)
        con.execute("UPDATE users SET frequency='none' WHERE id=?", (uid,))
        con.commit()
        return render(request, "unsubscribed.html",
                      {"ok": True, "email": user["email"]})
    finally:
        con.close()
