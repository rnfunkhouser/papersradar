"""Configuration loader: .env file + environment variables (env wins).

Every module (web app + pipeline) reads settings through `cfg()`, so tests can
point the app at a temp DB / stub OpenAlex by setting environment variables
before first use, and the server just has /srv/papersradar/.env.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_DEFAULTS = {
    "APP_SECRET": "",
    "BASE_URL": "http://127.0.0.1:8000",
    "DB_PATH": str(ROOT / "data" / "papersradar.db"),
    "LOG_DIR": str(ROOT / "logs"),
    "GROQ_API_KEY": "",
    "GEMINI_API_KEY": "",
    "CEREBRAS_API_KEY": "",
    "OPENROUTER_API_KEY": "",
    "EMBEDDER": "nemotron-3-embed-1b",
    # OpenRouter free-model requests/day. 50 on a plain free account; a
    # one-time $10 credit purchase permanently raises the account's cap to
    # 1,000 — set OPENROUTER_RPD=1000 in .env on such accounts. Enforced for
    # both the embed stage and the chat-router fallback accounting.
    "OPENROUTER_RPD": "50",
    "SMTP_HOST": "",
    "SMTP_PORT": "587",
    "SMTP_USER": "",
    "SMTP_PASS": "",
    "SMTP_FROM": "Research Radar <no-reply@papersradar.com>",
    "SOURCE_URL": "",     # public source-code repo; empty hides the link and
                          # any open-source wording (never claim it falsely)
    "OPENALEX_MAILTO": "admin@papersradar.com",
    "OPENALEX_BASE": "https://api.openalex.org",
    "ZOTERO_BASE": "https://api.zotero.org",
    "ARXIV_BASE": "https://export.arxiv.org",
    "OSF_BASE": "https://api.osf.io",
    "JUDGE_SHORTLIST_PER_USER": "40",
    "BRIEFING_MIN_FIT": "6",
    "BRIEFING_MAX_ITEMS": "5",
    "GATHER_WINDOW_DAYS": "4",
    "OPENALEX_MAX_PER_CONCEPT": "800",
    # Priority journals: papers from a user's chosen journals get guaranteed
    # judge slots when their embedding relevance is at or above this percentile
    # of the user's windowed pool (chosen empirically — see
    # analysis/priority_journal_threshold.md), capped at MAX_PER_USER extra
    # slots per day ON TOP of JUDGE_SHORTLIST_PER_USER.
    "PRIORITY_JOURNAL_MIN_REL_PCTL": "60",
    "PRIORITY_JOURNAL_MAX_PER_USER": "10",
    # Max works pulled per priority journal per gather run
    "OPENALEX_MAX_PER_JOURNAL": "100",
    # AI profile coach: all coach modes (autofill/suggestions/audit) share one
    # per-user daily LLM-call budget
    "COACH_DAILY_LIMIT": "10",
    # Vote-informed profile audit unlocks at this many votes
    "AUDIT_MIN_VOTES": "20",
}

_cache: dict | None = None


def _load_env_file() -> dict:
    """Parse KEY=value lines from the .env next to the repo root (or $ENV_FILE)."""
    path = Path(os.environ.get("ENV_FILE", ROOT / ".env"))
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out

def cfg(key: str, default: str | None = None) -> str:
    """Setting lookup: os.environ > .env file > _DEFAULTS > `default`."""
    global _cache
    if _cache is None:
        _cache = _load_env_file()
    if key in os.environ:
        return os.environ[key]
    if key in _cache:
        return _cache[key]
    if key in _DEFAULTS:
        return _DEFAULTS[key]
    if default is not None:
        return default
    raise KeyError(f"missing config: {key}")

def cfg_int(key: str) -> int:
    return int(cfg(key))

def reset_cache() -> None:
    """Forget the parsed .env (tests use this after changing env vars)."""
    global _cache
    _cache = None

def db_path() -> Path:
    p = Path(cfg("DB_PATH"))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def log_dir() -> Path:
    p = Path(cfg("LOG_DIR"))
    p.mkdir(parents=True, exist_ok=True)
    return p

def smtp_configured() -> bool:
    return bool(cfg("SMTP_HOST").strip())
