---
description: End a work session - update NOTES.md, regenerate MANIFEST if outputs changed, commit, push
---

Wrap up this work session.

1. Run `git status` and `git diff --stat` so I can see what changed this session.
2. If anything in `outputs/` changed, make sure `outputs/MANIFEST.md` is current: one line per output file with the script that produced it and the current commit hash (use `git rev-parse --short HEAD` after committing, or note "this commit").
3. Update `NOTES.md`:
   - Move today's date and a 2-5 line summary of what was done into a "## Session log" section (most recent first).
   - Update the "## Current status" section if the state of the project changed.
   - Update "## Open items" - add new ones, remove finished ones.
   Keep it terse. This is a handoff for the next machine, not a diary.
4. Show me the proposed commit message (one line, imperative, specific). Wait for my approval or edits.
5. `git add -A`, commit, then `git push`. Confirm the push succeeded.
6. If the push fails, do not force anything. Explain the error and stop.
