#!/usr/bin/env python3
"""Seed the owner's account so Papers Radar works on day one.

Imports Ryan's existing seed papers and interest profile from the single-user
repo (READ-ONLY source files — copy them to the server before running there):

    python3 -m pipeline.import_owner \
        --seeds-json  /path/to/frozen_seed_texts.json  \
        --profile-json /path/to/interest_profile.json

frozen_seed_texts.json: {doi: "Title. Abstract..."} (132 seeds with texts).
interest_profile.json:  the exact judge.py profile contract (flavors, fit_rule,
                        negatives, exemplars, core_statement).

Idempotent: re-running updates nothing that already exists. Retrieval
concepts + seed embeddings are filled in by `run_daily.py profiles`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db as appdb

OWNER_EMAIL = "ryan.n.funkhouser@gmail.com"
OWNER_NAME = "Ryan Funkhouser"
OLD_REPO = Path.home() / "claude" / "new_papers_briefing"


def split_seed_text(text: str) -> tuple[str, str]:
    """'Title. Abstract...' -> (title, abstract). Titles rarely contain '. ',
    so first-sentence split is the best available reconstruction."""
    text = (text or "").strip()
    cut = text.find(". ")
    if 20 <= cut <= 300:
        return text[:cut].strip(), text[cut + 2:].strip()
    return text[:300], text


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds-json",
                    default=str(OLD_REPO / "free_stack" / "frozen_seed_texts.json"))
    ap.add_argument("--profile-json",
                    default=str(OLD_REPO / "interest_profile.json"))
    ap.add_argument("--email", default=OWNER_EMAIL)
    a = ap.parse_args()

    seeds = json.loads(Path(a.seeds_json).read_text())
    profile = json.loads(Path(a.profile_json).read_text())

    con = appdb.connect()
    user = appdb.ensure_user(con, a.email)
    con.execute(
        "UPDATE users SET name=?, is_admin=1, frequency='daily', "
        "interest_statement=?, onboarded_at=COALESCE(onboarded_at, ?) WHERE id=?",
        (OWNER_NAME, profile.get("core_statement", ""), appdb.now(), user["id"]))
    con.commit()

    existing = {r["doi"] for r in con.execute(
        "SELECT doi FROM seeds WHERE user_id=?", (user["id"],)).fetchall()}
    added = 0
    for doi, text in sorted(seeds.items()):
        if doi in existing:
            continue
        title, abstract = split_seed_text(text)
        con.execute(
            "INSERT INTO seeds(user_id, doi, title, abstract, source, added_at) "
            "VALUES(?,?,?,?,?,?)",
            (user["id"], doi, title, abstract, "import", appdb.now()))
        added += 1
    con.commit()

    version = profile.get("version") or "imported-v1"
    body = {k: v for k, v in profile.items()
            if k in ("core_statement", "flavors", "fit_rule", "negatives",
                     "positive_exemplar_titles", "negative_exemplar_titles")}
    body["retrieval_concepts"] = []          # filled by the profiles stage
    if not appdb.get_profile(con, user["id"]):
        appdb.save_profile(con, user["id"], body, version)
        prof_msg = f"profile {version} imported"
    else:
        prof_msg = "profile already present — untouched"

    total = con.execute("SELECT COUNT(*) c FROM seeds WHERE user_id=?",
                        (user["id"],)).fetchone()["c"]
    print(f"owner {a.email}: {added} seeds added ({total} total); {prof_msg}. "
          f"Next: python3 -m pipeline.run_daily profiles")


if __name__ == "__main__":
    main()
