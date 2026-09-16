# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shortlist math: cosine relevance, top-k contrast recipe, per-user queue."""
import json

import numpy as np

from pipeline.shortlist import relevance_scores, shortlist_for_user
from pipeline.embedder import pack
from app import db as appdb


def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_relevance_orders_by_closeness():
    seeds = np.vstack([_unit([1, 0, 0]), _unit([0.9, 0.1, 0])])
    papers = np.vstack([
        _unit([1, 0.05, 0]),          # near the seeds
        _unit([0, 1, 0]),             # orthogonal
        _unit([0.5, 0.5, 0]),         # middling
    ])
    rel = relevance_scores(papers, seeds, contrast_w=0.0)
    assert rel[0] > rel[2] > rel[1]


def test_contrast_penalizes_generic_closeness():
    seeds = np.vstack([_unit([1, 0, 0])])
    # paper B sits at the pool centroid direction; A is specifically seed-like
    papers = np.vstack([_unit([1, 0.1, 0]), _unit([0.6, 0.8, 0]),
                        _unit([0.6, 0.8, 0.05]), _unit([0.6, 0.79, 0])])
    plain = relevance_scores(papers, seeds, contrast_w=0.0)
    contrast = relevance_scores(papers, seeds, contrast_w=0.3)
    # the specific paper keeps its lead and gains margin under contrast
    assert (contrast[0] - contrast[1]) > (plain[0] - plain[1])


def test_topk_uses_nearest_seeds_only():
    seeds = np.vstack([_unit([1, 0, 0]), _unit([0, 1, 0]), _unit([0, 0, 1]),
                       _unit([-1, 0, 0])])
    paper = np.vstack([_unit([1, 0.02, 0.02])])
    rel = relevance_scores(paper, seeds, nearest_k=1, contrast_w=0.0)
    assert rel[0] > 0.99                                  # far seeds don't drag it down


def _mk_user(con, email="u@example.com", shortlist_size=None):
    user = appdb.ensure_user(con, email)
    con.execute("UPDATE users SET onboarded_at=?, shortlist_size=? WHERE id=?",
                (appdb.now(), shortlist_size, user["id"]))
    con.commit()
    appdb.save_profile(con, user["id"], {"core_statement": "x", "flavors": []}, "v1")
    return appdb.get_user(con, user["id"])


def _mk_seed(con, uid, vec, embedder="nemotron-3-embed-1b"):
    cur = con.execute(
        "INSERT INTO seeds(user_id, title, added_at) VALUES(?,?,?)",
        (uid, "seed", appdb.now()))
    con.execute(
        "INSERT INTO seed_embeddings(seed_id, embedder, dim, vector, created_at) "
        "VALUES(?,?,?,?,?)", (cur.lastrowid, embedder, len(vec), pack(vec), appdb.now()))
    con.commit()


def _mk_paper(con, key, vec=None, abstract="abs", embedder="nemotron-3-embed-1b"):
    cur = con.execute(
        "INSERT INTO papers(key, title, abstract, first_seen) VALUES(?,?,?,?)",
        (key, key, abstract, appdb.today()))
    pid = cur.lastrowid
    if vec is not None:
        con.execute(
            "INSERT INTO paper_embeddings(paper_id, embedder, dim, vector, created_at) "
            "VALUES(?,?,?,?,?)", (pid, embedder, len(vec), pack(vec), appdb.now()))
    con.commit()
    return pid


def test_shortlist_for_user_ranks_and_caps(test_db, monkeypatch):
    monkeypatch.setenv("JUDGE_SHORTLIST_PER_USER", "2")
    user = _mk_user(test_db)
    _mk_seed(test_db, user["id"], _unit([1, 0, 0]).tolist())
    near = _mk_paper(test_db, "near", _unit([1, 0.05, 0]).tolist())
    mid = _mk_paper(test_db, "mid", _unit([0.7, 0.7, 0]).tolist())
    far = _mk_paper(test_db, "far", _unit([0, 0, 1]).tolist())
    _mk_paper(test_db, "unembedded")                       # no vector -> excluded
    _mk_paper(test_db, "noabs", _unit([1, 0, 0]).tolist(), abstract="")
    got = shortlist_for_user(test_db, user)
    assert [pid for pid, _ in got] == [near, mid]          # capped at 2, far excluded
    rels = [rel for _, rel in got]
    assert rels == sorted(rels, reverse=True)              # relevance rides along, desc


def test_shortlist_excludes_already_judged(test_db, monkeypatch):
    monkeypatch.setenv("JUDGE_SHORTLIST_PER_USER", "10")
    user = _mk_user(test_db, "v@example.com")
    _mk_seed(test_db, user["id"], _unit([1, 0, 0]).tolist())
    p1 = _mk_paper(test_db, "p1", _unit([1, 0, 0]).tolist())
    p2 = _mk_paper(test_db, "p2", _unit([0.9, 0.1, 0]).tolist())
    test_db.execute(
        "INSERT INTO judgments(user_id, paper_id, profile_version, fit, judged_at) "
        "VALUES(?,?,?,?,?)", (user["id"], p1, "v1", 8.0, appdb.now()))
    test_db.commit()
    assert [pid for pid, _ in shortlist_for_user(test_db, user)] == [p2]
    # profile version bump re-queues everything
    appdb.save_profile(test_db, user["id"],
                       {"core_statement": "x", "flavors": []}, "v2")
    assert {pid for pid, _ in shortlist_for_user(test_db, user)} == {p1, p2}


def test_shortlist_embedder_mismatch_is_empty(test_db):
    user = _mk_user(test_db, "w@example.com")
    _mk_seed(test_db, user["id"], _unit([1, 0, 0]).tolist(), embedder="other-model")
    _mk_paper(test_db, "p", _unit([1, 0, 0]).tolist())
    assert shortlist_for_user(test_db, user) == []         # never mixes embedders
