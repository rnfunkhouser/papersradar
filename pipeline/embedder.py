#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Embedding provider abstraction. Every stored vector carries the embedder
NAME and DIM (see seed_embeddings / paper_embeddings), so switching embedders
never corrupts existing data — shortlisting only compares same-embedder
vectors, and a config flip + backfill run migrates cleanly.

Active embedders:
  nemotron-3-embed-1b   OpenRouter nvidia/nemotron-3-embed-1b:free (2048-d,
                        API, 64 texts/request, OPENROUTER_RPD req/day — 50 on
                        a plain free account, 1,000 once the account has ever
                        bought $10 credits) — DEFAULT. Ported from the
                        validated free_stack/api_embed.py.
  qwen3-embedding-0.6b  local sentence-transformers Qwen/Qwen3-Embedding-0.6B
                        (1024-d). NOT for the 1 GB server today — enable via
                        EMBEDDER= once the box has RAM for torch.

Embedding input is the exact harvest.py construction: "title. abstract"[:2000].
Vectors are L2-normalized float32.
"""
from __future__ import annotations

import json
import math
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import cfg
from pipeline import providers


class QuotaExceeded(Exception):
    """Daily free-tier cap hit — resume next run (state is in the DB)."""


def paper_text(title: str, abstract: str) -> str:
    return ((title or "") + ". " + (abstract or "")).strip()[:2000]


def _normalize(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class NemotronEmbedder:
    name = "nemotron-3-embed-1b"
    model_id = "nvidia/nemotron-3-embed-1b:free"
    base = "https://openrouter.ai/api/v1"
    batch = 64
    rpm = 20
    _last = 0.0

    @property
    def rpd(self) -> int:
        """OpenRouter daily request cap — account-dependent (50 plain free;
        1,000 after a one-time $10 credit purchase), so a config knob."""
        from app.config import cfg_int
        return cfg_int("OPENROUTER_RPD")

    def _key(self) -> str:
        key = cfg("OPENROUTER_API_KEY").strip()
        if not key:
            raise providers.ProvidersUnavailable(
                "OPENROUTER_API_KEY missing (openrouter.ai/settings/keys)")
        return key

    def _pace(self):
        wait = 60.0 / self.rpm - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """One batched request per `batch` texts, RPM-paced, cap-aware."""
        key = self._key()
        out = []
        for i in range(0, len(texts), self.batch):
            if providers.calls_today("openrouter") >= self.rpd:
                raise QuotaExceeded(
                    f"OpenRouter daily cap ({self.rpd} requests) reached — "
                    "the embed stage resumes tomorrow from the DB")
            chunk = [t if (t or "").strip() else " " for t in texts[i:i + self.batch]]
            body = json.dumps({"model": self.model_id, "input": chunk}).encode()
            req = urllib.request.Request(
                self.base + "/embeddings", data=body, method="POST",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"})
            data = None
            for attempt in range(4):
                self._pace()
                try:
                    with urllib.request.urlopen(req, timeout=120,
                                                context=_ssl_ctx()) as r:
                        data = json.load(r)
                    break
                except urllib.error.HTTPError as e:
                    if e.code in (401, 403):
                        providers._record("openrouter", False, f"HTTP {e.code} key rejected")
                        raise providers.ProvidersUnavailable(
                            f"OpenRouter key rejected (HTTP {e.code})")
                    if e.code == 429 and attempt < 3:
                        ra = (e.headers or {}).get("Retry-After")
                        try:
                            time.sleep(min(float(ra), 120.0) if ra else 30.0 * (attempt + 1))
                        except ValueError:
                            time.sleep(30.0 * (attempt + 1))
                        continue
                    detail = ""
                    try:
                        detail = e.read().decode("utf-8", "replace")[:200]
                    except Exception:
                        pass
                    providers._record("openrouter", False, f"HTTP {e.code} {detail}")
                    raise QuotaExceeded(
                        f"OpenRouter /embeddings HTTP {e.code}: {detail}")
                except Exception as e:
                    if attempt < 3:
                        time.sleep(10.0)
                        continue
                    raise QuotaExceeded(
                        f"OpenRouter /embeddings failed: {type(e).__name__}: {e}")
            rows = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
            if len(rows) != len(chunk):
                raise QuotaExceeded("response count mismatch from /embeddings")
            out.extend(_normalize(d["embedding"]) for d in rows)
            n = providers._record("openrouter", True, f"embeddings x{len(chunk)}")
            print(f"[embed] openrouter request ok ({len(out)}/{len(texts)} texts; "
                  f"call #{n} today)", file=sys.stderr)
        return out


class LocalQwenEmbedder:
    """Local Qwen3-Embedding-0.6B — future swap-in when the server has RAM.
    Lazy import so the default path never touches torch."""
    name = "qwen3-embedding-0.6b"

    def __init__(self):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError(
                "sentence-transformers/torch not installed — the local embedder "
                "is reserved for a bigger server; keep EMBEDDER=nemotron-3-embed-1b"
            ) from e
        self._model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(texts, normalize_embeddings=True, batch_size=16)
        return [v.tolist() for v in vecs]


def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def get_embedder(name: str | None = None):
    name = name or cfg("EMBEDDER")
    if name == NemotronEmbedder.name:
        return NemotronEmbedder()
    if name == LocalQwenEmbedder.name:
        return LocalQwenEmbedder()
    raise ValueError(f"unknown EMBEDDER: {name}")


# --- vector <-> blob ---------------------------------------------------------

def pack(vec) -> bytes:
    import numpy as np
    return np.asarray(vec, dtype=np.float32).tobytes()


def unpack(blob: bytes):
    import numpy as np
    return np.frombuffer(blob, dtype=np.float32)
