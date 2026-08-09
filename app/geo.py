"""Geographic scope support for the per-user "Western-context" option.

The option (users.western_context, default OFF) narrows a user's briefings to
research from Western-context venues in two deliberate layers:

  1. HARD venue filter (pipeline.shortlist): papers whose journal/venue is
     based OUTSIDE the Broad West list below are excluded from that user's
     judge queue. Venues with UNKNOWN country (preprint servers, unenriched
     sources) are never excluded by this layer.
  2. SOFT topical deprioritization (pipeline.judging.build_prompt): the judge
     is told that topical focus on non-Western contexts should moderately
     lower fit as ONE consideration — strong, highly relevant papers can
     still score well.

BROAD WEST definition: United States, Canada, United Kingdom, Ireland,
Australia, New Zealand, plus the UN M49 geoscheme's Western, Northern, and
Southern Europe sub-regions (Eastern Europe is not included). Codes are
ISO 3166-1 alpha-2, matching OpenAlex source.country_code.
"""
from __future__ import annotations

BROAD_WEST_COUNTRIES = frozenset({
    # North America
    "US", "CA",
    # UK & Ireland (UN M49 lists them under Northern Europe; named explicitly)
    "GB", "IE",
    # Western Europe (UN M49)
    "AT", "BE", "CH", "DE", "FR", "LI", "LU", "MC", "NL",
    # Northern Europe (UN M49, rest of)
    "AX", "DK", "EE", "FI", "FO", "GG", "IM", "IS", "JE", "LT", "LV",
    "NO", "SE", "SJ",
    # Southern Europe (UN M49)
    "AD", "AL", "BA", "ES", "GI", "GR", "HR", "IT", "ME", "MK", "MT",
    "PT", "RS", "SI", "SM", "VA", "XK",
    # Oceania
    "AU", "NZ",
})


def is_broad_west(country_code: str | None) -> bool:
    """True for Broad-West venues AND for unknown countries ('' / None) —
    the hard filter only ever excludes a KNOWN outside venue."""
    cc = (country_code or "").strip().upper()
    return not cc or cc in BROAD_WEST_COUNTRIES


# The judge-prompt paragraph appended for users with the option ON. Changing
# this text changes verdicts, so any edit must be treated like a profile-
# wording change (the profile version already covers it: toggling the option
# bumps the user's profile version and re-queues judging).
WESTERN_SOFT_PROMPT = """
GEOGRAPHIC SCOPE: This researcher has chosen to focus on research about Western
contexts (North America, Western/Northern/Southern Europe, Australia, New
Zealand). When a paper's topical focus is a specific non-Western national or
regional context, treat that as ONE consideration that moderately lowers fit —
it should not dominate the judgment, and a strong, highly relevant paper should
still score well."""
