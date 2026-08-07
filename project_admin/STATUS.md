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
