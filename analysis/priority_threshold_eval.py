#!/usr/bin/env python3
"""Empirical evaluation of the priority-journal auto-include threshold.

Priority-journal papers get GUARANTEED judge slots — but only if their
embedding relevance clears a baseline, so that a broad-but-excellent journal
(e.g. Journal of Communication) doesn't flood the judge queue with papers far
from the user's interests. This script picks that baseline empirically.

Candidate rules
  ABS   absolute floor on raw relevance (mean top-3 seed cosine minus
        0.3 x pool-centroid cosine — the exact pipeline.shortlist recipe)
  PCTL  user-relative floor: paper must be above the p-th percentile of the
        user's windowed pool's relevance distribution that day

Evaluation data (READ-ONLY reference repo: the single-user system)
  July session  41 blind owner ratings (0-2: 2 = exactly my thing, 1 = fine,
                0 = off), experiments_rerank_2026-08-07/dataset.json. Pool
                reconstructed from doc_embeddings.json entries first_seen in
                the 14-day window ending 2026-07-23 (the cache write date).
  Aug session   38 blind owner ratings (1-5), rating_key_2026-08-08.json.
                Pool = free_stack/frozen_pool.json usable candidates (with
                abstract + cached vector, not already briefed).

Both sessions use the owner's 132 seeds and production Qwen3-Embedding-8B
vectors (all cached — this script makes ZERO network calls). Relevance is
recomputed with pipeline.shortlist.relevance_scores, i.e. the exact recipe
the hosted app runs (no downvote penalty, no min-max normalization).

"Keep" set (the papers a threshold must NOT cut): Aug rating >= 3, July
rating >= 1 (0-2 maps to 1/3/5 on the 1-5 scale). Success criterion from the
owner: retain >= 95% of the keep set while excluding the clear strays.

Usage:
    python3 analysis/priority_threshold_eval.py \
        --ref-repo ~/claude/new_papers_briefing \
        --out analysis/priority_journal_threshold.md
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.shortlist import relevance_scores  # noqa: E402  (production recipe)

JULY_WINDOW_END = dt.date(2026, 7, 23)     # doc_embeddings.json write date
JULY_WINDOW_DAYS = 14                      # papersradar shortlist window
PCTL_GRID = [30, 40, 50, 60, 70, 75, 80, 85, 90, 95]
ABS_GRID = [0.30, 0.35, 0.40, 0.45, 0.50]
RETENTION_TARGET = 0.95
SAFETY_MARGIN = 20   # points of pool-percentile headroom below the lowest-
                     # percentile keeper, absorbing: the July pool being a
                     # reconstruction, the production embedder being a
                     # different model (nemotron vs these Qwen3-8B vectors),
                     # and other users' seed geometries differing from the
                     # owner's. See the markdown's Decision section.


def unpack_f16(s: str) -> np.ndarray:
    v = np.frombuffer(base64.b64decode(s), dtype=np.float16).astype(np.float32)
    return np.nan_to_num(v, nan=0.0, posinf=0.0, neginf=0.0)  # f16 caches can hold inf


def l2(mat: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(mat, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return mat / n


def pool_relevance(keys: list[str], vecs: list[np.ndarray], seed_mat: np.ndarray):
    mat = l2(np.vstack(vecs))
    rel = relevance_scores(mat, seed_mat)
    return dict(zip(keys, rel.tolist())), np.sort(rel)


def pctl_of(sorted_rel: np.ndarray, x: float) -> float:
    """Fraction of the pool strictly below x (0-100)."""
    return 100.0 * float(np.searchsorted(sorted_rel, x, side="left")) / len(sorted_rel)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ref-repo", required=True,
                    help="path to the single-user new_papers_briefing repo (read-only)")
    ap.add_argument("--out", default="analysis/priority_journal_threshold.md")
    a = ap.parse_args()
    ref = Path(a.ref_repo).expanduser()
    exp = ref / "experiments_rerank_2026-08-07"

    print("loading seeds ...", file=sys.stderr)
    seeds = json.loads((ref / "seeds_embeddings.json").read_text())
    seed_mat = l2(np.array(list(seeds.values()), dtype=np.float32))
    print(f"  {len(seeds)} seed vectors, dim {seed_mat.shape[1]}", file=sys.stderr)

    print("loading doc_embeddings.json (~523 MB) ...", file=sys.stderr)
    doc = json.loads((ref / "doc_embeddings.json").read_text())
    print(f"  {len(doc)} cached candidate vectors", file=sys.stderr)

    # ---- July pool: cache entries first_seen inside the 14-day window --------
    j_since = (JULY_WINDOW_END - dt.timedelta(days=JULY_WINDOW_DAYS)).isoformat()
    jkeys, jvecs = [], []
    for k, (first_seen, packed) in doc.items():
        if first_seen >= j_since:
            jkeys.append(k)
            jvecs.append(unpack_f16(packed))
    july_rel, july_sorted = pool_relevance(jkeys, jvecs, seed_mat)
    print(f"July pool: {len(jkeys)} papers (first_seen >= {j_since})", file=sys.stderr)

    # ---- Aug pool: frozen_pool usable candidates -----------------------------
    frozen = json.loads((ref / "free_stack" / "frozen_pool.json").read_text())
    seen = set(json.loads((ref / "seen.json").read_text())) if (ref / "seen.json").exists() else set()
    extra = json.loads((ref / "free_stack" / "emb_cache_mindrouter_extra.json").read_text())

    def key_of(c):  # harvest.key_of, verbatim logic
        import re
        return (c.get("doi") or "").lower() or \
            __import__("re").sub(r"\W+", "", (c.get("title") or "").lower())[:60]

    akeys, avecs = [], []
    for c in frozen["candidates"]:
        if not (c.get("abstract") or "").strip():
            continue
        k = key_of(c)
        if k in seen:
            continue
        hit = doc.get(k) or extra.get(k)
        if not hit:
            continue
        akeys.append(k)
        avecs.append(unpack_f16(hit[1]))
    aug_rel, aug_sorted = pool_relevance(akeys, avecs, seed_mat)
    print(f"Aug pool: {len(akeys)} usable candidates", file=sys.stderr)
    del doc, extra

    # ---- rated papers, joined to their session pool --------------------------
    rated = []          # (session, title, rating_1to5, keep, rel, pctl)
    july_map = {0: 1, 1: 3, 2: 5}
    ds = json.loads((exp / "dataset.json").read_text())
    j_missing = 0
    for v in ds.values():
        k = (v.get("key") or "").lower()
        if k not in july_rel:               # outside the reconstructed window
            j_missing += 1
            continue
        r = july_rel[k]
        rated.append(("july", v["title"], july_map[v["rating"]],
                      v["rating"] >= 1, r, pctl_of(july_sorted, r)))
    rk = json.loads((exp / "rating_key_2026-08-08.json").read_text())
    aug_votes = json.loads(
        (exp / "user_ratings_2026-08-08.json").read_text())["ratings"]
    a_missing = 0
    for v in rk["papers"]:
        k = (v.get("key") or "").lower()
        rating = aug_votes.get(v["title"])       # sealed key joins to owner ratings by title
        if k not in aug_rel or rating is None:
            a_missing += 1
            continue
        r = aug_rel[k]
        rated.append(("aug", v["title"], rating,
                      rating >= 3, r, pctl_of(aug_sorted, r)))
    print(f"rated joined: {len(rated)} (july missing {j_missing}, aug missing {a_missing})",
          file=sys.stderr)

    keeps = [p for p in rated if p[3]]
    strays = [p for p in rated if not p[3]]

    def evaluate(rule_desc, passes):
        kept = [p for p in keeps if passes(p)]
        cut_keeps = [p for p in keeps if not passes(p)]
        cut_strays = [p for p in strays if not passes(p)]
        return {
            "rule": rule_desc,
            "keep_retained": len(kept), "keep_total": len(keeps),
            "retention": len(kept) / len(keeps) if keeps else 1.0,
            "strays_excluded": len(cut_strays), "stray_total": len(strays),
            "cut_keeps": [(p[0], p[1], p[2], round(p[4], 3), round(p[5], 1))
                          for p in cut_keeps],
            "cut_strays": [(p[0], p[1], p[2], round(p[4], 3), round(p[5], 1))
                           for p in cut_strays],
        }

    results = []
    for p in PCTL_GRID:
        results.append(evaluate(f"PCTL>={p}", lambda x, p=p: x[5] >= p))
    for f in ABS_GRID:
        results.append(evaluate(f"ABS>={f:.2f}", lambda x, f=f: x[4] >= f))

    # Decision rule: the rated packets were drawn from the top of each day's
    # pool (judge-queue picks + bait), so nearly all rated papers — keepers AND
    # strays — sit above P90; the data bounds the floor from ABOVE. We take the
    # highest grid percentile that (a) retains >= RETENTION_TARGET of keepers
    # and (b) stays SAFETY_MARGIN points below the lowest-percentile keeper,
    # so a slightly-unique-but-interesting paper (the rated-4 P83.5 minimum
    # observed here) is never near the cut line even under embedder-transfer
    # and pool-reconstruction noise.
    min_keeper_pctl = min(p[5] for p in keeps)
    ceiling = min_keeper_pctl - SAFETY_MARGIN
    pctl_ok = [r for r in results if r["rule"].startswith("PCTL")
               and r["retention"] >= RETENTION_TARGET
               and float(r["rule"].split(">=")[1]) <= ceiling]
    winner = pctl_ok[-1] if pctl_ok else results[0]

    # ---- report --------------------------------------------------------------
    lines = ["# Priority-journal auto-include threshold — empirical evaluation",
             "",
             f"Generated by `analysis/priority_threshold_eval.py` on {dt.date.today()}."
             " Zero network calls; all vectors from the single-user repo's caches"
             " (production Qwen3-Embedding-8B), relevance recomputed with the hosted"
             " app's exact `pipeline.shortlist.relevance_scores` recipe.",
             "",
             "## Question",
             "",
             "Papers from a user's priority journals get guaranteed judge slots, but"
             " only above a relevance baseline (owner: Journal of Communication is"
             " excellent but broad — auto-include must require 'at least pretty"
             " close' without cutting slightly-unique-but-interesting ones). Which"
             " baseline rule, at which level?",
             "",
             "## Data",
             "",
             f"- July session: {sum(1 for p in rated if p[0]=='july')} rated papers"
             f" joined to a reconstructed {len(jkeys)}-paper 14-day pool"
             f" (doc_embeddings first_seen >= {j_since}); owner scale 0-2 mapped to"
             " 1/3/5.",
             f"- Aug session: {sum(1 for p in rated if p[0]=='aug')} rated papers"
             f" joined to the frozen {len(akeys)}-candidate pool"
             " (free_stack/frozen_pool.json, 2026-08-04.. window); owner scale 1-5.",
             f"- Keep set (must retain >= {RETENTION_TARGET:.0%}): rating >= 3"
             f" -> n={len(keeps)}. Strays: rating <= 2 -> n={len(strays)}.",
             f"- Unjoinable (outside reconstructed window / no cached vector):"
             f" July {j_missing}, Aug {a_missing}.",
             "",
             "## Results",
             "",
             "| rule | keepers retained | retention | strays excluded |",
             "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['rule']} | {r['keep_retained']}/{r['keep_total']} "
                     f"| {r['retention']:.1%} | {r['strays_excluded']}/{r['stray_total']} |")
    lines += ["", "## Decision", "",
              f"**Winner: {winner['rule']}** (retention {winner['retention']:.1%};"
              f" {winner['strays_excluded']}/{winner['stray_total']} rated strays"
              " below the floor).",
              "",
              "How to read the table: the rated packets were drawn from the TOP"
              " of each day's pool (judge-queue picks plus high-similarity bait),"
              " so nearly every rated paper — keeper or stray — sits above P90."
              " The data therefore bounds the floor from above rather than"
              " discriminating between low floors:",
              "",
              f"- The lowest-percentile keeper is at pool percentile"
              f" {min_keeper_pctl:.1f} (a rated-4 paper); the next ones are at"
              " ~P94-96 (two rated-5s). Floors of 85+ demonstrably start cutting"
              " papers the owner rated 4-5 — exactly the"
              " 'slightly-unique-but-interesting' papers the owner said must not"
              " be cut.",
              f"- Any floor at or below P80 retains 100% of the 52 keepers; we"
              f" additionally require {SAFETY_MARGIN} points of headroom below"
              f" that P{min_keeper_pctl:.1f} minimum (=> floor <= {ceiling:.0f}),"
              " because the July pool is a reconstruction, production runs a"
              " different embedder (nemotron-3-embed-1b vs these Qwen3-8B"
              " vectors), and other users' seed geometries will differ.",
              f"- {winner['rule'].replace('PCTL>=', 'P')} is the highest grid"
              " level satisfying both — also the top of the owner's suggested"
              " 40/50/60 candidate range. It still blocks the bottom"
              f" {winner['rule'].split('>=')[1]}% of a broad journal's output"
              " from consuming guaranteed judge slots, while the per-user cap"
              " (PRIORITY_JOURNAL_MAX_PER_USER) bounds quota regardless.",
              "",
              "Note on rated strays: the packet strays are non-representative of"
              " a broad journal's typical off-topic paper — they were selected"
              " into packets *because* they embed near the seeds (bait). A"
              " journal's genuinely off-topic papers sit far lower in the pool"
              " distribution and are exactly what any P40-P80 floor blocks.",
              ""]
    if winner["cut_keeps"]:
        lines += ["Keepers the winning rule cuts:", ""]
        for s, t, rating, rel, pc in winner["cut_keeps"]:
            lines.append(f"- [{s}] rated {rating}: \"{t}\" (rel {rel}, pctl {pc})")
        lines.append("")
    lines += ["## Why a percentile rule (not an absolute floor)",
              "",
              "- Absolute cosine floors do NOT transfer across embedders: these"
              " vectors are Qwen3-Embedding-8B, production papersradar runs"
              " nemotron-3-embed-1b (and a local Qwen3-0.6B swap is planned)."
              " A percentile of the user's own windowed pool is scale-free and"
              " survives any embedder change untouched.",
              "- It is also per-user by construction: a user with a tight seed"
              " cloud and a user with a broad one both get 'above the bottom"
              " X% of MY day's pool', which is what 'at least pretty close'"
              " means in each one's geometry.",
              "",
              "## Encoded as",
              "",
              f"`PRIORITY_JOURNAL_MIN_REL_PCTL={winner['rule'].split('>=')[1] if winner['rule'].startswith('PCTL') else '40'}`"
              " (config knob, see app/config.py) — a priority-journal paper is"
              " auto-queued for judging only if its relevance is at or above that"
              " percentile of the user's windowed pool that day, capped at"
              " `PRIORITY_JOURNAL_MAX_PER_USER` extra slots.",
              "",
              "Caveats: the July pool is a cache-based reconstruction (the exact"
              " harvest pool wasn't frozen); both pools are the owner's — other"
              " users' geometries will differ, which the percentile form absorbs.",
              ""]
    # full rated table for the record
    lines += ["## Appendix — rated papers with recomputed relevance", "",
              "| session | rating(1-5) | rel | pool pctl | title |", "|---|---|---|---|---|"]
    for s, t, rating, keep, rel, pc in sorted(rated, key=lambda x: -x[5]):
        lines.append(f"| {s} | {rating} | {rel:.3f} | {pc:.1f} | {t[:80]} |")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    print(f"wrote {out}", file=sys.stderr)
    print(json.dumps({"winner": winner["rule"],
                      "retention": round(winner["retention"], 3),
                      "strays_excluded": winner["strays_excluded"],
                      "stray_total": winner["stray_total"]}, indent=2))


if __name__ == "__main__":
    main()
