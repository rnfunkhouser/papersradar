#!/usr/bin/env python3
"""The LLM judge — EXACT prompt/parse contract preserved from the single-user
system's judge.py (2026-07-23 design), plus the batched 8-papers-per-call
variant validated in free_stack (Phase C: 5/5 identical top picks vs the old
judge on Groq openai/gpt-oss-120b).

Pure functions here (prompt building + parsing) so tests run offline; the
network call goes through pipeline.providers.chat.
"""
from __future__ import annotations

import json
import re

MAX_VOTE_EXAMPLES = 10       # newest votes per side appended to the prompt
TEMPERATURE = 0.0            # determinism: same paper + same profile -> same verdict
BATCH_SIZE = 8               # papers per judge call (validated batch size)


def build_prompt(profile: dict, extra_pos=(), extra_neg=(),
                 western_focus: bool = False) -> str:
    """System prompt for the judge — verbatim contract from judge.py.
    extra_pos/extra_neg are recent voted titles, appended AFTER the curated
    exemplars so fresh feedback speaks last.

    western_focus (per-user option, default OFF) appends the soft geographic-
    scope instruction (app.geo.WESTERN_SOFT_PROMPT). Because it changes the
    prompt, toggling the option bumps the user's profile version (see
    routes_user._set_geo_scope) so cached verdicts never mix."""
    negs = "\n".join(f"- {n}" for n in profile.get("negatives", []))
    pos = list(profile.get("positive_exemplar_titles", [])) + \
        [f"{t} (recent 👍)" for t in list(extra_pos)[:MAX_VOTE_EXAMPLES]]
    neg_ex = list(profile.get("negative_exemplar_titles", [])) + \
        [f"{t} (recent 👎)" for t in list(extra_neg)[:MAX_VOTE_EXAMPLES]]
    pos_s = "\n".join(f"- {t}" for t in pos)
    neg_s = "\n".join(f"- {t}" for t in neg_ex)
    if profile.get("flavors"):
        # (CORE) marker only for flavors explicitly starred in the structured
        # editor — profiles without core flags render byte-identically to the
        # original judge.py contract.
        areas = "\n".join(
            f"- {f['key']}{' (CORE)' if f.get('core') else ''}: {f['description']}"
            for f in profile["flavors"])
        rubric = f"""INTEREST FLAVORS (each is already an intersection of the researcher's interests):
{areas}

FIT RULE: {profile.get('fit_rule', '')}

Given one paper's title and abstract, judge which flavors it SUBSTANTIVELY engages
(the flavor is the paper's central question or design — not a passing mention,
not just the application domain) and score fit for THIS researcher:

  9-10  squarely inside >=1 flavor: the flavor's defining combination IS the
        paper's central question (10 if it also connects a second flavor)
  7-8   clearly within a flavor, but it shares the stage with other aims, OR
        combines two flavors' components in a nearby, non-central way
  4-6   competent on one COMPONENT of a flavor (AI alone, politics alone,
        persuasion alone, narrative alone) without the flavored combination
  1-3   tangential; shares vocabulary but not the research space
  0     off-target or in the NOT-of-interest list"""
    else:                                   # legacy facet profile
        facets = "\n".join(
            f"- {f['key']}{' (CORE)' if f.get('core') else ' (secondary)'}: {f['description']}"
            for f in profile.get("facets", []))
        rubric = f"""FACETS:
{facets}

INTERSECTION RULE: {profile.get('intersection_rule', '')}

Score fit: 9-10 intersection of >=2 core facets is the topic; 7-8 one core facet
plus real engagement of a second; 4-6 solid single-facet; 1-3 tangential; 0 off-target."""
    geo = ""
    if western_focus:
        from app.geo import WESTERN_SOFT_PROMPT
        geo = "\n" + WESTERN_SOFT_PROMPT.strip() + "\n"
    return f"""You screen new academic papers for one specific researcher.

RESEARCHER PROFILE:
{profile['core_statement']}

EXPLICITLY NOT OF INTEREST:
{negs}

PAPERS THE RESEARCHER LIKED:
{pos_s}

PAPERS THE RESEARCHER REJECTED OR DOWNGRADED:
{neg_s}

{rubric}
{geo}
Respond with STRICT JSON only, no prose around it:
{{"facets": ["<engaged flavor keys>"], "fit": <0-10>, "why": "<ONE short sentence>"}}"""


def paper_user_msg(paper: dict) -> str:
    """Per-paper user message — verbatim contract."""
    return (f"Title: {paper.get('title')}\nVenue: {paper.get('venue') or '?'}\n"
            f"Abstract: {(paper.get('abstract') or '')[:2500]}")


def parse_single(txt: str) -> dict | None:
    """Strict-JSON verdict parser — verbatim contract from judge.py._parse."""
    m = re.search(r"\{.*\}", txt or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        fit = float(d.get("fit", -1))
        if not 0 <= fit <= 10:
            return None
        return {"facets": [str(x) for x in (d.get("facets") or [])],
                "fit": round(fit, 1), "why": str(d.get("why", ""))[:300]}
    except Exception:
        return None


# --- batched variant (free_stack Phase C contract) ---------------------------

BATCH_INSTRUCTIONS = """You will judge {n} papers IN ONE RESPONSE. Apply the same rubric \
to each paper independently. Respond with STRICT JSON only — a list with one object per \
paper, in the same order, no prose around it:
[{{"n": 1, "facets": ["<engaged flavor keys>"], "fit": <0-10>, "why": "<ONE short sentence>"}}, ...]"""


def batch_user_msg(papers: list[dict]) -> str:
    head = BATCH_INSTRUCTIONS.format(n=len(papers))
    body = "\n\n".join(f"PAPER {i}:\n{paper_user_msg(p)}"
                       for i, p in enumerate(papers, 1))
    return head + "\n\n" + body


def parse_batch(txt: str, n_expected: int) -> dict | None:
    """-> {1-based index: verdict} for parseable rows, or None if nothing parsed."""
    m = re.search(r"\[.*\]", txt or "", re.S)
    if not m:
        return None
    try:
        rows = json.loads(m.group(0))
    except Exception:
        return None
    out = {}
    for r in rows:
        try:
            i = int(r.get("n", 0))
            fit = float(r.get("fit", -1))
            if 1 <= i <= n_expected and 0 <= fit <= 10:
                out[i] = {"facets": [str(x) for x in (r.get("facets") or [])],
                          "fit": round(fit, 1), "why": str(r.get("why", ""))[:300]}
        except Exception:
            continue
    return out if out else None


def judge_batch(system: str, papers: list[dict], chat_fn) -> tuple[list[dict], str]:
    """Judge up to BATCH_SIZE papers in one call (3 parse attempts).
    chat_fn(system, user, temperature) -> (text, provider). Returns
    (verdicts aligned with `papers` — failed rows get fit -1, provider)."""
    user = batch_user_msg(papers)
    parsed, provider = None, ""
    for _ in range(3):
        text, provider = chat_fn(system, user, temperature=TEMPERATURE)
        parsed = parse_batch(text, len(papers))
        if parsed:
            break
    out = []
    for i in range(1, len(papers) + 1):
        if parsed and i in parsed:
            out.append(parsed[i])
        else:
            out.append({"facets": [], "fit": -1,
                        "why": "batch parse failed" if parsed else "batch call failed"})
    return out, provider
