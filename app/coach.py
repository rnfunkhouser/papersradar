# SPDX-License-Identifier: AGPL-3.0-or-later
"""AI profile coach — prompt builders, strict-JSON parsers, and the vote-
evidence assembly for its three modes:

  a) seed-based AUTOFILL: one call over seed titles+abstracts -> a draft
     profile (core statement, 3-6 intersection-style flavors, candidate
     negatives). The draft only ever PREFILLS the structured editor — the
     user edits and saves each step themselves.
  b) SUGGESTIONS on a draft: clarifying questions, concrete rephrasings
     (naming theories/frameworks visible in seeds but absent from the text),
     and flags of vague/broad phrasing. Rendered as dismissible notes beside
     the editor; nothing is applied automatically.
  c) vote-informed AUDIT: given the profile, seeds, and the user's vote
     evidence (downvotes the judge scored high, upvotes it scored low,
     per-flavor vote averages), propose specific current->suggested wording
     edits citing the motivating papers — the wording_proposals.md
     methodology from the single-user system, automated.

Pure functions here; the network call goes through pipeline.providers.chat so
coach usage lands in the same provider router, quota counters, and fallback
order as judging (admin page shows it under the same daily counts). Per-user
rate limiting lives in app.routes_coach (COACH_DAILY_LIMIT, all modes share
one budget).
"""
from __future__ import annotations

import json
import re

MAX_SEEDS_IN_PROMPT = 40
MAX_ABSTRACT_CHARS = 500
COACH_TEMPERATURE = 0.2

# --- a) seed-based autofill ---------------------------------------------------

AUTOFILL_SYSTEM = """A researcher wants their paper-screening profile drafted from papers \
they picked as exemplary of their interests. From the seed papers below, draft:
- core_statement: 3-6 sentences describing their research as they might to a sharp PhD \
student outside their subfield — what they study, the angle they take, and what only \
sounds related.
- flavors: 3-6 named sub-interests. Each must ALREADY be an intersection of interests \
("narrative persuasion in climate communication", not "climate change"), with a short \
name and 2-3 concrete sentences a reader could use to judge whether a new paper sits \
squarely inside it. Name specific theories, frameworks, and methods visible in the seeds.
- negatives: 2-5 candidate exclusions — adjacent-but-different areas that would otherwise \
sneak into results (nearby subfields, methods, or application domains the seeds noticeably \
avoid).

Respond with STRICT JSON only, no prose around it:
{"core_statement": "...", "flavors": [{"name": "...", "description": "..."}, ...], \
"negatives": ["...", ...]}"""


def autofill_user_msg(seeds: list[dict]) -> str:
    lines = []
    for s in seeds[:MAX_SEEDS_IN_PROMPT]:
        t = (s.get("title") or "").strip()
        a = (s.get("abstract") or "").strip()[:MAX_ABSTRACT_CHARS]
        lines.append(f"- {t}" + (f"\n  {a}" if a else ""))
    return "SEED PAPERS (title, then abstract when available):\n" + "\n".join(lines)


def parse_autofill(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    core = str(d.get("core_statement") or "").strip()[:4000]
    flavors = []
    for f in (d.get("flavors") or [])[:6]:
        name = str(f.get("name") or f.get("key") or "").strip()[:80]
        desc = str(f.get("description") or "").strip()[:600]
        if name and desc:
            flavors.append({"name": name, "description": desc})
    negatives = [str(n).strip()[:300] for n in (d.get("negatives") or [])[:8]
                 if str(n).strip()]
    if not core or not flavors:
        return None
    return {"core_statement": core, "flavors": flavors, "negatives": negatives}


# --- b) suggestions on the current draft --------------------------------------

SUGGEST_SYSTEM = """A researcher is drafting the Selection Criteria an AI judge will use to \
score new papers' fit for them (a core statement, named topic 'flavors' that should each be \
an intersection of interests, and exclusions). You see their current draft and their seed \
papers. Coach the WORDING — do not rewrite wholesale. Return:
- questions: 2-4 clarifying questions genuinely worth answering to sharpen the criteria \
(boundaries they haven't drawn, ambiguities a judge would trip on).
- suggestions: 2-5 concrete rephrasings or additions, each naming exactly what to add or \
change. Especially: theories, frameworks, or methods clearly visible in the seed papers \
but absent from the draft.
- flags: 0-4 quotes from the draft that are too vague or broad to steer a judge \
("misinformation", "AI and society"), each with one sentence on why it will misfire.

Respond with STRICT JSON only, no prose around it:
{"questions": ["..."], "suggestions": ["..."], "flags": ["..."]}"""


def suggest_user_msg(statement: str, flavors: list[dict], negatives: list[str],
                     seed_titles: list[str]) -> str:
    fl = "\n".join(f"- {f.get('name') or f.get('key') or '?'}: "
                   f"{f.get('description') or ''}" for f in flavors) or "(none yet)"
    ng = "\n".join(f"- {n}" for n in negatives) or "(none yet)"
    ts = "\n".join(f"- {t}" for t in seed_titles[:MAX_SEEDS_IN_PROMPT]) or "(none yet)"
    return (f"CURRENT DRAFT\n\nCore statement:\n{statement or '(empty)'}\n\n"
            f"Topics & intersections:\n{fl}\n\nExclusions:\n{ng}\n\n"
            f"SEED PAPER TITLES:\n{ts}")


def parse_suggestions(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    out = {k: [str(x).strip()[:500] for x in (d.get(k) or []) if str(x).strip()]
           for k in ("questions", "suggestions", "flags")}
    if not (out["questions"] or out["suggestions"] or out["flags"]):
        return None
    return out


# --- c) vote-informed audit ---------------------------------------------------

AUDIT_SYSTEM = """You audit the wording of a researcher's paper-screening profile against \
hard evidence: their thumbs-votes on papers an AI judge scored with that profile. The \
dominant failure mode of such profiles is UNDER-selection — wording loopholes that let the \
judge score papers the researcher actually wants at fit 0-4 (the judge's own 'why' usually \
quotes the missing permission). Over-selection (high fit, downvoted) points to a flavor or \
negative worded too loosely.

From the evidence, propose 1-6 SPECIFIC wording edits. Each proposal must cite the votes \
that motivate it and quote current wording where it exists. Kinds of edits: rewording a \
flavor description, adding a new flavor the votes reveal, rewording the core statement, \
adding/narrowing an exclusion. Do NOT propose edits the evidence doesn't support; fewer, \
better-grounded proposals beat many speculative ones. If a previous audit is shown, focus \
on what changed since: acknowledge fixed issues, don't repeat proposals already applied.

Respond with STRICT JSON only, no prose around it:
{"proposals": [{"target": "<core_statement | flavor:<name> | negatives | new_flavor>", \
"current": "<verbatim current text, or empty for additions>", \
"suggested": "<the proposed text>", \
"rationale": "<one or two sentences>", \
"motivating_papers": ["<title (their vote, judge fit, judge's why)>", ...]}, ...], \
"summary": "<2-3 sentences: the overall pattern in the votes>"}"""


def gather_audit_evidence(con, uid: int) -> dict:
    """Vote evidence joined to each paper's newest judgment for this user:
    downvotes the judge scored fit>=7 (with its why), upvotes at fit<=4, and
    per-flavor up/down counts."""
    rows = con.execute(
        "SELECT f.vote, f.title, j.fit, j.why, j.flavors_json, "
        "MAX(j.judged_at) AS _newest "
        "FROM feedback f JOIN judgments j "
        "  ON j.user_id = f.user_id AND j.paper_id = f.paper_id "
        "WHERE f.user_id=? AND f.vote != '' AND j.fit >= 0 "
        "GROUP BY f.paper_id", (uid,)).fetchall()
    down_high, up_low, flavor_votes = [], [], {}
    for r in rows:
        entry = {"title": r["title"], "vote": r["vote"], "fit": r["fit"],
                 "why": r["why"] or ""}
        if r["vote"] == "down" and r["fit"] >= 7:
            down_high.append(entry)
        if r["vote"] == "up" and r["fit"] <= 4:
            up_low.append(entry)
        for fl in json.loads(r["flavors_json"] or "[]"):
            d = flavor_votes.setdefault(fl, {"up": 0, "down": 0})
            d["up" if r["vote"] == "up" else "down"] += 1
    return {"n_votes": len(rows), "down_high": down_high, "up_low": up_low,
            "flavor_votes": flavor_votes}


def audit_user_msg(prof: dict, seed_titles: list[str], evidence: dict,
                   previous: dict | None = None) -> str:
    fl = "\n".join(f"- {f['key']}{' (CORE)' if f.get('core') else ''}: "
                   f"{f['description']}" for f in prof.get("flavors", []))
    ng = "\n".join(f"- {n}" for n in prof.get("negatives", [])) or "(none)"
    parts = [f"PROFILE\n\nCore statement:\n{prof.get('core_statement', '')}\n\n"
             f"Flavors:\n{fl}\n\nExclusions:\n{ng}",
             "SEED PAPER TITLES (sample):\n"
             + "\n".join(f"- {t}" for t in seed_titles[:25])]
    dh = evidence.get("down_high") or []
    ul = evidence.get("up_low") or []
    parts.append("DOWNVOTED papers the judge scored fit>=7 (profile too loose here?):\n"
                 + ("\n".join(f"- \"{e['title']}\" (judged {e['fit']:g}/10: {e['why']})"
                              for e in dh) or "(none)"))
    parts.append("UPVOTED papers the judge scored fit<=4 (wording loophole — the 'why' "
                 "usually names it):\n"
                 + ("\n".join(f"- \"{e['title']}\" (judged {e['fit']:g}/10: {e['why']})"
                              for e in ul) or "(none)"))
    fv = evidence.get("flavor_votes") or {}
    parts.append("PER-FLAVOR VOTES (up/down counts on judged+voted papers):\n"
                 + ("\n".join(f"- {k}: {v['up']} up / {v['down']} down"
                              for k, v in sorted(fv.items())) or "(none)"))
    if previous:
        prev = "\n".join(
            f"- [{p.get('target')}] {str(p.get('suggested'))[:160]}"
            for p in previous.get("proposals", [])[:6])
        parts.append(f"PREVIOUS AUDIT ({previous.get('created_at', '?')}) proposed:\n"
                     f"{prev}\nFocus on what the votes say has changed since.")
    return "\n\n".join(parts)


def parse_audit(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    props = []
    for p in (d.get("proposals") or [])[:8]:
        target = str(p.get("target") or "").strip()[:120]
        suggested = str(p.get("suggested") or "").strip()[:1200]
        if not target or not suggested:
            continue
        props.append({
            "target": target,
            "current": str(p.get("current") or "").strip()[:1200],
            "suggested": suggested,
            "rationale": str(p.get("rationale") or "").strip()[:600],
            "motivating_papers": [str(t).strip()[:300]
                                  for t in (p.get("motivating_papers") or [])[:6]],
        })
    if not props:
        return None
    return {"proposals": props, "summary": str(d.get("summary") or "").strip()[:800]}
