# SPDX-License-Identifier: AGPL-3.0-or-later
"""Briefing ordering: judge fit is the band, embedding relevance orders papers
within a band (validated 2026-08 on the single-user system's 41 blind
ratings). Covers the judgments.relevance migration, judge-time persistence,
select_items ordering with NULL fallback, and the legacy-row backfill."""
import json
import sqlite3

import pytest

from app import db as appdb
from pipeline import briefings
from pipeline.shortlist import shortlist_for_user
from tests.test_shortlist import _mk_user, _mk_seed, _mk_paper, _unit


# --- migration ---------------------------------------------------------------

def test_migration_adds_relevance_and_is_idempotent(tmp_path):
    # simulate a legacy DB whose judgments table predates the relevance column
    path = tmp_path / "legacy.db"
    raw = sqlite3.connect(path)
    raw.execute(
        "CREATE TABLE judgments (user_id INTEGER NOT NULL, paper_id INTEGER NOT NULL, "
        "profile_version TEXT NOT NULL, fit REAL NOT NULL, flavors_json TEXT DEFAULT '[]', "
        "why TEXT DEFAULT '', provider TEXT DEFAULT '', judged_at TEXT NOT NULL, "
        "UNIQUE(user_id, paper_id, profile_version))")
    raw.execute("INSERT INTO judgments(user_id, paper_id, profile_version, fit, judged_at) "
                "VALUES (1, 1, 'v1', 8.0, 'ts')")
    raw.commit()
    raw.close()

    con = appdb.connect(path)
    cols = [r["name"] for r in con.execute("PRAGMA table_info(judgments)")]
    assert "relevance" in cols
    # legacy row survives with NULL relevance
    assert con.execute("SELECT relevance FROM judgments").fetchone()["relevance"] is None
    con.close()

    con = appdb.connect(path)                  # second connect: no error, no dup column
    cols = [r["name"] for r in con.execute("PRAGMA table_info(judgments)")]
    assert cols.count("relevance") == 1
    con.close()


# --- judge-time persistence --------------------------------------------------

def test_relevance_persisted_at_judge_time(test_db, monkeypatch):
    monkeypatch.setenv("JUDGE_SHORTLIST_PER_USER", "10")
    user = _mk_user(test_db, "judge@example.com")
    _mk_seed(test_db, user["id"], _unit([1, 0, 0]).tolist())
    _mk_paper(test_db, "near", _unit([1, 0.05, 0]).tolist())
    _mk_paper(test_db, "mid", _unit([0.7, 0.7, 0]).tolist())
    expected = dict(shortlist_for_user(test_db, user))     # {paper_id: relevance}
    assert len(expected) == 2

    def fake_chat(system, user_msg, temperature=0.0, **kw):
        n = user_msg.count("PAPER ")
        rows = [{"n": i, "facets": [], "fit": 8, "why": "stub"}
                for i in range(1, n + 1)]
        return json.dumps(rows), "stub"

    import pipeline.run_daily as rd
    monkeypatch.setattr(rd.providers, "chat", fake_chat)
    rd.stage_shortlist_judge(test_db)

    rows = test_db.execute("SELECT paper_id, relevance FROM judgments WHERE user_id=?",
                           (user["id"],)).fetchall()
    assert len(rows) == 2
    for r in rows:
        assert r["relevance"] == pytest.approx(expected[r["paper_id"]])


# --- select_items ordering ---------------------------------------------------

def _judge(con, uid, pid, fit, relevance=None, version="v1"):
    con.execute(
        "INSERT INTO judgments(user_id, paper_id, profile_version, fit, relevance, "
        "judged_at) VALUES(?,?,?,?,?,?)", (uid, pid, version, fit, relevance, appdb.now()))
    con.commit()


def test_select_items_orders_by_relevance_within_fit(test_db):
    user = _mk_user(test_db, "order@example.com")
    a = _mk_paper(test_db, "a")
    b = _mk_paper(test_db, "b")
    d = _mk_paper(test_db, "d")
    e = _mk_paper(test_db, "e")
    _judge(test_db, user["id"], a, 8.0, relevance=0.2)
    _judge(test_db, user["id"], b, 8.0, relevance=0.9)
    _judge(test_db, user["id"], d, 9.0, relevance=0.05)    # higher fit band wins
    _judge(test_db, user["id"], e, 8.0, relevance=-0.1)    # below the NULL fallback (0)
    got = [r["id"] for r in briefings.select_items(test_db, user)]
    assert got == [d, b, a, e]


def test_select_items_null_relevance_falls_back_to_pub_date(test_db):
    user = _mk_user(test_db, "null@example.com")
    old = _mk_paper(test_db, "old")
    new = _mk_paper(test_db, "new")
    test_db.execute("UPDATE papers SET pub_date='2026-07-01' WHERE id=?", (old,))
    test_db.execute("UPDATE papers SET pub_date='2026-08-01' WHERE id=?", (new,))
    test_db.commit()
    _judge(test_db, user["id"], old, 8.0)                  # legacy rows: relevance NULL
    _judge(test_db, user["id"], new, 8.0)
    got = [r["id"] for r in briefings.select_items(test_db, user)]
    assert got == [new, old]                               # NULL -> 0, pub_date decides


# --- legacy backfill in the briefings stage ----------------------------------

def test_briefings_backfill_fills_null_relevance(test_db):
    user = _mk_user(test_db, "legacy@example.com")
    _mk_seed(test_db, user["id"], _unit([1, 0, 0]).tolist())
    near = _mk_paper(test_db, "near", _unit([1, 0.05, 0]).tolist())
    far = _mk_paper(test_db, "far", _unit([0, 1, 0]).tolist())
    for pid in (near, far):                                # pre-column judgments
        _judge(test_db, user["id"], pid, 8.0)

    summary = briefings.run(test_db)
    assert summary["relevance_backfilled"] == 2

    rows = {r["paper_id"]: r["relevance"] for r in test_db.execute(
        "SELECT paper_id, relevance FROM judgments WHERE user_id=?",
        (user["id"],)).fetchall()}
    assert rows[near] is not None and rows[far] is not None
    assert rows[near] > rows[far]
    ranked = [r["paper_id"] for r in test_db.execute(
        "SELECT paper_id FROM briefing_items WHERE user_id=? ORDER BY rank",
        (user["id"],)).fetchall()]
    assert ranked == [near, far]                           # day-one ordering correct

    # second run: nothing left to backfill
    assert briefings.run(test_db)["relevance_backfilled"] == 0
