# Podcast runbook — deploy, setup, and maintenance

Companion to `docs/PODCAST_DESIGN.md` (the locked spec). Code is built and
tested; everything below is the by-hand part on the VM, in order. The anchor
engine (§1–4) works with zero Google-account setup — do it first and you have
episodes on day one; the NotebookLM engine (§NLM) layers on after.

## 1. Deploy the code

```bash
DEPLOY_HOST=ubuntu@papersradar.com ./deploy/deploy.sh
ssh ubuntu@papersradar.com sudo apt install -y ffmpeg   # MP3 encoding
```

Install the new/changed systemd units (deploy.sh rsyncs them to
`/srv/papersradar/app/deploy/`; installation is manual by design):

```bash
sudo cp /srv/papersradar/app/deploy/papersradar-daily.timer /etc/systemd/system/
sudo cp /srv/papersradar/app/deploy/papersradar-podcast-retry.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now papersradar-podcast-retry.timer
sudo systemctl restart papersradar-daily.timer
systemctl list-timers | grep papersradar   # daily 3:00am PT, retry 4:30am PT
```

## 2. Configure `.env`

Append to `/srv/papersradar/.env` (see `.env.example` for the documented
block):

```bash
PODCAST_ENGINES=anchor            # add ,nlm after §NLM is done
```

`GEMINI_API_KEY` is already set for the judge. **Verify its Google Cloud
project has NO billing account attached** (AI Studio → project settings):
that is the $0 guarantee — past-quota TTS calls then error instead of
charging.

## 3. Enable your account + subscribe

```bash
cd /srv/papersradar/app
sudo -u papersradar ENV_FILE=/srv/papersradar/.env \
    ../venv/bin/python3 -m pipeline.podcast enable <your-email>
```

It prints your private feed URL. Subscribe by URL on your phone:
- **Overcast**: + → Add URL
- **Apple Podcasts**: Library → ⋯ → Follow a Show by URL
- **Pocket Casts**: Discover → search bar → paste URL

The feed sets `<itunes:block>Yes</itunes:block>` and is never listed in
directories; the token URL is the auth — don't share it. To rotate a leaked
token, blank it first (`enable` deliberately reuses a non-empty token):
`sqlite3 data/papersradar.db "UPDATE users SET podcast_token='' WHERE
email='...'"`, then re-run `enable` and re-subscribe.

## 4. Smoke-test the anchor engine

```bash
# TTS reachability (writes a short test file):
sudo -u papersradar ENV_FILE=/srv/papersradar/.env \
    ../venv/bin/python3 -m pipeline.tts --say "Papers Radar test." --out /tmp/t.mp3
# Full dry run against today's briefing (idempotent):
sudo -u papersradar ENV_FILE=/srv/papersradar/.env \
    ../venv/bin/python3 -m pipeline.run_daily fulltext
sudo -u papersradar ENV_FILE=/srv/papersradar/.env \
    ../venv/bin/python3 -m pipeline.run_daily podcast
sudo -u papersradar ENV_FILE=/srv/papersradar/.env \
    ../venv/bin/python3 -m pipeline.podcast status
```

Refresh the feed in your podcast app; the episode should appear.

## §TTS — when Gemini TTS 404s the model name

Preview TTS model names churn. List what your key can see and update
`GEMINI_TTS_MODEL` in `.env`:

```bash
curl -s "https://generativelanguage.googleapis.com/v1beta/models" \
  -H "x-goog-api-key: $GEMINI_API_KEY" | grep -o '"name": "[^"]*tts[^"]*"'
```

Voice alternatives for `PODCAST_ANCHOR_VOICE` (measured options): `Charon`
(default, deep), `Kore`, `Orus`, `Iapetus`. Render samples with
`python3 -m pipeline.tts --say "..." --voice Kore --out /tmp/kore.mp3`.

## §NLM — the NotebookLM two-host engine

One-time, ~an evening:

1. **Dedicated Google account** (blast radius / ToS isolation — see
   PODCAST_DESIGN.md Q&A). Create it; open notebooklm.google.com once to
   accept terms.
2. **Install the worker** on the VM:
   ```bash
   sudo mkdir -p /srv/notebooklm-mcp && sudo chown papersradar /srv/notebooklm-mcp
   cd /srv/notebooklm-mcp
   sudo apt install -y nodejs npm
   sudo -u papersradar npm install notebooklm-mcp   # github.com/roomi-fields/notebooklm-mcp
   ```
3. **One-time Google login** via the project's noVNC flow (its README;
   typically `npm run setup-auth` + browse to `http://<vm>:6080/vnc.html`
   through an SSH tunnel: `ssh -L 6080:127.0.0.1:6080 ...`). Log in as the
   dedicated account. The session persists on disk.
4. **Verify the endpoint map**: our client (`pipeline/podcast_nlm.py`)
   centralizes the worker's REST routes in `EP` — notebooklm-mcp is
   unofficial and its routes may differ by release. Compare with its docs,
   adjust `EP` if needed, then:
   ```bash
   sudo -u papersradar ENV_FILE=/srv/papersradar/.env \
       ../venv/bin/python3 -m pipeline.podcast_nlm --probe
   ```
5. **Service + config**:
   ```bash
   sudo cp /srv/papersradar/app/deploy/notebooklm-worker.service /etc/systemd/system/
   # adjust ExecStart if the package's serve command differs
   sudo systemctl daemon-reload && sudo systemctl enable --now notebooklm-worker
   ```
   In `.env`: `NLM_MCP_BASE=http://127.0.0.1:8100`,
   `NLM_VNC_URL=<the tunnel/noVNC URL you used>`, and switch
   `PODCAST_ENGINES=anchor,nlm` to start the trial week.

The worker unit carries `MemoryMax=450M`: on the 1 GB box an OOM can only
ever kill the worker (a Chromium-fallback moment), never the web app or
pipeline — worst case is a missing [NLM] episode, reported in the email
footer.

## Daily operation

- **3:00am PT** — full pipeline; episodes land in the feed, then the briefing
  email goes out with the podcast status footer (podcast users' emails are
  sent by the podcast stage, not the briefings stage).
- **4:30am PT** — retry timer re-runs fulltext+podcast; fills in only what
  failed, never re-sends the email.
- **Failure footer** decodes as:
  - `free-tier quota exhausted` — Gemini TTS free tier ran out; episode skips
    today, nothing to do (or check AI Studio quotas).
  - `NLM ... HTTP`/`session` — usually the Google session expired: open the
    noVNC link in the footer, re-login (~2 min).
  - `model ... not found` — see §TTS.
  - `worker not configured/unreachable` — `systemctl status notebooklm-worker`.
- **/admin** shows the same episode table (status, duration, error details).

## Trial week & after

Both engines publish daily as `[Anchor]` and `[NLM]` items in the one feed.
After a week, keep the winner: set `PODCAST_ENGINES` to just it. The loser's
code stays behind the switch (and `anchor` remains the natural fallback if
Google ever breaks the unofficial worker for good).
