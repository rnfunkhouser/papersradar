# Podcast feature — design spec (experimental, per-account opt-in)

> **Status (2026-09-17): experimental, not a general feature.** The podcast is an opt-in experiment enabled by the site administrator for individual accounts via `python3 -m pipeline.podcast enable <email>`. It is off by default (`PODCAST_ENGINES` empty), has no user-facing setting, is not offered on papersradar.com to the public, and is not required for any other part of the tool. The NotebookLM engine additionally depends on browser automation of a Google product and is not recommended for general use. Treat this code as a prototype.

*Locked 2026-08-31 with Ryan. Status: BUILT 2026-08-31 (130 tests passing);
deploy-by-hand steps in `PODCAST_RUNBOOK.md`.*
*Predecessor discussion: `new_papers_briefing/PODCAST_PROPOSAL.md`.*

## Decisions (final)

| Decision | Choice |
|---|---|
| Scope | Owner-only feature of papersradar (`podcast_enabled` flag, only Ryan's account). No multi-user work now. |
| Infrastructure | Existing 1 GB Oracle VM only. Worker under systemd with `MemoryMax≈450M` so OOM can only ever kill the podcast worker, never web app/pipeline. Second free VM is a later escape hatch only. |
| Cost | $0 strictly. Gemini API key on a **no-billing project** (cannot charge past free tier). No paid fallbacks. A missed morning is acceptable; fallback = one retry ~1h later, then skip + report. |
| Engines | **Trial week: both.** (a) NotebookLM via self-hosted notebooklm-mcp, dedicated Google account — two-host dialogue. (b) Script-first: our LLM writes verbatim script → Gemini multi-speaker/single TTS (free tier) — single anchor, Economist-briefing style. Both episodes published daily during trial, titles prefixed `[NLM]` / `[Anchor]`; Ryan picks the winner after a week. |
| Length | Dynamic, follows briefing size (tracks `BRIEFING_MAX_ITEMS` — if the email setting changes to 5/7/8 papers, the podcast follows): **3–4 min per full-text paper** (~450–600 words scripted), **≤1 min per abstract-only paper** (~≤150 words). |
| Schedule | Every day, episode ready **by 4:00am** (owner's tz). Daily pipeline timer moves to ~3:00am to leave generation headroom. |
| Spoken per paper | Institutions, author names (lead + "and colleagues"), journal/venue, and key numbers (sample sizes, effect sizes, CIs) for full-text papers. Full citations + links always in show notes. |
| Critique | "When warranted": neutral summary by default; flag a genuinely notable limitation/identification concern the way a good journal-club member would. No manufactured critiques. |
| Opening | Minimal dateline: "Papers Radar for <weekday>, <date>: N papers today, M with full text." Straight into paper one. Brief sign-off close. |
| Personalization | Fully third-person. Never "your work," no second person. Judge fit-rationale stays in show notes only. |
| Tone | Professional journalistic register for a PhD-level expert audience. No enthusiasm markers, superlatives, banter, rhetorical questions, or explaining standard methods terms. Mostly summary + brief neutral academic impact analysis; minimal speculation/commentary. |
| Full text | Port `fetch_fulltext.py` from new_papers_briefing as a post-judge stage; fetch OA full text only for briefed papers (~5–10/day). Judge stays abstract-based. Two-tier treatment: full-text papers get methods/results depth; abstract-only papers are flagged on air and summarized cautiously. |
| Delivery | Real RSS podcast: `papersradar.com/podcast/<secret-token>/feed.xml`, iTunes tags, cover art, chapters per paper, show notes with citations/links. Subscribe by URL. |
| Health alerting | Owner's daily briefing email gains a podcast status footer (✅ published / ⚠️ failure with specific cause: session-expired → noVNC re-login link, endpoint-changed, quota, worker-killed). Mirrored on /admin. Email goes via papersradar SMTP, independent of the Google account. |
| NotebookLM housekeeping | Fresh notebook daily; worker deletes notebooks older than 7 days (free-tier ~100-notebook cap). Free tier ~3 audio generations/day — 1/day + retry fits. Dedicated Google account (blast radius, account-level ToS enforcement, noise separation). |

## Draft prompt language

### A. Anchor script prompt (script-first engine) — the writer LLM receives:

> You are the writer for "Papers Radar," a daily audio research briefing.
> The listener is a PhD-level social scientist. Write a complete narration
> script for a single anchor, to be read verbatim by a TTS voice.
>
> REGISTER — this is the most important instruction: professional
> journalistic prose, in the style of a serious daily briefing (The
> Economist's morning briefing, not a chat show). Concretely:
> - Never use enthusiasm markers or superlatives: no "fascinating,"
>   "amazing," "exciting," "groundbreaking," "really interesting."
> - No second person, no rhetorical questions, no exclamation points.
> - Do not explain standard methods vocabulary (e.g., what
>   difference-in-differences or preregistration means). Assume expertise.
> - Speculation and editorializing are kept to a minimum; when noting a
>   paper's likely impact, do it in one or two neutral academic sentences.
>
> OPENING: exactly one dateline sentence — "Papers Radar for {weekday},
> {Month} {D}: {N} papers today, {M} with full text." Then paper one.
>
> FOR EACH FULL-TEXT PAPER (target 450–600 words, ~3–4 minutes):
> - Introduce with institutions, lead author ("... and colleagues"), and
>   venue, woven into prose (e.g., "The first paper today comes from a
>   team at ___ led by ___, published in ___, examining ___").
> - Research question and why it was open.
> - Design and data with specifics from the full text: sample sizes,
>   identification strategy, key effect sizes with uncertainty, spoken
>   precisely but readably ("an effect of roughly four percentage points,
>   with a confidence interval spanning one to seven").
> - Findings, then a brief neutral note on where this lands in its
>   literature.
> - If — and only if — a limitation or identification concern genuinely
>   stands out, note it in one or two sentences, as a careful colleague
>   would in a journal club. Do not manufacture critique for solid work.
>
> FOR EACH ABSTRACT-ONLY PAPER (≤150 words, under a minute):
> - Introduce the same way, state plainly that only the abstract is
>   available, summarize the claims cautiously, and note what a reader
>   would want to verify in the full paper.
>
> CLOSE: one sentence — paper count recap and "Full citations are in the
> show notes." No sign-off catchphrase.
>
> INPUT: the JSON below contains today's papers in order; records with
> `fulltext` get the full treatment, records with only `abstract` get the
> short treatment. Follow the given order.

### B. NotebookLM customization prompt (steering, best-effort):

> This audio overview is a daily research briefing for a PhD-level expert
> audience. Maintain a formal, professional journalistic register
> throughout — like serious radio journalism, not a casual chat. Avoid
> enthusiasm, superlatives, and banter entirely; do not say things like
> "fascinating" or "amazing." Do not explain standard research-methods
> terminology; the listener is an expert. One host presents each paper —
> naming the institutions, lead author, and journal — and the other asks
> only substantive methodological questions. For the papers provided as
> full PDFs ({list}), spend three to four minutes each and discuss the
> actual methods, sample sizes, and effect sizes with specific numbers.
> For the abstract-only papers ({list}), spend under one minute each,
> state on air that only the abstract is available, and summarize the
> claims cautiously. Note a paper's limitations only when one genuinely
> stands out. Keep speculation to a minimum. Open with the date and paper
> count, then proceed paper by paper in the order given.

## Defaults chosen (change any of these at build time)

- **Trial mechanics:** one feed, two episodes/day, titles `[NLM] Aug 31 — 5 papers` / `[Anchor] Aug 31 — 5 papers`; after the trial the losing engine's code stays behind the `PODCAST_ENGINE` switch.
- **Anchor voice:** 2–3 measured Gemini TTS voices rendered as samples on trial day one; Ryan picks.
- **Episode titles:** `{Mon D} — {N} papers ({M} full-text)`.
- **Cover art:** simple generated static image, set once.
- **No-papers day:** no episode published (feed silent), status footer says why.
- **Retry:** single retry ~60 min after failure, then skip + email footer report.

## Phase 2 (approved 2026-08-31, not yet built): multi-user anchor via BYO key

Goal: offer the anchor podcast to any papersradar user at zero marginal cost.
The one hard constraint is Gemini TTS's free tier (10 requests/day PER KEY,
measured); the fix is each user bringing their own free AI Studio key — no
card required, ~2 minutes — so capacity scales linearly and everyone stays
inside their own legitimate free tier. Scope:

1. **Schema** (additive migrations): `users.gemini_key_enc` (encrypted at
   rest exactly like `zotero_links.api_key_enc`, never sent to the browser),
   optional `users.podcast_voice` (default Charon). `podcast_enabled` +
   `podcast_token` already exist and are already multi-user.
2. **Onboarding**: one OPTIONAL step ("Daily audio briefing — beta"): short
   pitch, link + walkthrough for aistudio.google.com/apikey, paste field,
   voice picker, skippable in one click. Same card in Settings (add / replace
   / remove key, toggle off, show feed URL + subscribe-by-URL instructions).
   Key validation via the free models-list GET (never spends a TTS request).
3. **Pipeline**: `tts.synthesize(..., key=)` selects the user's decrypted key
   (server key remains only for the owner); pacing state per key; the
   "free-tier quota hit" email-footer case becomes "your Gemini key hit its
   daily cap — episode skipped today."
4. **Already done** (phase 1 built multi-user): per-user feeds/tokens/
   episodes/emails, fulltext stage scoping, admin episode table.
5. **Boundaries**: the nlm engine stays owner-only (gate on `is_admin`);
   /privacy gains a paragraph on the stored encrypted key; a
   `PODCAST_MAX_USERS` knob as a wall-clock safety valve (~1–2 min of paced
   TTS per user; revisit parallelizing across keys past ~20 users).
6. **Tests**: key encrypt/decrypt round-trip, per-user key selection,
   keyless users skipped cleanly, onboarding/settings parity (house pattern).

Estimated: ~a day. Next session's task.

## Build order (phase 1)

1. `pipeline/fetch_fulltext.py` port (post-judge, briefed papers only) + `fulltext_path` on briefing items.
2. Script-first engine end-to-end (writer prompt → Gemini TTS free tier → MP3 + chapters) — shippable without any Google-account setup.
3. RSS feed route + episode storage + cover art; subscribe on phone.
4. Email status footer + /admin mirror.
5. notebooklm-mcp worker (systemd, MemoryMax, dedicated Google account, noVNC auth) + NotebookLM engine.
6. Timer move to ~3:00am; begin trial week.
