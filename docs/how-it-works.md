# How Research Radar works — the full methods document

This document walks through every design and filtering decision in the
pipeline, with the exact thresholds and formulas, verified against the code
that runs in production. It is written for a technically-curious researcher;
you don't need to read code to follow it, but every section names the module
that implements it so you can check any claim.

Configuration values quoted below are the shipped defaults (`app/config.py`);
the operator can override any of them via the server's `.env`.

## 1. The shape of the system

Research Radar splits its daily work into a **shared** part, done once
regardless of how many users exist, and a **per-user** part:

- **Shared:** gathering candidate papers and computing their embeddings. All
  users draw from one corpus of papers keyed by paper identity, so a paper is
  fetched and embedded exactly once, ever.
- **Per-user:** shortlisting (pure vector math against the user's seed
  papers — no API calls) and judging (LLM calls over the user's shortlist,
  cached so each paper is judged at most once per user per profile version).

The pipeline (`pipeline/run_daily.py`) runs once a day as a sequence of five
idempotent stages — `profiles → gather → embed → shortlist-judge →
briefings`. Every stage stores its state in one SQLite database, so an
interrupted run (a hit API quota, a network failure) simply resumes on the
next run with no lost work.

## 2. Your profile: what the system stores about your research

Setup collects, in your own words:

- a **core statement** — a few sentences describing your research;
- **topics & intersections** ("flavors") — named sub-interests, each with a
  1–3 sentence description; you can star the ones that matter most;
- **exclusions** — adjacent-but-irrelevant areas to keep out;
- **seed papers** — 3–100 papers you wish you'd been alerted to (pasted
  DOIs/titles resolved against OpenAlex, or imported from a Zotero library);
- optional **priority journals**, delivery preferences, and the geographic-
  scope option.

From this, `pipeline/build_profile.py` composes the judge's rubric (the exact
"Selection Criteria" shown in Settings) and derives two retrieval aids:

- **Retrieval concepts:** each seed's OpenAlex record lists concept tags; the
  25 most frequent concept IDs across your seeds become your retrieval
  concepts, which steer Gathering (§3).
- **Seed embeddings:** each seed's `"title. abstract"` text (capped at 2,000
  characters) is embedded (§4) so Shortlisting (§5) can measure closeness.

Profiles carry a **version string** (timestamp with microseconds). Editing
any criteria wording, toggling the geographic scope, or re-saving structured
fields bumps the version. Judgments are cached per `(user, paper,
profile_version)` — so a criteria edit automatically re-queues the current
window of papers for re-judging under the new wording, and verdicts made
under different wordings can never mix.

If no LLM provider is reachable during onboarding, the system still composes
a working profile deterministically (your description becomes a single
catch-all flavor); enrichment retries on the nightly run. Onboarding never
blocks on an API.

## 3. Gathering — building the day's shared corpus

Module: `pipeline/gather.py`. Four sources, all queried for a recent window
(default: the last **4 days**, extended to 14 on a first-ever run so a new
install backfills; each per-user shortlist later considers a 14-day window,
so a paper missed one day gets more chances):

1. **OpenAlex works** — one cursor-paged query per retrieval concept in the
   union of all users' concepts (deduplicated; concepts shared by more users
   are paged first), filtered server-side to
   `type:article, language:en`, newest first, up to **800 works per concept**
   per run. Queries use OpenAlex's polite pool (a `mailto` parameter), which
   is keyless.
2. **arXiv** — the newest submissions in categories `cs.CY`, `cs.SI`,
   `cs.CL` (computers & society, social networks, computational language),
   up to 120 per run.
3. **OSF preprints** — SocArXiv and PsyArXiv, up to 800 per provider per
   run.
4. **Priority journals** — every user-chosen journal is additionally queried
   directly (up to **100 works per journal** per run), because a flagship
   journal's new issue may fall entirely outside the concept-derived queries.

Every candidate then passes the **noise filter** (`gather.keep()`):

- discard retractions, errata, corrigenda, editorial-board pages, tables of
  contents, front/back matter (title regex), and book reviews;
- English-language records only (when the source declares a language);
- scholarly types only: `article`, `preprint`, `posted-content`;
- titles shorter than 4 words are discarded (fragments, notices);
- publication dates more than 90 days in the future are discarded (metadata
  errors).

**Identity and dedupe:** a paper's key is its DOI (lowercased) or, if it has
none, its normalized title. Inserts are `INSERT OR IGNORE` against that key,
so re-running Gathering is idempotent and papers arriving via multiple routes
(a concept query and a priority journal, say) are stored once.

Finally, any newly-seen venue IDs are batch-enriched from the OpenAlex
sources API — that's where a venue's country code comes from, which powers
the geographic-scope venue filter (§5).

## 4. Embedding — turning abstracts into vectors

Module: `pipeline/embedder.py`. Every corpus paper with an abstract, and
every seed, is embedded from the exact text `"title. abstract"` capped at
2,000 characters. The active embedder is **nvidia/nemotron-3-embed-1b** via
OpenRouter (2,048 dimensions), called in batches of 64 texts per request,
rate-paced, with a free-tier cap of 50 requests/day — if the cap is hit, the
stage stops cleanly and resumes the next day from the database.

Vectors are L2-normalized float32, and every stored vector row records the
**embedder name and dimension**. That tag matters: shortlisting only ever
compares vectors with the same tag, so switching to a different embedding
model later (a local Qwen3-Embedding-0.6B is wired in, awaiting server RAM)
corrupts nothing — new vectors are written under the new name and the old
ones are simply ignored.

Embedding is shared work: the corpus is embedded once for all users.

## 5. Shortlisting — per-user relevance, pure math

Module: `pipeline/shortlist.py`. For each user, every corpus paper from the
last **14 days** that has an abstract and hasn't been judged under the user's
current profile version gets a relevance score:

```
relevance = mean(top-3 cosine similarities to the user's seed vectors)
          − 0.3 × cosine(paper, centroid of the day's pool)
```

Two deliberate choices in that formula:

- **Top-3 nearest seeds, not the seed average.** Your seeds usually span
  several distinct interests; averaging them produces a blurry "center of
  mass" that matches none of them. Scoring against the nearest few seeds lets
  a paper be shortlisted for being squarely close to *one* of your interests.
- **Minus 0.3 × pool-centroid similarity.** Without this contrast term,
  papers that are "generically close to today's average paper" outrank papers
  "specifically close to a few of your seeds." Subtracting a fraction of each
  paper's similarity to the pool's centroid cancels the generic component.
  The recipe (top-3, weight 0.3, pool contrast) was validated in the
  single-user predecessor system against owner-rated papers.

The top **40 papers** (default `JUDGE_SHORTLIST_PER_USER`; per-user override
possible) go to the judge. Two refinements:

- **Geographic scope (opt-in, default off):** users who enabled the
  Western-context option have papers excluded whose venue has a *known*
  country outside the "Broad West" list (North America, UK/Ireland,
  Western/Northern/Southern Europe, Australia/New Zealand — `app/geo.py`).
  Venues with unknown countries (preprint servers, unenriched sources) are
  never excluded by this layer.
- **Priority-journal guaranteed slots:** papers from the user's priority
  journals that didn't make the top 40 are appended — up to **10 additional
  slots** — provided their relevance is at or above the **60th percentile**
  of that user's windowed pool. The percentile rule and its level were chosen
  empirically against 79 owner-rated papers (see
  `analysis/priority_journal_threshold.md`): a guaranteed slot should mean
  "the judge definitely reads it," not "anything the journal prints gets
  through."

Shortlisting makes no API calls; it is numpy cosine math (the day's matrix is
roughly 3,000 papers × 2,048 dims ≈ 25 MB).

## 6. The judge — an LLM reads your shortlist

Modules: `pipeline/judging.py` (prompt + parsing), `pipeline/providers.py`
(routing), `pipeline/run_daily.py::stage_shortlist_judge` (orchestration).

**The prompt.** One system prompt is built per user per run, containing, in
order: your core statement; your exclusions ("EXPLICITLY NOT OF INTEREST");
positive and negative example papers — curated exemplars first, then your **10
newest thumbs-up and 10 newest thumbs-down titles** appended so fresh
feedback speaks last; your flavors with their descriptions (starred ones
marked "(CORE)"); the fit rule; and the scoring rubric:

- **9–10** squarely inside ≥1 flavor — the flavor's defining combination IS
  the paper's central question (10 if it also connects a second flavor)
- **7–8** clearly within a flavor but sharing the stage with other aims
- **4–6** competent on one *component* of a flavor without the combination
- **1–3** tangential; shares vocabulary but not the research space
- **0** off-target or on the not-interested list

Users with the geographic-scope option ON get one appended soft instruction:
topical focus on a non-Western context "moderately lowers fit as ONE
consideration — a strong, highly relevant paper should still score well."
Because this changes the prompt, toggling the option bumps the profile
version like any wording edit.

**The call.** Papers are judged in batches of **8 per LLM call** at
**temperature 0.0** (same paper + same profile → same verdict). The model
must answer in strict JSON — one `{fit, flavors engaged, one-sentence why}`
object per paper; the batch is retried up to 3 times if the JSON doesn't
parse, and unparseable rows are marked failed (they simply return to a future
shortlist) rather than guessed at. The batched-8 format was validated against
the single-user system's one-paper-per-call judge: 5/5 identical top picks on
the same corpus.

**Providers.** Calls go through a router that tries, in order: **Groq**
(`openai/gpt-oss-120b` — the validated primary), **Gemini Flash**,
**Cerebras** (`gpt-oss-120b`), **OpenRouter** free tier. Each provider is
rate-paced, daily-capped, retried once on transient errors, and skipped for
the rest of the run if its key is rejected. Every call (success or failure)
is counted in a per-provider daily ledger visible on the admin page. If all
providers are down, the judge stage stops cleanly and resumes next run —
nothing is scored by anything other than the LLM reading your criteria.

**The cache.** Verdicts are stored per `(user, paper, profile_version)`.
Steady-state cost is therefore much lower than the worst case: a paper that
stays in your 14-day window is judged once, not daily. Editing your criteria
discards (by version-mismatch, not deletion) your cached verdicts, and the
current window is re-judged under the new wording on the next run.

## 7. Briefing selection and ranking

Module: `pipeline/briefings.py`. Daily users get a briefing every day, weekly
users on Mondays; dashboard-only users get items built without email. From
your judged-but-never-briefed papers:

- **Fit bar:** only papers with **fit ≥ 6** (`BRIEFING_MIN_FIT`) are
  eligible. Quiet days are real: if nothing clears the bar, the briefing is
  empty rather than padded.
- **Size ceiling:** up to **5 papers** by default (`BRIEFING_MAX_ITEMS`),
  per-user adjustable 3–10. A ceiling, not a quota.
- **Ordering:** fit score descending; *within* a fit band, ties are broken by
  the embedding relevance from §5, then publication date. This fit-first,
  relevance-tiebreak ordering was validated against 41 blind owner ratings in
  the predecessor system — it beat both pure-relevance and pure-fit
  orderings.
- A paper is briefed to a user at most once, ever (`briefing_items` records
  it), so a slow news day never recycles old picks.

Priority-journal picks are labeled on the dashboard and in email.

## 8. Email and links

- Email digests are sent only when the server has SMTP configured, at the
  frequency you chose, with a one-click unsubscribe link (signed token, no
  login needed, idempotent) and a manage link in every footer.
- Abstract excerpts in email are cut at **sentence boundaries** (up to ~700
  characters, never mid-sentence); trimmed cards link to the full text on
  your dashboard.
- Outbound title links prefer the **DOI** for journal-published papers but
  the **hosting page** for preprints — fresh preprint DOIs are often not yet
  registered with Crossref (verified live: new PsyArXiv DOIs 404 on doi.org
  while the OSF page resolves).
- Title clicks pass through a logging redirect (`/out/<id>`), recorded with
  their context (dashboard vs email) — this is the tool's own measure of
  whether briefings are useful, and it stays on the server.

## 9. The feedback loop and the profile audit

- **Votes:** thumbs-up/down on any card is stored once per (user, paper) and
  becomes a boundary example in the judge prompt from the next run onward
  (§6). A few votes on borderline cases measurably sharpen selection.
- **AI profile coach** (all modes rate-limited to 10 calls/user/day, shared
  budget): *seed-based autofill* drafts criteria from your seed papers during
  setup; *suggestions* critiques the draft you're editing; the
  ***vote-informed audit*** (Settings only) unlocks at **20 votes** and
  cross-examines your criteria against hard evidence — papers you downvoted
  that the judge scored ≥7, papers you upvoted that it scored ≤4, per-flavor
  vote tallies — proposing specific current→suggested wording edits, each
  citing the votes that motivate it. Nothing any coach mode produces is ever
  applied automatically; you edit your own criteria.
- Repeat audits see the previous audit's proposals and focus on what changed.

## 10. What re-queues what (cache semantics)

| You change… | Effect |
|---|---|
| Criteria wording (statement/topics/exclusions/fit rule) | profile version bumps → current window re-judged next run |
| Geographic scope toggle | same as a criteria edit (the flag lives in the judge prompt) |
| Seed papers (add/remove/Zotero sync) | profile rebuild queued: retrieval concepts + seed embeddings refresh; judgments stay valid |
| Priority journals | takes effect next gather/shortlist; no re-judging |
| Delivery settings (frequency/size/name) | no pipeline effect |
| A vote | next run's judge prompt includes it (no re-judge of already-briefed papers) |

## 11. Quotas, capacity, and why it's free to run

All LLM and embedding calls use free tiers, with automatic fallback:

| Budget | Free/day | Used for |
|---|---|---|
| OpenAlex (keyless, polite pool) | ~100k requests | gathering + seed lookups — never the bound |
| OpenRouter embeddings | 50 requests × 64 texts | corpus embedding (shared) ≈ 3,200 texts/day |
| Groq chat | ~1,000 requests | judge primary → ~8,000 verdicts/day |
| Gemini chat | 250 requests | judge fallback + coach/profile drafting |
| Cerebras chat | ~1M tokens | judge fallback |

Because judging is batched (8 papers/call) and cached (once per paper per
user per profile version), the binding knob is the shortlist size. The whole
system runs on a 1 GB single-board cloud VM: SQLite in WAL mode, one web
worker, pipeline stages sequential and nice'd.

## 12. Privacy-relevant data flows

Verified against the code (see `/privacy` for the user-facing statement):

- One SQLite database holds: email, name, interest text, seeds, settings,
  votes, click logs, coach drafts/audits, judgments, briefings.
- What leaves the server: **paper titles/abstracts and your interest text**
  go to the LLM providers (Groq, Gemini, Cerebras/OpenRouter) for judging and
  coach calls. Never your email, name, or click history.
- Sign-in links are single-use, 20-minute, stored only as SHA-256 hashes.
  Sessions are signed cookies (90 days).
- A private Zotero API key (the non-recommended path) is encrypted at rest
  and never rendered to any page; the recommended public-group path stores no
  key at all.
- Account deletion is self-serve and removes every per-user row, including
  hashed tokens and the encrypted Zotero key; shared corpus papers (public
  metadata) remain.

## 13. Provenance

Research Radar is the multi-user evolution of a single-user pipeline the
founder ran on his own literature for months. The judged-selection design,
the relevance formula, the batch-judge format, the fit-then-relevance
ordering, and the priority-journal threshold each carry over from experiments
in that system that were validated against his hand-ratings of real briefing
output (blind where feasible). Where this document says "validated," that is
the evidence base: one researcher's rated corpus — sound enough to ship,
honest enough to name.
