#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Live verification of the AI-coach prompt wiring — exactly 3 routed chat
calls (one per coach mode), hard-capped, using synthetic example-profile-flavored
data. Run from a machine whose .env has at least one provider key:

    python3 analysis/verify_coach_live.py

Prints, per mode: provider that served it, whether the strict-JSON parser
accepted the reply, and a one-line sample. Exits non-zero if any mode fails.
The calls land in provider_usage like all other traffic (visible on /admin).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import coach                                    # noqa: E402
from pipeline import providers                           # noqa: E402

SEEDS = [
    {"title": "Durably reducing conspiracy beliefs through dialogues with AI",
     "abstract": "A conversational AI intervention durably reduces conspiracy "
                 "beliefs across a large sample, with effects persisting two months."},
    {"title": "Narrative persuasion in polarized online political discussion",
     "abstract": "Experiments show stories outperform statistics when crossing "
                 "partisan divides in online forums."},
    {"title": "Bridging divides with structured cross-partisan conversations",
     "abstract": "A field experiment testing whether structured dialogue reduces "
                 "affective polarization."},
]

STATEMENT = ("I study how conversational AI and narratives persuade people in "
             "online political contexts, and what durably changes attitudes.")

EVIDENCE = {
    "n_votes": 21,
    "down_high": [{"title": "Negative campaigning in digital political ads",
                   "vote": "down", "fit": 9.0,
                   "why": "Central question in online political discourse."}],
    "up_low": [{"title": "AI disclosure labels shape trust in chatbot advice",
                "vote": "up", "fit": 2.0,
                "why": "No persuasion or political communication component."}],
    "flavor_votes": {"political_discourse_online": {"up": 2, "down": 5},
                     "ai_persuasion": {"up": 6, "down": 0}},
}

PROFILE = {"core_statement": STATEMENT,
           "flavors": [{"key": "ai_persuasion",
                        "description": "Conversational AI that shifts attitudes."},
                       {"key": "political_discourse_online",
                        "description": "Dynamics of online political talk."}],
           "negatives": ["Chatbot UX without persuasion outcomes"]}


def main() -> int:
    try:
        providers.require_any_key()
    except providers.ProvidersUnavailable as e:
        print(f"SKIPPED (0 API calls spent): {e}")
        return 1
    failures = 0
    calls = [
        ("autofill", coach.AUTOFILL_SYSTEM, coach.autofill_user_msg(SEEDS),
         coach.parse_autofill),
        ("suggest", coach.SUGGEST_SYSTEM,
         coach.suggest_user_msg(STATEMENT, PROFILE["flavors"],
                                PROFILE["negatives"], [s["title"] for s in SEEDS]),
         coach.parse_suggestions),
        ("audit", coach.AUDIT_SYSTEM,
         coach.audit_user_msg(PROFILE, [s["title"] for s in SEEDS], EVIDENCE),
         coach.parse_audit),
    ]
    for name, system, user_msg, parse in calls:          # exactly 3 calls
        try:
            text, served = providers.chat(system, user_msg,
                                          temperature=coach.COACH_TEMPERATURE)
        except providers.ProvidersUnavailable as e:
            print(f"[{name}] UNAVAILABLE: {e}")
            failures += 1
            continue
        parsed = parse(text)
        sample = ""
        if parsed:
            if name == "autofill":
                sample = f"{len(parsed['flavors'])} flavors, first: " \
                         f"{parsed['flavors'][0]['name']!r}"
            elif name == "suggest":
                sample = f"{len(parsed['suggestions'])} suggestions, " \
                         f"{len(parsed['questions'])} questions"
            else:
                sample = f"{len(parsed['proposals'])} proposals, first target: " \
                         f"{parsed['proposals'][0]['target']!r}"
        print(f"[{name}] provider={served} parsed={'OK' if parsed else 'FAIL'} {sample}")
        if not parsed:
            print(f"  raw reply head: {text[:200]!r}")
            failures += 1
    print(f"\nspend: 3 routed chat calls (see provider_usage / admin page)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
