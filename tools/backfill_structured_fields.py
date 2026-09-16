#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Backfill a legacy user's structured settings fields from their live judge
profile, WITHOUT changing judge behavior.

Why: accounts created before the 2026-08 structured onboarding (in practice,
the owner's imported account) have a rich profiles.profile_json but empty
users.interest_flavors_json / interest_negatives_json — so the Settings page
shows an incomplete picture, and worse, SAVING it would recompose the judge
contract from those thin fields (dropping a custom fit_rule and bumping the
profile version, which re-judges everything).

This script:
  1. maps the live profile into the structured form fields,
  2. recomposes a candidate contract exactly as a settings save would,
  3. verifies the JUDGE PROMPT is byte-identical before touching anything,
  4. writes the users fields, and normalizes the stored profile to the
     recomposed dict UNDER THE SAME VERSION (no re-judging) so future saves
     compare equal and become no-ops.
If the prompt differs, it prints the diff and changes nothing (--force-report
shows the full prompts). Idempotent.

    python3 tools/backfill_structured_fields.py <email> [--apply]
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db as appdb
from pipeline import judging
from pipeline.build_profile import structured_profile


def form_fields_from_profile(prof: dict) -> tuple[str, list[dict], list[str]]:
    statement = (prof.get("core_statement") or "").strip()
    flavors = [{"name": f.get("key", ""),
                "description": f.get("description", ""),
                "core": bool(f.get("core"))}
               for f in prof.get("flavors", [])]
    negatives = [str(n) for n in prof.get("negatives", [])]
    return statement, flavors, negatives


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("email")
    ap.add_argument("--apply", action="store_true",
                    help="write changes (default: dry-run report only)")
    a = ap.parse_args()
    con = appdb.connect()
    user = appdb.get_user_by_email(con, a.email)
    if not user:
        sys.exit(f"no such user: {a.email}")
    prof = appdb.get_profile(con, user["id"])
    if not prof:
        sys.exit("user has no profile — nothing to backfill from")
    version = prof["version"]

    statement, flavors, negatives = form_fields_from_profile(prof)
    composed = structured_profile(statement, flavors, negatives)
    # simulate exactly what a settings save writes (routes_user.
    # _compose_profile_and_finish): only these keys change, rest preserved
    candidate = {k: v for k, v in prof.items() if k != "version"}
    # fit_rule deliberately NOT recomposed: a custom rule survives settings
    # saves too (routes_user preserves any non-default fit_rule)
    candidate.update({k: composed[k] for k in
                      ("core_statement", "flavors", "negatives")})

    prompt_before = judging.build_prompt(prof, [], [],
                                         western_focus=bool(user["western_context"]))
    cand_v = dict(candidate, version=version)
    prompt_after = judging.build_prompt(cand_v, [], [],
                                        western_focus=bool(user["western_context"]))

    if prompt_before != prompt_after:
        print("PROMPT WOULD CHANGE — not touching anything. Diff:")
        for line in difflib.unified_diff(prompt_before.splitlines(),
                                         prompt_after.splitlines(),
                                         "current", "after-save", lineterm=""):
            print(" ", line)
        sys.exit(1)

    already = (json.loads(user["interest_flavors_json"] or "[]") ==
               [{"name": f["name"], "description": f["description"],
                 "core": f["core"]} for f in flavors])
    print(f"judge prompt: IDENTICAL after recompose ({len(prompt_before)} chars)")
    print(f"statement: {len(statement)} chars | flavors: {len(flavors)} "
          f"({sum(1 for f in flavors if f['core'])} core) | "
          f"negatives: {len(negatives)}")
    if not a.apply:
        print("dry run — rerun with --apply to write")
        return
    con.execute(
        "UPDATE users SET interest_statement=?, interest_flavors_json=?, "
        "interest_negatives_json=? WHERE id=?",
        (statement, json.dumps(flavors, ensure_ascii=False),
         json.dumps(negatives, ensure_ascii=False), user["id"]))
    # normalize stored profile to the composed form UNDER THE SAME VERSION:
    # future settings saves compare equal -> no-op, no version bump
    appdb.save_profile(con, user["id"], candidate, version)
    con.commit()
    print(f"applied: users fields backfilled; profile normalized under "
          f"version {version} (unchanged{' — was already normalized' if already else ''})")


if __name__ == "__main__":
    main()
