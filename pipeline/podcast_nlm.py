#!/usr/bin/env python3
"""Client for a self-hosted notebooklm-mcp worker (the NotebookLM two-host
podcast engine). The worker (github.com/roomi-fields/notebooklm-mcp) exposes
NotebookLM — a dedicated Google account, logged in once via noVNC — as a local
REST API; this module drives one episode: fresh notebook, upload sources
(full-text PDFs + a notes doc for abstract-only papers), request the Audio
Overview with the steering prompt, poll, download WAV, prune old notebooks.

ENDPOINT MAP: notebooklm-mcp is an unofficial project and its REST routes may
differ between releases. The paths below are centralized in `EP` and MUST be
verified once against the installed worker at deploy time —
`python3 -m pipeline.podcast_nlm --probe` prints what the worker actually
serves (docs/PODCAST_RUNBOOK.md §NLM). Everything else in this module is
route-agnostic.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import cfg, cfg_int

# Verify against the installed notebooklm-mcp version (see module docstring).
EP = {
    "health":          "GET  /health",
    "list_notebooks":  "GET  /notebooks",
    "create_notebook": "POST /notebooks",                       # {"title"}
    "delete_notebook": "DELETE /notebooks/{id}",
    "add_text":        "POST /notebooks/{id}/sources/text",     # {"title","content"}
    "add_file":        "POST /notebooks/{id}/sources/file",     # multipart pdf
    "audio_create":    "POST /notebooks/{id}/audio",            # {"prompt"}
    "audio_status":    "GET  /notebooks/{id}/audio/status",
    "audio_download":  "GET  /notebooks/{id}/audio/download",
}

POLL_SEC = 30
NOTEBOOK_PREFIX = "PapersRadar"


class NLMError(Exception):
    pass


def _base() -> str:
    base = cfg("NLM_MCP_BASE").strip().rstrip("/")
    if not base:
        raise NLMError("NLM_MCP_BASE not configured (worker not installed?)")
    return base


def _url(key: str, **fmt) -> tuple[str, str]:
    method, _, path = EP[key].partition(" ")
    return method.strip(), _base() + path.strip().format(**fmt)


def _call(key: str, body: dict | None = None, raw: bytes | None = None,
          content_type: str = "application/json", timeout: int = 120, **fmt):
    method, url = _url(key, **fmt)
    data = raw if raw is not None else (
        json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": content_type})
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
        raise NLMError(f"{key}: HTTP {e.code} {detail}") from e
    except Exception as e:
        raise NLMError(f"{key}: {type(e).__name__}: {e}") from e
    if "json" in ctype:
        return json.loads(payload or b"{}")
    return payload


def _multipart(field: str, filename: str, content: bytes,
               mime: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; "
            f'name="{field}"; filename="{filename}"\r\n'
            f"Content-Type: {mime}\r\n\r\n").encode() + content \
        + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


# --- the engine flow ----------------------------------------------------------

def generate_episode(rows, fulltext_files: list[Path | None],
                     steering_prompt: str, date: str) -> bytes:
    """One episode -> WAV bytes. rows = briefed papers in rank order;
    fulltext_files aligns with rows (None = abstract-only)."""
    nb = _call("create_notebook", body={"title": f"{NOTEBOOK_PREFIX} {date}"})
    nb_id = nb.get("id") or nb.get("notebook_id")
    if not nb_id:
        raise NLMError(f"create_notebook: no id in response {str(nb)[:200]}")
    notes = []
    for i, (r, f) in enumerate(zip(rows, fulltext_files), 1):
        if f and f.suffix == ".pdf" and f.exists():
            body, ctype = _multipart("file", f.name, f.read_bytes(),
                                     "application/pdf")
            _call("add_file", raw=body, content_type=ctype, timeout=300,
                  id=nb_id)
        else:
            authors = ", ".join(json.loads(r["authors_json"] or "[]")[:10])
            notes.append(
                f"Paper {i} (ABSTRACT ONLY — flag this on air): {r['title']}\n"
                f"Authors: {authors}\nVenue: {r['venue']}\n"
                f"Published: {r['pub_date']}\nAbstract: {r['abstract']}")
    if notes:
        _call("add_text", id=nb_id, body={
            "title": "Briefing notes (abstract-only papers)",
            "content": "\n\n".join(notes)})
    _call("audio_create", id=nb_id, body={"prompt": steering_prompt},
          timeout=300)
    deadline = time.monotonic() + cfg_int("NLM_GENERATE_TIMEOUT_SEC")
    while True:
        st = _call("audio_status", id=nb_id)
        state = str(st.get("status") or st.get("state") or "").lower()
        if state in ("ready", "done", "completed", "complete"):
            break
        if state in ("failed", "error"):
            raise NLMError(f"audio generation failed: {str(st)[:200]}")
        if time.monotonic() > deadline:
            raise NLMError(f"audio generation timed out after "
                           f"{cfg('NLM_GENERATE_TIMEOUT_SEC')}s")
        time.sleep(POLL_SEC)
    wav = _call("audio_download", id=nb_id, timeout=600)
    if not isinstance(wav, bytes) or len(wav) < 10_000:
        raise NLMError("audio download returned no usable audio")
    return wav


def prune_notebooks() -> int:
    """Delete PapersRadar notebooks older than NLM_RETENTION_DAYS (free tier
    caps total notebooks). Best-effort; returns notebooks deleted."""
    cutoff = (dt.date.today()
              - dt.timedelta(days=cfg_int("NLM_RETENTION_DAYS"))).isoformat()
    try:
        listing = _call("list_notebooks")
    except NLMError:
        return 0
    items = listing if isinstance(listing, list) else listing.get("notebooks", [])
    deleted = 0
    for nb in items:
        title = str(nb.get("title") or nb.get("name") or "")
        nb_id = nb.get("id") or nb.get("notebook_id")
        if not nb_id or not title.startswith(NOTEBOOK_PREFIX + " "):
            continue
        nb_date = title.rsplit(" ", 1)[-1]
        if nb_date < cutoff:
            try:
                _call("delete_notebook", id=nb_id)
                deleted += 1
            except NLMError:
                pass
    return deleted


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe", action="store_true",
                    help="check the worker's health endpoint and print the "
                         "endpoint map to verify against its docs")
    a = ap.parse_args()
    if a.probe:
        print("configured endpoint map (verify against the installed "
              "notebooklm-mcp version):")
        for k, v in EP.items():
            print(f"  {k:16} {v}")
        try:
            print("health:", str(_call("health"))[:300])
        except NLMError as e:
            sys.exit(f"worker unreachable: {e}")
