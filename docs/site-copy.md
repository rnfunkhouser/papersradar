# Research Radar — Site Copy Worksheet

## How to use this file

- **To change wording:** edit any quoted text (the lines starting with `>`) directly in place. Whatever you write there is what should appear on the site.
- **To comment on structure or layout:** find the nearest `[STRUCTURE]` note and write a new line under it starting with `>> ` — e.g. `>> replace these emojis with theme-compatible mini symbols`.
- **Don't worry about code.** Anything in «angle brackets» is dynamic content the software fills in («user name», «paper count»); just keep the placeholder somewhere in your edited sentence. Symbols like ★ and ✕ are literal characters you can also swap.
- Strings that appear on many pages (header, footer, shared editors) live once in the **Shared chrome** and **Shared components** sections near the top; other pages refer back to them.

---

# Shared chrome — every page

[STRUCTURE] Fixed site header: radar logo (an SVG mark — dot with two arcs, like a radar/broadcast icon) + wordmark on the left; nav links on the right. Signed-out nav: one text link + one filled "Sign in" button. Signed-in nav: text links Dashboard / Settings / (Admin, admins only) / Sign out.

**Logo wordmark:**
> Research Radar

**Nav (signed out) — link:**
> How it works

**Nav (signed out) — button:**
> Sign in

**Nav (signed in) — links:**
> Dashboard · Archive · Settings · Admin · Sign out

[STRUCTURE] Decorative background at the bottom of every page: faint concentric radar arcs with two "blip" dots (pure decoration, SVG, no text).

[STRUCTURE] Site footer: single line of small text with dot-separated links. Ends with a coffee-cup emoji ☕.

**Footer:**
> Research Radar · a free tool built and run by a political-communication researcher at the University of Idaho · about · how the scores work · privacy · source code · useful to you? buy me a coffee ☕

(The "source code" link only shows when a public source URL is configured. "buy me a coffee ☕" links to Ko-fi.)

**Browser-tab titles (per page):** "Research Radar — your daily research radar" (landing), "Sign in — Research Radar", "Check your email — Research Radar", "Set up your radar — Research Radar", "Dashboard — Research Radar", "Archive — Research Radar", "Settings — Research Radar", "About — Research Radar", "How the scores work — Research Radar", "Privacy & your data — Research Radar", "Unsubscribed — Research Radar", "Account deleted — Research Radar", "Admin — Research Radar".

**Search-engine description (meta tag):**
> Your daily research radar — new papers that actually fit your interests, with a transparent AI rationale for every pick.

---

# Shared components — used in both Onboarding and Settings

## Worked example expander ("Want to see a full example?")

[STRUCTURE] A collapsible panel under the instructions of the research-description, topics, and exclusions editors. Collapsed it shows only the summary line; expanded it shows an attribution line, then the founder's real profile content for that step (statement, or topic cards, or a bulleted exclusion list — bullets use the • character).

**Expander label:**
> Want to see a full example?

**Attribution line:**
> This is the founder's own profile — a political-communication researcher. Yours can be shorter; specificity matters more than length.

**Example content — research statement:**
> I am a political-communication researcher. I study how communication — increasingly AI-mediated — persuades, changes behavior, and bridges or deepens ideological divides, especially online. My interests come in a few specific flavors (below); the best papers for me sit squarely inside one flavor or connect several. Papers about just 'AI' in general, or 'politics' in general, are background noise. AI matters to me as a COMMUNICATOR or INTERVENTION (a chatbot that persuades, an LLM that delivers arguments), not as an object of public opinion or a research tool.

**Example content — topics (name + description pairs):**
> **bridging divides** — Communication mechanisms for bridging ideological divides, especially online: depolarization interventions, cross-partisan conversation, perspective-taking dialogues, correcting misperceptions of the out-group, reducing partisan animosity and incivility.
>
> **narrative persuasion** — Narrative as a persuasion mechanism, in any domain (political, health, climate, civic): narrative transportation, entertainment-education, story-based appeals, narrative vs non-narrative message effects, inoculation/prebunking delivered through stories.
>
> **llm behavior change** — LLMs and chatbots for changing beliefs and behavior: conversational AI that durably shifts attitudes (e.g., conspiracy-belief reduction), AI dialogue interventions, chatbot-delivered persuasion or behavior-change programs, and their psychological mechanisms.
>
> **llm persuasion online** — LLMs and generative AI as persuaders in online and political contexts: AI-generated persuasive messages, persuasive bots, generative agents spreading or countering misinformation, AI's persuasive advantage over humans, computational propaganda with generative AI.
>
> **political discourse online** — Political and civic discourse online, broadly: how platforms, algorithms, norms and governance expectations, emotions, and attention dynamics shape political talk, public opinion, polarization, misinformation belief, and citizens' commitment to democratic norms. Persuasion need not be the focus — empirical work on the dynamics of online political/civic communication belongs here.
>
> **small stories** — 'Small stories' and fragmented narrative online: brief, fleeting, everyday story fragments as a framework for studying identity, attention, and meaning-making in fast-moving digital discourse; how fragmented content dynamics (attention, virality) shape what stories take hold. Computational models of collective attention to online content (what spreads, what fades, and how fast) count here.

**Example content — exclusions (bulleted list):**
> • Public attitudes TOWARD AI, AI governance, or AI ethics — where AI is the object of opinion rather than the communicator or intervention
> • LLMs as research or measurement tools (generating surveys, coding data, content analysis of model outputs) with no persuasion or behavior-change outcome
> • Chatbot UX, companionship, loneliness, or adoption studies with no persuasion, behavior-change, or political dimension
> • Clinical/diagnostic AI, robots for physical tasks, and AI engineering or productivity studies
> • Public acceptance of technologies (energy, climate tech, food tech) via framing, unless about political discourse, narrative, or misinformation
> • Consumer/brand marketing and purchase-decision persuasion with no narrative mechanism and no political dimension
> • Classroom or educational discourse pedagogy unless about political persuasion or bridging divides
> • Area-studies, policy, or governance pieces with no communication or persuasion mechanism
> • Broad state-of-AI or state-of-democracy think pieces with no empirical question (empirical studies of democratic attitudes are IN, per political_discourse_online)

## AI coach suggestion box

[STRUCTURE] Below each criteria editor: a ghost (outline) button + a small hint sentence beside it. Clicking fetches AI suggestions and renders them as dismissible note cards grouped under up to three mini-headings; each note has a ✕ dismiss button. While loading, the button label temporarily changes.

**Button:**
> Get suggestions on my draft

**Hint beside button:**
> An AI coach reads your draft and your seed papers, then suggests sharpenings — nothing changes unless you edit it yourself.

**Button label while loading:**
> Thinking…

**Result group headings:**
> Worth clarifying · Suggestions · Possibly too broad

**Empty result note:**
> No suggestions — this draft reads clearly.

**Generic failure note:**
> Something went wrong.

**Network failure note:**
> Could not reach the coach — try again shortly.

**Rate-limit message (shared by all coach features):**
> The AI coach is rate-limited to a few calls per day — please try again tomorrow.

**Provider-down message (shared):**
> The AI coach couldn't reach a language-model provider just now — please try again in a few minutes.

**Malformed-response messages:** suggestions: "The suggestions came back malformed — please try once more." / draft: "The draft came back malformed — please try once more." / audit: "The audit came back malformed — please try once more."

## Topics & intersections editor

[STRUCTURE] Repeatable rows. Each row: a one-line name field, a ★ star toggle button (marks a "core" topic), a ✕ remove button, and a two-line description textarea beneath. Under the rows, a ghost "+ Add another topic" button.

**Name field placeholder:**
> Short name, e.g. narrative persuasion

**Description placeholder:**
> 1–3 sentences: what combination of things makes a paper belong here?

**Star button tooltip:**
> Star = core topic (weighed most heavily)

**Remove button tooltip:**
> Remove this topic

**Add button:**
> + Add another topic

## "Not interested" (exclusions) editor

[STRUCTURE] Same repeatable-row pattern, one text field per row with a ✕ remove button; ghost add button below.

**Field placeholder:**
> e.g. Public attitudes toward AI, where AI isn't the communicator

**Remove tooltip:**
> Remove

**Add button:**
> + Add another exclusion

## Priority-journals editor

[STRUCTURE] Current journal list first (each row: journal name, ID + country code in small text, ✕ remove button), then a labeled search field with live-autocomplete results appearing beneath as clickable buttons ("Journal name · COUNTRY-CODE"), then a hint line.

**Search label:**
> Find a journal

**Search placeholder:**
> Start typing, e.g. Journal of Communication

**Hint under search:**
> We search OpenAlex's journal registry as you type — click a result to add it.

**Over-limit message (shown if adding beyond the cap):**
> limit of «max» priority journals reached

## Zotero widget

[STRUCTURE] A panel titled "Link a Zotero library". When not connected: hint sentence; an instruction note with a bold lead-in and a 4-item numbered list; a "Group URL or ID" field + "Connect public group" button; then a collapsible fallback section for API-key connection (library-type dropdown, ID field, key field, help note, ghost connect button). When connected: a status line, an import-scope dropdown (Entire library / Collection: «name»), "Preview import" ghost button, a preview note + sample rows + "Import «n» papers" button, then two ghost buttons side by side (Refresh / Disconnect).

**Panel heading:**
> Link a Zotero library

**Intro hint:**
> A quick way to add many seeds at once — **worth it if you have 20+ relevant papers saved**. Pasting DOIs above stays the simplest path.

**Recommended-path note:**
> **Recommended: a dedicated public group library.** This way you share only the seed papers you choose — not your whole personal library — and no API key is needed. Two minutes on zotero.org:
> 1. Go to *Groups → Create a new group* (free).
> 2. Choose *Public, Closed membership* — public makes it readable without a key; closed membership means only you can add to it.
> 3. Add just your seed papers to the group (drag them over in Zotero).
> 4. Paste the group's URL or ID below.

**Field label:** > Group URL or ID
**Field placeholder:** > https://www.zotero.org/groups/1234567/my-seed-papers — or just 1234567
**Button:** > Connect public group

**Fallback expander label:**
> Prefer to connect a private library with an API key? (fallback option)

**Fallback fields:** "Library type" (options: "My personal library" / "A private group library"), "Library ID" (placeholder "e.g. 1234567"), "Zotero API key (read-only)" (placeholder "paste your read-only key").

**Fallback help note:**
> On zotero.org, open *Settings → Security*. Your personal *library ID* ("userID") is shown in the Applications section there. Then click *"Create new private key"*, tick *read-only* access, and paste the key here. For a private group, the ID is the number in the group's URL. We only ever read your library — the key is stored encrypted and never shown again.

**Fallback button:** > Connect with API key

**Connected status line:**
> Connected to **«library type» library «library id»** · last import «date time»

**Import-scope label:** > What should we import?
**Preview button:** > Preview import

**Preview note:**
> **Preview:** «n» scholarly items found («n» total) — **«n» new to import** («n» with a DOI, «n» matched by title; «n» imported previously).

**"more" line under sample rows:** > …and «n» more.
**Import button:** > Import «n» papers
**Other buttons:** > Refresh seeds from Zotero · Disconnect

**Zotero status/error messages:**
> Zotero connected — now choose what to import and preview it.
>
> Zotero disconnected. Your imported seeds are kept — remove any you don't want from the list.
>
> Imported «n» paper(s) from Zotero; «n» couldn't be matched (no DOI and no confident title match).
>
> Paste your group's URL (zotero.org/groups/…) or its numeric ID (see the help text below the form).
>
> Connect your Zotero library first.
>
> Couldn't reach that Zotero library — double-check the group URL/ID and that the group is set to Public (for a private library, that the API key has read access to it).
>
> Couldn't fetch items from that Zotero library.

## Seed-row chrome (seed lists in onboarding + settings)

[STRUCTURE] Each seed paper is a row: title, then DOI in small muted text (or "no DOI"; Zotero-imported seeds add "· zotero"), and a ✕ remove button (tooltip "Remove").

---

# Landing — /

[STRUCTURE] Hero section: small uppercase "eyebrow" tag line, big two-line H1 with the phrase "research radar" in gradient color, subline paragraph, then two large buttons side by side (filled primary + ghost), then a small reassurance line.

**Eyebrow:**
> A fully free, open-source tool for researchers

(Without a configured source-code URL this reads "A fully free tool for researchers".)

**H1:**
> Your daily *research radar*. Never miss the paper that matters.

**Hero subline:**
> Research Radar scans the day's new publications and preprints each morning and surfaces the handful that actually fit *your* research — each with a plain-English rationale you can check.

**Primary button:** > Create an account
**Ghost button:** > How it works

**Reassurance line:**
> Free for everyone — no tiers, no card, no catch. Built by a researcher to advance research, not to sell anything.

[STRUCTURE] Feature section: centered H2 + lead paragraph, then three boxes in a row, each with a left-justified emoji icon (🌍, 🔍, 🎯), bold title, and a 2–3 sentence description.

**H2:**
> Made for how academics actually read

**Lead:**
> Keyword alerts are imprecise, and tables of contents arrive late. This tool reads new abstracts against a description of your work that you write and can edit.

**Feature 1 (🌍):**
> **Field-agnostic coverage** — OpenAlex, arXiv, SocArXiv and PsyArXiv — journals and preprints across disciplines, gathered daily from the research areas your own seed papers live in.

**Feature 2 (🔍):**
> **Readable AI rationales** — An AI judge reads every shortlisted abstract against criteria you can read and edit, then scores fit 0–10 with a one-sentence reason. No black-box ranking — the "why" is always shown.

**Feature 3 (🎯):**
> **Corrects with your feedback** — Thumbs-up and thumbs-down on any pick become boundary examples the judge reads on the next run, so the selection tracks your actual judgment over time.

[STRUCTURE] "How it works" section (anchor target of the hero ghost button): H2 + lead, then three numbered step boxes in a row, each with a bold title and short paragraph.

**H2:**
> How it works

**Lead:**
> Two stages, both inspectable: **Gathering** casts the net, **Selection** reads what was caught.

**Step 1:**
> **Describe your work** — Write down your interests in your own words and add a few papers you wish you'd been alerted to. Setup takes about five minutes.

**Step 2:**
> **Daily gathering & shortlist** — Each morning the pipeline searches the research areas your seed papers point to and shortlists new work that sits closest to them by semantic similarity, not keywords.

**Step 3:**
> **An AI judge reads the shortlist** — The judge scores each shortlisted abstract against your Selection Criteria. Papers that clear your bar appear in your dashboard and, if you want, your inbox — rationale attached.

[STRUCTURE] Testimonial section: a quote card with a small intro line, the quotation, and an attribution line.

**Intro line:** > From an early user:

**Quote:**
> "This is exactly what I was looking for. Instead of relying on seeing a colleague post about a relevant new pub (or on imprecise keyword alerts), this surfaces exactly the kinds of papers most relevant to my work."

**Attribution:** > — early user, political communication researcher

[STRUCTURE] "Free" strip: full-width tinted band, H2 + one paragraph with inline links (privacy, source code, Ko-fi with ☕).

**H2:**
> Free, because it should be

**Paragraph:**
> Research Radar is an open-source tool built and run by a researcher to advance research. There are no pricing tiers, no premium plan, and no credit card — every feature is available to everyone, and your data is never sold or shared (how your data is handled · source code). If you find it valuable and want to contribute, you can buy me a coffee ☕.

(Without a source URL: "…is a tool built and run by…" and no "source code" link.)

[STRUCTURE] Closing call-to-action band: boxed card with H2, one line, one large filled button.

**H2:** > Setup takes about five minutes.
**Line:** > No passwords and nothing to install — sign in with an emailed one-time link.
**Button:** > Create an account

---

# Sign in — /login

[STRUCTURE] Narrow page: H1, sub-line, (error banner if any), then a panel with a labeled email field and a large submit button, a hint line inside the panel, and a "Your data" hint paragraph below the panel.

**H1:**
> Sign in — or start your radar

**Sub-line:**
> No passwords here. Enter your academic email and we'll send a one-time sign-in link. New here? The same link creates your account.

**Field label:** > Email address
**Field placeholder:** > you@university.edu
**Button:** > Email me a sign-in link

**Hint under button:**
> Sign-in links work once; after you click one, you'll stay signed in on this device for 90 days (sign out anytime).

**"Your data" paragraph:**
> **Your data:** we store your email, your research-interest text, your seed papers, and (if you use them) your votes and briefing clicks — nothing more. We send you only the briefings you ask for and login links you request, run no trackers, never sell or share data, and you can delete everything yourself in Settings. Full privacy note.

**Validation / error messages (red banner):**
> That doesn't look like an email address.
>
> too many login attempts — wait 15 minutes
>
> That sign-in link is invalid or expired — request a fresh one.

---

# Check your email — /login (after submitting)

[STRUCTURE] Centered empty-state card: big 📧 emoji, H2, one paragraph.

**H2:** > Check your inbox

**Paragraph:**
> We sent a sign-in link to **«email»**. It works once and expires in 20 minutes. (No email? Check spam, then try again.)

[STRUCTURE] Dev-mode variant (only when the server has no outgoing email configured): H2 "Link created" + explanatory paragraph.

**Dev-mode paragraph:**
> This server is running without outgoing email (development mode). Your sign-in link for **«email»** has been written to the server log and the admin's /admin/dev-links page — ask the site owner to pass it along.

---

# Onboarding — /onboarding (entry fork + 7 steps)

[STRUCTURE] Onboarding opens with an ENTRY FORK (a "step 0" screen, before any interest fields): the user chooses "Start from my papers" (recommended — seed papers first, then the system drafts the interest editors from them) or "Write it myself" (interest editors first, seeds later). Both paths are the SAME seven steps — only the position of the Seed-papers step differs — and they share the same tail: About you → Priority journals → Review & launch. The Back button on step 1 returns to the fork, so the choice can be changed at any time; nothing already entered is lost.

[STRUCTURE] Every numbered step: H1 "Set up your radar", a row of 7 progress dots (filled up to the current step; the fork fills none), a step label line, optional green notice / red error banners, then the step's panel(s), then a ghost "Back" button.

**H1:** > Set up your radar

**Step label (fork):**
> Before step 1 · Choose your starting point

**Step label (numbered steps):**
> Step «n» of 7 · «step name»

**Step order — "Start from my papers" path:**
> Seed papers · Describe your research · Topics & intersections · Not interested · About you · Priority journals · Review & launch

**Step order — "Write it myself" path:**
> Describe your research · Topics & intersections · Not interested · Seed papers · About you · Priority journals · Review & launch

**First-sign-in notice (shown once, also on dashboard):**
> You're signed in — you'll stay signed in on this device for 90 days.

## Step 0 — The entry fork

[STRUCTURE] One panel: heading, an instruction note, then two bordered option boxes (each a button + a hint paragraph; the first button is filled with a small "recommended" tag beside it, the second is a ghost button), then a closing note about editing the draft.

**Panel heading:** > Two ways to write your Selection Criteria

**Instruction note:**
> Your radar runs on your **Selection Criteria** — a plain-English description of your research that an AI judge reads against every new paper, every morning. Choose how to write the first draft; either way, you review and edit every field before anything is saved.

**Option 1 button:** > Start from my papers
**Tag beside option 1:** > recommended
**Option 1 hint:**
> You add papers that fit your interests first — paste DOIs or link a Zotero library — and we draft your description, topics and exclusions from them. Then you walk through the same steps as the written path, with every field pre-filled for you to edit.

**Option 2 button (ghost):** > Write it myself
**Option 2 hint:**
> You describe your research in your own words, step by step, with a worked example at each step. Seed papers come after.

**Closing note:**
> One thing to know before you pick: a drafted profile is a starting point, not a finished setup. The radar is only as sharp as these descriptions, so plan to edit and refine whatever the draft gets almost-right. You can switch approaches anytime with the Back button.

## Seed papers step (step 1 on the papers path; step 4 on the manual path)

[STRUCTURE] Main panel: heading, instruction note (one extra sentence on the papers path), a paste-in textarea with label + hint + "Look up & add" button, then the current seed list ("Your seeds («n»)", seed rows with ✕). PAPERS PATH, once 3+ seeds exist: a "draft & continue" panel — this is the step's continue action (with a quiet skip link); if a draft already exists it shows Continue + a re-draft button instead. MANUAL PATH: the "head start" panel appears only if the interest editors are still untouched. Then the Zotero widget panel. Bottom row: Back button; on the manual path a Continue button (or the "not enough seeds yet" hint); on the papers path the draft panel is the way forward.

**Panel heading (papers path):** > Add your seed papers
**Panel heading (manual path):** > Add seed papers

**Instruction note:**
> **What seeds do:** seeds steer the *Gathering* stage — every morning we search the research areas your seed papers live in and shortlist new work that sits semantically close to them. *(papers path only:)* They're also the raw material for your drafted Selection Criteria (next step). Aim for 3–100 papers you wish you'd been alerted to when they came out. More seeds = a better-aimed net *(papers path: and a sharper draft)*.

**Textarea label:** > Paste DOIs or titles — one per line
**Textarea placeholder:**
> 10.1038/s41586-024-01234-5
> The title of a paper also works

**Hint:**
> We look each one up on OpenAlex and show you what we found — remove anything that isn't right.

**Button:** > Look up & add

**Seed list heading:** > Your seeds («n»)

**Draft panel heading (papers path, 3+ seeds):** > Next: we draft your criteria from these papers
**Draft panel hint:**
> One AI pass reads your «n» seeds and drafts your research description, topics and exclusions. You'll edit each step before anything is saved — the draft is a starting point, and the radar is only as sharp as your final wording.
**Draft panel button:** > Draft my criteria & continue
**Draft panel skip line:**
> Or continue without a draft and write the steps yourself.

**Draft panel, when a draft already exists — hint:**
> A draft from your seeds is ready — continue to review and edit it, or re-draft if you've changed your seeds since.
**Buttons:** > Continue to your draft · Re-draft from current seeds

**Head-start panel (manual path, 3+ seeds, editors still empty) — heading:** > Want a head start on your criteria?
**Head-start hint:**
> We can draft your research description, topics and exclusions **from these seed papers** — you land back in the editor to make every word yours before anything is saved.
**Head-start button:** > Draft my profile from my seed papers

**Gate hint (fewer than 3 seeds):**
> Add at least 3 seeds to continue («n» so far)

**Messages:**
> Added «n» papers.
>
> Couldn't find: «list of misses». Try the DOI instead of the title.
>
> Add at least 3 seed papers first — the draft is built from them.

## Describe your research (step 2 on the papers path; step 1 on the manual path)

[STRUCTURE] Optional AI-draft banner at top; panel with heading, instruction note, the worked-example expander (statement version), a 7-row textarea, the AI-coach box, "Continue" button. Below the form, one of two affordances: if the user has 3+ seeds and no draft yet, a ghost "draft this from my seed papers" button + hint; if they have no seeds and nothing written (manual path start), a hint pointing back to the fork. Then the Back button.

**AI-draft banner (the three interest editors, when a coach draft is loaded; wording varies):**
> **AI draft — edit to make it yours.** These fields were drafted from your seed papers. Nothing is saved until you review and continue through each step.
>
> (topics variant) **AI draft — edit to make it yours.** Topics below were drafted from your seed papers — rename, rewrite or remove them freely; nothing is saved until you continue.
>
> (exclusions variant) **AI draft — edit to make it yours.** These candidate exclusions were drafted from your seed papers — keep only the ones that ring true.

**Panel heading:** > Describe your research in a few sentences

**Instruction note:**
> Write it as you would to a **sharp PhD student outside your subfield**: what you study, what angle you take, and what only *sounds* related but isn't. This becomes the opening of your Selection Criteria — the instructions an AI reader uses to score every paper's fit for you. You can edit every word later.

**Textarea label:** > Your research, in a few sentences
**Textarea placeholder:**
> I study how ... I'm especially interested in ... Papers about X in general are background noise; what I care about is ...

**Button:** > Continue

**Late-draft button (3+ seeds, no draft yet):** > Draft this from my seed papers
**Hint beside it:**
> Pre-fills any empty fields from your «n» seeds — your own words are never overwritten.

**Fork-pointer hint (no seeds, nothing written):**
> Prefer to start from a draft built from your papers? Go back and choose "Start from my papers".

**Validation:**
> A few sentences helps the judge a lot — please write at least a short paragraph.

## Topics & intersections (step 3 papers path / step 2 manual path)

[STRUCTURE] Optional AI-draft banner; panel with heading, instruction note, worked-example expander (topics version), the topics editor (see Shared components), coach box, "Continue"; Back button below.

**Panel heading:** > Your topics & intersections

**Instruction note:**
> Add the specific topics you want papers about — each with a short name and 1–3 sentences. Name the **specific theories, frameworks, and methods you want to see** in results. **Intersections beat broad topics:** "misinformation" alone will bury you, but "inoculation interventions against health misinformation" hits the mark; likewise "narrative persuasion in climate communication" beats "climate change". Star (★) the topics that matter most.

**Validation:**
> Add at least one topic with both a short name and a description.

## Not interested (step 4 papers path / step 3 manual path)

[STRUCTURE] Optional AI-draft banner; panel with heading, instruction note, worked-example expander (exclusions version), the exclusions editor, coach box, "Continue"; Back button below.

**Panel heading:** > What you're *not* interested in

**Instruction note:**
> List the **adjacent-but-irrelevant** areas that would otherwise sneak in: nearby subfields you don't follow, methods or literatures to exclude, applications of your topic that don't interest you. This is optional but does a lot of work — it's how the AI reader learns your boundaries.

## Step 5 — About you (both paths)

[STRUCTURE] One panel: heading, then name field, briefing-frequency dropdown, briefing-size dropdown + hint, a "Western context" checkbox with a long hint paragraph, a final hint, "Continue" button; Back button below.

**Panel heading:** > Nearly there — a few basics.

**Name label:** > Your name
**Name placeholder:** > Dr. Ada Lovelace

**Frequency label:** > How often should we email your briefing?
**Frequency options:**
> Daily (each morning) · Weekly (Mondays) · Don't email me — I'll use the dashboard

**Size label:** > How many papers per briefing?
**Size options:**
> Standard (up to «default count») · Up to 3 … Up to 10

**Size hint:**
> Only papers that clear your fit bar make the briefing — this sets the ceiling, not a quota.

**Checkbox label:** > Focus my briefings on Western-context research

**Checkbox hint (shared verbatim with Settings → Geographic scope, except the last sentence):**
> Research from every region and context matters, and a healthy literature includes all of those voices. At the same time, broad geographic coverage can make a daily briefing less relevant for some researchers' specific work — that's the only reason this option exists. When it's on, papers from venues based outside North America, Western, Northern and Southern Europe, Australia and New Zealand are filtered out, and papers focused on non-Western contexts are weighed somewhat lower — though strong, highly relevant work can still make your briefing. Off by default; change it any time in Settings.

**Final hint:** > You can change any of this any time in Settings.
**Button:** > Continue

**Validation:** > Please tell us your name.

## Step 6 — Priority journals (both paths)

[STRUCTURE] Panel with heading, instruction note, and the priority-journals editor. Below: Back button (left) and Continue button (right — labeled "Continue (skip)" when no journals are picked).

**Panel heading:** > Journals you never want to miss

**Instruction note:**
> Optional. Pick the journals whose new papers you'd always want screened — your field's flagship outlets, or a favorite niche journal. We fetch **every new paper** these journals publish (even ones our seed-based search wouldn't have found), and any that sit reasonably close to your interests get a **guaranteed spot** in front of the AI judge. Picks from these journals are labeled in your briefing.

**Buttons:** > Back · Continue / Continue (skip)

## Step 7 — Review & launch (both paths)

[STRUCTURE] One panel: heading, intro line, then three-to-four short paragraphs each opening with a bold lead-in ("1 · Gathering", "2 · Selection", optional "Plus:", "You stay in charge:"). Bottom row: Back button (left) and a large "Launch my radar" button (right).

**Panel heading:** > How your radar will work
**Intro line:** > Two stages, every morning:

**Paragraph 1:**
> **1 · Gathering** casts the net: we search OpenAlex, arXiv, SocArXiv and PsyArXiv in the research areas learned from your **«n» seed papers**, and shortlist the new papers that sit closest to them.

**Paragraph 2:**
> **2 · Selection** decides: an AI judge reads each shortlisted abstract against your Selection Criteria — your description, your **«n» topics**, and your «n» exclusions — and scores its **fit** from 0–10 with a one-sentence rationale. Only the best make your briefing.

**Paragraph 3 (only with priority journals):**
> **Plus:** every new paper from your «n» priority journals is fetched daily; the ones close enough to your interests get guaranteed judge slots and are labeled in your briefing.

**Paragraph 4:**
> **You stay in charge:** thumbs-up/down any pick and the judge treats it as a boundary example the very next day. Edit your criteria any time in Settings — every scoring rule is plain English you can read.

**Launch button:** > Launch my radar

**Validation (if steps are incomplete):**
> A couple of steps still need attention before we can start your radar.

---

# Dashboard — /dashboard

[STRUCTURE] H1, optional welcome notice, a sub-line (date · pick count · link), a horizontal date bar of the last 14 briefing dates (current date highlighted), then a stack of paper cards. Each card: title as an outbound link (H2), author/venue/date meta line, optional purple "priority journal" badge, a pill-shaped score chip (linked, with tooltip), an italic quoted "why" line, a collapsible "Abstract" panel, and a footer with 👍 / 👎 vote buttons plus a small note. If no cards: an empty state with a big 📡 emoji.

**H1:** > Your briefing

**Welcome notice (first sign-in):**
> You're signed in — you'll stay signed in on this device for 90 days. You can sign out anytime from the menu above.

**Sub-line:**
> «date» · «n» picks · how these scores work

**Priority-journal badge:**
> from *«journal name»* — your priority list

**Badge tooltip:**
> You marked this journal as a priority — close-enough papers from it always reach the judge.

**Score chip text:** > «score»/10 · «flavor list»

**Chip tooltip:**
> An AI judge read this abstract against your Selection Criteria and scored its fit for you, 0–10. The tags are the interest flavors it engages.

**Abstract expander label:** > Abstract

**Vote tooltips:** 👍 "More like this" · 👎 "Fewer like this"

**Vote note:**
> Votes teach the judge — they become boundary examples tomorrow.

**Empty state — profile still building (📡):**
> **Your radar is warming up** — Your «n» seed papers are in. The next pipeline run (each morning) finishes your profile, gathers candidates, and scores them — your first briefing appears here after that.

**Empty state — quiet day (📡):**
> **No briefing yet for this day** — Quiet days happen — when nothing clears your fit bar, we'd rather show you nothing than noise. Check back tomorrow, or broaden your Selection Criteria.

---

# Archive — /archive

[STRUCTURE] Signed-in page ("Archive" in the nav, next to Dashboard). H1 + a count sub-line, then a search row (search field + filled "Search" button + ghost "Clear" button when a search or day is active). Below, one of three views: (a) default — the user's past briefing days grouped by month in collapsible panels (newest month open; each day row: linked date on the left, "«weekday» · «n» papers" on the right); (b) day view — a back link + that day's full cards (the same card component as the dashboard, votes included — votes on archived papers still teach the judge); (c) search results — a match-count line + matching cards, each with an extra "in your briefing of «date»" line. Empty states use the big 📡 emoji.

**H1:** > Your briefing archive

**Count sub-line:**
> «n» briefing days · «n» papers — every pick that ever made your briefing stays here.

**Search placeholder:**
> Search your past picks — title, journal, author…

**Buttons:** > Search · Clear

**Search result line:**
> «n» matches for "«query»" in your archive.

(With exactly 100 matches the line appends " (first 100 shown)".)

**Per-card briefed-date line (search results only):**
> in your briefing of «date»

**Day-view back line:**
> ← All briefing days · «date» · «n» picks

**Month panel summary:** > «Month YYYY» — «n» briefings
**Day row:** > «date» — «weekday» · «n» papers

**Empty state — no archive yet (📡):**
> **No briefings archived yet** — Every briefing you receive is kept here, searchable, from your first one on. Once your radar delivers its first picks, they'll appear on this page.

**Empty state — no search matches (📡):**
> **No matches** — Nothing in your archived briefings matches that search — try a shorter word, or an author's last name.

---

# Settings — /settings

[STRUCTURE] Narrow page: H1 "Settings", optional notice/error banners, then a stack of panels in this order: Account, Geographic scope, Priority journals, Selection Criteria, Profile audit, Seed papers, Zotero widget, Delete account (tinted red "danger" panel).

**H1:** > Settings

## Account panel

[STRUCTURE] Heading, name field, two dropdowns, hint, "Save account" button.

**Heading:** > Account
**Labels:** > Name · Briefing emails · Papers per briefing
**Frequency options:** > Daily (each morning) · Weekly (Mondays) · Dashboard only
**Size options:** > Standard (up to «default count») · Up to 3 … Up to 10

**Hint:**
> Applies to the dashboard briefing and the email digest. Only papers that clear your fit bar are included — this sets the ceiling, not a quota. Currently: up to «n» per day.

**Button:** > Save account
**Success notice:** > Account settings saved.

## Geographic scope panel

[STRUCTURE] Heading, checkbox + long hint (same text as onboarding step 1, different final sentence), "Save scope" button.

**Heading:** > Geographic scope
**Checkbox:** > Focus my briefings on Western-context research
**Hint:** same as onboarding step 1 (see there), except the closing sentence reads:
> Toggling this re-judges the current window of papers on the next run.

**Button:** > Save scope
**Success notices:** > Scope saved. / Scope saved. Papers will be re-judged under the new scope on the next run.

## Priority journals panel

**Heading:** > Priority journals («n»)

**Hint:**
> Journals whose new papers you never want to miss — your field's flagship outlets, or a favorite niche journal. We fetch **every new paper** they publish (even ones the seed-based search wouldn't find), and any that sit reasonably close to your interests get a **guaranteed spot** in front of the AI judge. Picks from these journals are labeled in your briefing.

(Then the shared priority-journals editor.)

## Selection Criteria panel

[STRUCTURE] Heading + hint, then four labeled blocks: research statement (example expander + textarea), topics (hint + example expander + topics editor), exclusions (hint + example expander + exclusions editor), fit rule (hint + textarea). Coach box, then "Save criteria" button.

**Heading:** > Selection Criteria

**Panel hint:**
> This is exactly what the AI judge reads. Editing anything here re-judges the current window of papers against the new wording on the next run. How scoring works.

**Labels:** > Your research, in a few sentences · Topics & intersections · Explicitly *not* of interest · Fit rule (optional fine print for the judge)

**Topics hint:**
> Each topic gets a short name and 1–3 sentences. Intersections beat broad topics; star (★) the ones that matter most.

**Exclusions hint:**
> Adjacent-but-irrelevant areas, methods or literatures to exclude.

**Fit-rule hint:**
> Leave blank to use the default rule (a paper squarely inside one topic is a bullseye; connecting several is even better).

**Button:** > Save criteria

**Success notice:**
> Selection Criteria saved. Papers will be re-judged against the new wording on the next run.

**Validation:**
> The core statement is what the judge reads first — please keep at least a short paragraph.
>
> At least one topic is required (short name + description).

## Profile audit panel

[STRUCTURE] Heading; either a locked state (explanatory hint + disabled button) or an unlocked state (hint + active button). Below, if an audit exists: "Latest audit — «date»" sub-heading, optional summary line, then proposal cards (target label, "Current:" line, "Suggested:" line, rationale, bulleted motivating papers), a closing hint, and a "Past audits" line.

**Heading:** > Profile audit

**Locked hint:**
> The audit compares your Selection Criteria against your **votes**: papers you thumbed down that the judge scored high, papers you thumbed up that it scored low, and how each topic is performing. It unlocks once you've voted on **«minimum»** papers, so it has real evidence to work from — you've voted on «n» so far. Keep voting on your briefings and this will light up.

**Unlocked hint:**
> One AI pass over your criteria, your seeds, and your «n» votes — it proposes specific wording edits (current → suggested), citing the papers that motivate each. Nothing is applied automatically: take the ones you agree with into the Selection Criteria editor above.

**Button:** > Run profile audit

**Latest-audit heading:** > Latest audit — «date»
**Proposal card labels:** > Current: / Suggested:
**Closing hint:** > Apply edits you agree with in the Selection Criteria editor above.

**Past-audits line:**
> Past audits: «date» («n» votes) · … — each new audit sees the previous one and focuses on what changed.

**Messages:**
> Audit complete — proposals below. Apply the ones you agree with in the Selection Criteria editor.
>
> The audit unlocks at «minimum» votes («n» so far) — votes are its evidence.

## Seed papers panel

**Heading:** > Seed papers («n»)

**Hint:**
> Seeds steer Gathering — the daily search covers the research areas your seeds live in. Add papers you wish you'd been alerted to.

**Add label:** > Add seeds — DOIs or titles, one per line
**Button:** > Look up & add
**Messages:** > Added «n» papers. / Couldn't find: «list of misses»

(Then the scrollable seed list — shared seed-row chrome.)

## Delete account panel (danger style)

**Heading:** > Delete account

**Hint:**
> Removes your account and **all** of your data — email, research-interest text, seed papers, votes, click logs, briefings, and any Zotero connection — immediately and permanently. You'll receive no further email from us. (See the privacy note for exactly what we store.)

**Confirm label:** > Type `DELETE` to confirm
**Confirm placeholder:** > DELETE
**Button (red):** > Delete my account and all data

**Browser popup if mistyped:** > Type DELETE in the box to confirm.
**Server-side validation:** > To delete your account, type DELETE in the confirmation box.

---

# About — /about

[STRUCTURE] Narrow text page, technical-first: H1, an intro paragraph, then a compact PIPELINE VISUAL — four stages stacked vertically, each a numbered brand-blue circle chip + bold stage name + one-sentence description, connected by short vertical lines (the site's step/chip visual language, no emoji). Then two prose paragraphs on the mechanics, then a highlighted methods-note box (left brand-blue border). At the BOTTOM: a small visually-distinct "Behind the tool" card (bordered, tinted) with a compact photo of Ryan on the left and two short paragraphs (bio + contact, support line with the ☕ Ko-fi link).

**H1:** > How Research Radar works

**Intro paragraph:**
> Research Radar exists because keeping up with new research shouldn't come down to luck. Keyword alerts bury the occasional right paper under a pile of near-misses — and still miss work you genuinely need to see. This page explains what the tool actually does each morning; the mechanics are simple enough to state precisely.

**Pipeline visual — stage 1 (chip "1"):**
> **Gathering** — New papers and preprints pulled daily from OpenAlex, arXiv, SocArXiv and PsyArXiv, searched in the research areas your seed papers live in.

**Pipeline visual — stage 2 (chip "2"):**
> **Shortlist by meaning** — Each candidate is compared to your seed papers by embedding similarity — closeness of meaning, not shared keywords. The closest form your shortlist.

**Pipeline visual — stage 3 (chip "3"):**
> **The AI judge** — A language model reads every shortlisted abstract against the Selection Criteria you wrote, scores fit 0–10, and gives a one-sentence rationale.

**Pipeline visual — stage 4 (chip "4"):**
> **Your briefing** — Papers that clear your fit bar, ranked by fit — on your dashboard and, if you want, in your inbox. Your votes feed the next day's judging.

**Prose paragraph 1:**
> The first two stages cast the net. Every morning the pipeline pulls the newest publications across fields from **OpenAlex** (which indexes most scholarly journals) plus the **arXiv, SocArXiv and PsyArXiv** preprint servers, searching the research areas derived from users' seed papers, with obvious noise (errata, book reviews, non-articles) filtered out. Each candidate's title and abstract is turned into an *embedding* — a numerical representation of its meaning — and compared to the embeddings of your seed papers; the candidates that sit closest form your daily shortlist. This stage is deliberately generous: its job isn't to decide, only to make sure the right papers reach the judge.

**Prose paragraph 2:**
> The judge is where selection actually happens. A large language model reads each shortlisted title and abstract against your **Selection Criteria** — the description, topics, and exclusions you wrote in your own words — and scores the paper's fit for you from 0 to 10 with a one-sentence rationale you can check on every card. Your briefing shows what clears your fit bar, ranked by fit score, with embedding closeness to your seeds breaking ties. Thumbs-up and thumbs-down votes become boundary examples the judge reads on every following run, so the selection tracks your actual judgment over time.

**Methods-note box (with a configured source URL, "docs/how-it-works.md" and "GitHub repository" are links into the repo):**
> Want every detail under the hood — each design and filtering decision, with the exact thresholds and formulas? The full methods document (docs/how-it-works.md) in the GitHub repository walks through the whole pipeline.

**Methods-note placeholder suffix (only while no source URL is configured — link rendered as inert text):**
> (repository link coming soon)

**"Behind the tool" card — heading:** > Behind the tool

**Card paragraph 1:**
> I'm Ryan Funkhouser, a political-communication researcher at the University of Idaho, where I study how communication shapes political attitudes and behavior. I built Research Radar — in part using AI — because my own keyword alerts kept missing the papers that mattered. It's free, and I welcome feedback, feature requests, or bug reports at admin@papersradar.com.

**Card paragraph 2:**
> If you find it a useful service and want to help with the basic costs of running it, you can buy me a coffee ☕. Appreciated, never expected.

---

# How the scores work — /about-scores

[STRUCTURE] Narrow page: H1 + sub-line, then four panels: Stage 1, Stage 2 (includes a 5-row score legend of pill chips), "What are flavors?", and feedback.

**H1:** > How your papers are chosen & scored
**Sub-line:** > Everything here is inspectable — no black boxes.

**Panel 1 heading:** > Stage 1 · Gathering
**Panel 1:**
> Every morning we pull the newest papers and preprints from **OpenAlex** (which indexes most scholarly journals), **arXiv**, **SocArXiv** and **PsyArXiv** — searching the research areas learned from *your seed papers*. Each candidate is then compared to your seeds by *semantic closeness* (meaning, not keywords), and the closest form your daily shortlist.

**Panel 2 heading:** > Stage 2 · Selection — the judge
**Panel 2 intro:**
> An AI reader (a large language model) reads every shortlisted title and abstract against your **Selection Criteria** — the plain-English description you wrote, plus your flavors, exclusions, and example papers — and scores **fit** for you:

[STRUCTURE] Score legend: five lines, each starting with a pill chip showing the score band.

> **9–10** squarely inside one of your flavors — the flavor *is* the paper's central question
> **7–8** clearly within a flavor, sharing the stage with other aims
> **4–6** competent on one component (your topic area alone) without the combination
> **1–3** tangential — shares vocabulary, not the research space
> **0** off-target or on your not-interested list

**Panel 2 close:**
> Every score comes with a one-sentence rationale — that's the quoted line on each card. If the rationale is wrong, that's your cue to edit your criteria.
>
> Your briefing is ranked by that fit score; equally fitting papers are ordered by semantic closeness to your seed papers.

**Panel 3 heading:** > What are "flavors"?
**Panel 3:**
> Your *topics & intersections* from setup — named sub-interests, each an *intersection* of things you care about (e.g. "narrative persuasion: narrative as a persuasion mechanism, in any domain..."). A paper squarely inside *one* flavor is a bullseye; it doesn't need to touch all of them. The tags on each card's chip show which flavors the judge thinks a paper engages. Edit them in Settings → Selection Criteria.

**Panel 4 heading:** > Your feedback is part of the system
**Panel 4:**
> Thumbs-up and thumbs-down on any card become *boundary examples* shown to the judge from the next run onward — "papers the researcher liked / rejected". A few votes on borderline cases sharpen your radar noticeably. Clicking through to a paper is also recorded so we can evaluate how useful your briefings are.

---

# Privacy — /privacy

[STRUCTURE] Narrow page: H1 + sub-line, then seven titled panels, then a closing contact hint.

**H1:** > Privacy & your data, in plain English
**Sub-line:**
> Research Radar is a free service run to advance research. Everything below is a factual description of how the software works.

**Panel — What we store:**
> Your account lives in a single database on our server. It holds: your **email address** and name, your **research-interest text** (your description, topics, and exclusions), your **seed papers**, your settings (briefing frequency and size, scope option, **priority journals**), and — if you use them — your **thumbs-up/down votes**, **briefing click logs** (which picks you opened), and any **AI-coach drafts and audit reports** generated from your own seeds and votes, plus the briefings and fit scores we compute for you. That's it — there is nothing else to store, because there are no payments and no profiles beyond your research interests.

**Panel — Signing in:**
> There are no passwords. Sign-in links are **one-time** and expire in 20 minutes; we keep only a **hashed** copy of each link's token, so a stored token can't be replayed. After you click a link, you stay signed in on that device via a signed browser **cookie** for **90 days** (or until you sign out).

**Panel — Zotero:**
> The recommended way to connect Zotero is a **public group library**, which needs no API key at all. If you instead provide a private read-only API key, it is **encrypted at rest** and **never displayed again** — not to you, not in any page. You can disconnect at any time.

**Panel — What leaves our server:**
> To compute your briefing, **paper titles and abstracts** and **your research-interest text** are sent to third-party LLM APIs — **Groq, Google Gemini, and OpenRouter/Cerebras**. No other personal data is sent: not your email address, not your name, not your click history. Paper metadata itself comes from public scholarly indexes (OpenAlex, arXiv, OSF preprint servers).

**Panel — No tracking, no selling:**
> We run **no third-party analytics or trackers** — every asset on this site is served from our own server, and the only logs are the click logs described above, used to make your briefings better. We **never sell or share your data** with anyone.

**Panel — Email:**
> You will receive **only** the briefing emails at the frequency you chose, plus sign-in links you request — nothing else, ever. Every briefing email has a working unsubscribe link, and you can switch to dashboard-only delivery in Settings.

**Panel — Deleting everything:**
> You can **delete your account and all of your data yourself, anytime**, in Settings → Delete account. Deletion removes your account, interest text, seed papers, votes, click logs, briefings, and any Zotero connection from our database immediately.

**Closing hint:**
> Questions? Email admin@papersradar.com.

---

# Unsubscribed — /unsubscribe/«token»

[STRUCTURE] Centered empty-state card: big emoji (📭 success / ❓ failure), H2, paragraph.

**Success (📭):**
> **You're unsubscribed** — Briefing emails to **«email»** are off. Your radar keeps running — your briefings are still on your dashboard whenever you want them, and you can turn emails back on in Settings anytime.

**Failure (❓):**
> **That unsubscribe link didn't work** — The link may be incomplete. You can also turn briefing emails off in Settings (choose "Dashboard only").

---

# Account deleted — shown after deletion

[STRUCTURE] Centered empty-state card: big 👋 emoji, H2, two paragraphs.

> **Your account and all your data are deleted** — Your email, research-interest text, seed papers, votes, click logs, briefings, and any Zotero connection have been removed from our database. You won't receive any further email from us.
>
> If you ever want to come back, just sign in again — you'll start fresh.

---

# Admin — /admin (owner only)

[STRUCTURE] Wide page: H1 + status sub-line, then data-table panels: Users, Provider quota — today, Pipeline runs, Recent errors. Mostly raw data; a ✓ marks admin users.

**H1:** > Admin
**Sub-line:** > «n» papers in the corpus · «n» embedded · **DEV MODE (no SMTP)** — login links

**Panel headings:** > Users · Provider quota — today · Pipeline runs · Recent errors
**Empty-table rows:** > No provider calls yet today. / No pipeline runs yet.

## Dev login links — /admin/dev-links

**H1:** > Dev-mode login links
**Sub-line (dev mode):**
> SMTP is not configured, so magic links are not emailed — pending links appear here (and in the server log) instead. Pass them to the requesting user through a trusted channel.

**Sub-line (SMTP configured):**
> SMTP is configured — links are emailed; nothing should appear here.

**Empty-table row:** > No pending links.

---

# Emails

## Magic-link (sign-in) email

[STRUCTURE] Minimal HTML email, max ~480px wide: blue "Research Radar" heading, one sentence, a solid blue rounded sign-in button, a small gray disclaimer line. A plain-text alternative is included for text-only mail clients.

**Subject:** > Your Research Radar sign-in link

**Body:**
> **Research Radar**
>
> Click to sign in — this link works once and expires in 20 minutes:
>
> [ Sign in to Research Radar ]  ← button
>
> If you didn't request this, ignore this email.

**Plain-text version:**
> Sign in to Research Radar: «link» (This link works once and expires in 20 minutes.)

## Daily briefing email

[STRUCTURE] HTML email, max ~640px wide. Header: small radar logo image + blue "Research Radar" title, then a gray date line. Then one bordered rounded card per paper: bold title (blue link) → gray authors line with italic venue and date → optional indigo priority-journal line → indigo pill chip (fit score + flavors) → italic why-quote → gray abstract excerpt, with a "full summary" link when the excerpt is trimmed (trimming never cuts mid-sentence). After the cards: a small-print explainer, then a bordered footer with manage/unsubscribe links.

**Subject:** > Research Radar — «n» picks for «date»

**Date line:**
> «Weekday, Month DD, YYYY» · «n» picks for «user name»

**Per-card priority-journal line:**
> from *«journal name»* — your priority list

**Per-card chip:** > «score»/10 · «flavor list»

**Excerpt "more" link:**
> Full summary on your dashboard →

**Explainer (small print):**
> Each pick was scored by an AI judge reading the abstract against your Selection Criteria — the chip shows its fit score and matched flavors. Picks are ranked by fit; equally fitting papers are ordered by closeness to your seed papers. Open your dashboard to vote on picks or tune your criteria.

**Footer:**
> Research Radar is a free tool that scans each day's new papers and preprints for the ones that fit your research. You're receiving this because you chose «daily (7-per-week) / weekly (1-per-week)» briefings — manage or unsubscribe in one click.

**Plain-text fallback (all HTML emails):**
> This message is best viewed as HTML.

---

# Inventory of emojis & symbols

Every emoji/symbol currently rendered in the UI, for the planned swap to themed SVG mini-symbols:

| Symbol | Where it appears |
|---|---|
| 🌍 | Landing, feature box 1 icon ("Field-agnostic coverage") |
| 🔍 | Landing, feature box 2 icon ("Readable AI rationales") |
| 🎯 | Landing, feature box 3 icon ("Corrects with your feedback") |
| ☕ | Footer (every page), landing "Free" strip, About page — all in "buy me a coffee ☕" |
| 📧 | "Check your inbox" page, big empty-state icon |
| 📡 | Dashboard empty states ("radar warming up" / "no briefing yet") and Archive empty states ("no briefings archived yet" / "no matches"), big icon |
| 👍 | Paper-card vote button ("More like this") — dashboard + archive |
| 👎 | Paper-card vote button ("Fewer like this") — dashboard + archive |
| 📭 | Unsubscribe-success page, big icon |
| ❓ | Unsubscribe-failure page, big icon |
| 👋 | Account-deleted page, big icon |
| ★ | Topics editor star toggle (core topic); also referenced in copy as "Star (★)" in onboarding step 3 and the Settings topics hint |
| ✕ | Remove buttons everywhere: seed rows, journal rows, topic rows, exclusion rows, coach-note dismiss |
| ✓ | Admin users table, "admin" column |
| → | Briefing email "Full summary on your dashboard →"; Settings audit hint "(current → suggested)" |
| ← | Archive day view, "← All briefing days" back link |
| … | Archive search placeholder ("…author…"); also in "Thinking…" (coach button) |
| • | Bullets in the worked-example exclusions list |
| " " (curly quotes) | Dashboard card why-quote and landing testimonial |

Not emoji, but part of the same visual language: the SVG radar logo (header + email header + favicon), the decorative page-bottom radar arcs, the round score chips, and the progress dots in onboarding.
