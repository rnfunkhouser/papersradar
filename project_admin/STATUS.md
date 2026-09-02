# STATUS

## 2026-08-07 — initial build complete, not yet deployed

Built in one pass from the validated `new_papers_briefing/free_stack`
comparison (2026-08-07): judge = batched 8-papers/call on Groq
openai/gpt-oss-120b (5/5 top-pick parity with the old MindRouter judge),
embeddings = OpenRouter nemotron-3-embed-1b:free with an embedder-tagged
vector store so local Qwen3-0.6B can swap in later.

Done:
- DESIGN.md (architecture, schema, quota math: ~200-user ceiling on Groq at
  shortlist=40, knob `JUDGE_SHORTLIST_PER_USER`)
- Web app: landing, magic-link auth (+dev mode), 4-step onboarding, dashboard
  with judge chips + votes + click logging, settings (criteria/seeds/account),
  Zotero linking (connect/preview/import/resync/disconnect, key encrypted at
  rest), admin (users, runs, quotas, errors, dev links)
- Pipeline CLI: profiles / gather / embed / shortlist-judge / briefings, all
  idempotent + resumable, state in SQLite (WAL), pipeline_runs audit rows
- Owner import script (132 seeds + profile from the old repo)
- Tests: 39 passing, fully offline (stubbed OpenAlex/Zotero/arXiv/OSF)
- Deploy assets + DEPLOY.md runbook

Next (deploy-time, by Ryan):
- Run DEPLOY.md sections 0–3 on the VM; first gather backfill is the slow step
- Fill SMTP_* when an email sender is chosen (until then: dev-mode links)
- Watch /admin quota counters for the first week; tune GATHER window /
  shortlist size if OpenRouter's 50/day embed cap binds

Deferred (designed, not built): per-user inbound email (email_ingest table
reserved), local embedder swap, LLM prose summaries, feedback CSV export.

## 2026-08-07 — Research Radar release (rebrand + privacy + structured onboarding)

- Rebranded all user-facing surfaces to "Research Radar" (domain/package/
  services/DB stay `papersradar`); landing copy shifted to researcher-built
  tool tone, exact early-user testimonial, free-service emphasis; SOURCE_URL
  config gates "source code" links + open-source wording (empty = hidden).
- /privacy (claims verified against code) + inline data note on login/signup;
  self-serve account deletion in Settings (type DELETE, full cascade).
- Structured onboarding (6 steps): describe research / topics & intersections
  (starrable, repeatable) / exclusions — each with the founder's real profile
  as a "full example" expander (app/founder_example.py). structured_profile()
  composes the judge contract (default intersections fit rule; starred
  flavors rendered "(CORE)"); additive users columns migrate on connect;
  legacy paragraph-only users keep the fallback path. Settings has the same
  structured editor.
- Zotero: recommended path is a keyless PUBLIC group library (paste group URL
  or ID); private API-key path kept as secondary fallback.
- 30-day sessions surfaced (login copy + post-login notice); briefing-email
  footer with manage + signed one-click unsubscribe (GET /unsubscribe/<tok>,
  no login, idempotent).
- Tests: 54 passing, fully offline.
- Deploy note: server .env SMTP_FROM display name should be updated to
  "Research Radar <no-reply@papersradar.com>"; set SOURCE_URL when the public
  repo exists.

## 2026-08-09 — feature batch: coach, priority journals, geo scope, fixes

- **AI profile coach** (app/coach.py, app/routes_coach.py; COACH_DAILY_LIMIT=10
  calls/user/day shared across modes, counted in provider_usage):
  seed-based autofill (draft prefills the editor under an "AI draft" banner,
  never auto-saves), "Get suggestions on my draft" on every interest editor
  (dismissible notes, nothing applied), and the vote-informed profile audit
  in Settings (unlocks at AUDIT_MIN_VOTES=20; wording_proposals.md
  methodology; history in profile_audits, repeat audits see the previous one).
- **Priority journals**: onboarding step 5 + settings panel, OpenAlex sources
  autocomplete; gather fetches all users' priority journals + enriches
  sources.country_code; guaranteed judge slots when relevance ≥ the 60th
  percentile of the user's windowed pool (empirical: 79 owner-rated papers,
  analysis/priority_journal_threshold.md), capped at 10/user/day ON TOP of
  the shortlist (worst-case ceiling now ~142 users on Groq alone); picks
  labeled "from <journal> — your priority list" on dashboard + email.
- **Western-context scope option** (per-user, default OFF, respectful copy):
  hard filter of KNOWN non-Broad-West venues at the user's queue (app/geo.py,
  UN M49 W/N/S Europe + US/CA/GB/IE/AU/NZ) + soft judge-prompt
  deprioritization; the flag is part of the prompt so toggling bumps
  profile_version (verdict caches never mix).
- **Per-user briefing size** (5–10, users.briefing_size, NULL=global 8) in
  onboarding + settings; applies to dashboard briefing and email digest.
- **Settings parity** with onboarding enforced by tests/test_settings_parity.py
  (every wizard field must have a settings control; new wizard inputs fail
  the test until mapped).
- **Fixes**: HTML entities decoded at ingest + one-shot legacy scrub
  (data_migrations); preprint links prefer the hosting page over often-
  unregistered DOIs; email abstracts are sentence-safe excerpts with a
  "Full summary on your dashboard" deep link (/more/<id> → #paper-<id>);
  sessions now 90 days; bump_version now microsecond-precise.
- Tests: 102 passing, fully offline.

## 2026-08-09 (later) — live operations, branding, about, size default

All deployed to papersradar.com and verified:
- Ranking: within-fit-band embedding tiebreak (judgments.relevance persisted,
  legacy backfill done) — validated twice against owner blind ratings
  (P@5 1.00 both sessions vs 0.80 baseline).
- Branding: "Echo" logo (dot + two broken arcs) in nav, theme-aware SVG
  favicon + PNGs (regenerate: tools/gen_logo_assets.py, Pillow dev-only),
  email header logo, decorative bottom-arc background (.page-arcs — landing
  CTA floats over it; remove the div+CSS block to kill the treatment).
- /about page (photo app/static/ryan.jpg, origin story, contact
  admin@papersradar.com, Ko-fi support); Ko-fi links in footer + landing
  free box (ko-fi.com/rfunkhouser).
- Briefing size range now 3–10, global default 5 (owner's account uses the
  default — set 8 in Settings if preferred).
- Email: Brevo domain authenticated via API (UI verification was silently
  incomplete — see memory notes); daily briefings delivering since 08-08.
  Cloudflare Email Routing enabled for admin@papersradar.com →
  rfunkhouser@uidaho.edu: PENDING the owner clicking the destination
  verification link, then create the rule (POST /email/routing/rules — the
  exact call is in the session notes).

## NEXT — agreed plan, not yet executed
1. Owner edits docs/site-copy.md (full site copy + structure worksheet;
   `>> ` lines = structure notes) → apply all copy/structure edits → redeploy.
2. Open-sourcing (owner-confirmed decisions): AGPL-3.0 license; NEW public
   repo `research-radar` (owner runs `gh repo create` himself — permission
   classifier blocks Claude); archive old `new_papers_radar` with a pointer
   README; then set SOURCE_URL in /srv/papersradar/.env + restart web to
   activate open-source tagline + source links.
3. Oracle ARM (A1.Flex 2ocpu/12GB) still out of capacity in us-sanjose-1:
   retry = Resource Manager stack "Apply"; on success → migrate via deploy.sh
   + local Qwen3-0.6B embedder (EMBEDDER env flip + profiles/embed backfill;
   vectors are embedder-tagged).
4. Parked: tip-jar was DONE (Ko-fi); optional password login (only if 90-day
   sessions don't cover it); WYSIWYG copy-block editor (declined for now);
   GitHub Sponsors once repo public; owner's UIdaho profile v4 draft awaits
   his read + VPN-connected validation run (see new_papers_briefing/
   profile_review_2026-08-08/).

## 2026-08-09 (night) — onboarding fork, technical About, archive, full-cap embedding
Deployed + verified live:
- Onboarding opens at a binary fork: "Start from my papers" (seeds first →
  coach autofill prefills all criteria editors) vs "Write it myself" (manual);
  same 7 shared steps, path stored in users.onboarding_path; audit confirmed
  settings-only (regression test guards it). 114 tests.
- /about is technical-first (4-stage pipeline visual, verified mechanics,
  pointer to docs/how-it-works.md — auto-links when SOURCE_URL set); bio card
  at bottom. docs/how-it-works.md = comprehensive every-decision methods doc.
- /archive: per-user past briefings, month-grouped, searchable, votes live.
- OPENROUTER_RPD knob (server .env = 1000 after owner's one-time $10);
  backlog drained same night. Embedding strategy evaluation (see
  new_papers_briefing/embedding_eval_2026-08-09/): verdict = stay on nemotron,
  Cloudflare Workers AI as fallback, gte-small-on-Micro validated as escape
  hatch, ARM + local Qwen3-0.6B still the only real quality upgrade (Mac does
  the one-shot backfill), consider Oracle PAYG upgrade.
- docs/setup-evaluation.md: top-5 wording/eliciting improvements (negatives
  over-broadness warning, autofill seed sampling fix, exemplar elicitation,
  de-founder the judge rubric band, bullseye/permission-clause patterns) —
  PROPOSALS ONLY, awaiting owner's copy pass over docs/site-copy.md.

## 2026-08-31 — daily podcast (owner-only): built + tested, awaiting VM deploy
Spec locked with owner in docs/PODCAST_DESIGN.md; deploy-by-hand steps in
docs/PODCAST_RUNBOOK.md. Built (130 tests passing, 16 new, fully offline):
- Pipeline stages `fulltext` (OA-only fetch for podcast users' briefed papers:
  arXiv → Unpaywall → oa_url, sniffed PDF/HTML, negative cache in
  paper_fulltext) and `podcast` (per podcast-enabled user, every engine in
  PODCAST_ENGINES; idempotent for the 4:30am retry timer).
- Engines: `anchor` = scripted single-anchor in the locked journalistic
  register (segment-per-paper via provider router → Gemini TTS free tier →
  ffmpeg MP3 with ID3 per-paper chapters; WAV fallback sans ffmpeg);
  `nlm` = NotebookLM two-host via self-hosted notebooklm-mcp worker
  (pipeline/podcast_nlm.py; endpoint map EP must be verified at install —
  runbook §NLM). Trial week = both, [Anchor]/[NLM] items in one feed.
- Private RSS: /podcast/<token>/feed.xml (+ episode/chapters routes), iTunes
  tags, itunes:block, procedural radar cover art (tools/make_cover.py).
- Briefing email for podcast users is deferred to the podcast stage and gains
  the episode status footer (✅ duration / ⚠️ cause + noVNC re-login link);
  send idempotent via podcast_email_log. /admin shows the episode table.
- Enable via `python3 -m pipeline.podcast enable <email>` (mints feed token).
- Deploy assets: daily timer moved to 3:00am America/Los_Angeles (episodes by
  4:00), papersradar-podcast-retry.{service,timer} (4:30), notebooklm-worker
  .service (MemoryMax=450M so OOM can only kill the worker). New deps:
  pypdf, mutagen; system ffmpeg.
Next (owner, on the VM): runbook §1–4 for anchor engine day one; §NLM for the
NotebookLM engine + trial week; verify GEMINI key project has no billing.

## NEXT (queued 2026-08-31, owner-approved): multi-user anchor podcast, BYO Gemini key
Offer the anchor podcast to all users at $0: optional onboarding/settings step
where each user generates their own free AI Studio key (10 TTS req/day per
key = one episode + headroom each). Scope in docs/PODCAST_DESIGN.md "Phase 2":
users.gemini_key_enc (Zotero-key encryption pattern), optional onboarding step
+ settings card with key walkthrough/voice picker, per-user key + pacing in
tts.py, quota-cap footer message, nlm engine stays owner-only, privacy-page
note, PODCAST_MAX_USERS valve, tests. ~1 day. Feeds/episodes/emails are
already multi-user from phase 1.

## 2026-08-31 (night) — deployed live; anchor ready, nlm blocked by Google-side changes
Deployed to the VM and live-tested end-to-end. Working: feed (subscribed on
owner's phone; trailer episode placed because Apple rejects empty feeds),
timers (3:00/4:30am PT), fulltext (3/8 papers OA), TTS verified. Live testing
caught + fixed: (1) TTS free tier is 10 req/day/model -> batched episodes
(2-4 req) + pacing + 429 retry; (2) worker response envelope unwrap;
(3) DATA_DIR=/data on the worker container — Google session now persisted in
the volume (survives recreation, verified) and file-path uploads allowed.
BLOCKED (external): NotebookLM has rebranded to "Gemini Notebook" with a
redesigned add-sources UI (screenshot verified) AND showed an active
incident banner; notebooklm-mcp's source-detection selectors target the old
UI and no upstream fix exists yet (issues checked 2026-08-31). nlm engine
left enabled — fails gracefully into the email footer, retries daily; watch
upstream for a Gemini Notebook selector update. Anchor is the working engine;
first real episode expected 2026-09-01 4:00am PT.

## 2026-09-02 — nlm engine LIVE: vision agent completed a full episode
The Gemini computer-use agent (NLM_MODE=agent, gemini-3.5-flash-lite)
completed the entire flow live in 56 steps: create notebook, upload 2 PDFs,
add abstract-notes source, insert steering prompt, generate Audio Overview,
poll ready, download — m4a transcoded to a 21:54 MP3. Feed now carries both
trial episodes for Sep 1: [Anchor] 9:41 and [NLM] 21:54. Session-burn bug
fixed (cookie sync-back in finally); one noVNC re-login was needed after the
earlier burn. Trial week runs automatically from the 3:00am pipeline; the
[NLM] runtime (~22 min vs the 8-12 min spec) is steered by the customization
prompt only softly — a tuning candidate if the owner finds it long.
