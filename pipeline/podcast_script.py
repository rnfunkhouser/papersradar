#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Podcast script writer: turns one day's briefed papers into (a) a verbatim
single-anchor narration script — one segment per paper, written by the LLM
router in the locked register (docs/PODCAST_DESIGN.md §A) — and (b) the
NotebookLM customization prompt for the two-host engine (§B).

Register (locked 2026-08-31): professional journalistic prose for a PhD-level
expert audience; no enthusiasm markers, superlatives, banter, second person,
or rhetorical questions; institutions/lead author/venue and key numbers
spoken; critique only when genuinely warranted; fully third-person.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import providers
from pipeline.fetch_fulltext import extract_text

# 3-4 min per full-text paper, <=1 min per abstract-only, at ~150 spoken wpm.
FULLTEXT_WORDS = (450, 600)
ABSTRACT_WORDS = 150

REGISTER = """\
REGISTER — this is the most important instruction: professional journalistic
prose, in the style of a serious daily briefing (The Economist's morning
briefing, not a chat show). Concretely:
- Never use enthusiasm markers or superlatives: no "fascinating," "amazing,"
  "exciting," "groundbreaking," "really interesting."
- No second person, no rhetorical questions, no exclamation points.
- Do not explain standard methods vocabulary (e.g., what
  difference-in-differences or preregistration means). Assume expertise.
- Speculation and editorializing are kept to a minimum; when noting a paper's
  likely impact, do it in one or two neutral academic sentences.
- Fully third-person: never reference the listener or their work.
- Plain narration only: no headings, stage directions, host names, or markup —
  every word you write will be read aloud verbatim."""

FULLTEXT_INSTRUCTIONS = f"""\
Write the narration segment for ONE paper for which the full text is provided
below (target {FULLTEXT_WORDS[0]}–{FULLTEXT_WORDS[1]} words, about three to
four minutes read aloud):
- OPEN WITH FRAMING, not facts: one or two sentences that orient the listener
  in plain conceptual terms — what area this paper sits in and what it is
  about — before any specifics land (e.g., "This next paper is about how
  culture-war language travels between platforms. The team was interested in
  the word 'woke' as a rhetorical hinge in that discourse."). Then move into
  the substance.
- Weave in institutions, lead author ("... and colleagues"), and venue as the
  framing hands off to the substance (e.g., "The work comes from a team at
  ___ led by ___, published in ___").
- The research question and why it was open.
- Design and data with specifics from the full text: sample sizes,
  identification strategy, key effect sizes with uncertainty, spoken precisely
  but readably ("an effect of roughly four percentage points, with a
  confidence interval spanning one to seven").
- Findings, then a brief neutral note on where this lands in its literature.
- If — and only if — a limitation or identification concern genuinely stands
  out, note it in one or two sentences, as a careful colleague would in a
  journal club. Do not manufacture critique for solid work."""

ABSTRACT_INSTRUCTIONS = f"""\
Write the narration segment for ONE paper for which ONLY the abstract is
available (at most {ABSTRACT_WORDS} words, under a minute read aloud):
- Open with ONE plain-language framing sentence saying what the paper is
  about before any specifics, then weave in institutions, lead author, and
  venue, state plainly that only the abstract is available, summarize the
  claims cautiously, and note what a reader would want to verify in the full
  paper."""


def _authors(paper) -> list[str]:
    try:
        return [str(a) for a in json.loads(paper["authors_json"] or "[]")]
    except ValueError:
        return []


def paper_block(paper, fulltext: str) -> str:
    """The one-paper input block handed to the writer."""
    authors = ", ".join(_authors(paper)[:10]) or "(authors unavailable)"
    lines = [f"Title: {paper['title']}",
             f"Authors: {authors}",
             f"Venue: {paper['venue'] or '(venue unavailable)'}",
             f"Published: {paper['pub_date'] or '(date unavailable)'}",
             f"Abstract: {paper['abstract'] or '(no abstract)'}"]
    if fulltext:
        lines.append(f"FULL TEXT (extracted, may contain artifacts):\n{fulltext}")
    return "\n".join(lines)


def dateline(date: str, n_papers: int, n_fulltext: int) -> str:
    nice = dt.date.fromisoformat(date).strftime("%A, %B %-d")
    ft = (f"{n_fulltext} with full text" if n_fulltext != 1
          else "one with full text")
    n = {1: "one paper", 2: "two papers", 3: "three papers", 4: "four papers",
         5: "five papers", 6: "six papers", 7: "seven papers",
         8: "eight papers", 9: "nine papers", 10: "ten papers"}.get(
             n_papers, f"{n_papers} papers")
    return f"Papers Radar for {nice}: {n} today, {ft}."


def closing(n_papers: int) -> str:
    n = "one paper" if n_papers == 1 else f"{n_papers} papers"
    return (f"That concludes today's briefing of {n}. "
            f"Full citations are in the show notes.")


def _strip_markup(text: str) -> str:
    """Defense against writer drift: drop headings/bullets/bold so nothing
    non-prose reaches the TTS voice."""
    text = re.sub(r"^\s*#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.M)
    text = text.replace("**", "").replace("__", "")
    return text.strip()


def write_segment(paper, fulltext: str, ordinal: str) -> tuple[str, str]:
    """One paper -> (narration_text, provider). Raises ProvidersUnavailable."""
    grounded = bool(fulltext)
    system = (REGISTER + "\n\n"
              + (FULLTEXT_INSTRUCTIONS if grounded else ABSTRACT_INSTRUCTIONS)
              + f"\n\nThis is the {ordinal} paper of the episode — open the "
                f"segment accordingly (\"The first paper today...\", \"Next,...\","
                f" \"The final paper today...\"), never with a heading.")
    user = paper_block(paper, fulltext)
    text, served = providers.chat(system, user, temperature=0.4,
                                  max_tokens=2000)
    return _strip_markup(text), served


def build_script(con, rows, date: str) -> dict:
    """All segments for one user's episode. rows = briefed papers in rank
    order. Returns {"segments": [{"title", "text", "grounded"}], "n_fulltext"}
    — segment 0 is the dateline, last is the close; papers in between."""
    fulltexts = [extract_text(con, r["id"]) for r in rows]
    n_ft = sum(1 for t in fulltexts if t)
    segments = [{"title": "Introduction",
                 "text": dateline(date, len(rows), n_ft), "grounded": False}]
    ordinals = ["first", "second", "third", "fourth", "fifth", "sixth",
                "seventh", "eighth", "ninth", "tenth"]
    for i, (r, ft) in enumerate(zip(rows, fulltexts)):
        ordinal = ordinals[i] if i < len(ordinals) else f"{i + 1}th"
        if i == len(rows) - 1 and len(rows) > 1:
            ordinal = "final"
        text, _ = write_segment(r, ft, ordinal)
        segments.append({"title": r["title"], "text": text, "grounded": bool(ft)})
    segments.append({"title": "Close", "text": closing(len(rows)),
                     "grounded": False})
    return {"segments": segments, "n_fulltext": n_ft}


# --- NotebookLM (two-host engine) --------------------------------------------

def nlm_steering_prompt(rows, fulltexts: list[str], date: str) -> str:
    """The Audio Overview customization prompt (docs/PODCAST_DESIGN.md §B),
    with the full-text / abstract-only paper lists filled in."""
    ft_titles = [r["title"] for r, t in zip(rows, fulltexts) if t]
    ab_titles = [r["title"] for r, t in zip(rows, fulltexts) if not t]
    ft_list = "; ".join(f'"{t}"' for t in ft_titles) or "(none)"
    ab_list = "; ".join(f'"{t}"' for t in ab_titles) or "(none)"
    nice = dt.date.fromisoformat(date).strftime("%A, %B %-d")
    return (
        "This audio overview is a daily research briefing for a PhD-level "
        "expert audience. Maintain a formal, professional journalistic "
        "register throughout — like serious radio journalism, not a casual "
        "chat. Avoid enthusiasm, superlatives, and banter entirely; do not "
        "say things like \"fascinating\" or \"amazing.\" Do not explain "
        "standard research-methods terminology; the listener is an expert. "
        "One host presents each paper — naming the institutions, lead "
        "author, and journal — and the other asks only substantive "
        "methodological questions. Open every paper with a sentence or two "
        "of plain-language framing (what the paper is about and the area it "
        "sits in) before any specific findings or numbers. "
        f"For the papers provided as full documents ({ft_list}), spend three "
        "to four minutes each and discuss the actual methods, sample sizes, "
        "and effect sizes with specific numbers. "
        f"For the abstract-only papers ({ab_list}), spend under one minute "
        "each, state on air that only the abstract is available, and "
        "summarize the claims cautiously. Note a paper's limitations only "
        "when one genuinely stands out. Keep speculation to a minimum. "
        f"Open with the date ({nice}) and paper count, then proceed paper by "
        "paper in the order given.")
