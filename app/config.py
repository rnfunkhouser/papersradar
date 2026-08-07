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
    "SMTP_HOST": "",
    "SMTP_PORT": "587",
    "SMTP_USER": "",
    "SMTP_PASS": "",
    "SMTP_FROM": "Papers Radar <no-reply@papersradar.com>",
    "OPENALEX_MAILTO": "admin@papersradar.com",
    "OPENALEX_BASE": "https://api.openalex.org",
    "ZOTERO_BASE": "https://api.zotero.org",
    "JUDGE_SHORTLIST_PER_USER": "40",
    "BRIEFING_MIN_FIT": "6",
    "BRIEFING_MAX_ITEMS": "8",
    "GATHER_WINDOW_DAYS": "4",
    "OPENALEX_MAX_PER_CONCEPT": "800",
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
