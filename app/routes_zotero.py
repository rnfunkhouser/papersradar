"""Zotero linking routes — used from onboarding step 3 AND settings.
Flow: connect (validates creds, stores key encrypted) -> pick collection &
preview -> confirm import -> seeds appear; later: re-sync / disconnect.
The API key is never rendered back to the browser after save."""
from __future__ import annotations

import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import auth, db, zotero
from app.web import get_user, login_redirect

router = APIRouter()


def _safe_next(next_url: str) -> str:
    return next_url if next_url.startswith("/") else "/settings"


def get_link(con, uid: int):
    return con.execute("SELECT * FROM zotero_links WHERE user_id=?", (uid,)).fetchone()


def link_ctx(con, uid: int, want_preview: bool = False) -> dict:
    """Template context for the Zotero widget (onboarding + settings).
    Collections are fetched live only when connected; failures degrade to [].
    want_preview=True (the ?zpreview=1 page load) also fetches the items and
    computes the import preview."""
    link = get_link(con, uid)
    if not link:
        return {"zotero": None, "zotero_collections": [], "zotero_preview": None}
    key = auth.decrypt_secret(link["api_key_enc"])
    cols, pv = [], None
    try:
        cols = zotero.fetch_collections(link["library_type"], link["library_id"], key)
        if want_preview:
            items = zotero.fetch_items(link["library_type"], link["library_id"],
                                       key, link["collection_key"] or "")
            pv = zotero.preview(items, json.loads(link["ledger_json"] or "{}"))
    except zotero.ZoteroError:
        pass
    return {"zotero": link, "zotero_collections": cols, "zotero_preview": pv}


def _redirect_with(next_url: str, **params) -> RedirectResponse:
    from urllib.parse import urlencode, urlparse, parse_qsl
    u = urlparse(_safe_next(next_url))
    q = dict(parse_qsl(u.query))
    q.update({k: v for k, v in params.items() if v})
    dest = u.path + ("?" + urlencode(q) if q else "")
    return RedirectResponse(dest, status_code=303)


@router.post("/zotero/connect")
def zotero_connect(request: Request, library_type: str = Form("user"),
                   library_id: str = Form(""), api_key: str = Form(""),
                   next: str = Form("/settings")):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        library_type = library_type if library_type in ("user", "group") else "user"
        library_id = library_id.strip()
        api_key = api_key.strip()
        if not library_id.isdigit():
            return _redirect_with(next, zerr="The library ID should be a number "
                                             "(see the help text below the form).")
        try:
            zotero.fetch_collections(library_type, library_id, api_key)
        except zotero.ZoteroError as e:
            return _redirect_with(next, zerr=str(e))
        con.execute(
            "INSERT INTO zotero_links(user_id, library_type, library_id, "
            "collection_key, api_key_enc, connected_at, ledger_json) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
            "library_type=excluded.library_type, library_id=excluded.library_id, "
            "api_key_enc=excluded.api_key_enc, connected_at=excluded.connected_at",
            (user["id"], library_type, library_id, "",
             auth.encrypt_secret(api_key), db.now(), "{}"))
        con.commit()
        return _redirect_with(next, znotice="Zotero connected — now choose what to "
                                            "import and preview it.")
    finally:
        con.close()


@router.post("/zotero/preview")
def zotero_preview(request: Request, collection_key: str = Form(""),
                   next: str = Form("/settings")):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        link = get_link(con, user["id"])
        if not link:
            return _redirect_with(next, zerr="Connect your Zotero library first.")
        con.execute("UPDATE zotero_links SET collection_key=? WHERE user_id=?",
                    (collection_key.strip(), user["id"]))
        con.commit()
        # the destination page recomputes the preview on load (?zpreview=1) —
        # stateless, so a refresh always shows current numbers
        return _redirect_with(next, zpreview="1")
    finally:
        con.close()


@router.post("/zotero/import")
def zotero_import(request: Request, next: str = Form("/settings")):
    from app.routes_user import _spawn_profile_build
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        link = get_link(con, user["id"])
        if not link:
            return _redirect_with(next, zerr="Connect your Zotero library first.")
        try:
            items = zotero.fetch_items(link["library_type"], link["library_id"],
                                       auth.decrypt_secret(link["api_key_enc"]),
                                       link["collection_key"] or "")
        except zotero.ZoteroError as e:
            return _redirect_with(next, zerr=str(e))
        result = zotero.import_items(con, user["id"], items,
                                     json.loads(link["ledger_json"] or "{}"))
        con.execute("UPDATE zotero_links SET ledger_json=?, last_sync_at=? "
                    "WHERE user_id=?",
                    (json.dumps(result["ledger"]), db.now(), user["id"]))
        con.commit()
        if result["added"]:
            _spawn_profile_build(user["id"])
        msg = (f"Imported {result['added']} paper(s) from Zotero"
               + (f"; {result['skipped_unresolvable']} couldn't be matched "
                  f"(no DOI and no confident title match)"
                  if result["skipped_unresolvable"] else "") + ".")
        return _redirect_with(next, znotice=msg)
    finally:
        con.close()


@router.post("/zotero/resync")
def zotero_resync(request: Request, next: str = Form("/settings")):
    return zotero_import(request, next)


@router.post("/zotero/disconnect")
def zotero_disconnect(request: Request, next: str = Form("/settings")):
    con = db.connect()
    try:
        user = get_user(request, con)
        if not user:
            return login_redirect()
        con.execute("DELETE FROM zotero_links WHERE user_id=?", (user["id"],))
        con.commit()
        return _redirect_with(next, znotice="Zotero disconnected. Your imported "
                                            "seeds are kept — remove any you don't "
                                            "want from the list.")
    finally:
        con.close()
