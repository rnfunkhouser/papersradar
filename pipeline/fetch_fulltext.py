#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Full-text stage: fetch OPEN-ACCESS full text for papers briefed today to
podcast-enabled users, so podcast scripts are grounded in the actual paper
instead of the abstract (ported from the single-user system's
fetch_fulltext.py, 2026-07).

Open-access routes only (no library-proxy automation — publisher licenses
prohibit it):
    1. arXiv                → the PDF always exists (abs URL -> /pdf/)
    2. Unpaywall (by DOI)   → best OA location's PDF, else its HTML page
    3. the record's oa_url  → whatever it serves (sniffed: PDF vs HTML)

Files land in <data dir>/fulltext/<date>/; results are recorded in
paper_fulltext (status 'ok' with path/route/kind, or 'none' as a negative
cache so a paywalled paper isn't retried every day). Best-effort throughout:
a paper that can't be fetched keeps its abstract-only treatment.

    python3 -m pipeline.fetch_fulltext              # today's briefed papers
    python3 -m pipeline.fetch_fulltext --date 2026-08-31
"""
from __future__ import annotations

import argparse
import re
import ssl
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import cfg, cfg_int, db_path
from app import db as appdb

TIMEOUT = 60


def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _get(url: str, accept: str = "*/*") -> tuple[bytes, str]:
    ua = f"papersradar fulltext fetcher (mailto:{cfg('OPENALEX_MAILTO')})"
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": accept})
    max_bytes = cfg_int("FULLTEXT_MAX_MB") * 1024 * 1024
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_ctx()) as r:
        data = r.read(max_bytes + 1)
        ctype = (r.headers.get("Content-Type") or "").lower()
    if len(data) > max_bytes:
        return b"", ""
    return data, ctype


def _sniff(data: bytes, ctype: str) -> str | None:
    """'pdf' | 'html' | None — magic bytes + Content-Type, never the extension."""
    if data[:5] == b"%PDF-":
        return "pdf"
    if "pdf" in ctype:
        return None                       # claimed PDF without the magic bytes
    if "html" in ctype or data[:200].lstrip()[:1] in (b"<",):
        return "html"
    return None


def _unpaywall(doi: str) -> dict:
    import json as _json
    url = (f"{cfg('UNPAYWALL_BASE').rstrip('/')}/v2/{quote(doi)}"
           f"?email={cfg('OPENALEX_MAILTO')}")
    try:
        data, _ = _get(url, accept="application/json")
        return _json.loads(data)
    except Exception:
        return {}


def routes_for(paper) -> list[tuple[str, str]]:
    """Candidate URLs for one paper row, best-first: (url, route_label)."""
    out = []
    oa = (paper["oa_url"] or "").strip()
    doi = (paper["doi"] or "").strip()
    m = re.search(r"arxiv\.org/abs/([^\s?#]+)", oa, re.I)
    if not m and doi.lower().startswith("10.48550/"):
        m = re.search(r"arxiv\.(.+)$", doi, re.I)
    if m:
        out.append((f"{cfg('ARXIV_PDF_BASE').rstrip('/')}/pdf/{m.group(1)}",
                    "arxiv-pdf"))
    if doi:
        loc = (_unpaywall(doi) or {}).get("best_oa_location") or {}
        if loc.get("url_for_pdf"):
            out.append((loc["url_for_pdf"], "unpaywall-pdf"))
        if loc.get("url") and loc.get("url") != loc.get("url_for_pdf"):
            out.append((loc["url"], "unpaywall-page"))
    if oa and "arxiv.org/abs" not in oa.lower():
        out.append((oa, "oa_url"))
    return out


def fetch_one(con, paper, date: str) -> str:
    """Fetch OA full text for one paper row -> resulting status ('ok'|'none').
    Idempotent: an existing 'ok' row backed by a real file is left alone; an
    existing 'none' row is trusted (negative cache)."""
    data_dir = db_path().parent
    row = con.execute("SELECT * FROM paper_fulltext WHERE paper_id=?",
                      (paper["id"],)).fetchone()
    if row:
        if row["status"] == "none":
            return "none"
        f = data_dir / row["path"]
        if f.exists() and f.stat().st_size > 0:
            return "ok"
        con.execute("DELETE FROM paper_fulltext WHERE paper_id=?", (paper["id"],))
    for url, route in routes_for(paper):
        try:
            data, ctype = _get(url)
        except Exception:
            continue
        kind = _sniff(data, ctype) if data else None
        if not kind:
            continue
        # an HTML page under ~15 KB is a landing/paywall stub, not an article
        if kind == "html" and len(data) < 15_000:
            continue
        outdir = data_dir / "fulltext" / date
        outdir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"\W+", "_", (paper["title"] or "paper").lower())[:50]
        f = outdir / f"{paper['id']}_{slug}.{kind}"
        f.write_bytes(data)
        con.execute(
            "INSERT OR REPLACE INTO paper_fulltext(paper_id, status, path, route, "
            "kind, bytes, fetched_at) VALUES(?,?,?,?,?,?,?)",
            (paper["id"], "ok", str(f.relative_to(data_dir)), route, kind,
             len(data), appdb.now()))
        con.commit()
        return "ok"
    con.execute(
        "INSERT OR REPLACE INTO paper_fulltext(paper_id, status, path, route, "
        "kind, bytes, fetched_at) VALUES(?,?,'','','',0,?)",
        (paper["id"], "none", appdb.now()))
    con.commit()
    return "none"


def papers_for_date(con, date: str):
    """Papers briefed on `date` to any podcast-enabled user (deduped)."""
    return con.execute(
        "SELECT DISTINCT p.* FROM briefing_items b "
        "JOIN users u ON u.id = b.user_id AND u.podcast_enabled=1 "
        "JOIN papers p ON p.id = b.paper_id WHERE b.date=?", (date,)).fetchall()


def run(con, date: str | None = None) -> dict:
    date = date or appdb.today()
    if not cfg("PODCAST_ENGINES").strip():
        return {"date": date, "skipped": "PODCAST_ENGINES empty"}
    papers = papers_for_date(con, date)
    got = miss = 0
    for p in papers:
        if fetch_one(con, p, date) == "ok":
            got += 1
        else:
            miss += 1
    summary = {"date": date, "papers": len(papers), "fetched": got, "no_oa": miss}
    print(f"[fulltext] {summary}", file=sys.stderr)
    return summary


# --- text extraction (used by the podcast script writer) ---------------------

EXTRACT_MAX_CHARS = 28_000        # keeps a 5-8 paper day inside judge-size context


def extract_text(con, paper_id: int, limit: int = EXTRACT_MAX_CHARS) -> str:
    """Plain text of a fetched full-text file, '' when unavailable. PDF via
    pypdf, HTML via a stdlib tag-stripper; always capped at `limit` chars."""
    row = con.execute("SELECT * FROM paper_fulltext WHERE paper_id=? AND status='ok'",
                      (paper_id,)).fetchone()
    if not row:
        return ""
    f = db_path().parent / row["path"]
    if not f.exists():
        return ""
    try:
        if row["kind"] == "pdf":
            text = _pdf_text(f, limit)
        else:
            text = _html_text(f.read_bytes())
    except Exception:
        return ""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit]


def _pdf_text(path: Path, limit: int) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    parts = []
    total = 0
    for page in reader.pages:
        t = page.extract_text() or ""
        parts.append(t)
        total += len(t)
        if total >= limit:
            break
    return "\n".join(parts)


class _HTMLText(HTMLParser):
    SKIP = {"script", "style", "nav", "header", "footer", "noscript"}

    def __init__(self):
        super().__init__()
        self.out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)


def _html_text(data: bytes) -> str:
    p = _HTMLText()
    p.feed(data.decode("utf-8", "replace"))
    return "".join(p.out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", help="briefing date (YYYY-MM-DD, default today)")
    a = ap.parse_args()
    run(appdb.connect(), a.date)
