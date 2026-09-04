#!/usr/bin/env python3
"""Summaries stage: a real generated prose summary for every paper briefed
today (any user), fulfilling the email's "full summary on your dashboard"
link. Grounded in fetched OA full text when available (methods, samples, key
numbers), else written cautiously from the abstract. Paper-level and neutral
— shared across users — stored once in paper_summaries; idempotent, so the
retry timer can re-run it.

    python3 -m pipeline.summaries [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db as appdb
from pipeline import providers
from pipeline.fetch_fulltext import extract_text

SYSTEM_GROUNDED = """\
Write a summary of the research paper below for a PhD-level expert reader,
using the provided full text. 120-180 words of plain prose (no headings, no
bullets, no markdown). Cover: the research question, the design and data with
specifics (sample sizes, methods, key effect sizes or results with numbers
where the text provides them), the findings, and in one closing sentence
where this lands in its literature. Professional, factual register — no
superlatives, no second person, no editorializing. Do not repeat the title."""

SYSTEM_ABSTRACT = """\
Write a summary of the research paper below for a PhD-level expert reader.
ONLY the abstract is available, so 60-100 words of plain prose (no headings,
no bullets, no markdown): state the research question and the claims the
abstract makes, phrased cautiously (the full paper has not been read), and
note in a short closing clause what a reader would want to verify in the full
text. Professional, factual register — no superlatives, no second person. Do
not repeat the title."""


def write_summary(con, paper) -> tuple[str, int, str]:
    """One paper -> (summary, grounded, provider). Raises on LLM failure."""
    fulltext = extract_text(con, paper["id"])
    system = SYSTEM_GROUNDED if fulltext else SYSTEM_ABSTRACT
    body = (f"Title: {paper['title']}\n"
            f"Venue: {paper['venue'] or '(unknown)'}\n"
            f"Abstract: {paper['abstract'] or '(none)'}")
    if fulltext:
        body += f"\n\nFULL TEXT (extracted, may contain artifacts):\n{fulltext}"
    text, served = providers.chat(system, body, temperature=0.3,
                                  max_tokens=600)
    return text.strip(), 1 if fulltext else 0, served


def run(con, date: str | None = None) -> dict:
    date = date or appdb.today()
    papers = con.execute(
        "SELECT DISTINCT p.* FROM briefing_items b "
        "JOIN papers p ON p.id = b.paper_id "
        "WHERE b.date=? AND p.id NOT IN (SELECT paper_id FROM paper_summaries)",
        (date,)).fetchall()
    done = failed = 0
    for p in papers:
        try:
            summary, grounded, served = write_summary(con, p)
        except providers.ProvidersUnavailable as e:
            print(f"[summaries] stopping early ({e}) — resumes on retry",
                  file=sys.stderr)
            failed = len(papers) - done
            break
        con.execute(
            "INSERT OR REPLACE INTO paper_summaries(paper_id, summary, "
            "grounded, provider, created_at) VALUES(?,?,?,?,?)",
            (p["id"], summary, grounded, served, appdb.now()))
        con.commit()
        done += 1
    out = {"date": date, "written": done, "pending": failed}
    print(f"[summaries] {out}", file=sys.stderr)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date")
    a = ap.parse_args()
    run(appdb.connect(), a.date)
