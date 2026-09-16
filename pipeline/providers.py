#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Multi-provider OpenAI-compatible chat router (adapted from the validated
free_stack/providers.py, 2026-08-07 comparison run).

Provider order for judging: Groq `openai/gpt-oss-120b` FIRST — the batched
judge on Groq matched the old MindRouter judge's top-5 picks 5/5 — then
Gemini flash, Cerebras, OpenRouter :free. RPM pacing per provider, daily
request counters persisted in the shared SQLite DB (admin page reads them),
automatic fallback on 429/5xx/timeouts, and a curl-subprocess transport
fallback for providers whose Cloudflare edge blocks urllib's TLS fingerprint
(403 "error code: 1010" — measured on Groq/Cerebras).

Standalone checks:
    python3 -m pipeline.providers --check    # keys present + today's counters
    python3 -m pipeline.providers --test     # ONE tiny routed chat call
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import cfg
from app import db as appdb

DEFAULT_TEMPERATURE = 0.0
DEFAULT_TIMEOUT = 120
ATTEMPTS_PER_PROVIDER = 2

# Priority order: validated judge recipe (Groq primary; see DESIGN.md §4-5).
PROVIDERS = [
    {"name": "groq",
     "base": "https://api.groq.com/openai/v1",
     "env": "GROQ_API_KEY",
     "model": "openai/gpt-oss-120b",
     "rpm": 30, "rpd": 1000},
    {"name": "gemini",
     "base": "https://generativelanguage.googleapis.com/v1beta/openai",
     "env": "GEMINI_API_KEY",
     "model": "gemini-flash-latest",
     "rpm": 10, "rpd": 250},
    {"name": "cerebras",
     "base": "https://api.cerebras.ai/v1",
     "env": "CEREBRAS_API_KEY",
     "model": "gpt-oss-120b",
     "rpm": 5, "rpd": 14400},          # token-capped (1M/day) more than request-capped
    {"name": "openrouter",
     "base": "https://openrouter.ai/api/v1",
     "env": "OPENROUTER_API_KEY",
     "model": "openrouter/free",
     "rpm": 20, "rpd": 50},        # actual cap via provider_rpd()/OPENROUTER_RPD
]


def provider_rpd(p: dict) -> int:
    """Daily request cap for a provider. OpenRouter's is account-dependent
    (50 plain free; 1,000 once the account has ever bought $10 in credits),
    so it is a config knob — OPENROUTER_RPD — not a hardcoded constant."""
    if p["name"] == "openrouter":
        from app.config import cfg_int
        return cfg_int("OPENROUTER_RPD")
    return p["rpd"]


class ProvidersUnavailable(Exception):
    """No provider could serve the call (missing keys, quotas, or all failed)."""


def keys_present() -> dict:
    return {p["name"]: bool(cfg(p["env"]).strip()) for p in PROVIDERS}


def require_any_key() -> None:
    if not any(keys_present().values()):
        raise ProvidersUnavailable(
            "No API keys configured. Fill in .env — key names: "
            + ", ".join(p["env"] for p in PROVIDERS)
            + ". Free keys: console.groq.com/keys, aistudio.google.com/apikey, "
              "cloud.cerebras.ai, openrouter.ai/settings/keys.")


# --- counters (SQLite provider_usage) + pacing -------------------------------

_LAST_CALL: dict = {}
_BAD_KEY: set = set()
_CON = None


def _con():
    global _CON
    if _CON is None:
        _CON = appdb.connect()
    return _CON


def calls_today(provider: str) -> int:
    return appdb.provider_calls_today(_con(), provider)


def _record(provider: str, ok: bool, detail: str = "") -> int:
    return appdb.record_provider(_con(), provider, ok, detail)


def _pace(p: dict) -> None:
    gap = 60.0 / max(1, p["rpm"])
    last = _LAST_CALL.get(p["name"])
    if last is not None:
        wait = gap - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
    _LAST_CALL[p["name"]] = time.monotonic()


# --- transports --------------------------------------------------------------

def _ssl_ctx():
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_NEEDS_CURL: set = set()


def _post_json_curl(url, payload, key, timeout):
    """curl fallback for Cloudflare TLS-fingerprint blocks (403 error 1010).
    The key travels via a curl config on stdin, never argv."""
    import subprocess
    cfg_s = (f'url = "{url}"\n'
             f'header = "Authorization: Bearer {key}"\n'
             'header = "Content-Type: application/json"\n')
    proc = subprocess.run(
        ["curl", "-sS", "--max-time", str(int(timeout)), "-K", "-",
         "-w", "\n%{http_code}", "--data-binary", json.dumps(payload)],
        input=cfg_s.encode(), capture_output=True, timeout=timeout + 10)
    out = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0 or "\n" not in out:
        raise urllib.error.URLError(
            f"curl transport failed: rc={proc.returncode} "
            f"{proc.stderr.decode('utf-8', 'replace')[:150]}")
    body, _, code_s = out.rpartition("\n")
    code = int(code_s.strip() or 0)
    if code >= 400:
        raise urllib.error.HTTPError(url, code, "curl", hdrs=None,
                                     fp=__import__("io").BytesIO(body.encode()))
    return json.loads(body)


def _post_json(url, payload, key, timeout, provider=None):
    if provider in _NEEDS_CURL:
        return _post_json_curl(url, payload, key, timeout)
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            try:
                detail = e.read().decode("utf-8", "replace")
            except Exception:
                detail = ""
            if "1010" in detail or "cloudflare" in detail.lower():
                if provider:
                    _NEEDS_CURL.add(provider)
                    print(f"[providers] {provider}: urllib blocked by edge bot filter "
                          f"— switching to curl transport", file=sys.stderr)
                return _post_json_curl(url, payload, key, timeout)
            raise urllib.error.HTTPError(e.url, e.code, e.msg, e.headers,
                                         __import__("io").BytesIO(detail.encode()))
        raise


# --- the router --------------------------------------------------------------

def chat(system: str, user: str, model: str | None = None,
         temperature: float = DEFAULT_TEMPERATURE, timeout: int = DEFAULT_TIMEOUT,
         max_tokens: int | None = None, provider: str | None = None) -> tuple[str, str]:
    """One routed chat call -> (text, provider_name). Walks PROVIDERS in order;
    per provider: retry once on 429/5xx/timeout, then fall through.
    Raises ProvidersUnavailable when nothing served the call."""
    errors = []
    for p in PROVIDERS:
        if provider and p["name"] != provider:
            continue
        key = cfg(p["env"]).strip()
        if not key:
            errors.append(f"{p['name']}: no key")
            continue
        if p["name"] in _BAD_KEY:
            errors.append(f"{p['name']}: key rejected earlier this run")
            continue
        rpd = provider_rpd(p)
        if calls_today(p["name"]) >= rpd:
            errors.append(f"{p['name']}: daily cap ({rpd}) reached")
            continue
        mdl = model or p["model"]
        payload = {"model": mdl, "temperature": temperature,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}]}
        if max_tokens:
            payload["max_tokens"] = max_tokens
        for attempt in range(ATTEMPTS_PER_PROVIDER):
            _pace(p)
            try:
                data = _post_json(p["base"].rstrip("/") + "/chat/completions",
                                  payload, key, timeout, provider=p["name"])
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:200]
                except Exception:
                    pass
                if e.code in (401, 403):
                    _BAD_KEY.add(p["name"])
                    _record(p["name"], False, f"HTTP {e.code} key rejected")
                    errors.append(f"{p['name']}: HTTP {e.code} (bad key)")
                    break
                _record(p["name"], False, f"HTTP {e.code} {detail}")
                errors.append(f"{p['name']}: HTTP {e.code}")
                if e.code == 429 and attempt + 1 < ATTEMPTS_PER_PROVIDER:
                    ra = e.headers.get("Retry-After") if e.headers else None
                    try:
                        time.sleep(min(float(ra), 60.0) if ra else 15.0)
                    except ValueError:
                        time.sleep(15.0)
                    continue
                if 500 <= e.code < 600 and attempt + 1 < ATTEMPTS_PER_PROVIDER:
                    time.sleep(5.0)
                    continue
                break
            except Exception as e:                       # timeout / network
                _record(p["name"], False, f"{type(e).__name__}: {e}")
                errors.append(f"{p['name']}: {type(e).__name__}")
                if attempt + 1 < ATTEMPTS_PER_PROVIDER:
                    time.sleep(5.0)
                    continue
                break
            msg = (data.get("choices") or [{}])[0].get("message", {})
            out = (msg.get("content") or msg.get("reasoning_content")
                   or msg.get("reasoning") or "").strip()
            n = _record(p["name"], True, f"model={mdl}")
            print(f"[providers] {p['name']} served call (#{n} today, model {mdl})",
                  file=sys.stderr)
            return out, p["name"]
    raise ProvidersUnavailable("all providers failed or unavailable: " + "; ".join(errors))


if __name__ == "__main__":
    if "--check" in sys.argv:
        present = keys_present()
        for p in PROVIDERS:
            print(f"  {p['name']:<11} key={'YES' if present[p['name']] else 'no ':<3} "
                  f"default={p['model']:<28} rpm={p['rpm']:<3} "
                  f"today={calls_today(p['name'])}/{provider_rpd(p)}")
        sys.exit(0 if any(present.values()) else 1)
    elif "--test" in sys.argv:
        try:
            require_any_key()
            out, served = chat("You are a terse assistant.",
                               "Reply with exactly the word: ready", temperature=0.0)
            print(f"router reply via {served}: {out[:80]!r}")
        except ProvidersUnavailable as e:
            sys.exit(f"UNAVAILABLE: {e}")
    else:
        print("usage: python3 -m pipeline.providers --check | --test")
