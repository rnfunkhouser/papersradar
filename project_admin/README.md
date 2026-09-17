# Research Radar

Multi-user hosted "daily research radar" for academics: gathers new papers and
preprints (OpenAlex, arXiv, SocArXiv, PsyArXiv) every morning, shortlists each
user's closest matches by embedding similarity to their seed papers, has an
LLM judge score fit 0–10 against the user's editable plain-English Selection
Criteria, and delivers briefings by dashboard + email. Evolved from the
single-user `new_papers_briefing` pipeline; runs entirely on free-tier
providers (Groq/Gemini/Cerebras/OpenRouter + keyless OpenAlex).

- `DESIGN.md` — architecture, data model, quota math
- `DEPLOY.md` — server runbook (Oracle VM, papersradar.com)
- `LICENSE` — GNU AGPL-3.0-or-later (see below)

## Layout

```
app/        FastAPI web app (landing, magic-link auth, onboarding wizard,
            dashboard, settings, Zotero linking, admin) + templates + static
pipeline/   batch CLI: run_daily.py (profiles|gather|embed|shortlist-judge|
            briefings), build_profile.py, providers.py
            (free-tier chat router), embedder.py, judging.py (judge contract)
deploy/     systemd units, Caddyfile snippet, deploy.sh (rsync + restart)
tests/      pytest suite + e2e smoke — fully offline (stub OpenAlex/Zotero)
```

## Experimental: daily podcast (not a general feature)

`pipeline/podcast*.py`, `pipeline/tts.py`, `pipeline/nlm_agent.py`,
`app/routes_podcast.py`, `deploy/nlm-agent/` and `docs/PODCAST_*.md` implement an
opt-in audio briefing. The podcast is an opt-in experiment enabled by the site administrator for individual accounts via `python3 -m pipeline.podcast enable <email>`. It is off by default (`PODCAST_ENGINES` empty), has no user-facing setting, is not offered on papersradar.com to the public, and is not required for any other part of the tool. The NotebookLM engine additionally depends on browser automation of a Google product and is not recommended for general use. Treat this code as a prototype.


## Local dev

```bash
python3 -m venv .venv && .venv/bin/pip install -r project_admin/requirements.txt
cp .env.example .env          # set APP_SECRET at minimum
.venv/bin/uvicorn app.main:app --reload      # http://127.0.0.1:8000
.venv/bin/python -m pytest                   # 54 tests, no network
```

With `SMTP_HOST` empty the app runs in dev mode: magic-link URLs are logged
and shown on `/admin/dev-links` instead of emailed.

Pipeline pieces run standalone:

```bash
python3 -m pipeline.providers --check        # keys + today's quota counters
python3 -m pipeline.run_daily gather --since 2026-08-01
python3 -m pipeline.build_profile --user you@example.com
```

## License

Research Radar is free software under the **GNU Affero General Public License,
version 3 or later** (`LICENSE` at the repo root; every `.py` file carries an
SPDX header). You may use, study, modify and redistribute it. If you run a
modified version as a network service, the AGPL requires you to offer its
source to the users of that service. Contributions are accepted under the same
license.
