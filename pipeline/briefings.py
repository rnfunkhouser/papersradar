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
    """Judged papers above the fit bar that were never briefed to this user."""
    prof = appdb.get_profile(con, user["id"])
    if not prof:
        return []
    min_fit = cfg_int("BRIEFING_MIN_FIT")
    max_items = cfg_int("BRIEFING_MAX_ITEMS")
    return con.execute(
        "SELECT p.*, j.fit, j.flavors_json, j.why FROM judgments j "
        "JOIN papers p ON p.id = j.paper_id "
        "WHERE j.user_id=? AND j.profile_version=? AND j.fit >= ? "
        "AND j.paper_id NOT IN (SELECT paper_id FROM briefing_items WHERE user_id=?) "
        "ORDER BY j.fit DESC, p.pub_date DESC LIMIT ?",
        (user["id"], prof["version"], min_fit, user["id"], max_items)).fetchall()


def build_briefing(con, user, date: str) -> list:
    rows = select_items(con, user)
    for rank, r in enumerate(rows, 1):
        con.execute(
            "INSERT OR IGNORE INTO briefing_items(user_id, date, paper_id, rank, fit) "
            "VALUES(?,?,?,?,?)", (user["id"], date, r["id"], rank, r["fit"]))
    con.commit()
    return rows


def render_email(user, rows, date: str) -> str:
    base = cfg("BASE_URL").rstrip("/")
    nice = dt.date.fromisoformat(date).strftime("%A, %B %d, %Y")
    cards = []
    for r in rows:
        flavors = ", ".join(f.replace("_", " ")
                            for f in json.loads(r["flavors_json"] or "[]"))
        authors = ", ".join(json.loads(r["authors_json"] or "[]")[:6])
        link = f"{base}/out/{r['id']}?ctx=email"
        cards.append(f"""
        <div style="border:1px solid #e2e8f0;border-radius:10px;padding:16px;margin:0 0 14px">
          <div style="font-size:16px;font-weight:600;line-height:1.4">
            <a href="{link}" style="color:#1a56db;text-decoration:none">{html.escape(r['title'])}</a></div>
          <div style="color:#64748b;font-size:13px;margin:4px 0">{html.escape(authors)}
            · <i>{html.escape(r['venue'] or '')}</i> · {html.escape(r['pub_date'] or '')}</div>
          <div style="margin:6px 0"><span style="background:#eef2ff;color:#3730a3;
            border-radius:99px;padding:2px 10px;font-size:12px;font-weight:600">
            {r['fit']:g}/10{(' · ' + html.escape(flavors)) if flavors else ''}</span></div>
          <div style="color:#334155;font-size:14px;font-style:italic">{html.escape(r['why'] or '')}</div>
          <div style="color:#475569;font-size:13px;margin-top:8px">{html.escape((r['abstract'] or '')[:600])}{'…' if len(r['abstract'] or '') > 600 else ''}</div>
        </div>""")
    return f"""
    <div style="font-family:system-ui,-apple-system,sans-serif;max-width:640px;margin:0 auto;padding:8px">
      <h2 style="color:#1a56db;margin-bottom:2px">Research Radar</h2>
      <div style="color:#64748b;margin-bottom:18px">{nice} · {len(rows)} picks for
        {html.escape(user['name'] or user['email'])}</div>
      {''.join(cards)}
      <div style="color:#94a3b8;font-size:12px;margin-top:16px">
        Each pick was scored by an AI judge reading the abstract against your Selection
        Criteria — the chip shows its fit score and matched flavors.
        <a href="{base}/dashboard" style="color:#1a56db">Open your dashboard</a> to vote
        on picks or <a href="{base}/settings" style="color:#1a56db">tune your criteria</a>.
      </div>
    </div>"""


def run(con, date: str | None = None) -> dict:
    date = date or appdb.today()
    today = dt.date.fromisoformat(date)
    built = sent = 0
    for user in con.execute("SELECT * FROM users").fetchall():
        if not due_today(user, today):
            continue
        rows = build_briefing(con, user, date)
        if rows:
            built += 1
            if user["frequency"] != "none":
                subj = f"Research Radar — {len(rows)} picks for {date}"
                if mailer.send(user["email"], subj, render_email(user, rows, date)):
                    sent += 1
    summary = {"date": date, "users_with_items": built, "emails_sent": sent}
    print(f"[briefings] {summary}", file=sys.stderr)
    return summary
