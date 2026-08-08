#!/usr/bin/env python3
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


def shortlist_for_user(con, user,
                       embedder_name: str | None = None) -> list[tuple[int, float]]:
    """(paper_id, relevance) pairs for this user's judge queue, relevance
    descending: top `shortlist_size` windowed, abstract-having papers,
    excluding papers already judged under the user's current profile version.
    Empty if the user has no seed vectors. The relevance is persisted into
    judgments.relevance at judge time — briefings use it to order papers
    within a fit band."""
    from app import db as appdb
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
    paper_rows = con.execute(
        "SELECT p.id, pe.vector FROM papers p "
        "JOIN paper_embeddings pe ON pe.paper_id = p.id AND pe.embedder=? "
        "WHERE p.first_seen >= ? AND p.abstract != '' "
        "AND p.id NOT IN (SELECT paper_id FROM judgments "
        "                 WHERE user_id=? AND profile_version=?)",
        (embedder_name, cutoff, user["id"], version)).fetchall()
    if not paper_rows:
        return []

    ids, mat = _load_matrix([(r["id"], r["vector"]) for r in paper_rows])
    _, seeds = _load_matrix([(r["seed_id"], r["vector"]) for r in seed_rows])
    rel = relevance_scores(mat, seeds)
    order = sorted(range(len(ids)), key=lambda i: -float(rel[i]))
    return [(ids[i], float(rel[i])) for i in order[:size]]
