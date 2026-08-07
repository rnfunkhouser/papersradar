"""OpenAlex client used by onboarding (seed lookup-and-confirm) and by the
pipeline (seed record fetch, gathering). Keyless "polite pool" (mailto param).
Base URL is configurable so tests run against a local stub.
"""
from __future__ import annotations

import json
import re
import ssl
import time
import urllib.parse
import urllib.request

from app.config import cfg

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.I)


def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def get_json(url: str, tries: int = 3, pause: float = 1.0):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": f"papersradar ({cfg('OPENALEX_MAILTO')})"})
            with urllib.request.urlopen(req, timeout=30, context=_ssl_ctx()) as r:
                return json.load(r)
        except Exception:
            if attempt + 1 == tries:
                return None
            time.sleep(pause * (attempt + 1))
    return None


def _mailto() -> str:
    return urllib.parse.quote(cfg("OPENALEX_MAILTO"))


def parse_work(w: dict) -> dict:
    """OpenAlex work -> our normalized record (same fields the old parse_openalex
    produced, minus internals)."""
    src = (w.get("primary_location") or {}).get("source") or {}
    return {
        "openalex_id": (w.get("id") or "").rsplit("/", 1)[-1],
        "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
        "title": (w.get("title") or w.get("display_name") or "").strip(),
        "venue": src.get("display_name") or "",
        "authors": [a["author"]["display_name"] for a in w.get("authorships", [])
                    if a.get("author")],
        "date": w.get("publication_date", "") or "",
        "created": w.get("created_date", "") or "",
        "type": w.get("type", "") or "",
        "language": w.get("language") or "",
        "abstract": reconstruct_abstract(w.get("abstract_inverted_index")),
        "concept_ids": [c["id"] for c in w.get("concepts", [])
                        if c.get("score", 0) >= 0.3],
        "countries": sorted({(i.get("country_code") or "").upper()
                             for a in w.get("authorships", [])
                             for i in (a.get("institutions") or [])
                             if i.get("country_code")}),
        "cited_by": w.get("cited_by_count", 0),
        "oa_url": (w.get("open_access") or {}).get("oa_url") or "",
        "source": "openalex",
    }


ABSTRACT_CAP = 8000


def cap_abstract(text: str) -> str:
    """Never cut mid-sentence (ported verbatim from harvest.py)."""
    text = (text or "").strip()
    if len(text) <= ABSTRACT_CAP:
        return text
    cut = text[:ABSTRACT_CAP]
    end = max(cut.rfind(". "), cut.rfind(".\n"), cut.rfind("? "), cut.rfind("! "))
    return cut[:end + 1] if end > 200 else cut


def reconstruct_abstract(inv) -> str:
    if not inv:
        return ""
    words = {}
    for word, idxs in inv.items():
        for i in idxs:
            words[i] = word
    return cap_abstract(" ".join(words[i] for i in sorted(words)))


def lookup(text: str) -> dict | None:
    """Resolve one pasted line (DOI, DOI URL, or title) to a work record.
    Returns the parsed record or None. This powers lookup-and-confirm."""
    text = (text or "").strip()
    if not text:
        return None
    base = cfg("OPENALEX_BASE").rstrip("/")
    m = DOI_RE.search(text)
    if m:
        doi = m.group(0).rstrip(".,;)")
        data = get_json(f"{base}/works/https://doi.org/"
                        f"{urllib.parse.quote(doi, safe='')}?mailto={_mailto()}")
        if data and data.get("id"):
            return parse_work(data)
        return None
    # title search — take the top hit only if it's a close match
    q = urllib.parse.quote(text[:300])
    data = get_json(f"{base}/works?search={q}&per-page=1&mailto={_mailto()}")
    results = (data or {}).get("results") or []
    if not results:
        return None
    rec = parse_work(results[0])
    a, b = _norm_title(text), _norm_title(rec["title"])
    if a and b and (a in b or b in a or _token_overlap(a, b) >= 0.6):
        return rec
    return None


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", (t or "").lower()).strip()


def _token_overlap(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    return len(sa & sb) / max(1, len(sa | sb))
