#!/usr/bin/env python3
"""Live quality probe of the autofill coach (docs/setup-evaluation.md §5).

Runs the ACTUAL coach prompts through the ACTUAL provider router over:
  - two synthetic researcher personas built from REAL OpenAlex papers
    (keyless fetch; deliberately includes a few stray seeds — realistic
    library noise);
  - the owner's frozen 132-seed set (first-40 slice AND a seeded random-40
    sample — the two runs demonstrate the MAX_SEEDS_IN_PROMPT sampling
    sensitivity reported in the evaluation);
  - one suggest-mode call on a deliberately weak draft (tautological flavor,
    blanket negatives) to test failure-mode detection.

Reproduce:
    python3 analysis/autofill_probe.py --env-file /path/to/keys.env \
        [--frozen-seeds /path/to/frozen_seed_texts.json] [--out results.json]

--env-file: KEY=value lines providing GROQ_API_KEY etc. (never committed).
--frozen-seeds: optional; the owner-set runs are skipped without it.
State: uses a throwaway DB in a temp dir — the project DB is never touched.
Budget: hard cap of 12 LLM calls (the 2026-08-09 run used 5).
Frozen output of the 2026-08-09 run: autofill_probe_results_2026-08-09.json.
"""
import argparse
import json
import os
import random
import ssl
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

MAX_CALLS = 12
calls_made = 0


def load_env_file(path: str) -> None:
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def oa_search(query: str, n: int = 5) -> list[dict]:
    url = ("https://api.openalex.org/works?search=" + urllib.parse.quote(query)
           + "&filter=has_abstract:true,type:article"
           + f"&per-page={n}&mailto=admin@papersradar.com")
    with urllib.request.urlopen(url, timeout=30, context=_ssl_ctx()) as r:
        data = json.load(r)
    out = []
    for w in data.get("results", []):
        inv = w.get("abstract_inverted_index") or {}
        pos = {}
        for word, idxs in inv.items():
            for i in idxs:
                pos[i] = word
        abstract = " ".join(pos[i] for i in sorted(pos))[:1500]
        if w.get("title") and abstract:
            out.append({"title": w["title"], "abstract": abstract})
    return out


PERSONAS = {
    "dev_psych_numeracy": [
        "home mathematics environment early numeracy preschool",
        "approximate number system training arithmetic children",
        "parent number talk math development children",
    ],
    "coral_reef_acoustics": [
        "coral bleaching thermal tolerance heat stress reef",
        "coral reef soundscape passive acoustic monitoring",
        "acoustic enrichment reef restoration larval settlement",
    ],
}


def build_persona_seeds(searches, per=4, cap=10):
    seeds, seen = [], set()
    for q in searches:
        for s in oa_search(q, per):
            t = s["title"].lower()
            if t not in seen:
                seen.add(t)
                seeds.append(s)
        time.sleep(0.3)
    return seeds[:cap]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--env-file", required=True,
                    help="KEY=value file with provider API keys")
    ap.add_argument("--frozen-seeds", default="",
                    help="frozen_seed_texts.json ({doi: 'title. abstract'}) "
                         "for the owner-set comparison runs")
    ap.add_argument("--out", default="analysis/autofill_probe_results.json")
    a = ap.parse_args()

    load_env_file(a.env_file)
    tmp = tempfile.mkdtemp(prefix="autofill_probe_")
    os.environ["DB_PATH"] = os.path.join(tmp, "probe.db")
    os.environ["LOG_DIR"] = os.path.join(tmp, "logs")
    os.environ["ENV_FILE"] = "/nonexistent"

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app import coach
    from pipeline import providers

    def chat(system, user, temperature=coach.COACH_TEMPERATURE):
        global calls_made
        if calls_made >= MAX_CALLS:
            raise RuntimeError("call budget exhausted")
        calls_made += 1
        return providers.chat(system, user, temperature=temperature)

    def run_autofill(seeds, label, results):
        msg = coach.autofill_user_msg(seeds)
        text = provider = None
        for _ in range(2):
            text, provider = chat(coach.AUTOFILL_SYSTEM, msg)
            parsed = coach.parse_autofill(text)
            if parsed:
                results[label] = {"provider": provider,
                                  "n_seeds_in": len(seeds), "draft": parsed}
                return parsed
        results[label] = {"provider": provider, "n_seeds_in": len(seeds),
                          "draft": None, "raw": (text or "")[:2000]}
        return None

    results = {"personas": {}, "owner": {}, "suggest": None}

    for name, searches in PERSONAS.items():
        seeds = build_persona_seeds(searches)
        results["personas"][name] = {"seed_titles": [s["title"] for s in seeds]}
        ok = run_autofill(seeds, "draft", results["personas"][name])
        print(f"[{name}] {len(seeds)} seeds -> {'ok' if ok else 'FAILED'}",
              file=sys.stderr)

    if a.frozen_seeds:
        frozen = json.load(open(a.frozen_seeds))
        owner_seeds = []
        for _doi, text in frozen.items():
            head, _, rest = text.partition(". ")
            owner_seeds.append({"title": head[:250], "abstract": rest[:1500]})
        run_autofill(owner_seeds[:40], "first40", results["owner"])
        rnd = random.Random(42)                       # fixed seed: reproducible
        run_autofill(rnd.sample(owner_seeds, 40), "random40_seed42",
                     results["owner"])

    pa = results["personas"]["dev_psych_numeracy"]
    weak_stmt = ("I study how children learn math and how families and "
                 "schools can help.")
    weak_flavors = [{"name": "math learning",
                     "description": "Children learning mathematics."}]
    weak_negs = ["neuroscience", "education policy"]
    msg = coach.suggest_user_msg(weak_stmt, weak_flavors, weak_negs,
                                 pa.get("seed_titles", []))
    text, provider = chat(coach.SUGGEST_SYSTEM, msg)
    results["suggest"] = {"provider": provider,
                          "input": {"statement": weak_stmt,
                                    "flavors": weak_flavors,
                                    "negatives": weak_negs},
                          "out": coach.parse_suggestions(text) or text[:2000]}

    results["llm_calls"] = calls_made
    Path(a.out).write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"done: {calls_made} LLM calls -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
