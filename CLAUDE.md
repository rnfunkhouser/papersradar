# papersradar (Research Radar)

The multi-user "Research Radar" web app and daily pipeline behind papersradar.com: users give seed papers and plain-English selection criteria; each morning the pipeline gathers new papers, embeds and shortlists them, has an LLM judge score fit, and emails a briefing plus a dashboard. Runs on an Oracle Cloud VM (see DEPLOY.md); architecture in DESIGN.md.

Conventions: follow the global ~/.claude/CLAUDE.md. Manuscript work happens outside this repo; see NOTES.md for the location.

Read NOTES.md first each session for current status and the next pickup point.

## Data

- No raw research data in this repo. `data/` is gitignored and holds only the local dev SQLite database and runtime state.
- Production state lives on the VM at `/srv/papersradar/data/papersradar.db` and is never pulled into git.
- Secrets live in `.env` (gitignored; `.env.example` is the committed template) and in `/srv/papersradar/.env` on the VM.

## Commands

See DEPLOY.md for the runbook. Local: `python3 -m venv .venv && .venv/bin/pip install -r project_admin/requirements.txt`; tests with `.venv/bin/pytest`.
