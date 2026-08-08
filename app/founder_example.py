"""The founder's own research-interest profile, used as the worked example in
the structured onboarding wizard ("Want to see a full example?") and settings.

Hardcoded verbatim from the founder's real interest_profile.json (2026-07-23-v3)
so onboarding needs no file or network access. Attributed in the UI as "the
founder's own profile". The source file does not star any flavor as 'core' —
each is treated as a bullseye in its own right — so none are starred here.
"""
from __future__ import annotations

FOUNDER_ATTRIBUTION = ("This is the founder's own profile — a political-"
                       "communication researcher. Yours can be shorter; "
                       "specificity matters more than length.")

FOUNDER_CORE_STATEMENT = (
    "I am a political-communication researcher. I study how communication — "
    "increasingly AI-mediated — persuades, changes behavior, and bridges or "
    "deepens ideological divides, especially online. My interests come in a few "
    "specific flavors (below); the best papers for me sit squarely inside one "
    "flavor or connect several. Papers about just 'AI' in general, or 'politics' "
    "in general, are background noise. AI matters to me as a COMMUNICATOR or "
    "INTERVENTION (a chatbot that persuades, an LLM that delivers arguments), "
    "not as an object of public opinion or a research tool."
)

FOUNDER_FLAVORS = [
    {"key": "bridging_divides", "core": False, "description":
     "Communication mechanisms for bridging ideological divides, especially "
     "online: depolarization interventions, cross-partisan conversation, "
     "perspective-taking dialogues, correcting misperceptions of the out-group, "
     "reducing partisan animosity and incivility."},
    {"key": "narrative_persuasion", "core": False, "description":
     "Narrative as a persuasion mechanism, in any domain (political, health, "
     "climate, civic): narrative transportation, entertainment-education, "
     "story-based appeals, narrative vs non-narrative message effects, "
     "inoculation/prebunking delivered through stories."},
    {"key": "llm_behavior_change", "core": False, "description":
     "LLMs and chatbots for changing beliefs and behavior: conversational AI "
     "that durably shifts attitudes (e.g., conspiracy-belief reduction), AI "
     "dialogue interventions, chatbot-delivered persuasion or behavior-change "
     "programs, and their psychological mechanisms."},
    {"key": "llm_persuasion_online", "core": False, "description":
     "LLMs and generative AI as persuaders in online and political contexts: "
     "AI-generated persuasive messages, persuasive bots, generative agents "
     "spreading or countering misinformation, AI's persuasive advantage over "
     "humans, computational propaganda with generative AI."},
    {"key": "political_discourse_online", "core": False, "description":
     "Political and civic discourse online, broadly: how platforms, algorithms, "
     "norms and governance expectations, emotions, and attention dynamics shape "
     "political talk, public opinion, polarization, misinformation belief, and "
     "citizens' commitment to democratic norms. Persuasion need not be the "
     "focus — empirical work on the dynamics of online political/civic "
     "communication belongs here."},
    {"key": "small_stories", "core": False, "description":
     "'Small stories' and fragmented narrative online: brief, fleeting, "
     "everyday story fragments as a framework for studying identity, attention, "
     "and meaning-making in fast-moving digital discourse; how fragmented "
     "content dynamics (attention, virality) shape what stories take hold. "
     "Computational models of collective attention to online content (what "
     "spreads, what fades, and how fast) count here."},
]

FOUNDER_NEGATIVES = [
    "Public attitudes TOWARD AI, AI governance, or AI ethics — where AI is the "
    "object of opinion rather than the communicator or intervention",
    "LLMs as research or measurement tools (generating surveys, coding data, "
    "content analysis of model outputs) with no persuasion or behavior-change "
    "outcome",
    "Chatbot UX, companionship, loneliness, or adoption studies with no "
    "persuasion, behavior-change, or political dimension",
    "Clinical/diagnostic AI, robots for physical tasks, and AI engineering or "
    "productivity studies",
    "Public acceptance of technologies (energy, climate tech, food tech) via "
    "framing, unless about political discourse, narrative, or misinformation",
    "Consumer/brand marketing and purchase-decision persuasion with no "
    "narrative mechanism and no political dimension",
    "Classroom or educational discourse pedagogy unless about political "
    "persuasion or bridging divides",
    "Area-studies, policy, or governance pieces with no communication or "
    "persuasion mechanism",
    "Broad state-of-AI or state-of-democracy think pieces with no empirical "
    "question (empirical studies of democratic attitudes are IN, per "
    "political_discourse_online)",
]
