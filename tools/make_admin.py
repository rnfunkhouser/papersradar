#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Create (or promote) an admin account. Use once on a fresh install so the
first person can log in and reach /admin; they then complete onboarding
through the normal wizard.

    python3 tools/make_admin.py --email you@example.com [--name "Your Name"]

Idempotent: re-running on an existing user just sets is_admin=1.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db as appdb  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", default="")
    a = ap.parse_args()

    con = appdb.connect()
    user = appdb.ensure_user(con, a.email.strip().lower())
    con.execute("UPDATE users SET is_admin=1, name=COALESCE(NULLIF(?, ''), name) WHERE id=?",
                (a.name, user["id"]))
    con.commit()
    print(f"admin: {a.email} (user id {user['id']})")


if __name__ == "__main__":
    main()
