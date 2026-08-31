"""SQLite access layer: single-file DB, WAL mode, schema-on-connect.

Shared by the web app and the pipeline CLIs. Every caller gets its own
connection (`connect()`); SQLite WAL handles the single-writer coordination
we need (uvicorn single worker + one sequential pipeline process).
"""
from __future__ import annotations

import json
import sqlite3
import datetime as dt

from app.config import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    name        TEXT DEFAULT '',
    is_admin    INTEGER DEFAULT 0,
    frequency   TEXT DEFAULT 'daily',          -- daily | weekly | none
    shortlist_size INTEGER,                    -- NULL = global default
    interest_statement TEXT DEFAULT '',        -- onboarding step 2, in their own words
    onboarded_at TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_tokens (
    token_hash  TEXT PRIMARY KEY,
    email       TEXT NOT NULL,
    dev_link    TEXT,                          -- full URL, dev mode only
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    used_at     TEXT
);
CREATE TABLE IF NOT EXISTS login_attempts (
    email       TEXT,
    ip          TEXT,
    ts          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
    user_id     INTEGER PRIMARY KEY REFERENCES users(id),
    version     TEXT NOT NULL,
    profile_json TEXT NOT NULL,                -- judge.py contract (see DESIGN.md)
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS seeds (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    doi         TEXT DEFAULT '',
    openalex_id TEXT DEFAULT '',
    title       TEXT NOT NULL,
    abstract    TEXT DEFAULT '',
    source      TEXT DEFAULT 'onboarding',     -- onboarding | settings | import
    added_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_seeds_user ON seeds(user_id);
CREATE TABLE IF NOT EXISTS seed_embeddings (
    seed_id     INTEGER NOT NULL REFERENCES seeds(id),
    embedder    TEXT NOT NULL,
    dim         INTEGER NOT NULL,
    vector      BLOB NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE(seed_id, embedder)
);
CREATE TABLE IF NOT EXISTS papers (
    id          INTEGER PRIMARY KEY,
    key         TEXT NOT NULL UNIQUE,          -- doi-lower or normalized title
    doi         TEXT DEFAULT '',
    title       TEXT NOT NULL,
    venue       TEXT DEFAULT '',
    authors_json TEXT DEFAULT '[]',
    pub_date    TEXT DEFAULT '',
    created_date TEXT DEFAULT '',
    type        TEXT DEFAULT '',
    abstract    TEXT DEFAULT '',
    oa_url      TEXT DEFAULT '',
    source      TEXT DEFAULT '',               -- openalex | arxiv | socarxiv | psyarxiv | email (future)
    concept_ids_json TEXT DEFAULT '[]',
    countries_json TEXT DEFAULT '[]',
    first_seen  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_papers_first_seen ON papers(first_seen);
CREATE TABLE IF NOT EXISTS paper_embeddings (
    paper_id    INTEGER NOT NULL REFERENCES papers(id),
    embedder    TEXT NOT NULL,
    dim         INTEGER NOT NULL,
    vector      BLOB NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE(paper_id, embedder)
);
CREATE TABLE IF NOT EXISTS judgments (
    user_id     INTEGER NOT NULL REFERENCES users(id),
    paper_id    INTEGER NOT NULL REFERENCES papers(id),
    profile_version TEXT NOT NULL,
    fit         REAL NOT NULL,                 -- 0-10; -1 = judge failed
    flavors_json TEXT DEFAULT '[]',
    why         TEXT DEFAULT '',
    provider    TEXT DEFAULT '',
    judged_at   TEXT NOT NULL,
    UNIQUE(user_id, paper_id, profile_version)
);
CREATE TABLE IF NOT EXISTS briefing_items (
    user_id     INTEGER NOT NULL REFERENCES users(id),
    date        TEXT NOT NULL,
    paper_id    INTEGER NOT NULL REFERENCES papers(id),
    rank        INTEGER NOT NULL,
    fit         REAL,
    UNIQUE(user_id, date, paper_id)
);
CREATE TABLE IF NOT EXISTS feedback (
    user_id     INTEGER NOT NULL REFERENCES users(id),
    paper_id    INTEGER NOT NULL REFERENCES papers(id),
    vote        TEXT NOT NULL,                 -- up | down | '' (cleared)
    title       TEXT DEFAULT '',
    ts          TEXT NOT NULL,
    UNIQUE(user_id, paper_id)
);
CREATE TABLE IF NOT EXISTS clicks (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    paper_id    INTEGER NOT NULL,
    ts          TEXT NOT NULL,
    context     TEXT DEFAULT ''                -- dashboard | email
);
CREATE TABLE IF NOT EXISTS provider_usage (
    date        TEXT NOT NULL,
    provider    TEXT NOT NULL,
    ok_count    INTEGER DEFAULT 0,
    err_count   INTEGER DEFAULT 0,
    last_detail TEXT DEFAULT '',
    last_ts     TEXT DEFAULT '',
    UNIQUE(date, provider)
);
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id          INTEGER PRIMARY KEY,
    stage       TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT DEFAULT 'running',        -- running | ok | error
    detail      TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS zotero_links (
    user_id     INTEGER PRIMARY KEY REFERENCES users(id),
    library_type TEXT NOT NULL,               -- user | group
    library_id  TEXT NOT NULL,
    collection_key TEXT DEFAULT '',           -- '' = entire library
    api_key_enc TEXT DEFAULT '',              -- encrypted at rest; NEVER sent to browser
    connected_at TEXT NOT NULL,
    last_sync_at TEXT,
    ledger_json TEXT DEFAULT '{}'             -- {dois: [], keys: []} append-only sync ledger
);
-- Journal/venue registry (OpenAlex sources). country_code powers the
-- Western-context scope option; rows are written by the priority-journal
-- autocomplete and by the gather stage's source enrichment.
CREATE TABLE IF NOT EXISTS sources (
    id          TEXT PRIMARY KEY,               -- OpenAlex source id (S...)
    display_name TEXT DEFAULT '',
    country_code TEXT DEFAULT '',               -- ISO 3166-1 alpha-2, '' = unknown
    type        TEXT DEFAULT '',
    fetched_at  TEXT
);
-- Per-user priority journals: gathered unconditionally, and given guaranteed
-- judge slots when relevance clears PRIORITY_JOURNAL_MIN_REL_PCTL.
CREATE TABLE IF NOT EXISTS priority_journals (
    user_id     INTEGER NOT NULL REFERENCES users(id),
    source_id   TEXT NOT NULL,
    display_name TEXT DEFAULT '',
    country_code TEXT DEFAULT '',
    added_at    TEXT NOT NULL,
    UNIQUE(user_id, source_id)
);
-- AI profile coach: per-user daily rate limit counter (all coach modes share
-- one budget), the latest unsaved autofill draft, and the audit history.
CREATE TABLE IF NOT EXISTS coach_usage (
    user_id     INTEGER NOT NULL REFERENCES users(id),
    date        TEXT NOT NULL,
    count       INTEGER DEFAULT 0,
    UNIQUE(user_id, date)
);
CREATE TABLE IF NOT EXISTS coach_drafts (
    user_id     INTEGER PRIMARY KEY REFERENCES users(id),
    draft_json  TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_audits (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL,
    n_votes     INTEGER DEFAULT 0,
    proposals_json TEXT DEFAULT '[]',
    provider    TEXT DEFAULT ''
);
-- One-shot data fix-ups that have run against this DB (see DATA_MIGRATIONS).
CREATE TABLE IF NOT EXISTS data_migrations (
    name        TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL
);
-- Open-access full text fetched for briefed papers (podcast grounding; see
-- docs/PODCAST_DESIGN.md). Shared corpus data, keyed by paper — status 'none'
-- is a negative cache so a paper with no OA copy isn't retried daily.
CREATE TABLE IF NOT EXISTS paper_fulltext (
    paper_id    INTEGER PRIMARY KEY REFERENCES papers(id),
    status      TEXT NOT NULL,                 -- ok | none
    path        TEXT DEFAULT '',               -- relative to the data dir
    route       TEXT DEFAULT '',               -- arxiv-pdf | unpaywall-pdf | unpaywall-page | oa_url
    kind        TEXT DEFAULT '',               -- pdf | html
    bytes       INTEGER DEFAULT 0,
    fetched_at  TEXT NOT NULL
);
-- Daily podcast episodes (owner-only feature for now; users.podcast_enabled
-- gates it). One row per (user, date, engine) — the trial runs two engines.
CREATE TABLE IF NOT EXISTS podcast_episodes (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    date        TEXT NOT NULL,
    engine      TEXT NOT NULL,                 -- anchor | nlm
    status      TEXT NOT NULL,                 -- ok | error
    detail      TEXT DEFAULT '',               -- error cause, for the email footer
    title       TEXT DEFAULT '',
    audio_path  TEXT DEFAULT '',               -- relative to the data dir
    mime        TEXT DEFAULT '',               -- audio/mpeg | audio/wav
    bytes       INTEGER DEFAULT 0,
    duration_sec INTEGER DEFAULT 0,
    chapters_json TEXT DEFAULT '[]',           -- [{start_sec, title}]
    shownotes_html TEXT DEFAULT '',
    created_at  TEXT NOT NULL,
    UNIQUE(user_id, date, engine)
);
-- The briefing email for podcast users is sent by the podcast stage (so it
-- can carry the episode status footer); this makes that send idempotent
-- across the 90-minute retry run.
CREATE TABLE IF NOT EXISTS podcast_email_log (
    user_id     INTEGER NOT NULL REFERENCES users(id),
    date        TEXT NOT NULL,
    sent_at     TEXT NOT NULL,
    UNIQUE(user_id, date)
);
-- RESERVED for per-user inbound email (Scholar alert forwarding) — nothing
-- writes this yet; see DESIGN.md §7.
CREATE TABLE IF NOT EXISTS email_ingest (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id),
    msg_id      TEXT,
    received_at TEXT,
    from_addr   TEXT,
    subject     TEXT,
    raw_path    TEXT,
    parsed_json TEXT,
    status      TEXT DEFAULT 'new'
);
"""


# Additive migrations for existing databases (CREATE TABLE IF NOT EXISTS never
# adds columns). Applied on connect; each is a no-op once present.
MIGRATIONS = [
    # structured research-interest onboarding (2026-08): repeatable topic
    # entries + explicit exclusions, kept alongside the legacy paragraph
    ("users", "interest_flavors_json",
     "ALTER TABLE users ADD COLUMN interest_flavors_json TEXT DEFAULT '[]'"),
    ("users", "interest_negatives_json",
     "ALTER TABLE users ADD COLUMN interest_negatives_json TEXT DEFAULT '[]'"),
    # briefing ordering tiebreak (2026-08): the shortlist's embedding relevance
    # for this (user, paper), captured at judge time. NULL on legacy rows —
    # the briefings stage backfills rows that can still enter a briefing.
    ("judgments", "relevance",
     "ALTER TABLE judgments ADD COLUMN relevance REAL"),
    # Western-context scope option (2026-08, per-user, default OFF): hard
    # venue-country filter + soft topical deprioritization in the judge prompt.
    ("users", "western_context",
     "ALTER TABLE users ADD COLUMN western_context INTEGER DEFAULT 0"),
    # per-user briefing size 5-10 (2026-08): NULL = global BRIEFING_MAX_ITEMS,
    # same override pattern as users.shortlist_size.
    ("users", "briefing_size",
     "ALTER TABLE users ADD COLUMN briefing_size INTEGER"),
    # OpenAlex source id of the paper's venue (2026-08) — joins to sources for
    # priority-journal marking and the Western-context country filter.
    ("papers", "source_id",
     "ALTER TABLE papers ADD COLUMN source_id TEXT DEFAULT ''"),
    # Onboarding entry fork (2026-08): 'papers' (seeds first, coach-drafted
    # criteria) or 'manual' (write criteria first). '' = fork not answered;
    # users who progressed before the fork existed continue as 'manual'.
    ("users", "onboarding_path",
     "ALTER TABLE users ADD COLUMN onboarding_path TEXT DEFAULT ''"),
    # Daily podcast (2026-08, owner-only for now): enabled flag + the secret
    # in the user's private RSS feed URL. Set via `python3 -m pipeline.podcast
    # enable <email>`; no self-serve UI yet.
    ("users", "podcast_enabled",
     "ALTER TABLE users ADD COLUMN podcast_enabled INTEGER DEFAULT 0"),
    ("users", "podcast_token",
     "ALTER TABLE users ADD COLUMN podcast_token TEXT DEFAULT ''"),
]


def _scrub_html_entities(con: sqlite3.Connection) -> None:
    """One-time fix-up (2026-08): early ingests stored HTML entities from
    OpenAlex/arXiv ('AI &amp;amp; Society'), which templates then escaped
    AGAIN at render. Ingest now unescapes (openalex.clean_text); this scrubs
    the rows stored before the fix. Idempotent — clean_text is a fixpoint.
    Past sent emails cannot be fixed; dashboards and future emails render
    clean after this runs."""
    from app.openalex import clean_text
    for r in con.execute("SELECT id, title, venue, abstract, authors_json "
                         "FROM papers WHERE title LIKE '%&%' OR venue LIKE '%&%' "
                         "OR abstract LIKE '%&%' OR authors_json LIKE '%&%'").fetchall():
        try:
            authors = json.loads(r["authors_json"] or "[]")
        except ValueError:
            authors = []
        con.execute(
            "UPDATE papers SET title=?, venue=?, abstract=?, authors_json=? WHERE id=?",
            (clean_text(r["title"]), clean_text(r["venue"]),
             clean_text(r["abstract"]),
             json.dumps([clean_text(str(a)) for a in authors]), r["id"]))
    for r in con.execute("SELECT id, title, abstract FROM seeds "
                         "WHERE title LIKE '%&%' OR abstract LIKE '%&%'").fetchall():
        con.execute("UPDATE seeds SET title=?, abstract=? WHERE id=?",
                    (clean_text(r["title"]), clean_text(r["abstract"]), r["id"]))
    for r in con.execute("SELECT user_id, paper_id, title FROM feedback "
                         "WHERE title LIKE '%&%'").fetchall():
        con.execute("UPDATE feedback SET title=? WHERE user_id=? AND paper_id=?",
                    (clean_text(r["title"]), r["user_id"], r["paper_id"]))


# One-shot data fix-ups, tracked in data_migrations so each runs exactly once
# per database (they are also safe to re-run by hand).
DATA_MIGRATIONS = [
    ("scrub_html_entities_2026-08", _scrub_html_entities),
]


def _migrate(con: sqlite3.Connection) -> None:
    for table, column, ddl in MIGRATIONS:
        cols = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            con.execute(ddl)
    applied = {r["name"] for r in con.execute("SELECT name FROM data_migrations")}
    for name, fn in DATA_MIGRATIONS:
        if name not in applied:
            fn(con)
            con.execute("INSERT INTO data_migrations(name, applied_at) VALUES(?,?)",
                        (name, now()))
    con.commit()


def connect(path=None) -> sqlite3.Connection:
    con = sqlite3.connect(path or db_path(), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    _migrate(con)
    return con


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def today() -> str:
    return dt.date.today().isoformat()


# --- small shared helpers ----------------------------------------------------

def get_user_by_email(con, email: str):
    return con.execute("SELECT * FROM users WHERE email=?", (email.lower(),)).fetchone()


def get_user(con, uid: int):
    return con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def ensure_user(con, email: str):
    """Existing row or a fresh one (first successful magic-link click)."""
    row = get_user_by_email(con, email)
    if row:
        return row
    con.execute("INSERT INTO users(email, created_at) VALUES(?,?)",
                (email.lower(), now()))
    con.commit()
    return get_user_by_email(con, email)


def get_profile(con, uid: int) -> dict | None:
    row = con.execute("SELECT * FROM profiles WHERE user_id=?", (uid,)).fetchone()
    if not row:
        return None
    prof = json.loads(row["profile_json"])
    prof["version"] = row["version"]
    return prof


def save_profile(con, uid: int, prof: dict, version: str) -> None:
    body = {k: v for k, v in prof.items() if k != "version"}
    con.execute(
        "INSERT INTO profiles(user_id, version, profile_json, updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET version=excluded.version, "
        "profile_json=excluded.profile_json, updated_at=excluded.updated_at",
        (uid, version, json.dumps(body, ensure_ascii=False), now()))
    con.commit()


def delete_user_cascade(con, uid: int) -> None:
    """Self-serve account deletion: remove every row belonging to the user —
    votes, click logs, briefings, judgments, seeds + their vectors, Zotero
    link (and its encrypted key), profile, pending login tokens, rate-limit
    rows, and the account itself. Shared corpus rows (papers) stay: they are
    not personal data."""
    user = get_user(con, uid)
    if not user:
        return
    email = user["email"]
    con.execute("DELETE FROM clicks WHERE user_id=?", (uid,))
    con.execute("DELETE FROM feedback WHERE user_id=?", (uid,))
    con.execute("DELETE FROM briefing_items WHERE user_id=?", (uid,))
    con.execute("DELETE FROM judgments WHERE user_id=?", (uid,))
    con.execute("DELETE FROM seed_embeddings WHERE seed_id IN "
                "(SELECT id FROM seeds WHERE user_id=?)", (uid,))
    con.execute("DELETE FROM seeds WHERE user_id=?", (uid,))
    con.execute("DELETE FROM zotero_links WHERE user_id=?", (uid,))
    con.execute("DELETE FROM priority_journals WHERE user_id=?", (uid,))
    con.execute("DELETE FROM coach_usage WHERE user_id=?", (uid,))
    con.execute("DELETE FROM coach_drafts WHERE user_id=?", (uid,))
    con.execute("DELETE FROM profile_audits WHERE user_id=?", (uid,))
    con.execute("DELETE FROM profiles WHERE user_id=?", (uid,))
    for r in con.execute("SELECT audio_path FROM podcast_episodes "
                         "WHERE user_id=? AND audio_path != ''", (uid,)).fetchall():
        try:
            (db_path().parent / r["audio_path"]).unlink(missing_ok=True)
        except OSError:
            pass
    con.execute("DELETE FROM podcast_episodes WHERE user_id=?", (uid,))
    con.execute("DELETE FROM podcast_email_log WHERE user_id=?", (uid,))
    con.execute("DELETE FROM email_ingest WHERE user_id=?", (uid,))
    con.execute("DELETE FROM auth_tokens WHERE email=?", (email,))
    con.execute("DELETE FROM login_attempts WHERE email=?", (email,))
    con.execute("DELETE FROM users WHERE id=?", (uid,))
    con.commit()


def upsert_source(con, src: dict) -> None:
    """Insert/refresh one OpenAlex source (journal) row. Empty country_code
    never overwrites a known one (works-derived rows are dehydrated)."""
    con.execute(
        "INSERT INTO sources(id, display_name, country_code, type, fetched_at) "
        "VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
        "display_name=excluded.display_name, "
        "country_code=CASE WHEN excluded.country_code='' THEN sources.country_code "
        "ELSE excluded.country_code END, "
        "type=excluded.type, fetched_at=excluded.fetched_at",
        (src["id"], src.get("display_name", ""),
         (src.get("country_code") or "").upper(), src.get("type", ""), now()))


def record_provider(con, provider: str, ok: bool, detail: str = "") -> int:
    """Bump today's counter for a provider; returns ok_count so far today."""
    con.execute(
        "INSERT INTO provider_usage(date, provider, ok_count, err_count, last_detail, last_ts) "
        "VALUES(?,?,?,?,?,?) ON CONFLICT(date, provider) DO UPDATE SET "
        "ok_count = ok_count + excluded.ok_count, err_count = err_count + excluded.err_count, "
        "last_detail = excluded.last_detail, last_ts = excluded.last_ts",
        (today(), provider, 1 if ok else 0, 0 if ok else 1, detail[:200], now()))
    con.commit()
    row = con.execute("SELECT ok_count FROM provider_usage WHERE date=? AND provider=?",
                      (today(), provider)).fetchone()
    return row["ok_count"] if row else 0


def provider_calls_today(con, provider: str) -> int:
    row = con.execute("SELECT ok_count FROM provider_usage WHERE date=? AND provider=?",
                      (today(), provider)).fetchone()
    return row["ok_count"] if row else 0
