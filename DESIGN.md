# Research Radar — design

(Branded "Research Radar" in all user-facing surfaces since 2026-08; the
domain, package, service names, and DB stay `papersradar`.)

Multi-user hosted evolution of the single-user `new_papers_briefing` pipeline.
Target: papersradar.com on a 1 GB Oracle Cloud VM (Ubuntu 24.04, Python 3.12,
Caddy already terminating TLS). Free-tier LLM/embedding providers only.

## 1. What changes going multi-user

The single-user system hardcodes one person everywhere: one `seeds.txt`, one
`interest_profile.json`, one `feedback.json`, one briefing directory, one email
address, one MindRouter key. The hosted version splits state into:

- **Shared, per-day work (done once):** gathering candidate papers from
  OpenAlex/arXiv/OSF and embedding them. Papers and their vectors live in a
  shared corpus keyed by paper identity. Cost does NOT scale with user count.
- **Per-user, cheap work:** shortlisting (cosine math against the user's seed
  vectors — no API calls) and LLM-judging the user's shortlist (batched 8
  papers/call, cached per (user, paper, profile-version) so each paper is
  judged once ever per user). Cost scales with user count but is bounded by a
  config knob (`JUDGE_SHORTLIST_PER_USER`).
- **Per-user state:** account, interest profile (core statement + flavors +
  negatives + exemplars — the exact `judge.py` contract), seed papers + their
  embeddings, judgments, briefings, feedback votes, click logs, settings.

## 2. Product surface

### Landing page (`/`)
Modern SaaS marketing page: gradient/glass hero ("Your daily research radar"),
value props (field-agnostic coverage from OpenAlex + preprint servers,
transparent AI rationales on every pick, tune-it-yourself criteria), 3-step
how-it-works, testimonial-style placeholder, responsive, light+dark, zero CDN
assets. Served by the app (Caddy reverse-proxies everything; the old static
placeholder is retired).

### Auth — magic-link, no passwords
- `POST /login` with an email → single-use token (32 random bytes; only its
  SHA-256 stored), 20-minute expiry → emailed link `/auth/<token>`.
- Clicking sets a signed session cookie: `uid.expiry.HMAC(APP_SECRET)`,
  30-day life, `HttpOnly; SameSite=Lax; Secure` behind Caddy.
- Signup and login are the same flow: an unknown email creates a user row on
  first successful link click (so no unverified accounts exist).
- Rate limits (DB-backed): 5 requests / email / 15 min, 30 / IP / 15 min.
- **Dev mode:** when `SMTP_HOST` is unset, the login link is written to the
  structured log AND listed on `/admin/dev-links` (admin-only). First-ever
  login on a fresh install: `pipeline/import_owner.py` creates the admin, and
  the link also appears in the app log — documented in DEPLOY.md.

### Onboarding wizard (`/onboarding`, steps 1–6, progress bar)
Each step explains itself in plain language for a non-technical academic.
Steps 2–4 are the STRUCTURED interest editor (2026-08): each carries a
"Want to see a full example?" expander showing the founder's real profile
(hardcoded in `app/founder_example.py`).
1. **About you** — name, how often to email (daily / weekly / dashboard-only).
2. **Describe your research** — a few sentences, "as you would to a sharp PhD
   student outside your subfield" → the profile's `core_statement`.
3. **Topics & intersections** — repeatable entries (short name + 1–3 sentence
   description, star = core); guidance nudges specific theories/frameworks/
   methods and explains that intersections beat broad topics → `flavors`
   (keys slugified; starred entries get `core: true`, rendered "(CORE)" in
   the judge prompt; `fit_rule` composed from a default intersections
   template, +CORE sentence only when something is starred).
4. **Not interested** — repeatable exclusion entries (optional) → `negatives`.
   Structured entries live additively on users
   (`interest_flavors_json` / `interest_negatives_json`, migrated on
   connect); legacy users with only `interest_statement` keep the fallback +
   LLM-drafted-flavors path.
5. **Seed papers** — paste DOIs or titles (3 minimum, ~10–100 ideal); each is
   looked up on OpenAlex and shown back (title/venue/year) for confirm/remove.
   Explained: "Seeds steer the *Gathering* stage — we search the areas your
   seeds live in and shortlist new papers that sit close to them."
   **Or link a Zotero library** — the RECOMMENDED path is a dedicated
   PUBLIC group library (create a free group, Public + Closed membership, add
   just the seed papers, paste the group URL or ID — public groups need NO
   API key, and users never hand over their whole personal library). The
   private-library path (READ-ONLY API key, encrypted at rest) remains as a
   clearly-secondary fallback. After connecting they pick a collection (or "entire library"), see a preview of
   what would be imported (counts + sample titles, DOI vs needs-title-match),
   and confirm. The import logic is ported from the single-user
   `harvest.sync_zotero()`: scholarly item types only, DOI from the record or
   the `extra` field, no-DOI items title-resolved against OpenAlex with a
   close-match guard, and an append-only per-user ledger (`{dois, keys}`) so
   re-sync is idempotent and a seed the user deleted is never re-added.
   Credentials live in `zotero_links` with the API key encrypted at rest
   (HMAC-SHA256 keystream keyed off APP_SECRET) and are NEVER rendered back
   to the browser; settings offers "refresh from Zotero" and disconnect
   (disconnect keeps imported seeds).
6. **Review & finish** — shows the drafted setup; explains the two stages
   (Gathering casts the net from your seeds; Selection is an AI judge reading
   every shortlisted abstract against your criteria and scoring fit 0–10 with
   a one-sentence rationale) and what "flavors" are (named sub-interests the
   judge tags each pick with).

Finishing stores seeds + description and triggers `build_profile` for the user
(inline best-effort thread; the nightly pipeline retries anything pending):
seed OpenAlex records fetched → retrieval concepts derived; an LLM drafts
2–5 flavors from the description + seed titles (falls back to a single flavor
= the user's own description verbatim if no provider is reachable, so
onboarding never blocks on an API).

### Dashboard (`/dashboard`)
Evolved card design from `dashboard.py`: per-day briefing of cards — title
(links out through a click-logging redirect), citation line, judge chip
(`fit/10` + flavor tags), judge rationale, abstract, 👍/👎 buttons. Chip and
scores link to `/about-scores`, a plain-language explainer page (tooltips on
the chip as well). Archive of past briefing days. Quiet-day state and
"pipeline hasn't run yet" state.

### Settings (`/settings`)
Edit name, email frequency; edit Selection Criteria with the SAME structured
editor as onboarding (core statement, topic entries with core stars,
exclusions, optional hand-written fit rule — bumps profile version, which
discards that user's judgment cache exactly like `judge.py`); add/remove
seed papers (re-runs profile build); DELETE ACCOUNT (type DELETE to confirm
→ `db.delete_user_cascade` removes every per-user row, incl. hashed login
tokens and the encrypted Zotero key; shared corpus papers stay).

### Privacy & email surface
`/privacy` states, verified against the code: what is stored (email,
interest text, seeds, votes, clicks — one SQLite DB), hashed one-time login
tokens, 30-day cookie sessions (surfaced on the login page and in a
post-login notice), Zotero keys encrypted at rest and never re-displayed,
titles/abstracts + interest text sent to Groq/Gemini/OpenRouter-Cerebras
(nothing else personal), no third-party analytics, no selling/sharing, only
chosen briefings + requested login links, self-serve deletion. Briefing
emails carry a footer with manage (settings) and one-click unsubscribe
links; `GET /unsubscribe/<uid.hmac>` (signed with APP_SECRET, no login,
idempotent) sets frequency='none'. `SOURCE_URL` config gates "source code"
links / open-source wording (hidden until the repo is public).

### Admin (`/admin`, `is_admin` users)
User list (seeds/judgments/last-briefing counts), pipeline run history +
status, per-provider daily quota counters, recent errors, dev-mode login
links.

### Feedback capture (pilot-evaluation data — day one)
- 👍/👎 on every card → `feedback(user_id, paper_id, vote, ts)`; votes also
  feed the judge prompt as boundary examples (exactly as `judge.py` does).
- Every outbound title click goes through `/out/<paper_id>` → logs
  `clicks(user_id, paper_id, ts, context)` then 302s to the DOI/OA URL.
- Both tables are append-friendly and exportable (admin CSV later).

## 3. Data model (SQLite, WAL mode, single file `data/papersradar.db`)

```
users            id, email UNIQUE, name, is_admin, frequency('daily'|'weekly'|'none'),
                 shortlist_size NULL (per-user override of JUDGE_SHORTLIST_PER_USER),
                 onboarded_at, created_at
auth_tokens      token_hash UNIQUE, email, created_at, expires_at, used_at
login_attempts   email, ip, ts                       (rate limiting)
profiles         user_id UNIQUE, version, profile_json, updated_at
                 -- profile_json holds the exact judge.py contract:
                 -- {core_statement, flavors[], fit_rule, negatives[],
                 --  positive_exemplar_titles[], negative_exemplar_titles[],
                 --  retrieval_concepts[]}
seeds            id, user_id, doi, openalex_id, title, abstract, added_at,
                 source('onboarding'|'settings'|'zotero'|'import')
zotero_links     user_id UNIQUE, library_type('user'|'group'), library_id,
                 collection_key(''=whole library), api_key_enc (encrypted at rest,
                 never sent to the browser), connected_at, last_sync_at,
                 ledger_json({dois,keys} append-only sync ledger)
seed_embeddings  seed_id, embedder, dim, vector BLOB   UNIQUE(seed_id, embedder)
papers           id, key UNIQUE (doi-lower or normalized-title), doi, title, venue,
                 authors_json, pub_date, created_date, type, abstract, oa_url,
                 source, concept_ids_json, countries_json, first_seen
paper_embeddings paper_id, embedder, dim, vector BLOB  UNIQUE(paper_id, embedder)
judgments        user_id, paper_id, profile_version, fit, flavors_json, why,
                 provider, judged_at                   UNIQUE(user_id, paper_id, profile_version)
briefing_items   user_id, date, paper_id, rank, fit    UNIQUE(user_id, date, paper_id)
feedback         user_id, paper_id, vote('up'|'down'|''), title, ts  UNIQUE(user_id, paper_id)
clicks           id, user_id, paper_id, ts, context
provider_usage   date, provider, ok_count, err_count, last_detail, last_ts
                 UNIQUE(date, provider)               (quota counters, admin-visible)
pipeline_runs    id, stage, started_at, finished_at, status, detail
email_ingest     id, user_id, msg_id, received_at, from_addr, subject, raw_path,
                 parsed_json, status                  -- RESERVED: per-user inbound
                 -- email (Scholar-alert forwarding). Schema exists; nothing
                 -- writes it yet. A future MX/webhook worker inserts rows and a
                 -- parser promotes them into `papers` with source='email'.
```

**Vectors** are float32 blobs with `embedder` + `dim` recorded on every row.
Switching embedders (the planned local Qwen3-Embedding-0.6B once the server
has RAM) invalidates nothing destructively: new vectors are written under the
new embedder name; shortlisting only ever compares vectors with the SAME
embedder tag; old rows can be pruned later. `EMBEDDER` config selects the
active one (`nemotron-3-embed-1b` today, 2048-d; `qwen3-embedding-0.6b`,
1024-d, when enabled).

## 4. Pipeline (plain CLI, cron/systemd-timer, sequential, nice'd)

`pipeline/run_daily.py <stage>|all` — every stage idempotent, resumable, all
state in the DB, structured logging to `logs/pipeline.log`, a `pipeline_runs`
row per stage. Stages, in order:

1. **profiles** — (re)build any pending user profiles (new signups, edited
   seeds): fetch seed records from OpenAlex, embed seed texts (`title.
   abstract`[:2000] — the exact harvest construction), derive retrieval
   concepts, LLM-draft flavors if missing.
2. **gather** — OpenAlex per-concept cursor paging over the UNION of all
   users' retrieval concepts (deduped), polite-pool `mailto`, plus arXiv +
   SocArXiv/PsyArXiv; window `--since` (default 4 days back; first run
   backfills 14). Noise/type/language filters from `harvest.keep()`. Dedupe
   against `papers.key`; insert new rows only.
3. **embed** — corpus papers missing a vector for the active embedder →
   batched (64/request) OpenRouter nemotron calls, RPM-paced, daily-cap-aware
   (stops cleanly at the cap; next run resumes). Shared across all users.
4. **shortlist** — per user: cosine of each windowed paper vs the user's seed
   vectors (mean of top-3 nearest seeds, minus 0.3 × similarity to the pool
   centroid — the validated `contrast="pool"` recipe), take top
   `shortlist_size` not yet judged under the current profile version.
5. **judge** — per user: batched 8-papers-per-call through the provider
   router (Groq `openai/gpt-oss-120b` primary — the validated 5/5-identical
   recipe — then Gemini flash, Cerebras, OpenRouter). EXACT `judge.py`
   prompt: same system prompt builder (profile + recent-vote boundary
   examples), same per-paper user message, same strict-JSON parse, the
   Phase-C batch instruction block, temperature 0.0. Verdicts →
   `judgments`, cached per profile version.
6. **briefings** — per user due today (daily users every day; weekly users on
   Monday): pick judged-but-never-briefed papers with fit ≥ `BRIEFING_MIN_FIT`
   (default 6), top `BRIEFING_MAX_ITEMS` (default 8) → `briefing_items` →
   dashboard shows it; email digest via SMTP abstraction (silently
   dashboard-only when SMTP unset).

`pipeline/build_profile.py --user <id|email>` is independently runnable (also
invoked by the web app on onboarding/settings change).
`pipeline/import_owner.py` seeds Ryan's account (email
ryan.n.funkhouser@gmail.com, admin) from the old repo's
`free_stack/frozen_seed_texts.json` (132 seeds with texts) + his existing
`interest_profile.json` — day-one working account.

## 5. Quota math (free tiers, checked 2026-08-07)

| budget | free/day | spent on | capacity |
|---|---|---|---|
| OpenAlex (keyless) | ~100k req | gathering (shared) + seed lookups | ~200–400 req/day — never the bound |
| OpenRouter embeddings | 50 req (1,000 if account ever bought $10 credits) | corpus embedding, 64 texts/req, shared | 3,200 texts/day (64k with credits). Typical daily new corpus 1–3k papers → fits; overflow resumes next day |
| Groq chat (~1,000 req) | judge primary | 8 verdicts/req → **8,000 verdicts/day** |
| Gemini chat (250 req) | judge fallback + profile drafting | +2,000 verdicts/day |
| Cerebras chat (1M tok/day) | judge fallback | ~+1,500 verdicts/day when active |

Worst case (every shortlisted paper new, shortlist=40): 5 judge calls per
user per day → **~200 users on Groq alone**, ~250+ with fallbacks. Steady
state is far cheaper because judgments are cached per paper. The binding knob
is `JUDGE_SHORTLIST_PER_USER` (default 40; per-user override column). The
embedding stage is shared, so user count doesn't touch it; the real embedding
bound is corpus size per day, which the gather window/paging caps control.

## 6. Server fit (1 GB RAM)

- SQLite WAL, single uvicorn worker (`--workers 1`), no ORM; web app resident
  ~60–90 MB (stdlib + FastAPI + Jinja2; numpy is imported by pipeline
  processes only, never by the web app).
- Pipeline runs sequentially under `nice -n 10`, one stage at a time; peak is
  the shortlist stage's numpy matrix (~3k papers × 2048 f32 ≈ 25 MB).
- systemd: `papersradar-web.service` (uvicorn on 127.0.0.1:8000, MemoryMax
  guard), `papersradar-daily.service` + `.timer` (daily pipeline).
- Caddy: `papersradar.com` reverse_proxy → 127.0.0.1:8000; www redirect kept.

## 7. Deferred (designed-for, not built)

- **Per-user inbound email** (Google Scholar alert forwarding): `email_ingest`
  table reserved (above); `papers.source` already free-text so `'email'`
  slots in; per-user ingest addresses would be `u<id>@in.papersradar.com` via
  an MX or forwarding webhook.
- Local embedder swap (needs server RAM): `EMBEDDER=qwen3-embedding-0.6b`
  config flip + backfill run; vector rows are embedder-tagged so the swap is
  non-destructive.
- LLM prose summaries per briefing entry (the old `write_briefing.py` step):
  quota-expensive per-user; v1 shows judge rationale + abstract instead.
- Admin CSV export of feedback/clicks; downvote-cluster alerts; coverage
  audit proposals (single-user features that port cleanly later).
