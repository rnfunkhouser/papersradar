#!/usr/bin/env python3
"""Daily pipeline orchestrator — plain CLI, invoked by cron/systemd-timer.
Every stage is idempotent and safe to re-run; all state lives in the SQLite
DB; each stage writes a pipeline_runs row and structured lines to
logs/pipeline.log.

    python3 -m pipeline.run_daily all
    python3 -m pipeline.run_daily gather --since 2026-08-01
    python3 -m pipeline.run_daily profiles|gather|embed|shortlist-judge|briefings

Stages (sequential, 1 GB RAM budget — nothing runs in parallel):
  profiles         (re)build pending user profiles (new signups, edited seeds)
  gather           shared corpus from OpenAlex/arXiv/OSF (union of user concepts)
  embed            embed corpus papers missing a vector (batched, resumable)
  shortlist-judge  per user: cosine shortlist -> batched-8 LLM judge -> judgments
  briefings        per user due today: briefing_items + email digest
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import cfg, log_dir
from app import db as appdb
from pipeline import gather, briefings, judging, providers, build_profile
from pipeline.embedder import get_embedder, pack, paper_text, QuotaExceeded
from pipeline.shortlist import shortlist_for_user

log = logging.getLogger("papersradar.pipeline")


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stderr),
                  logging.FileHandler(log_dir() / "pipeline.log")])


def _staged(con, stage: str, fn) -> bool:
    """Run one stage inside a pipeline_runs row. Returns success."""
    cur = con.execute("INSERT INTO pipeline_runs(stage, started_at) VALUES(?,?)",
                      (stage, appdb.now()))
    run_id = cur.lastrowid
    con.commit()
    try:
        detail = fn()
        con.execute("UPDATE pipeline_runs SET finished_at=?, status='ok', detail=? "
                    "WHERE id=?", (appdb.now(), json.dumps(detail or {}), run_id))
        con.commit()
        log.info("stage %s ok: %s", stage, detail)
        return True
    except Exception as e:
        con.execute("UPDATE pipeline_runs SET finished_at=?, status='error', detail=? "
                    "WHERE id=?", (appdb.now(), f"{type(e).__name__}: {e}"[:500], run_id))
        con.commit()
        log.exception("stage %s FAILED", stage)
        return False


# --- stages ------------------------------------------------------------------

def stage_profiles(con):
    results = []
    for user in build_profile.pending_users(con):
        results.append(build_profile.build(con, user))
    return {"rebuilt": len(results), "detail": results}


def stage_gather(con, since=None):
    return gather.run(con, since)


EMBED_DB_BATCH = 256      # papers loaded per outer loop (bounds memory)


def stage_embed(con):
    emb = get_embedder()
    total = 0
    while True:
        rows = con.execute(
            "SELECT id, title, abstract FROM papers WHERE abstract != '' AND id NOT IN "
            "(SELECT paper_id FROM paper_embeddings WHERE embedder=?) LIMIT ?",
            (emb.name, EMBED_DB_BATCH)).fetchall()
        if not rows:
            break
        try:
            vecs = emb.embed([paper_text(r["title"], r["abstract"]) for r in rows])
        except (QuotaExceeded, providers.ProvidersUnavailable) as e:
            log.warning("embed stage stopping early (%s) — resumes next run", e)
            return {"embedder": emb.name, "embedded": total, "stopped": str(e)[:200]}
        dim = len(vecs[0])
        for r, v in zip(rows, vecs):
            con.execute(
                "INSERT OR REPLACE INTO paper_embeddings(paper_id, embedder, dim, "
                "vector, created_at) VALUES(?,?,?,?,?)",
                (r["id"], emb.name, dim, pack(v), appdb.now()))
        con.commit()
        total += len(rows)
    return {"embedder": emb.name, "embedded": total}


def _recent_vote_titles(con, uid: int):
    """(upvoted, downvoted) titles, newest first — judge boundary examples."""
    rows = con.execute(
        "SELECT vote, title FROM feedback WHERE user_id=? AND title != '' "
        "ORDER BY ts DESC", (uid,)).fetchall()
    up = [r["title"] for r in rows if r["vote"] == "up"][:judging.MAX_VOTE_EXAMPLES]
    down = [r["title"] for r in rows if r["vote"] == "down"][:judging.MAX_VOTE_EXAMPLES]
    return up, down


def stage_shortlist_judge(con):
    out = []
    for user in con.execute(
            "SELECT * FROM users WHERE onboarded_at IS NOT NULL").fetchall():
        prof = appdb.get_profile(con, user["id"])
        if not prof:
            continue
        paper_ids = shortlist_for_user(con, user)
        if not paper_ids:
            out.append({"user": user["email"], "queued": 0})
            continue
        papers = [dict(con.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone())
                  for pid in paper_ids]
        up, down = _recent_vote_titles(con, user["id"])
        system = judging.build_prompt(prof, up, down)
        version = prof["version"]
        judged = 0
        for i in range(0, len(papers), judging.BATCH_SIZE):
            group = papers[i:i + judging.BATCH_SIZE]
            try:
                verdicts, served = judging.judge_batch(system, group, providers.chat)
            except providers.ProvidersUnavailable as e:
                log.warning("judge stopping early for %s (%s) — resumes next run",
                            user["email"], e)
                break
            for p, v in zip(group, verdicts):
                con.execute(
                    "INSERT OR REPLACE INTO judgments(user_id, paper_id, "
                    "profile_version, fit, flavors_json, why, provider, judged_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (user["id"], p["id"], version, v["fit"],
                     json.dumps(v["facets"]), v["why"], served, appdb.now()))
                judged += 1
            con.commit()
        out.append({"user": user["email"], "queued": len(papers), "judged": judged})
    return {"users": out}


def stage_briefings(con, date=None):
    return briefings.run(con, date)


STAGES = ["profiles", "gather", "embed", "shortlist-judge", "briefings"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=STAGES + ["all"])
    ap.add_argument("--since", help="gather window start (YYYY-MM-DD)")
    ap.add_argument("--date", help="briefing date (YYYY-MM-DD, default today)")
    a = ap.parse_args()
    _setup_logging()
    con = appdb.connect()
    todo = STAGES if a.stage == "all" else [a.stage]
    ok = True
    for stage in todo:
        fn = {
            "profiles": lambda: stage_profiles(con),
            "gather": lambda: stage_gather(con, a.since),
            "embed": lambda: stage_embed(con),
            "shortlist-judge": lambda: stage_shortlist_judge(con),
            "briefings": lambda: stage_briefings(con, a.date),
        }[stage]
        ok = _staged(con, stage, fn) and ok
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
