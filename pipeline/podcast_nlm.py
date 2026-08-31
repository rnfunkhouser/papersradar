#!/usr/bin/env python3
"""Client for a self-hosted notebooklm-mcp worker (the NotebookLM two-host
podcast engine). The worker (github.com/roomi-fields/notebooklm-mcp, run via
its Docker image — a dedicated Google account logged in once through noVNC)
exposes NotebookLM as a local REST API; this module drives one episode:
fresh notebook, add sources (full-text PDFs by file path + a notes doc for
abstract-only papers), generate the Audio Overview with the steering prompt
as custom_instructions, download the audio, prune old notebooks.

Endpoint map verified against the project's OpenAPI spec
(deployment/docs/openapi.yaml, checked 2026-08-31):
    GET  /health
    GET  /notebooks                     list
    POST /notebooks/create              {name, description}
    DELETE /notebooks/{id}
    POST /content/sources               {source_type: file|text, file_path|text,
                                         title, notebook_id/notebook_url}
    POST /content/generate              {content_type: "audio_overview",
                                         custom_instructions, ...} -> metadata
    GET  /content/download?content_id=  -> audio bytes

Releases may still drift from the spec — `python3 -m pipeline.podcast_nlm
--probe` checks /health at install time (docs/PODCAST_RUNBOOK.md §NLM).

PDF sources are passed by FILE PATH, resolved inside the worker (its Docker
container must bind-mount the papersradar data dir); NLM_FILE_MAP rewrites
host paths to container paths, e.g. "/srv/papersradar/data:/data/papersradar".
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import cfg, cfg_int

GENERATE_POLL_SEC = 30
NOTEBOOK_PREFIX = "PapersRadar"


class NLMError(Exception):
    pass


def _base() -> str:
    base = cfg("NLM_MCP_BASE").strip().rstrip("/")
    if not base:
        raise NLMError("NLM_MCP_BASE not configured (worker not installed?)")
    return base


def _call(method: str, path: str, body: dict | None = None,
          timeout: int = 120):
    url = _base() + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
            ctype = (r.headers.get("Content-Type") or "").lower()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise NLMError(f"{method} {path}: HTTP {e.code} {detail}") from e
    except Exception as e:
        raise NLMError(f"{method} {path}: {type(e).__name__}: {e}") from e
    if "json" in ctype:
        data = json.loads(payload or b"{}")
        # the worker wraps JSON responses in a {"success", "data"} envelope
        # (observed live 2026-08-31); unwrap so callers see the object itself
        if isinstance(data, dict) and "success" in data and "data" in data:
            if not data["success"]:
                raise NLMError(f"{method} {path}: {str(data)[:300]}")
            return data["data"]
        return data
    return payload


def map_path(host_path: Path) -> str:
    """Host file path -> the path the worker sees (NLM_FILE_MAP
    'host_prefix:worker_prefix'; empty = same filesystem view)."""
    mapping = cfg("NLM_FILE_MAP", "").strip()
    p = str(host_path)
    if mapping and ":" in mapping:
        host_prefix, _, worker_prefix = mapping.partition(":")
        if p.startswith(host_prefix):
            return worker_prefix + p[len(host_prefix):]
    return p


def _notebook_refs(nb) -> dict:
    """Both id- and url-style references, so requests work across releases."""
    refs = {}
    if isinstance(nb, dict):
        inner = nb.get("notebook") if isinstance(nb.get("notebook"), dict) else nb
        for key in ("id", "notebook_id"):
            if inner.get(key):
                refs["notebook_id"] = inner[key]
                break
        for key in ("url", "notebook_url"):
            if inner.get(key):
                refs["notebook_url"] = inner[key]
                break
    if not refs:
        raise NLMError(f"create returned no notebook reference: {str(nb)[:200]}")
    return refs


# --- the engine flow ----------------------------------------------------------

def generate_episode(rows, fulltext_files: list[Path | None],
                     steering_prompt: str, date: str) -> bytes:
    """One episode -> audio bytes (WAV). rows = briefed papers in rank order;
    fulltext_files aligns with rows (None = abstract-only)."""
    nb = _call("POST", "/notebooks/create",
               {"name": f"{NOTEBOOK_PREFIX} {date}",
                "description": "Daily Papers Radar episode sources"})
    refs = _notebook_refs(nb)
    notes = []
    for i, (r, f) in enumerate(zip(rows, fulltext_files), 1):
        if f and f.suffix == ".pdf" and f.exists():
            _call("POST", "/content/sources", {
                "source_type": "file", "file_path": map_path(f),
                "title": r["title"], **refs}, timeout=300)
        else:
            authors = ", ".join(json.loads(r["authors_json"] or "[]")[:10])
            notes.append(
                f"Paper {i} (ABSTRACT ONLY — flag this on air): {r['title']}\n"
                f"Authors: {authors}\nVenue: {r['venue']}\n"
                f"Published: {r['pub_date']}\nAbstract: {r['abstract']}")
    if notes:
        _call("POST", "/content/sources", {
            "source_type": "text", "text": "\n\n".join(notes),
            "title": "Briefing notes (abstract-only papers)", **refs},
            timeout=300)
    # /content/generate returns the artifact metadata when generation is done
    # (NotebookLM takes minutes) — give it the full budget in one call.
    meta = _call("POST", "/content/generate", {
        "content_type": "audio_overview",
        "custom_instructions": steering_prompt, **refs},
        timeout=cfg_int("NLM_GENERATE_TIMEOUT_SEC"))
    content_id = _content_id(meta)
    deadline = time.monotonic() + cfg_int("NLM_GENERATE_TIMEOUT_SEC")
    while True:
        try:
            audio = _call("GET", f"/content/download?content_id={content_id}",
                          timeout=600)
        except NLMError:
            audio = None
        if isinstance(audio, bytes) and len(audio) > 10_000:
            return audio
        if time.monotonic() > deadline:
            raise NLMError("audio not downloadable before timeout "
                           f"(content_id={content_id})")
        time.sleep(GENERATE_POLL_SEC)


def _content_id(meta) -> str:
    if isinstance(meta, dict):
        for key in ("content_id", "id", "artifact_id"):
            if meta.get(key):
                return str(meta[key])
        inner = meta.get("artifact") or meta.get("content") or {}
        if isinstance(inner, dict):
            for key in ("content_id", "id"):
                if inner.get(key):
                    return str(inner[key])
    raise NLMError(f"generate returned no content id: {str(meta)[:200]}")


def prune_notebooks() -> int:
    """Delete PapersRadar notebooks older than NLM_RETENTION_DAYS (free tier
    caps total notebooks). Best-effort; returns notebooks deleted."""
    cutoff = (dt.date.today()
              - dt.timedelta(days=cfg_int("NLM_RETENTION_DAYS"))).isoformat()
    try:
        listing = _call("GET", "/notebooks")
    except NLMError:
        return 0
    items = listing if isinstance(listing, list) else (
        listing.get("notebooks") or listing.get("items") or [])
    deleted = 0
    for nb in items:
        title = str(nb.get("name") or nb.get("title") or "")
        nb_id = nb.get("id") or nb.get("notebook_id")
        if not nb_id or not title.startswith(NOTEBOOK_PREFIX + " "):
            continue
        nb_date = title.rsplit(" ", 1)[-1]
        if nb_date < cutoff:
            try:
                _call("DELETE", f"/notebooks/{nb_id}")
                deleted += 1
            except NLMError:
                pass
    return deleted


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe", action="store_true",
                    help="check the worker's /health and list notebooks")
    a = ap.parse_args()
    if a.probe:
        try:
            print("health:", str(_call("GET", "/health"))[:300])
            print("notebooks:", str(_call("GET", "/notebooks"))[:300])
        except NLMError as e:
            sys.exit(f"worker problem: {e}")
