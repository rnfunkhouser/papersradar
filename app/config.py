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
    # 14-day gather window + deep per-concept cap (2026-09-02, owner-approved):
    # matches the old system's validated buffer design and the 14-day
    # shortlist eligibility window (shortlist.WINDOW_DAYS). OpenAlex ingests
    # in bursts with near-zero days between (measured: 2,437-3,591 on batch
    # days, 4-16 on troughs); a shallow window + tight cap left zero unbriefed
    # fit>=8 reserve, so troughs briefed 7-point residue. The wide window
    # keeps strong papers re-competing; the cap must widen with it or
    # pub-date-desc paging truncates back to the same recent slice.
    "GATHER_WINDOW_DAYS": "14",
    "OPENALEX_MAX_PER_CONCEPT": "2400",
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
    # --- daily podcast (owner-only; see docs/PODCAST_DESIGN.md) --------------
    # Comma-separated engines to run each day; empty = feature off globally.
    # "anchor" = scripted single-anchor (writer LLM -> Gemini TTS free tier);
    # "nlm" = NotebookLM two-host via a self-hosted notebooklm-mcp worker.
    # Trial week runs "anchor,nlm".
    "PODCAST_ENGINES": "",
    # Gemini TTS: preview model names churn — if this 404s, list live models
    # (docs/PODCAST_RUNBOOK.md §TTS) and update here.
    "GEMINI_TTS_MODEL": "gemini-2.5-flash-preview-tts",
    "GEMINI_TTS_BASE": "https://generativelanguage.googleapis.com",
    "PODCAST_ANCHOR_VOICE": "Charon",
    # notebooklm-mcp worker: base URL of its local REST API (Docker image
    # serves on 3000); empty = the nlm engine reports "worker not configured"
    # instead of failing hard.
    "NLM_MCP_BASE": "",
    # host_prefix:worker_prefix rewrite for PDF file paths (the worker
    # resolves file_path inside its container; bind-mount the data dir), e.g.
    # "/srv/papersradar/data:/data/papersradar". Empty = same filesystem view.
    "NLM_FILE_MAP": "",
    # Shown in failure emails so re-auth is one click away (worker's noVNC).
    "NLM_VNC_URL": "",
    # Audio-overview generation wait (NotebookLM takes minutes)
    "NLM_GENERATE_TIMEOUT_SEC": "1800",
    # nlm engine implementation: "agent" (vision-driven computer-use loop in
    # the nlm-agent container; robust to Google UI redesigns) or "mcp"
    # (legacy selector-based worker flow; pre-2026-07 UI only).
    "NLM_MODE": "agent",
    # Computer-use-capable model for the agent loop
    "NLM_CU_MODEL": "gemini-3.7-flash",
    # Docker image tag the podcast stage invokes per episode
    "NLM_AGENT_IMAGE": "nlm-agent",
    # Fresh notebook daily; worker deletes notebooks older than this
    "NLM_RETENTION_DAYS": "7",
    # Full-text fetch (OA-only; briefed papers of podcast users)
    "UNPAYWALL_BASE": "https://api.unpaywall.org",
    "ARXIV_PDF_BASE": "https://arxiv.org",
    "FULLTEXT_MAX_MB": "30",
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
