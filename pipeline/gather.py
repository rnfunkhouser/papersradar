#!/usr/bin/env python3
"""Gathering stage: build the SHARED daily corpus from OpenAlex (union of all
users' retrieval concepts), arXiv, and OSF preprint servers. Ported and
trimmed from the single-user harvest.py. Dedupe against papers.key; only new
rows are inserted, so re-runs are idempotent and free.
"""
from __future__ import annotations

import json
import re
import sys
import time
import datetime as dt
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import cfg, cfg_int
from app import db as appdb
from app import openalex

OPENALEX_PER_PAGE = 200
ARXIV_CATS = ["cs.CY", "cs.SI", "cs.CL"]
ARXIV_MAX = 120
OSF_PROVIDERS = ("socarxiv", "psyarxiv")
OSF_MAX_PER_PROVIDER = 800

NOISE_TITLE = re.compile(
    r"\b(retraction|erratum|corrigendum|correction to|editorial board|"
    r"issue information|table of contents|front matter|back matter)\b", re.I)
GOOD_TYPES = {"article", "preprint", "posted-content"}
BOOK_REVIEW_RE = re.compile(r"^\s*(book review|review of\b|review essay)", re.I)


def key_of(rec: dict) -> str:
    """Paper identity: doi-lower, else normalized title (same as harvest.py)."""
    return (rec.get("doi", "") or "").lower() or \
        re.sub(r"\W+", "", (rec.get("title", "") or "").lower())[:60]


def keep(rec: dict) -> bool:
    """Noise/type/language filters — ported from harvest.keep()."""
    t = rec.get("title") or ""
    if not t or NOISE_TITLE.search(t) or BOOK_REVIEW_RE.match(t):
        return False
    if rec.get("language") and rec["language"] != "en":
        return False
    if rec.get("type") and rec["type"] not in GOOD_TYPES:
        return False
    if len(t.split()) < 4:
        return False
    try:
        if (dt.date.fromisoformat(rec["date"]) - dt.date.today()).days > 90:
            return False
    except Exception:
        pass
    return True


# --- sources -----------------------------------------------------------------

def union_concepts(con) -> list[str]:
    """Union of retrieval concepts across all onboarded users' profiles,
    ordered by how many users share each (shared interests paged first)."""
    counts: dict[str, int] = {}
    for row in con.execute("SELECT profile_json FROM profiles"):
        prof = json.loads(row["profile_json"])
        for cid in prof.get("retrieval_concepts", []):
            counts[cid] = counts.get(cid, 0) + 1
    return [c for c, _ in sorted(counts.items(), key=lambda kv: -kv[1])]


def _page_works(filter_extra: str, since: str, cap: int) -> list[dict]:
    """Cursor-page one /works filter query, newest first, up to `cap`."""
    base = cfg("OPENALEX_BASE").rstrip("/")
    mailto = urllib.parse.quote(cfg("OPENALEX_MAILTO"))
    out = []
    cursor, pulled = "*", 0
    while cursor and pulled < cap:
        url = (f"{base}/works?filter=from_publication_date:{since},"
               f"{filter_extra},type:article,language:en"
               f"&per-page={OPENALEX_PER_PAGE}&sort=publication_date:desc"
               f"&cursor={urllib.parse.quote(cursor)}&mailto={mailto}")
        data = openalex.get_json(url)
        if not data:
            break
        results = data.get("results", [])
        out.extend(openalex.parse_work(w) for w in results)
        pulled += len(results)
        cursor = (data.get("meta") or {}).get("next_cursor")
        if not results:
            break
        time.sleep(0.2)
    return out


def harvest_openalex(concepts: list[str], since: str,
                     max_per_concept: int | None = None) -> list[dict]:
    cap = max_per_concept or cfg_int("OPENALEX_MAX_PER_CONCEPT")
    out = []
    for cid in concepts:
        short = cid.rsplit("/", 1)[-1]
        out.extend(_page_works(f"concepts.id:{short}", since, cap))
    return out


def priority_journal_ids(con) -> list[str]:
    """Union of ALL users' priority journals (shared gather cost)."""
    return [r["source_id"] for r in con.execute(
        "SELECT DISTINCT source_id FROM priority_journals ORDER BY source_id")]


def harvest_priority_journals(con, since: str) -> list[dict]:
    """Recent works from every user's priority journals. These may sit outside
    the concept-derived queries entirely, so they are fetched explicitly and
    deduped into the shared corpus like any other source."""
    cap = cfg_int("OPENALEX_MAX_PER_JOURNAL")
    out = []
    for sid in priority_journal_ids(con):
        out.extend(_page_works(f"primary_location.source.id:{sid}", since, cap))
    return out


def enrich_sources(con) -> int:
    """Fill the sources table (incl. country_code, used by the Western-context
    venue filter) for venue ids seen on papers but not fetched yet — works
    responses carry only dehydrated sources without a country."""
    missing = [r["source_id"] for r in con.execute(
        "SELECT DISTINCT source_id FROM papers WHERE source_id != '' "
        "AND source_id NOT IN (SELECT id FROM sources)")]
    if not missing:
        return 0
    n = 0
    for src in openalex.fetch_sources_by_id(missing):
        if src.get("id"):
            appdb.upsert_source(con, src)
            n += 1
    con.commit()
    return n


def harvest_arxiv(since: str) -> list[dict]:
    import urllib.request
    cat_q = "+OR+".join(f"cat:{c}" for c in ARXIV_CATS)
    base = cfg("ARXIV_BASE", "https://export.arxiv.org").rstrip("/")
    url = (f"{base}/api/query?search_query=({cat_q})"
           f"&start=0&max_results={ARXIV_MAX}&sortBy=submittedDate&sortOrder=descending")
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            xml = r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"[gather] arxiv failed ({e}) — non-fatal", file=sys.stderr)
        return []
    out = []
    for entry in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        def tag(t):
            m = re.search(fr"<{t}>(.*?)</{t}>", entry, re.S)
            return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
        date = tag("published")[:10]
        if date < since:
            continue
        out.append({
            "source": "arxiv", "doi": "", "title": openalex.clean_text(tag("title")),
            "venue": "arXiv (preprint)",
            "authors": [openalex.clean_text(n)
                        for n in re.findall(r"<name>(.*?)</name>", entry)],
            "date": date, "created": date, "type": "preprint",
            "abstract": openalex.cap_abstract(tag("summary")),
            "concept_ids": [], "countries": [],
            "oa_url": (re.search(r"<id>(.*?)</id>", entry) or [None, ""])[1],
        })
    return out


def harvest_osf(since: str) -> list[dict]:
    out = []
    for prov in OSF_PROVIDERS:
        venue = {"socarxiv": "SocArXiv (preprint)",
                 "psyarxiv": "PsyArXiv (preprint)"}[prov]
        osf_base = cfg("OSF_BASE", "https://api.osf.io").rstrip("/")
        url = (osf_base + "/v2/preprints/?filter[provider]=" + prov
               + "&filter[date_published][gte]=" + since
               + "&page[size]=100&sort=-date_published")
        pulled = 0
        while url and pulled < OSF_MAX_PER_PROVIDER:
            d = openalex.get_json(url)
            if not d:
                break
            for r in d.get("data", []):
                a = r.get("attributes") or {}
                doi = ((r.get("links") or {}).get("preprint_doi") or "")
                doi = re.sub(r"_v\d+$", "", doi.replace("https://doi.org/", ""))
                out.append({
                    "source": prov, "doi": doi,
                    "title": openalex.clean_text((a.get("title") or "").strip()),
                    "venue": venue, "authors": [],
                    "date": (a.get("date_published") or "")[:10],
                    "created": (a.get("date_published") or "")[:10],
                    "type": "preprint",
                    "abstract": openalex.cap_abstract(a.get("description") or ""),
                    "concept_ids": [], "countries": [],
                    "oa_url": ((r.get("links") or {}).get("html") or ""),
                })
            pulled += len(d.get("data", []))
            url = (d.get("links") or {}).get("next")
        print(f"[gather] {prov}: {pulled} preprints", file=sys.stderr)
    return out


# --- persistence -------------------------------------------------------------

def insert_new(con, records: list[dict]) -> int:
    """Dedupe within batch + against papers.key; insert only new rows."""
    seen_batch: set[str] = set()
    n = 0
    for rec in records:
        if not keep(rec):
            continue
        k = key_of(rec)
        if not k or k in seen_batch:
            continue
        seen_batch.add(k)
        cur = con.execute(
            "INSERT OR IGNORE INTO papers(key, doi, title, venue, authors_json, "
            "pub_date, created_date, type, abstract, oa_url, source, source_id, "
            "concept_ids_json, countries_json, first_seen) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (k, rec.get("doi", ""), rec.get("title", ""), rec.get("venue", ""),
             json.dumps(rec.get("authors", [])[:20]), rec.get("date", ""),
             rec.get("created", ""), rec.get("type", ""),
             rec.get("abstract", ""), rec.get("oa_url", ""),
             rec.get("source", ""), rec.get("source_id", ""),
             json.dumps(rec.get("concept_ids", [])),
             json.dumps(rec.get("countries", [])), appdb.today()))
        n += cur.rowcount
    con.commit()
    return n


def run(con, since: str | None = None) -> dict:
    """The gather stage. Returns a summary dict for pipeline_runs.detail."""
    if since is None:
        has_any = con.execute("SELECT COUNT(*) c FROM papers").fetchone()["c"]
        days = 14 if not has_any else cfg_int("GATHER_WINDOW_DAYS")
        since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    concepts = union_concepts(con)
    recs = harvest_openalex(concepts, since)
    n_oa = insert_new(con, recs)
    n_ax = insert_new(con, harvest_arxiv(since))
    n_osf = insert_new(con, harvest_osf(since))
    n_pj = insert_new(con, harvest_priority_journals(con, since))
    n_src = enrich_sources(con)
    summary = {"since": since, "concepts": len(concepts),
               "new_openalex": n_oa, "new_arxiv": n_ax, "new_osf": n_osf,
               "new_priority_journal": n_pj, "sources_enriched": n_src}
    print(f"[gather] {summary}", file=sys.stderr)
    return summary
