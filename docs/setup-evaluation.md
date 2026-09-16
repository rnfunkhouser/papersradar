# Setup-pipeline evaluation: can onboarding produce dialed-in judges?

2026-08-09. Method: (i) a code-level trace of every collected field into the
judge prompt; (ii) a replay of the six evidence-grounded failure modes from
the single-user system's `profile_review_2026-08-08/wording_proposals.md`
against the current wizard guidance; (iii) a gap analysis against the owner's
hand-tuned v3 profile; (iv) a live probe — the ACTUAL autofill coach run over
two synthetic researcher personas (real OpenAlex papers) and over the owner's
frozen 132-seed set, compared to his v3 profile. **5 LLM calls spent** (cap
was 30), through the production provider router.

Everything in "PROPOSED WORDING" blocks is a proposal for the owner's copy
pass — nothing below has been applied to the live step copy.

---

## 1. Field trace: what the wizard collects vs what the judge reads

`app/routes_user.py` (collection) → `pipeline/build_profile.py::
structured_profile` (composition) → `pipeline/judging.py::build_prompt`
(the prompt).

| Collected in setup | Profile field | In judge prompt? |
|---|---|---|
| Describe-step statement | `core_statement` | Yes — "RESEARCHER PROFILE", read first |
| Topic entries (name/desc/★) | `flavors[]` (+`core`) | Yes — "INTEREST FLAVORS", ★ renders "(CORE)" + one fit-rule sentence |
| Exclusions | `negatives[]` | Yes — "EXPLICITLY NOT OF INTEREST" |
| — (not collected in onboarding) | `fit_rule` | Yes — composed default only; hand-editable in Settings only |
| — (no UI anywhere) | `positive_exemplar_titles[]` | Yes — "PAPERS THE RESEARCHER LIKED" (empty for every new user) |
| — (no UI anywhere) | `negative_exemplar_titles[]` | Yes — "PAPERS THE RESEARCHER REJECTED" (empty for every new user) |
| Seeds | `retrieval_concepts` (derived) | No (Gathering only) — correct |
| Name / frequency / size / journals | — | No — correct |
| Western-context option | prompt flag | Yes (soft geo paragraph) — correct |

Findings:

- **T1 — The exemplar slots are prompt-rendered but never elicited.** The
  judge contract carries curated positive/negative exemplars; the owner's v3
  has 8 + 7 (two negatives *annotated* with the reason — "fine paper, but
  chatbot wellbeing without persuasion/politics is a 1, not a 2" — which the
  judge reads verbatim). New users' prompts render these sections empty until
  votes accumulate (votes append as "(recent 👍/👎)" titles). This is the
  single largest collected-vs-valuable gap. Note the mechanism is cheap: the
  user already pastes seed papers — starring 3–5 of them as "exactly my
  thing" would populate `positive_exemplar_titles` with zero new UI concepts.
- **T2 — `fit_rule` is a Settings-only afterthought.** Onboarding composes
  `DEFAULT_FIT_RULE` (good text) but offers no way to add the calibration
  notes that do real work in the owner's rule ("political advertising ...
  solid background (4-6) ... unless"; "prejudice-reduction counts only when
  ideological divides are the target"). The Settings hint even says "Leave
  blank to use the default rule", which reads as "ignore this".
- **T3 — Owner-specific text leaks into EVERY user's rubric.** The hardcoded
  4–6 band in `judging.build_prompt` reads "competent on one COMPONENT of a
  flavor **(AI alone, politics alone, persuasion alone, narrative alone)**".
  Those parenthetical examples are the *example profile's* components; a coral
  ecologist's judge is told about "politics alone". Worse, "persuasion alone"
  is precisely the clause his own review (W1) identified as a wording
  bottleneck. The parenthetical should be dropped or generated from the
  user's own flavor names.
- No collected-but-unused fields exist (name/frequency/journals correctly
  stay out of the prompt).

## 2. Failure-mode replay: would the wizard prevent or reproduce them?

The reference review's evidence: the judge's false-positive problem is
essentially solved; the dominant error is **under-selection through wording
loopholes**. Per failure mode:

| Failure mode (ref) | Current wizard behavior | Verdict |
|---|---|---|
| **W1 — missing flavor → wanted papers at fit ≤2** (persuasion-alone science was top-shelf for him, but no flavor claimed it) | The topics step *pushes* intersections ("Intersections beat broad topics") and the hardcoded rubric bins single components at 4–6. A user whose interests include a standalone dimension gets no prompt to declare it, and the guidance actively steers them away from doing so. | **Reproduces it.** The intersection doctrine is right for noise control but needs the counter-question: "is any single strand a bullseye on its own? Say so explicitly." |
| **W2 — over-broad negatives swallowing wanted papers** ("attitudes TOWARD AI" + "chatbot UX" vetoed AI-as-communicator perception work the example-profile author rated 4–5) | The negatives step says exclusions "do a lot of work" and encourages adding them; no warning that a broad negative outranks flavors in practice, no nudge toward conditional phrasing ("X *with no* Y") or IN-pointers ("...are IN, per flavor_z"). The example profile silently models the conditional pattern, but nothing names it. | **Reproduces it** (guidance); the *suggest* coach, when invoked, does catch it — see probe §5. |
| **W3 — advertising/theory loophole** (fit_rule calibration never applied because the judge cites the flavor description, not the rule) | Users can't write calibration notes at all during onboarding (T2), so they can't even create this bug — but they also can't do the fix (put calibrations INTO the flavor description). No guidance says "the judge reads each flavor description as self-contained; put boundary rules inside the flavor they police." | **Reproduces the class.** |
| **W5 — never-firing flavor** (small_stories: 0 fires in ~150 verdicts; a missing "even with no persuasion or politics component" permission killed its best match) | Nothing tells users that a flavor whose description leans on the profile's other themes will never fire alone; no "permission clause" pattern is taught; the product surfaces per-flavor evidence only inside the ≥20-votes audit. | **Reproduces it.** |
| **W6 — mid-list mentions too weak** (the judge denied the very phrases the flavor contained, because they sat mid-list; dedicated sentences fixed it) | No guidance on sentence placement or one-claim-per-sentence writing. | **Reproduces it.** |
| **W4/W7 — borderline weighting** (one flavor's bullseyes systematically weaker) | The ★ CORE mechanism exists and is explained — this is the one documented issue the public app already has a lever for. | **Partially prevents.** |

The vote-informed audit (Settings-only, ≥20 votes) is the designed safety
net for all of the above, and its system prompt encodes exactly the right
doctrine ("the dominant failure mode ... is UNDER-selection"). But it fires
weeks in; the wording above determines the quality of the briefings that
decide whether a user stays long enough to reach 20 votes.

## 3. What the owner's high-performing profile has that the wizard never elicits

1. **Curated, annotated exemplars** (T1) — no UI.
2. **Fit-rule calibration notes** (T2) — no onboarding surface, discouraging
   Settings hint.
3. **Permission clauses** — "Persuasion need not be the focus — empirical
   work on the dynamics ... belongs here" (political_discourse_online). The
   wizard never teaches this pattern; it is exactly what W5/W6 needed more of.
4. **A boundary sentence in the core statement** — "AI matters to me as a
   COMMUNICATOR or INTERVENTION ..., not as an object of public opinion or a
   research tool." The describe step's "what only *sounds* related" prompt
   points here — good — but the placeholder text doesn't model the X-as-ROLE
   / not-as-ROLE form, which is the strongest sentence in his profile.
5. **Conditional negatives with IN-pointers** — "...unless about political
   discourse, narrative, or misinformation"; "(empirical studies of
   democratic attitudes are IN, per political_discourse_online)". Modeled in
   the example profile, never named in guidance.
6. **~6 flavors** — wizard/coach ranges (3–6) match; no gap.

## 4. Per-step verdicts

Steps in the new (2026-08-09) order; verdicts: KEEP / REWORD / ADD / COMBINE.

**Entry fork — KEEP.** The "only as sharp as these descriptions" note is the
right priming and the recommended path front-loads the highest-value input
(seeds). No change requested.

**Seeds step — KEEP (one addition later, see Top-5 #2).** Copy is clear;
the Gathering explanation is honest; the papers-path "draft & continue" panel
correctly frames the draft as a starting point.

**Describe your research — KEEP with one REWORD.** The sharp-PhD-outside-
your-subfield priming is deployed at the single best moment (it is also in
the autofill system prompt — good). The placeholder should model the
boundary-sentence form:

> PROPOSED WORDING (textarea placeholder): "I study how ... I'm especially
> interested in ... X matters to me as a «role it plays for you», not as
> «the nearby role you don't care about». Papers about X in general are
> background noise."

**Topics & intersections — REWORD (two additions).** The intersection
doctrine and example-profile expanders are right and well-placed, but the step needs
the W1 counter-question and the W5/W6 permission-clause pattern:

> PROPOSED WORDING (append to instruction note): "Two checks before you
> continue: (1) If one strand of your work is a bullseye *on its own* — a
> mechanism or literature you'd want even with none of your other themes
> attached — give it its own topic and say so in its description ('counts
> here even without X or Y'). Otherwise the judge will file those papers as
> background. (2) The judge reads each description as a self-contained rule:
> a boundary that matters for a topic belongs in *that topic's* sentences,
> not somewhere else, and one claim per sentence beats a long list."

**Not interested — REWORD (this is the priority fix).** The current note
praises exclusions ("does a lot of work") with no counter-weight, and the
documented failure mode is exclusions eating wanted papers:

> PROPOSED WORDING (append to instruction note): "One caution: a broad
> exclusion outweighs everything else — 'chatbot studies' would also veto the
> chatbot-persuasion papers you *do* want. Make exclusions conditional:
> '«area» *with no* «the thing that would redeem it»', and when an exclusion
> sits next to a topic you kept, say which side wins ('...— studies of X are
> still in, per «topic name»')."

**About you / Priority journals / Review — KEEP.** Delivery and mechanics;
no judge-quality leverage. Review's two-stage explanation is accurate. One
small ADD to Review: a line noting the criteria are living ("expect to
sharpen wording in Settings once you see real briefings — the rationale on
each card tells you which sentence to fix") would set the tuning loop
expectation the whole system depends on.

**Coach: autofill — KEEP (see probe).** **Coach: suggestions — REWORD the
system prompt** (not user copy): `SUGGEST_SYSTEM` should carry the audit's
doctrine sentence ("the dominant failure mode is under-selection; flag
negatives broad enough to veto papers the flavors want, and flavors that can
never fire alone") — the probe shows the model finds these when the material
is in front of it. **Audit — KEEP, Settings-only placement verified** (no
onboarding surface mentions it; regression-guarded by
`test_onboarding_never_mentions_the_audit`).

**ADD (new elicitation, smallest useful version):** a "star your bullseyes"
moment — on the review step (or seeds list), let the user mark 3–5 seeds as
"exactly the kind of paper I want" → `positive_exemplar_titles`. Negative
exemplars can stay vote-driven (they need papers the user has *seen and
rejected*, which new users don't have; the annotated-negative pattern is an
audit-era refinement).

## 5. Live quality probe (5 LLM calls, production router: 4× Groq gpt-oss-120b, 1× Gemini flash)

### Persona A — developmental psychologist, early numeracy (10 real OpenAlex seeds, 3 deliberately-stray papers among them)

Draft quality: **structurally excellent.** 5 flavors, all genuine
intersections, naming real theories/methods the judge can use — e.g.
(verbatim):

> "**Approximate Number System Training and Transfer** — Focuses on
> experimental interventions that sharpen ANS acuity (Weber fraction) and
> assess downstream effects on symbolic arithmetic, especially for
> low-performing children. Grounded in the ANS-symbolic mapping hypothesis
> and magnitude representation theory..."

It even converted the stray seeds (autism prevalence, obesity prevention,
media-use papers) into negatives — "Epidemiological surveillance of autism
prevalence", "Systematic reviews of childhood obesity prevention programs".
Two caveats a user must catch by editing: it *invents* commitments from thin
evidence (one fMRI seed became "I combine ... developmental neuroimaging" in
the core statement and a whole neuro flavor), and it bakes **methods into
membership rules** ("Papers that decompose HME into distinct subscales ...
belong here") — method-conditioned flavors are under-selection seeds of
exactly the W1 kind.

### Persona B — coral-reef ecologist, thermal stress × reef acoustics

Same picture: 5 granular intersections ("Acoustic enrichment for ecological
restoration", "Microbiome-mediated thermal tolerance"), named frameworks
(holobiont theory, acoustic complexity index), and — notably — negatives
that already use the conditional pattern the guidance never teaches:

> "Macroalgal phase-shift dynamics **without explicit microbial or acoustic
> components**" · "Socio-economic assessments of reef tourism or fisheries
> **that lack a biological mechanistic focus**"

### The owner's 132 seeds vs his hand-tuned v3 — the delta the flow must inspire

Two autofill runs (the coach truncates at `MAX_SEEDS_IN_PROMPT = 40`): the
**first-40** slice (what the app would actually send today — seeds in
insertion order) and a **seeded random-40** sample.

- **first-40 draft:** flavors "Narrative Inoculation for Climate
  Misinformation", "Computational Propaganda and Bot-Mediated Persuasion",
  "Deliberative Dialogue and Persuasive Argument Quality", "Identity Fusion &
  Moral Foundations in Extremist Persuasion", and — invented from a single
  stray meta-analysis seed — "Digital Media Developmental Impacts via
  Persuasive Message Design". **Missing vs v3:** bridging_divides entirely,
  llm_behavior_change as its own thing, all of political_discourse_online's
  breadth, small_stories entirely, and the core statement's AI-as-communicator
  boundary sentence.
- **random-40 draft:** substantially different — it found "Small Stories
  Research and Interactional Positioning Theory" (the flavor first-40 never
  saw) and "AI-Mediated Political Persuasion", but lost bridging_divides and
  narrative_persuasion-in-general.
- **Both drafts** lack everything §3 lists: exemplars, calibration notes,
  permission clauses, IN-pointer negatives — and both embed method
  requirements ("hierarchical Bayesian signal-detection analyses") that his
  actual profile deliberately avoids.

Two conclusions. First, **the sampling is a real defect**: which 40 of 132
seeds the coach sees materially changes which interests exist in the draft
(first-40 is insertion-ordered, so early Zotero imports dominate). Second,
**the delta between any draft and v3 is exactly the editing the flow must
inspire**: merging over-specific flavors, deleting invented ones, stripping
method conditions, adding boundary/permission sentences. The fork's "only as
sharp as these descriptions" note plus the AI-draft banners are the right
frame; the topics/negatives rewordings above give the edit direction.

### Suggest-mode probe (deliberately weak draft: tautological flavor, blanket negatives "neuroscience" / "education policy")

The coach caught all three planted problems, verbatim flags:

> "'math learning: Children learning mathematics.' – This phrase is
> tautological and does not delineate any specific angle..." · "'Exclusions:
> neuroscience' – The draft later lists a functional imaging study, creating
> a direct conflict..." — and suggested the exact conditional narrowing
> pattern: "...rather than a blanket ban."

So the correction capacity exists; it is just behind an optional button and
un-primed about which failure mode dominates.

### Verdict on the "recommended" label

**Yes — keep "recommended" on the papers-first path.** Across three distinct
seed sets the autofill produced granular, theory-naming, judge-usable
intersections and sensible negatives — plainly better raw material than a
cold-start blank textarea, and `build_prompt` over these drafts would yield a
discriminating (if initially over-narrow) judge. The label is honest *as
long as* the fork's editing note stays and the seed-sampling defect is fixed.

## 6. Top-5 changes, prioritized

1. **Rewrite the negatives-step guidance to warn against over-broad
   exclusions** (conditional phrasing + IN-pointers; wording in §4). Directly
   targets the documented W2 class; zero code.
2. **Fix autofill seed sampling**: replace the first-40 slice with a random
   (seeded) or stratified sample of the user's seeds — or raise
   `MAX_SEEDS_IN_PROMPT` with title-only rows beyond 40. The probe shows the
   slice choice changes which interests exist in the draft. Small code
   change in `app/coach.py`.
3. **Elicit positive exemplars from seeds** ("star 3–5 seeds as 'exactly my
   thing'" → `positive_exemplar_titles`). Fills the empty prompt section the
   owner's profile leans on; reuses existing UI patterns.
4. **Generalize the hardcoded 4–6 rubric band** in `judging.build_prompt`
   ("AI alone, politics alone, persuasion alone" → the user's own flavor
   components, or drop the parenthetical). Every non-political-comm user's
   judge currently reads another researcher's examples mid-rubric.
5. **Add the bullseye-on-its-own check + permission-clause pattern to the
   topics step, and the under-selection doctrine to `SUGGEST_SYSTEM`**
   (wording in §4). Targets W1/W5/W6, the three loopholes that cost the
   owner's profile its highest-rated papers.

(Honorable mention: surface the fit-rule as "calibration notes (optional)"
with an example-profile excerpt instead of "leave blank to use the default" — T2.)
