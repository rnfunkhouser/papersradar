#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-user shortlist: cosine relevance of each corpus paper against the
user's seed vectors, using the validated recipe from harvest.py's
attach_embedding_relevance(contrast="pool"):

    rel = mean(top-3 similarities to seed vectors) - 0.3 * sim(pool centroid)

The pool-centroid subtraction stops "generically close to today's average
paper" from outranking "specifically close to a few seeds". Pure math — the
core is `relevance_scores()` (numpy, testable offline).
"""
from __future__ import annotations

import sys
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import cfg, cfg_int
from pipeline.embedder import unpack

NEAREST_K = 3
CONTRAST_W = 0.3
WINDOW_DAYS = 14           # papers eligible for a user's shortlist


def relevance_scores(paper_mat, seed_mat, nearest_k: int = NEAREST_K,
                     contrast_w: float = CONTRAST_W):
    """paper_mat (n×d) and seed_mat (m×d), rows L2-normalized ->
    length-n relevance array."""
    import numpy as np
    paper_mat = np.asarray(paper_mat, dtype=np.float32)
    seed_mat = np.asarray(seed_mat, dtype=np.float32)
    sims = paper_mat @ seed_mat.T                       # n×m cosine matrix
    k = min(nearest_k, sims.shape[1])
    topk = np.sort(sims, axis=1)[:, -k:]
    base = topk.mean(axis=1)
    centroid = paper_mat.mean(axis=0)
    norm = np.linalg.norm(centroid)
    if norm > 0 and contrast_w:
        centroid = centroid / norm
        base = base - contrast_w * (paper_mat @ centroid)
    return base


def _load_matrix(rows):
    """[(id, blob)] -> (ids, n×d numpy matrix, renormalized)."""
    import numpy as np
    ids = [r[0] for r in rows]
    mat = np.vstack([unpack(r[1]) for r in rows])
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return ids, mat / norms


def _user_row_get(user, key):
    """sqlite3.Row has no .get(); tolerate plain dicts in tests too."""
    try:
        return user[key]
    except (KeyError, IndexError):
        return None


def shortlist_for_user(con, user,
                       embedder_name: str | None = None) -> list[tuple[int, float]]:
    """(paper_id, relevance) pairs for this user's judge queue, relevance
    descending: top `shortlist_size` windowed, abstract-having papers,
    excluding papers already judged under the user's current profile version.
    Empty if the user has no seed vectors. The relevance is persisted into
    judgments.relevance at judge time — briefings use it to order papers
    within a fit band.

    Two per-user refinements:
      - Western-context option ON -> papers whose venue has a KNOWN country
        outside app.geo.BROAD_WEST_COUNTRIES are excluded from the pool
        entirely (unknown-country venues are kept).
      - Priority journals: up to PRIORITY_JOURNAL_MAX_PER_USER ADDITIONAL
        papers from the user's priority journals are appended after the
        normal top-N, when their relevance is at or above the
        PRIORITY_JOURNAL_MIN_REL_PCTL percentile of this user's windowed
        pool (see analysis/priority_journal_threshold.md)."""
    from app import db as appdb
    from app.geo import BROAD_WEST_COUNTRIES
    embedder_name = embedder_name or cfg("EMBEDDER")
    prof = appdb.get_profile(con, user["id"])
    if not prof:
        return []
    version = prof.get("version", "v0")
    size = user["shortlist_size"] or cfg_int("JUDGE_SHORTLIST_PER_USER")

    seed_rows = con.execute(
        "SELECT se.seed_id, se.vector FROM seed_embeddings se "
        "JOIN seeds s ON s.id = se.seed_id "
        "WHERE s.user_id=? AND se.embedder=?",
        (user["id"], embedder_name)).fetchall()
    if not seed_rows:
        return []

    cutoff = (dt.date.today() - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    geo_sql = ""
    if _user_row_get(user, "western_context"):
        # exclude ONLY venues whose country is KNOWN and outside the Broad
        # West; unknown venues/countries (preprints, unenriched) stay in
        placeholders = ",".join("?" for _ in BROAD_WEST_COUNTRIES)
        geo_sql = (" AND p.source_id NOT IN (SELECT id FROM sources "
                   "WHERE country_code != '' AND country_code NOT IN "
                   f"({placeholders}))")
    paper_rows = con.execute(
        "SELECT p.id, p.source_id, pe.vector FROM papers p "
        "JOIN paper_embeddings pe ON pe.paper_id = p.id AND pe.embedder=? "
        "WHERE p.first_seen >= ? AND p.abstract != '' "
        "AND p.id NOT IN (SELECT paper_id FROM judgments "
        "                 WHERE user_id=? AND profile_version=?)" + geo_sql,
        (embedder_name, cutoff, user["id"], version)
        + (tuple(BROAD_WEST_COUNTRIES) if geo_sql else ())).fetchall()
    if not paper_rows:
        return []

    ids, mat = _load_matrix([(r["id"], r["vector"]) for r in paper_rows])
    _, seeds = _load_matrix([(r["seed_id"], r["vector"]) for r in seed_rows])
    rel = relevance_scores(mat, seeds)
    order = sorted(range(len(ids)), key=lambda i: -float(rel[i]))
    picks = [(ids[i], float(rel[i])) for i in order[:size]]

    # --- guaranteed priority-journal slots (additional to the top-N) ---------
    pj_sources = {r["source_id"] for r in con.execute(
        "SELECT source_id FROM priority_journals WHERE user_id=?",
        (user["id"],)).fetchall()}
    if pj_sources:
        import numpy as np
        floor = float(np.percentile(
            np.asarray(rel, dtype=np.float32),
            cfg_int("PRIORITY_JOURNAL_MIN_REL_PCTL")))
        src_by_id = {r["id"]: r["source_id"] for r in paper_rows}
        cap = cfg_int("PRIORITY_JOURNAL_MAX_PER_USER")
        extra = [i for i in order[size:]
                 if src_by_id[ids[i]] in pj_sources and float(rel[i]) >= floor]
        picks.extend((ids[i], float(rel[i])) for i in extra[:cap])
    return picks
