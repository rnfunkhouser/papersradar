#!/usr/bin/env python3
"""Briefing stage: per user due today, select judged-but-never-briefed papers
(fit >= BRIEFING_MIN_FIT, top BRIEFING_MAX_ITEMS) into briefing_items — the
dashboard reads that table — and send the email digest when SMTP is
configured (silently dashboard-only otherwise).
"""
from __future__ import annotations

import html
import json
import sys
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import cfg, cfg_int
from app import db as appdb
from app import mailer

WEEKLY_DOW = 0            # Monday


def due_today(user, today: dt.date) -> bool:
    if not user["onboarded_at"]:
        return False
    if user["frequency"] == "weekly":
        return today.weekday() == WEEKLY_DOW
    return True           # daily AND 'none' (dashboard-only) both get items built


def select_items(con, user) -> list:
    """Judged papers above the fit bar that were never briefed to this user.

    Ordering (validated 2026-08 against 41 blind owner ratings — see the
    single-user system's rerank_comparison.md): judge fit is the band, the
    shortlist's embedding relevance orders papers WITHIN a band, pub_date is
    the last tiebreak. Legacy judgments may have NULL relevance (COALESCE 0);
    `backfill_relevance` fills them for users due a briefing."""
    prof = appdb.get_profile(con, user["id"])
    if not prof:
        return []
    min_fit = cfg_int("BRIEFING_MIN_FIT")
    # per-user briefing size (5-10, set in onboarding/settings); NULL = global
    max_items = user["briefing_size"] or cfg_int("BRIEFING_MAX_ITEMS")
    return con.execute(
        "SELECT p.*, j.fit, j.flavors_json, j.why, "
        "COALESCE(s.summary, '') AS gen_summary, "
        "COALESCE(pj.display_name, '') AS pj_name FROM judgments j "
        "JOIN papers p ON p.id = j.paper_id "
        "LEFT JOIN paper_summaries s ON s.paper_id = j.paper_id "
        "LEFT JOIN priority_journals pj ON pj.user_id = j.user_id "
        "     AND pj.source_id = p.source_id AND p.source_id != '' "
        "WHERE j.user_id=? AND j.profile_version=? AND j.fit >= ? "
        "AND j.paper_id NOT IN (SELECT paper_id FROM briefing_items WHERE user_id=?) "
        "ORDER BY j.fit DESC, COALESCE(j.relevance, 0) DESC, p.pub_date DESC LIMIT ?",
        (user["id"], prof["version"], min_fit, user["id"], max_items)).fetchall()


def backfill_relevance(con, user) -> int:
    """Fill judgments.relevance on legacy rows (judged before the column
    existed) that can still enter this user's briefings, so day-one ordering
    works. Reuses the shortlist recipe on vectors already in the DB; the
    contrast centroid is the backfill batch rather than the original 14-day
    pool — an acceptable approximation for legacy rows, since only the
    relative order within this user's judged set matters. Returns rows filled."""
    from pipeline.shortlist import relevance_scores, _load_matrix
    prof = appdb.get_profile(con, user["id"])
    if not prof:
        return 0
    embedder = cfg("EMBEDDER")
    min_fit = cfg_int("BRIEFING_MIN_FIT")
    rows = con.execute(
        "SELECT j.paper_id, pe.vector FROM judgments j "
        "JOIN paper_embeddings pe ON pe.paper_id = j.paper_id AND pe.embedder=? "
        "WHERE j.user_id=? AND j.profile_version=? AND j.relevance IS NULL "
        "AND j.fit >= ? AND j.paper_id NOT IN "
        "(SELECT paper_id FROM briefing_items WHERE user_id=?)",
        (embedder, user["id"], prof["version"], min_fit, user["id"])).fetchall()
    if not rows:
        return 0
    seed_rows = con.execute(
        "SELECT se.seed_id, se.vector FROM seed_embeddings se "
        "JOIN seeds s ON s.id = se.seed_id "
        "WHERE s.user_id=? AND se.embedder=?",
        (user["id"], embedder)).fetchall()
    if not seed_rows:
        return 0
    ids, mat = _load_matrix([(r["paper_id"], r["vector"]) for r in rows])
    _, seeds = _load_matrix([(r["seed_id"], r["vector"]) for r in seed_rows])
    rel = relevance_scores(mat, seeds)
    for pid, rv in zip(ids, rel):
        con.execute(
            "UPDATE judgments SET relevance=? "
            "WHERE user_id=? AND paper_id=? AND profile_version=?",
            (float(rv), user["id"], pid, prof["version"]))
    con.commit()
    return len(ids)


def build_briefing(con, user, date: str) -> list:
    rows = select_items(con, user)
    for rank, r in enumerate(rows, 1):
        con.execute(
            "INSERT OR IGNORE INTO briefing_items(user_id, date, paper_id, rank, fit) "
            "VALUES(?,?,?,?,?)", (user["id"], date, r["id"], rank, r["fit"]))
    con.commit()
    return rows


EMAIL_EXCERPT_CHARS = 700


def email_excerpt(text: str, limit: int = EMAIL_EXCERPT_CHARS) -> str:
    """Abstract excerpt for the email card — never cut mid-sentence (same rule
    as the abstract cap at ingest); falls back to a word boundary + ellipsis."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind(".\n"), cut.rfind("? "), cut.rfind("! "))
    if end > limit * 0.4:
        return cut[:end + 1]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > 0 else cut) + " …"


def render_email(user, rows, date: str) -> str:
    from app import auth
    base = cfg("BASE_URL").rstrip("/")
    nice = dt.date.fromisoformat(date).strftime("%A, %B %d, %Y")
    unsub = auth.make_unsubscribe_token(user["id"])
    freq_phrase = ("weekly (1-per-week)" if user["frequency"] == "weekly"
                   else "daily (7-per-week)")
    cards = []
    for r in rows:
        flavors = ", ".join(f.replace("_", " ")
                            for f in json.loads(r["flavors_json"] or "[]"))
        authors = ", ".join(json.loads(r["authors_json"] or "[]")[:6])
        link = f"{base}/out/{r['id']}?ctx=email"
        try:
            pj_name = r["pj_name"]
        except (KeyError, IndexError):
            pj_name = ""
        pj_line = ""
        if pj_name:
            pj_line = (f'<div style="color:#3730a3;font-size:12px;margin:4px 0">'
                       f'from <i>{html.escape(pj_name)}</i> — your priority list</div>')
        # excerpt the GENERATED summary when one exists (it continues
        # seamlessly on the dashboard card); abstract excerpt is the fallback
        # for rows briefed/emailed before the summaries stage ran
        try:
            body = r["gen_summary"] or r["abstract"] or ""
        except (KeyError, IndexError):
            body = r["abstract"] or ""
        excerpt = email_excerpt(body)
        more = ""
        if excerpt != body.strip():
            more = (f' <a href="{base}/more/{r["id"]}" style="color:#1a56db">'
                    f'Full summary on your dashboard &rarr;</a>')
        cards.append(f"""
        <div style="border:1px solid #e2e8f0;border-radius:10px;padding:16px;margin:0 0 14px">
          <div style="font-size:16px;font-weight:600;line-height:1.4">
            <a href="{link}" style="color:#1a56db;text-decoration:none">{html.escape(r['title'])}</a></div>
          <div style="color:#64748b;font-size:13px;margin:4px 0">{html.escape(authors)}
            · <i>{html.escape(r['venue'] or '')}</i> · {html.escape(r['pub_date'] or '')}</div>
          {pj_line}
          <div style="margin:6px 0"><span style="background:#eef2ff;color:#3730a3;
            border-radius:99px;padding:2px 10px;font-size:12px;font-weight:600">
            {r['fit']:g}/10{(' · ' + html.escape(flavors)) if flavors else ''}</span></div>
          <div style="color:#334155;font-size:14px;font-style:italic">{html.escape(r['why'] or '')}</div>
          <div style="color:#475569;font-size:13px;margin-top:8px">{html.escape(excerpt)}{more}</div>
        </div>""")
    return f"""
    <div style="font-family:system-ui,-apple-system,sans-serif;max-width:640px;margin:0 auto;padding:8px">
      <h2 style="color:#1a56db;margin-bottom:2px"><img src="{base}/static/logo-email.png" width="28" height="28" alt="" style="vertical-align:-5px;margin-right:9px">Research Radar</h2>
      <div style="color:#64748b;margin-bottom:18px">{nice} · {len(rows)} picks for
        {html.escape(user['name'] or user['email'])}</div>
      {''.join(cards)}
      <div style="color:#94a3b8;font-size:12px;margin-top:16px">
        Each pick was scored by an AI judge reading the abstract against your Selection
        Criteria — the chip shows its fit score and matched flavors. Picks are ranked
        by fit; equally fitting papers are ordered by closeness to your seed papers.
        <a href="{base}/dashboard" style="color:#1a56db">Open your dashboard</a> to vote
        on picks or <a href="{base}/settings" style="color:#1a56db">tune your criteria</a>.
      </div>
      <div style="color:#94a3b8;font-size:12px;margin-top:10px;border-top:1px solid #e2e8f0;padding-top:10px">
        Research Radar is a free tool that scans each day's new papers and preprints
        for the ones that fit your research. You're receiving this because you chose
        {freq_phrase} briefings —
        <a href="{base}/settings" style="color:#1a56db">manage</a> or
        <a href="{base}/unsubscribe/{unsub}" style="color:#1a56db">unsubscribe</a> in
        one click.
      </div>
    </div>"""


def email_deferred_to_podcast(user) -> bool:
    """Podcast-enabled users get their briefing email from the podcast stage
    instead (same email + episode status footer), so it can report on
    episodes that don't exist yet when this stage runs."""
    return bool(user["podcast_enabled"]) and bool(cfg("PODCAST_ENGINES").strip())


def run(con, date: str | None = None) -> dict:
    date = date or appdb.today()
    today = dt.date.fromisoformat(date)
    built = sent = deferred = backfilled = 0
    for user in con.execute("SELECT * FROM users").fetchall():
        if not due_today(user, today):
            continue
        backfilled += backfill_relevance(con, user)
        rows = build_briefing(con, user, date)
        if rows:
            built += 1
            if user["frequency"] != "none":
                if email_deferred_to_podcast(user):
                    deferred += 1
                    continue
                subj = f"Research Radar — {len(rows)} picks for {date}"
                if mailer.send(user["email"], subj, render_email(user, rows, date)):
                    sent += 1
    summary = {"date": date, "users_with_items": built, "emails_sent": sent,
               "emails_deferred_to_podcast": deferred,
               "relevance_backfilled": backfilled}
    print(f"[briefings] {summary}", file=sys.stderr)
    return summary
