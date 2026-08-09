# DEPLOY.md — Papers Radar runbook

Target: the Oracle Cloud VM (Ubuntu 24.04, 1 GB RAM + 2 GB swap, Python 3.12,
Caddy already serving papersradar.com). You run these; nothing here is
automated from the dev machine except `deploy.sh`.

## 0. One-time server prep

```bash
# as your sudo user on the VM
sudo useradd -r -m -d /srv/papersradar -s /usr/sbin/nologin papersradar || true
sudo mkdir -p /srv/papersradar/{app,data,logs}
sudo chown -R papersradar:papersradar /srv/papersradar
# your deploy user needs write access for rsync + sudo systemctl restart:
sudo usermod -aG papersradar $USER   # then re-login, or chown app/ to your user
```

Server env file `/srv/papersradar/.env` (never in git, never rsynced):

```bash
sudo -u papersradar cp /srv/papersradar/app/.env.example /srv/papersradar/.env
sudo -u papersradar nano /srv/papersradar/.env
```

Set at minimum:
- `APP_SECRET` — `python3 -c "import secrets; print(secrets.token_hex(32))"`
- `BASE_URL=https://papersradar.com`
- `DB_PATH=/srv/papersradar/data/papersradar.db`
- `LOG_DIR=/srv/papersradar/logs`
- `GROQ_API_KEY`, `GEMINI_API_KEY`, `CEREBRAS_API_KEY`, `OPENROUTER_API_KEY`
- `OPENALEX_MAILTO=<your email>` (polite pool)
- `SMTP_*` — leave `SMTP_HOST` empty to start in **dev mode** (login links land
  in `/srv/papersradar/logs/web.log` and on `/admin/dev-links`; briefings are
  dashboard-only). Fill them later; no restart-order gotchas.

## 1. First deploy

From the dev machine (repo root):

```bash
DEPLOY_HOST=ubuntu@papersradar.com ./deploy/deploy.sh
```

(`deploy.sh` rsyncs the repo to `/srv/papersradar/app`, pip-installs pinned
requirements into `/srv/papersradar/venv`, restarts the web service. On the
very first run the restart step fails because the unit isn't installed yet —
that's fine, continue below.)

Install systemd units (on the VM):

```bash
cd /srv/papersradar/app
sudo cp deploy/papersradar-web.service deploy/papersradar-daily.service \
        deploy/papersradar-daily.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now papersradar-web
sudo systemctl enable --now papersradar-daily.timer
```

Caddy — replace the static-placeholder site block in `/etc/caddy/Caddyfile`
with `deploy/Caddyfile.snippet` (reverse_proxy to 127.0.0.1:8000; keeps the
www→apex redirect), then:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
```

## 2. First-run data setup

Copy the two owner-import files from the old repo to the VM (they are personal
data, not in this git repo):

```bash
scp ~/claude/new_papers_briefing/free_stack/frozen_seed_texts.json \
    ~/claude/new_papers_briefing/interest_profile.json \
    ubuntu@papersradar.com:/tmp/
```

Then on the VM (creates the DB, imports Ryan's account as admin, runs the
first pipeline):

```bash
cd /srv/papersradar/app
sudo -u papersradar ENV_FILE=/srv/papersradar/.env \
    /srv/papersradar/venv/bin/python3 -m pipeline.import_owner \
    --seeds-json /tmp/frozen_seed_texts.json --profile-json /tmp/interest_profile.json
sudo -u papersradar ENV_FILE=/srv/papersradar/.env nice -n 10 \
    /srv/papersradar/venv/bin/python3 -m pipeline.run_daily all
rm /tmp/frozen_seed_texts.json /tmp/interest_profile.json
```

Notes on the first `run_daily all`:
- `profiles` embeds the 132 seeds ≈ 3 OpenRouter requests; fetching their
  OpenAlex records is ~132 keyless calls.
- `gather` backfills a 14-day window (DB empty ⇒ automatic backfill) — this is
  the long stage (tens of minutes, OpenAlex paging).
- `embed` may hit the OpenRouter 50-requests/day cap mid-backfill (≈3,200
  texts/day). It stops cleanly; tomorrow's timer run resumes. Judge/briefings
  cover whatever is embedded so far.

## 3. Smoke checks

```bash
curl -I https://papersradar.com/                     # 200, landing page
curl -s https://papersradar.com/login | grep -q "sign-in link" && echo login ok
sudo -u papersradar sqlite3 /srv/papersradar/data/papersradar.db \
  "SELECT stage, status, detail FROM pipeline_runs ORDER BY id DESC LIMIT 5;"
```

Then in a browser: request a login link for ryan.n.funkhouser@gmail.com. In
dev mode grab it with:

```bash
grep "magic link" /srv/papersradar/logs/web.log | tail -1
```

Sign in → dashboard should show the first briefing (or the warming-up state if
embed is still resuming). `/admin` shows users, run history, quota counters.

## 4. Routine deploys

```bash
DEPLOY_HOST=ubuntu@papersradar.com ./deploy/deploy.sh
```

DB schema changes are additive (`CREATE TABLE IF NOT EXISTS`) and applied on
first connection — no migration step for now.

## 5. Rollback

Code: `git log` locally, `git checkout <good-sha>`, re-run `deploy.sh`
(rsync `--delete` makes the server tree match the checkout exactly).

Data: the DB is a single file. Before risky changes:

```bash
sudo -u papersradar sqlite3 /srv/papersradar/data/papersradar.db \
  ".backup /srv/papersradar/data/backup-$(date +%F).db"
```

Restore by stopping both services, copying the backup over `papersradar.db`
(remove `-wal`/`-shm` siblings), and starting the web service.

Full outage fallback: point the Caddy site block back at the old static
placeholder (`root * /srv/papersradar/static` + `file_server`) and reload
Caddy — the domain stays up while you debug.

## 6. Operational notes

- **Memory**: web unit capped at 300 MB (typ. ~90 MB), pipeline at 500 MB and
  nice'd; they never run in parallel workers.
- **Quota watch**: `/admin` shows today's per-provider counters vs caps.
  Groq is the judge workhorse (1,000 req/day = ~8,000 verdicts batched).
- **Logs**: `/srv/papersradar/logs/{web,pipeline}.log`,
  `journalctl -u papersradar-web -u papersradar-daily`.
- **Manual pipeline run**: `sudo systemctl start papersradar-daily.service`.
- **Switching embedders later** (server upgrade): install
  sentence-transformers into the venv, set `EMBEDDER=qwen3-embedding-0.6b`,
  run `python3 -m pipeline.run_daily profiles && ... embed` to backfill —
  vectors are embedder-tagged, nothing breaks mid-switch.

## 7. 2026-08-09 feature batch — deploy notes

New env knobs (all have safe defaults; see `.env.example`):
`PRIORITY_JOURNAL_MIN_REL_PCTL` (60), `PRIORITY_JOURNAL_MAX_PER_USER` (10),
`OPENALEX_MAX_PER_JOURNAL` (100), `COACH_DAILY_LIMIT` (10),
`AUDIT_MIN_VOTES` (20).

Migrations are automatic on first connect (web request or pipeline run):
additive columns (`users.western_context`, `users.briefing_size`,
`papers.source_id`), new tables (`sources`, `priority_journals`,
`coach_usage`, `coach_drafts`, `profile_audits`, `data_migrations`), and a
ONE-SHOT data scrub that decodes HTML entities in already-stored
papers/seeds/feedback titles (tracked in `data_migrations`; idempotent; may
take a few seconds on the first connect after deploy). Already-sent emails
cannot be fixed retroactively.

Expected first-run behavior:
- `gather` logs two new summary keys (`new_priority_journal`,
  `sources_enriched`); source-country enrichment backfills venue ids already
  in `papers` on its first pass (one batched OpenAlex call per 50 venues).
- Priority-journal slots and the Western-context option do nothing until a
  user opts in; toggling the scope option re-judges that user's window on
  the next run (profile-version bump — expected judge-load blip).
- Coach endpoints refuse politely when no provider key is configured.

Post-deploy check (spends exactly 3 LLM calls):
`sudo -u papersradar /srv/papersradar/.venv/bin/python3 analysis/verify_coach_live.py`
