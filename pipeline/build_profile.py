#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build or refresh ONE user's interest profile. Runnable standalone
(onboarding/settings changes also enqueue it; the nightly `profiles` stage
sweeps anyone still pending).

    python3 -m pipeline.build_profile --user you@example.com

Steps (each best-effort and resumable):
  1. Core profile row: exists already (created synchronously at onboarding
     with a fallback flavor). Missing pieces are filled in here.
  2. Retrieval concepts: fetch each seed's OpenAlex record (by DOI) and take
     the most frequent concept ids across seeds — these steer Gathering.
  3. Flavors: if the profile still has only the fallback flavor, ask the LLM
     router to draft 2-5 flavors from the user's own description + seed
     titles (STRICT JSON contract; falls back silently — the fallback flavor
     already works with the judge prompt).
  4. Seed embeddings: embed "title. abstract"[:2000] for seeds missing a
     vector under the active embedder.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import cfg
from app import db as appdb
from app import openalex
from pipeline import providers
from pipeline.embedder import get_embedder, pack, paper_text, QuotaExceeded

PROFILE_TOP_CONCEPTS = 25
FALLBACK_FLAVOR_KEY = "my_research_interests"

FLAVOR_DRAFT_SYSTEM = """A researcher described their interests in their own words, \
and listed papers they consider exemplary. Draft 2-5 'flavors' — named sub-interests, \
each ALREADY an intersection of their interests, concrete enough that a reader could \
judge whether a new paper sits squarely inside it. Respond with STRICT JSON only:
{"flavors": [{"key": "<short_snake_case>", "description": "<2-3 concrete sentences>"}, ...]}"""


def fallback_profile(name: str, statement: str) -> dict:
    """A working judge profile built from nothing but the user's description.
    Deterministic, no network — onboarding never blocks on an API."""
    return {
        "core_statement": statement.strip(),
        "flavors": [{"key": FALLBACK_FLAVOR_KEY,
                     "description": statement.strip()[:600]}],
        "fit_rule": ("A paper fits when the researcher's stated interests are its "
                     "central question or design — not a passing mention or just "
                     "the application domain."),
        "negatives": [],
        "positive_exemplar_titles": [],
        "negative_exemplar_titles": [],
        "retrieval_concepts": [],
    }


def bump_version() -> str:
    # microseconds included so two edits inside the same second (e.g. saving
    # criteria then toggling the geo scope) can never share a version — the
    # judgment cache keys on this string
    import datetime as dt
    return dt.datetime.now().strftime("%Y-%m-%d-%H%M%S.%f")


# --- structured onboarding -> judge profile ----------------------------------

# Default fit rule composed for structured profiles: flavors-as-intersections,
# modeled on the example profile's rule. The CORE sentence is appended only when
# the user starred at least one flavor.
DEFAULT_FIT_RULE = (
    "Each flavor above is already an intersection of the researcher's "
    "interests, so a paper squarely inside ONE flavor is a bullseye — it does "
    "not also need to touch the others. Connecting two or more flavors makes "
    "it even better. 'Squarely inside' means the flavor is the paper's central "
    "research question or design — tested or theorized substantively, not a "
    "passing mention, not just the application domain, and not a motivating "
    "citation."
)
CORE_FIT_SENTENCE = (
    " Flavors marked CORE are the researcher's highest priorities — weigh "
    "them most heavily on borderline papers."
)


def slug_key(name: str) -> str:
    """'Narrative persuasion' -> 'narrative_persuasion' (judge flavor key)."""
    return re.sub(r"\W+", "_", (name or "").strip().lower()).strip("_")[:40]


def structured_profile(statement: str, flavors: list[dict],
                       negatives: list[str]) -> dict:
    """Compose the judge-profile contract from the structured onboarding
    fields (core statement + repeatable topic entries + exclusions).
    Deterministic, no network. Entries missing a name or description are
    dropped; with no usable flavor entries this degrades to the legacy
    fallback profile so the judge always has a rubric."""
    prof = fallback_profile("", statement)
    flist = []
    for f in flavors or []:
        key = slug_key(f.get("key") or f.get("name") or "")
        desc = str(f.get("description") or "").strip()[:600]
        if key and desc:
            flist.append({"key": key, "description": desc,
                          "core": bool(f.get("core"))})
    if flist:
        prof["flavors"] = flist
        prof["fit_rule"] = DEFAULT_FIT_RULE + (
            CORE_FIT_SENTENCE if any(f["core"] for f in flist) else "")
    prof["negatives"] = [str(n).strip() for n in (negatives or [])
                         if str(n).strip()][:20]
    return prof


def draft_flavors(statement: str, seed_titles: list[str]):
    """LLM-drafted flavors, or None if unavailable/unparseable."""
    user = ("DESCRIPTION:\n" + statement + "\n\nEXEMPLARY PAPERS:\n"
            + "\n".join(f"- {t}" for t in seed_titles[:30]))
    try:
        text, _ = providers.chat(FLAVOR_DRAFT_SYSTEM, user, temperature=0.2)
    except providers.ProvidersUnavailable as e:
        print(f"[profile] flavor drafting skipped ({e})", file=sys.stderr)
        return None
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        flavors = json.loads(m.group(0)).get("flavors") or []
    except Exception:
        return None
    out = []
    for f in flavors[:5]:
        key = re.sub(r"\W+", "_", str(f.get("key", "")).strip().lower())[:40]
        desc = str(f.get("description", ""))[:600]
        if key and desc:
            out.append({"key": key, "description": desc})
    return out or None


def fetch_concepts(con, uid: int) -> list[str]:
    """Most frequent OpenAlex concept ids across the user's seeds (per-seed
    lookups fill in missing abstracts too)."""
    base = cfg("OPENALEX_BASE").rstrip("/")
    mailto = urllib.parse.quote(cfg("OPENALEX_MAILTO"))
    counts: Counter = Counter()
    for s in con.execute("SELECT * FROM seeds WHERE user_id=?", (uid,)).fetchall():
        rec = None
        if s["openalex_id"]:
            rec = openalex.get_json(f"{base}/works/{s['openalex_id']}?mailto={mailto}")
        elif s["doi"]:
            rec = openalex.get_json(
                f"{base}/works/https://doi.org/"
                f"{urllib.parse.quote(s['doi'], safe='')}?mailto={mailto}")
        if not rec or not rec.get("id"):
            continue
        parsed = openalex.parse_work(rec)
        counts.update(parsed["concept_ids"])
        if parsed["abstract"] and not s["abstract"]:
            con.execute("UPDATE seeds SET abstract=?, openalex_id=? WHERE id=?",
                        (parsed["abstract"], parsed["openalex_id"], s["id"]))
    con.commit()
    return [c for c, _ in counts.most_common(PROFILE_TOP_CONCEPTS)]


def embed_seeds(con, uid: int) -> int:
    """Embed seeds missing a vector under the active embedder. Returns count."""
    emb = get_embedder()
    rows = con.execute(
        "SELECT * FROM seeds WHERE user_id=? AND id NOT IN "
        "(SELECT seed_id FROM seed_embeddings WHERE embedder=?)",
        (uid, emb.name)).fetchall()
    if not rows:
        return 0
    texts = [paper_text(r["title"], r["abstract"]) for r in rows]
    vecs = emb.embed(texts)
    dim = len(vecs[0])
    for r, v in zip(rows, vecs):
        con.execute(
            "INSERT OR REPLACE INTO seed_embeddings(seed_id, embedder, dim, vector, "
            "created_at) VALUES(?,?,?,?,?)",
            (r["id"], emb.name, dim, pack(v), appdb.now()))
    con.commit()
    return len(rows)


def build(con, user, allow_network: bool = True) -> dict:
    """Fill in whatever the user's profile is missing. Never raises on API
    unavailability — partial progress persists and the nightly stage retries."""
    uid = user["id"]
    prof = appdb.get_profile(con, uid)
    if not prof:
        prof = fallback_profile(user["name"], user["interest_statement"] or "")
        appdb.save_profile(con, uid, prof, bump_version())
        prof = appdb.get_profile(con, uid)
    result = {"user": user["email"]}

    if allow_network and not prof.get("retrieval_concepts"):
        concepts = fetch_concepts(con, uid)
        if concepts:
            prof["retrieval_concepts"] = concepts
            appdb.save_profile(con, uid, prof, prof["version"])  # no re-judge needed
            result["concepts"] = len(concepts)

    only_fallback = (len(prof.get("flavors", [])) == 1
                     and prof["flavors"][0]["key"] == FALLBACK_FLAVOR_KEY)
    if allow_network and only_fallback and user["interest_statement"]:
        titles = [r["title"] for r in con.execute(
            "SELECT title FROM seeds WHERE user_id=?", (uid,)).fetchall()]
        flavors = draft_flavors(user["interest_statement"], titles)
        if flavors:
            prof["flavors"] = flavors
            appdb.save_profile(con, uid, prof, bump_version())  # rubric changed -> re-judge
            result["flavors"] = len(flavors)

    if allow_network:
        try:
            result["seeds_embedded"] = embed_seeds(con, uid)
        except (QuotaExceeded, providers.ProvidersUnavailable, RuntimeError) as e:
            print(f"[profile] seed embedding pending ({e})", file=sys.stderr)
            result["seeds_embedded"] = "pending"
    return result


def pending_users(con):
    """Users whose profile still needs work: no profile row, no retrieval
    concepts, or seeds missing embeddings under the active embedder."""
    emb_name = cfg("EMBEDDER")
    out = []
    for u in con.execute("SELECT * FROM users WHERE onboarded_at IS NOT NULL").fetchall():
        prof = appdb.get_profile(con, u["id"])
        if not prof or not prof.get("retrieval_concepts"):
            out.append(u)
            continue
        n_unembedded = con.execute(
            "SELECT COUNT(*) c FROM seeds WHERE user_id=? AND id NOT IN "
            "(SELECT seed_id FROM seed_embeddings WHERE embedder=?)",
            (u["id"], emb_name)).fetchone()["c"]
        if n_unembedded:
            out.append(u)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--user", required=True, help="user id or email")
    a = ap.parse_args()
    con = appdb.connect()
    user = (appdb.get_user(con, int(a.user)) if a.user.isdigit()
            else appdb.get_user_by_email(con, a.user))
    if not user:
        sys.exit(f"no such user: {a.user}")
    print(json.dumps(build(con, user), indent=2))


if __name__ == "__main__":
    main()
