"""Shared web helpers: template env, per-request DB, session -> user."""
from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import db, auth

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# The founder's real profile, shown as the worked example in the structured
# interest editor (onboarding + settings).
from app import founder_example  # noqa: E402
templates.env.globals["founder"] = {
    "attribution": founder_example.FOUNDER_ATTRIBUTION,
    "core_statement": founder_example.FOUNDER_CORE_STATEMENT,
    "flavors": founder_example.FOUNDER_FLAVORS,
    "negatives": founder_example.FOUNDER_NEGATIVES,
}

SESSION_COOKIE = "pr_session"


def render(request: Request, name: str, ctx: dict | None = None,
           status_code: int = 200):
    from app.config import cfg
    ctx = dict(ctx or {})
    ctx["request"] = request
    ctx.setdefault("user", getattr(request.state, "user", None))
    # public repo link; empty hides it AND any open-source wording site-wide
    ctx.setdefault("source_url", cfg("SOURCE_URL").strip())
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def get_user(request: Request, con):
    uid = auth.read_session(request.cookies.get(SESSION_COOKIE))
    if uid is None:
        return None
    user = db.get_user(con, uid)
    request.state.user = user
    return user


def login_redirect() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


def set_session_cookie(resp, uid: int) -> None:
    resp.set_cookie(SESSION_COOKIE, auth.make_session(uid),
                    max_age=auth.SESSION_TTL_DAYS * 86400,
                    httponly=True, samesite="lax",
                    secure=request_is_https())


def request_is_https() -> bool:
    from app.config import cfg
    return cfg("BASE_URL").startswith("https://")


def clear_session_cookie(resp) -> None:
    resp.delete_cookie(SESSION_COOKIE)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"
