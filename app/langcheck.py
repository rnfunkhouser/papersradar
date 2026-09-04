"""Lightweight English-text check (pure stdlib) for ingest filtering.

OpenAlex is filtered server-side (language:en) and gather.keep() honors a
declared non-English language field — but OSF/SocArXiv preprints often carry
no language metadata, which let a French abstract reach a briefing
(2026-09-04). This closes that gap by stopword ratio: a text is dropped only
when another language's stopwords clearly dominate English's, so short or
ambiguous text defaults to KEEP (false drops of English papers are worse
than the occasional leak).
"""
from __future__ import annotations

import re

_WORD = re.compile(r"[a-zà-ÿäöüßáéíóúâêîôûãõç]+")

STOPWORDS = {
    "en": {"the", "of", "and", "to", "in", "is", "that", "for", "on", "with",
           "as", "are", "this", "by", "from", "we", "be", "it", "an", "was",
           "were", "which", "these", "their", "our", "has", "have", "not",
           "at", "or", "its", "how", "can", "than", "between", "into",
           "about", "both", "among", "more", "when", "who", "such", "may"},
    "fr": {"le", "la", "les", "des", "du", "et", "une", "que", "qui", "dans",
           "pour", "sur", "est", "aux", "ce", "cette", "comme", "par",
           "elle", "nous", "sont", "leur", "leurs", "ses", "mais", "avec",
           "été", "être", "ont", "d'abord", "ensuite", "plutôt", "au"},
    "es": {"el", "los", "las", "del", "una", "que", "es", "por", "con",
           "para", "su", "se", "al", "lo", "como", "más", "entre", "este",
           "esta", "sus", "son", "también", "sobre", "pero", "nos", "hay"},
    "de": {"der", "die", "das", "und", "ist", "von", "mit", "für", "auf",
           "den", "dem", "ein", "eine", "zu", "im", "nicht", "als", "auch",
           "sich", "wird", "werden", "durch", "bei", "aus", "einer", "dass"},
    "pt": {"os", "do", "da", "dos", "das", "em", "um", "uma", "que", "por",
           "com", "para", "no", "na", "se", "ao", "como", "mais", "são",
           "uma", "pela", "pelo", "à", "às", "não", "também", "entre"},
}


def looks_english(text: str) -> bool:
    """True unless a non-English language clearly dominates. Conservative:
    short/ambiguous text is treated as English."""
    tokens = _WORD.findall((text or "").lower())
    if len(tokens) < 10:
        return True
    hits = {lang: sum(1 for t in tokens if t in words)
            for lang, words in STOPWORDS.items()}
    en = hits.pop("en")
    best_other = max(hits.values())
    # dominance requires real signal (>=8% of tokens) AND a clear margin
    if best_other >= max(3, len(tokens) * 0.08) and best_other > en * 1.5:
        return False
    return True
