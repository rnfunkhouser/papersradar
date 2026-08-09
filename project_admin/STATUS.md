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
