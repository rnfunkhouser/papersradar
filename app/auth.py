"""Magic-link auth + signed-cookie sessions. No passwords anywhere.

Tokens: 32 random url-safe bytes; only the SHA-256 hex is stored, single-use,
20-minute expiry. Sessions: `uid.expiry.hmac` signed with APP_SECRET.
Rate limits are DB-backed so they survive restarts.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import re
import secrets

from app.config import cfg, smtp_configured
from app import db

TOKEN_TTL_MIN = 20
SESSION_TTL_DAYS = 30
RATE_PER_EMAIL = 5          # login requests per email per window
RATE_PER_IP = 30            # per client IP per window
RATE_WINDOW_MIN = 15

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RateLimited(Exception):
    pass


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match((email or "").strip().lower())) and len(email) < 200


# --- magic-link tokens -------------------------------------------------------

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def check_rate_limit(con, email: str, ip: str) -> None:
    cutoff = (dt.datetime.now() - dt.timedelta(minutes=RATE_WINDOW_MIN)).isoformat()
    con.execute("DELETE FROM login_attempts WHERE ts < ?",
                ((dt.datetime.now() - dt.timedelta(days=1)).isoformat(),))
    n_email = con.execute("SELECT COUNT(*) c FROM login_attempts WHERE email=? AND ts>=?",
                          (email, cutoff)).fetchone()["c"]
    n_ip = con.execute("SELECT COUNT(*) c FROM login_attempts WHERE ip=? AND ts>=?",
                       (ip, cutoff)).fetchone()["c"]
    if n_email >= RATE_PER_EMAIL or n_ip >= RATE_PER_IP:
        raise RateLimited(f"too many login attempts — wait {RATE_WINDOW_MIN} minutes")
    con.execute("INSERT INTO login_attempts(email, ip, ts) VALUES(?,?,?)",
                (email, ip, db.now()))
    con.commit()


def issue_token(con, email: str) -> tuple[str, str]:
    """Create a login token; returns (token, full_login_url). In dev mode
    (no SMTP) the URL is also stored for the admin dev-links page."""
    email = email.strip().lower()
    token = secrets.token_urlsafe(32)
    url = cfg("BASE_URL").rstrip("/") + "/auth/" + token
    expires = (dt.datetime.now() + dt.timedelta(minutes=TOKEN_TTL_MIN)).isoformat()
    con.execute(
        "INSERT INTO auth_tokens(token_hash, email, dev_link, created_at, expires_at) "
        "VALUES(?,?,?,?,?)",
        (_hash(token), email, url if not smtp_configured() else None,
         db.now(), expires))
    con.commit()
    return token, url


def redeem_token(con, token: str) -> str | None:
    """Single-use redemption -> email, or None if unknown/expired/used."""
    row = con.execute("SELECT * FROM auth_tokens WHERE token_hash=?",
                      (_hash(token),)).fetchone()
    if not row or row["used_at"] or row["expires_at"] < dt.datetime.now().isoformat():
        return None
    con.execute("UPDATE auth_tokens SET used_at=?, dev_link=NULL WHERE token_hash=?",
                (db.now(), row["token_hash"]))
    con.commit()
    return row["email"]


# --- sessions ----------------------------------------------------------------

def _sign(payload: str) -> str:
    secret = cfg("APP_SECRET")
    if not secret:
        raise RuntimeError("APP_SECRET is not set — refusing to sign sessions")
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_session(uid: int) -> str:
    exp = int((dt.datetime.now() + dt.timedelta(days=SESSION_TTL_DAYS)).timestamp())
    payload = f"{uid}.{exp}"
    return payload + "." + _sign(payload)


def read_session(cookie: str | None) -> int | None:
    """Cookie value -> user id, or None if absent/tampered/expired."""
    if not cookie or cookie.count(".") != 2:
        return None
    uid_s, exp_s, sig = cookie.split(".")
    payload = f"{uid_s}.{exp_s}"
    try:
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        if int(exp_s) < dt.datetime.now().timestamp():
            return None
        return int(uid_s)
    except (ValueError, RuntimeError):
        return None
