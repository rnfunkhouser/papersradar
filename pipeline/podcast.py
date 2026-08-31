#!/usr/bin/env python3
"""Podcast stage: for each podcast-enabled user briefed today, generate the
day's episode(s) with every engine in PODCAST_ENGINES ("anchor" = scripted
single-anchor via Gemini TTS; "nlm" = NotebookLM two-host via the
notebooklm-mcp worker), then send the user's briefing email with the episode
status footer (the briefings stage defers these users' emails to here).

Idempotent: engines that already produced an ok episode for the date are
skipped, and the email sends once per (user, date) — so the 90-minute retry
timer can re-run this stage to fill in whatever failed, without double
emails. A failed engine never blocks the other engine or the email.

    python3 -m pipeline.podcast run [--date YYYY-MM-DD]
    python3 -m pipeline.podcast enable <email>     # sets flag + feed token,
    python3 -m pipeline.podcast disable <email>    #   prints the feed URL
    python3 -m pipeline.podcast status
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import cfg, db_path
from app import db as appdb
from app import mailer
from pipeline import briefings, podcast_script, tts

ENGINE_LABEL = {"anchor": "Anchor", "nlm": "NLM"}


def engines_enabled() -> list[str]:
    return [e.strip() for e in cfg("PODCAST_ENGINES").split(",") if e.strip()]


def briefed_rows(con, user, date: str):
    """The user's briefed papers for `date`, rank order, in the shape
    briefings.render_email expects (paper columns + fit/flavors/why +
    pj_name). Judge fields come from the latest judgment for the pair."""
    return con.execute(
        "SELECT p.*, b.fit, j.flavors_json, j.why, "
        "COALESCE(pj.display_name, '') AS pj_name "
        "FROM briefing_items b JOIN papers p ON p.id = b.paper_id "
        "LEFT JOIN judgments j ON j.user_id = b.user_id AND j.paper_id = b.paper_id "
        "     AND j.judged_at = (SELECT MAX(j2.judged_at) FROM judgments j2 "
        "         WHERE j2.user_id = b.user_id AND j2.paper_id = b.paper_id) "
        "LEFT JOIN priority_journals pj ON pj.user_id = b.user_id "
        "     AND pj.source_id = p.source_id AND p.source_id != '' "
        "WHERE b.user_id=? AND b.date=? ORDER BY b.rank",
        (user["id"], date)).fetchall()


def episode_title(date: str, n_papers: int, n_fulltext: int) -> str:
    nice = dt.date.fromisoformat(date).strftime("%b %-d")
    return f"{nice} — {n_papers} papers ({n_fulltext} full-text)"


def shownotes(con, rows, base: str) -> str:
    """Citation list for the feed item description and the episode row."""
    items = []
    for r in rows:
        authors = ", ".join(json.loads(r["authors_json"] or "[]")[:6])
        ft = con.execute(
            "SELECT 1 FROM paper_fulltext WHERE paper_id=? AND status='ok'",
            (r["id"],)).fetchone()
        tag = " [full text]" if ft else " [abstract only]"
        link = f"{base}/out/{r['id']}?ctx=podcast"
        items.append(
            f'<li><a href="{link}">{html.escape(r["title"])}</a><br>'
            f'{html.escape(authors)} · <i>{html.escape(r["venue"] or "")}</i> '
            f'· {html.escape(r["pub_date"] or "")}{tag}<br>'
            f'<i>{html.escape(r["why"] or "")}</i></li>')
    return "<ol>" + "".join(items) + "</ol>"


def _episode_dir(uid: int) -> Path:
    return db_path().parent / "podcasts" / str(uid)


def _save_episode(con, user, date: str, engine: str, title: str,
                  info: dict, notes: str) -> None:
    con.execute(
        "INSERT OR REPLACE INTO podcast_episodes(user_id, date, engine, status, "
        "detail, title, audio_path, mime, bytes, duration_sec, chapters_json, "
        "shownotes_html, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (user["id"], date, engine, "ok", "", title,
         str(info["path"].relative_to(db_path().parent)), info["mime"],
         info["bytes"], info["duration_sec"], json.dumps(info["chapters"]),
         notes, appdb.now()))
    con.commit()


def _save_failure(con, user, date: str, engine: str, err: str) -> None:
    con.execute(
        "INSERT OR REPLACE INTO podcast_episodes(user_id, date, engine, status, "
        "detail, created_at) VALUES(?,?,?,?,?,?)",
        (user["id"], date, engine, "error", err[:500], appdb.now()))
    con.commit()


# --- engines ------------------------------------------------------------------

def run_anchor(con, user, rows, date: str, title: str) -> dict:
    script = podcast_script.build_script(con, rows, date)
    # batched: the whole script uses a handful of TTS requests (free tier
    # allows only 10/day for the TTS model — see pipeline/tts.py)
    pcms, chapters = tts.synthesize_script(script["segments"])
    return tts.assemble(pcms, [c["title"] for c in chapters],
                        _episode_dir(user["id"]) / f"{date}_anchor",
                        chapters=chapters)


def run_nlm(con, user, rows, date: str, title: str) -> dict:
    from pipeline import podcast_nlm
    data_dir = db_path().parent
    files, fulltexts = [], []
    for r in rows:
        ft = con.execute(
            "SELECT * FROM paper_fulltext WHERE paper_id=? AND status='ok' "
            "AND kind='pdf'", (r["id"],)).fetchone()
        files.append(data_dir / ft["path"] if ft else None)
        fulltexts.append("x" if ft else "")
    prompt = podcast_script.nlm_steering_prompt(rows, fulltexts, date)
    wav = podcast_nlm.generate_episode(rows, files, prompt, date)
    pcm = tts.wav_to_pcm(wav)
    info = tts.assemble([pcm], [title], _episode_dir(user["id"]) / f"{date}_nlm")
    deleted = podcast_nlm.prune_notebooks()
    if deleted:
        print(f"[podcast] pruned {deleted} old notebooks", file=sys.stderr)
    return info


ENGINES = {"anchor": run_anchor, "nlm": run_nlm}


# --- email with status footer -------------------------------------------------

def status_footer(con, user, date: str) -> str:
    lines = []
    for eng in engines_enabled():
        row = con.execute(
            "SELECT * FROM podcast_episodes WHERE user_id=? AND date=? AND engine=?",
            (user["id"], date, eng)).fetchone()
        label = ENGINE_LABEL.get(eng, eng)
        if row and row["status"] == "ok":
            mins = max(1, round(row["duration_sec"] / 60))
            lines.append(f"✅ [{label}] episode published — {mins} min, "
                         f"in your podcast feed.")
        else:
            cause = html.escape(row["detail"] if row else "engine did not run")
            line = f"⚠️ [{label}] FAILED — {cause}"
            if eng == "nlm" and cfg("NLM_VNC_URL").strip():
                line += (f' — if the Google session expired, re-login via '
                         f'<a href="{cfg("NLM_VNC_URL")}">noVNC</a> '
                         f'(runbook §NLM).')
            lines.append(line)
    if not lines:
        return ""
    body = "<br>".join(lines)
    return (f'<div style="color:#64748b;font-size:12px;margin-top:10px;'
            f'border-top:1px solid #e2e8f0;padding-top:10px">'
            f'<b>Podcast</b><br>{body}</div>')


def send_briefing_email(con, user, rows, date: str) -> bool:
    if user["frequency"] == "none" or not rows:
        return False
    already = con.execute(
        "SELECT 1 FROM podcast_email_log WHERE user_id=? AND date=?",
        (user["id"], date)).fetchone()
    if already:
        return False
    body = briefings.render_email(user, rows, date) + status_footer(con, user, date)
    subj = f"Research Radar — {len(rows)} picks for {date}"
    sent = mailer.send(user["email"], subj, body)
    # record the attempt either way: dev mode (send()->False) must not retry
    con.execute("INSERT OR IGNORE INTO podcast_email_log(user_id, date, sent_at) "
                "VALUES(?,?,?)", (user["id"], date, appdb.now()))
    con.commit()
    return sent


# --- the stage ----------------------------------------------------------------

def run(con, date: str | None = None) -> dict:
    date = date or appdb.today()
    engines = engines_enabled()
    if not engines:
        return {"date": date, "skipped": "PODCAST_ENGINES empty"}
    unknown = [e for e in engines if e not in ENGINES]
    if unknown:
        return {"date": date, "skipped": f"unknown engines {unknown}"}
    base = cfg("BASE_URL").rstrip("/")
    out = []
    for user in con.execute(
            "SELECT * FROM users WHERE podcast_enabled=1").fetchall():
        rows = briefed_rows(con, user, date)
        if not rows:
            out.append({"user": user["email"], "papers": 0})
            continue
        n_ft = sum(1 for r in rows if con.execute(
            "SELECT 1 FROM paper_fulltext WHERE paper_id=? AND status='ok'",
            (r["id"],)).fetchone())
        title = episode_title(date, len(rows), n_ft)
        notes = shownotes(con, rows, base)
        statuses = {}
        for eng in engines:
            existing = con.execute(
                "SELECT status FROM podcast_episodes WHERE user_id=? AND date=? "
                "AND engine=?", (user["id"], date, eng)).fetchone()
            if existing and existing["status"] == "ok":
                statuses[eng] = "ok (cached)"
                continue
            try:
                info = ENGINES[eng](con, user, rows, date, title)
                _save_episode(con, user, date, eng, title, info, notes)
                statuses[eng] = "ok"
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                _save_failure(con, user, date, eng, err)
                statuses[eng] = f"error: {err[:120]}"
                print(f"[podcast] {user['email']} {eng} failed: {err}",
                      file=sys.stderr)
        sent = send_briefing_email(con, user, rows, date)
        out.append({"user": user["email"], "papers": len(rows),
                    "fulltext": n_ft, "engines": statuses, "email_sent": sent})
    summary = {"date": date, "users": out}
    print(f"[podcast] {summary}", file=sys.stderr)
    return summary


# --- CLI ----------------------------------------------------------------------

def enable_user(con, email: str):
    user = appdb.get_user_by_email(con, email)
    if not user:
        sys.exit(f"no such user: {email}")
    token = user["podcast_token"] or secrets.token_urlsafe(24)
    con.execute("UPDATE users SET podcast_enabled=1, podcast_token=? WHERE id=?",
                (token, user["id"]))
    con.commit()
    base = cfg("BASE_URL").rstrip("/")
    print(f"podcast enabled for {email}")
    print(f"private feed: {base}/podcast/{token}/feed.xml")
    if not cfg("PODCAST_ENGINES").strip():
        print("NOTE: PODCAST_ENGINES is empty in .env — set e.g. "
              "PODCAST_ENGINES=anchor,nlm to actually generate episodes.")


def disable_user(con, email: str):
    user = appdb.get_user_by_email(con, email)
    if not user:
        sys.exit(f"no such user: {email}")
    con.execute("UPDATE users SET podcast_enabled=0 WHERE id=?", (user["id"],))
    con.commit()
    print(f"podcast disabled for {email} (feed token kept; episodes kept)")


def status(con):
    print(f"engines: {engines_enabled() or '(none — feature off)'}")
    for u in con.execute("SELECT * FROM users WHERE podcast_enabled=1").fetchall():
        print(f"  {u['email']}")
        for e in con.execute(
                "SELECT * FROM podcast_episodes WHERE user_id=? "
                "ORDER BY date DESC, engine LIMIT 6", (u["id"],)).fetchall():
            extra = (f"{e['duration_sec']}s {e['mime']}" if e["status"] == "ok"
                     else e["detail"][:80])
            print(f"    {e['date']} [{e['engine']:6}] {e['status']:5} {extra}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "enable", "disable", "status"])
    ap.add_argument("email", nargs="?")
    ap.add_argument("--date")
    a = ap.parse_args()
    con = appdb.connect()
    if a.cmd == "run":
        run(con, a.date)
    elif a.cmd == "enable":
        enable_user(con, a.email or sys.exit("enable needs an email"))
    elif a.cmd == "disable":
        disable_user(con, a.email or sys.exit("disable needs an email"))
    else:
        status(con)


if __name__ == "__main__":
    main()
