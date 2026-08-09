"""Zotero client — ported from the single-user harvest.py sync_zotero()
(append-only ledger, DOI from the record or the 'extra' field, confident
title-resolution fallback) and adapted per-user:

  - credentials live in zotero_links (API key encrypted at rest, read-only key
    expected, never rendered back to the browser);
  - the no-DOI fallback resolves the title against OpenAlex (app.openalex.lookup)
    instead of Crossref — same confidence-guarded idea;
  - the ledger ({dois, keys}) is per-user JSON in the same row, so re-sync is
    idempotent and removal-safe: deleting a seed here never gets re-added by a
    later sync, and removing an item from Zotero leaves the seed in place.

Base URL is configurable (ZOTERO_BASE) so tests run against a local stub.
"""
from __future__ import annotations

import json
import re

from app import openalex
from app.config import cfg

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.I)

# A pasted group URL like https://www.zotero.org/groups/1234567/my-seeds
GROUP_URL_RE = re.compile(r"zotero\.org/groups/(\d+)", re.I)


def parse_library_ref(text: str, library_type: str = "group") -> tuple[str, str] | None:
    """User-pasted library reference -> (library_type, library_id) or None.
    Accepts a Zotero group URL (forces type 'group') or a bare numeric ID
    (kept under the given type). Public groups need no API key at all."""
    text = (text or "").strip()
    m = GROUP_URL_RE.search(text)
    if m:
        return "group", m.group(1)
    if text.isdigit():
        return ("group" if library_type == "group" else "user"), text
    return None

# Item types worth seeding (skip attachments, notes, blog posts, web pages...)
SCHOLARLY = {"journalArticle", "bookSection", "book", "conferencePaper",
             "preprint", "report", "thesis", "manuscript"}


def _base() -> str:
    return cfg("ZOTERO_BASE", "https://api.zotero.org").rstrip("/")


def _lib_path(library_type: str, library_id: str) -> str:
    lib = "groups" if library_type == "group" else "users"
    return f"{_base()}/{lib}/{library_id}"


def _get(url: str, api_key: str):
    headers = {"Zotero-API-Version": "3"}
    if api_key:
        headers["Zotero-API-Key"] = api_key
    import urllib.request
    import ssl
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return json.load(r)
    except Exception:
        return None


class ZoteroError(Exception):
    pass


def fetch_collections(library_type: str, library_id: str, api_key: str) -> list[dict]:
    """Top-level collections — also serves as the credentials check.
    Raises ZoteroError when the library is unreachable (bad ID or key)."""
    page = _get(_lib_path(library_type, library_id)
                + "/collections?format=json&limit=100", api_key)
    if page is None:
        raise ZoteroError(
            "Couldn't reach that Zotero library — double-check the group URL/ID "
            "and that the group is set to Public (for a private library, that "
            "the API key has read access to it).")
    return [{"key": c.get("key", ""),
             "name": (c.get("data") or {}).get("name", "(unnamed)")}
            for c in page if c.get("key")]


def fetch_items(library_type: str, library_id: str, api_key: str,
                collection_key: str = "") -> list[dict]:
    """Top-level (parent) items, paginated — /items/top excludes attachments
    and notes, exactly as the single-user sync did."""
    base = _lib_path(library_type, library_id)
    path = (f"/collections/{collection_key}/items/top" if collection_key
            else "/items/top")
    out, start, limit = [], 0, 100
    while True:
        page = _get(f"{base}{path}?format=json&limit={limit}&start={start}", api_key)
        if page is None:
            if not out:
                raise ZoteroError("Couldn't fetch items from that Zotero library.")
            break
        out += page
        if len(page) < limit:
            break
        start += limit
    return out


def scholarly_items(items: list[dict]) -> list[dict]:
    return [it for it in items
            if (it.get("data") or {}).get("itemType") in SCHOLARLY]


def item_doi(data: dict) -> tuple[str, str]:
    """(doi, how) for one Zotero item's data dict: its own DOI field, else a
    DOI hiding in 'extra', else '' (title resolution happens at import time)."""
    doi = (data.get("DOI") or "").strip().replace("https://doi.org/", "")
    if not doi:
        m = DOI_RE.search(data.get("extra", "") or "")
        if m:
            doi = m.group(0).rstrip(".,;)")
    if doi:
        return doi, "DOI in record"
    return "", "no DOI in record"


def resolve_item(data: dict) -> dict | None:
    """One Zotero item -> a seed record {doi, openalex_id, title, abstract} or
    None when unresolvable. DOI'd items are looked up on OpenAlex to pull the
    abstract; no-DOI items are title-resolved against OpenAlex with the
    close-match guard in openalex.lookup()."""
    title = openalex.clean_text((data.get("title") or "").strip())
    z_abstract = openalex.clean_text(data.get("abstractNote") or "")
    doi, _ = item_doi(data)
    if doi:
        rec = openalex.lookup(doi)
        return {"doi": (rec or {}).get("doi") or doi,
                "openalex_id": (rec or {}).get("openalex_id", ""),
                "title": (rec or {}).get("title") or title or doi,
                "abstract": (rec or {}).get("abstract", "") or z_abstract}
    if len(title) < 8:
        return None
    rec = openalex.lookup(title)
    if not rec:
        # keep the item anyway if Zotero itself has an abstract — the embedding
        # only needs title+abstract text, not an OpenAlex identity
        if z_abstract:
            return {"doi": "", "openalex_id": "", "title": title,
                    "abstract": z_abstract}
        return None
    return {"doi": rec.get("doi", ""), "openalex_id": rec.get("openalex_id", ""),
            "title": rec.get("title") or title,
            "abstract": rec.get("abstract", "") or z_abstract}


def preview(items: list[dict], ledger: dict) -> dict:
    """Summarize what an import would do (no network): counts + sample titles."""
    keys_done = set(ledger.get("keys", []))
    sch = scholarly_items(items)
    new = [it for it in sch if it.get("key") not in keys_done]
    with_doi = sum(1 for it in new if item_doi(it.get("data") or {})[0])
    return {
        "total_items": len(items),
        "scholarly": len(sch),
        "new": len(new),
        "already_imported": len(sch) - len(new),
        "with_doi": with_doi,
        "needs_title_match": len(new) - with_doi,
        "sample": [{"title": (it.get("data") or {}).get("title", "(untitled)")[:110],
                    "has_doi": bool(item_doi(it.get("data") or {})[0])}
                   for it in new[:20]],
    }


def import_items(con, user_id: int, items: list[dict], ledger: dict) -> dict:
    """Append-only import into seeds (source='zotero'), mirroring sync_zotero():
    a Zotero item key is processed once ever; a DOI ever imported is never
    re-added (so user deletions stick). Returns counts + the updated ledger."""
    from app import db as appdb
    dois_led = set(ledger.get("dois", []))
    keys_led = set(ledger.get("keys", []))
    existing = {r["doi"].lower() for r in con.execute(
        "SELECT doi FROM seeds WHERE user_id=?", (user_id,)).fetchall() if r["doi"]}
    added, skipped = 0, 0
    for it in scholarly_items(items):
        key = it.get("key") or ""
        if key and key in keys_led:
            continue
        if key:
            keys_led.add(key)
        rec = resolve_item(it.get("data") or {})
        if not rec or not rec.get("title"):
            skipped += 1
            continue
        dl = (rec.get("doi") or "").lower()
        if dl:
            if dl in dois_led:               # imported before -> respect removals
                continue
            dois_led.add(dl)
            if dl in existing:
                continue
            existing.add(dl)
        con.execute(
            "INSERT INTO seeds(user_id, doi, openalex_id, title, abstract, source, "
            "added_at) VALUES(?,?,?,?,?,?,?)",
            (user_id, rec.get("doi", ""), rec.get("openalex_id", ""),
             rec["title"], rec.get("abstract", ""), "zotero", appdb.now()))
        added += 1
    con.commit()
    return {"added": added, "skipped_unresolvable": skipped,
            "ledger": {"dois": sorted(dois_led), "keys": sorted(keys_led)}}
