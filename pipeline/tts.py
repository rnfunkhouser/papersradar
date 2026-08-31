#!/usr/bin/env python3
"""Gemini TTS + episode audio assembly for the scripted anchor engine.

Each script segment is synthesized separately (bounds request size and gives
exact per-paper chapter offsets), the PCM is concatenated, and ffmpeg encodes
one 64 kbps mono MP3 with ID3 chapter marks (mutagen). Without ffmpeg the
episode degrades to WAV, no chapters — the feed carries either.

The key must be a Google AI Studio key on a project with NO billing account
attached: past the free-tier quota the API errors instead of charging
(the $0 guarantee — docs/PODCAST_DESIGN.md).

    python3 -m pipeline.tts --say "Papers Radar test." --out /tmp/test.mp3
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import ssl
import struct
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import cfg

SAMPLE_RATE = 24_000          # Gemini TTS output: 16-bit mono PCM @ 24 kHz
BYTES_PER_SEC = SAMPLE_RATE * 2
MP3_KBPS = 64
TTS_TIMEOUT = 300

# Read-style directive prefixed to every request; the register itself lives in
# the script text (podcast_script.REGISTER).
STYLE = ("Read the following in a measured, professional news-broadcast "
         "tone at a moderate pace, like a serious morning radio briefing: ")


class TTSError(Exception):
    def __init__(self, msg: str, code: int = 0, retry_delay: float = 0.0):
        super().__init__(msg)
        self.code = code
        self.retry_delay = retry_delay


def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


# The free-tier TTS preview quota is TEN requests per day per model
# (GenerateRequestsPerDayPerProjectPerModel-FreeTier, measured 2026-08-31),
# with ~3 requests/min. So an episode must fit in a handful of calls: the
# script is batched into chunks of whole segments (chunk_segments), calls are
# paced, and 429s retry with the server's retryDelay.
CHUNK_MAX_CHARS = 3500
PACE_SEC = 21              # ~3 requests/min with margin
RETRIES_429 = 2

_last_call = 0.0


def _pace():
    import time
    global _last_call
    wait = PACE_SEC - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def synthesize(text: str, voice: str | None = None) -> bytes:
    """One paced TTS call (429s retried) -> raw PCM (s16le mono 24 kHz)."""
    import time
    for attempt in range(RETRIES_429 + 1):
        _pace()
        try:
            return _request(text, voice)
        except TTSError as e:
            if e.code == 429 and attempt < RETRIES_429:
                time.sleep(max(e.retry_delay, 30.0))
                continue
            raise


def _request(text: str, voice: str | None) -> bytes:
    key = cfg("GEMINI_API_KEY").strip()
    if not key:
        raise TTSError("GEMINI_API_KEY not configured")
    model = cfg("GEMINI_TTS_MODEL")
    url = (f"{cfg('GEMINI_TTS_BASE').rstrip('/')}/v1beta/models/"
           f"{model}:generateContent")
    payload = {
        "contents": [{"parts": [{"text": STYLE + text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {
                "voiceName": voice or cfg("PODCAST_ANCHOR_VOICE")}}},
        },
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=TTS_TIMEOUT,
                                    context=_ssl_ctx()) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        if e.code == 404:
            raise TTSError(
                f"model {model!r} not found — TTS preview names churn; see "
                f"docs/PODCAST_RUNBOOK.md §TTS to list live models "
                f"({detail[:200]})", code=404) from e
        if e.code == 429:
            m = re.search(r'retryDelay[^0-9]*([0-9.]+)s', detail)
            quota = re.search(r'"quotaId":\s*"([^"]+)"', detail)
            raise TTSError(
                "free-tier quota hit (HTTP 429"
                + (f", {quota.group(1)}" if quota else "") + ")",
                code=429,
                retry_delay=float(m.group(1)) if m else 0.0) from e
        raise TTSError(f"HTTP {e.code}: {detail[:300]}", code=e.code) from e
    except Exception as e:
        raise TTSError(f"{type(e).__name__}: {e}") from e
    try:
        part = data["candidates"][0]["content"]["parts"][0]["inlineData"]
        return base64.b64decode(part["data"])
    except (KeyError, IndexError, TypeError) as e:
        raise TTSError(f"unexpected response shape: {str(data)[:300]}") from e


def chunk_segments(segments: list[dict],
                   max_chars: int = CHUNK_MAX_CHARS) -> list[list[dict]]:
    """Group whole script segments into as few TTS requests as fit the char
    budget (the 10-requests/day free tier is the scarce resource). A single
    over-budget segment still gets its own chunk."""
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    n = 0
    for seg in segments:
        length = len(seg["text"])
        if cur and n + length > max_chars:
            chunks.append(cur)
            cur, n = [], 0
        cur.append(seg)
        n += length
    if cur:
        chunks.append(cur)
    return chunks


def synthesize_script(segments: list[dict]) -> tuple[list[bytes], list[dict]]:
    """Whole script -> (chunk_pcms, chapters). Chapters are exact at chunk
    boundaries and estimated by character proportion inside a chunk."""
    chunks = chunk_segments(segments)
    pcms: list[bytes] = []
    chapters: list[dict] = []
    offset = 0
    for chunk in chunks:
        pcm = synthesize("\n\n".join(s["text"] for s in chunk))
        total = sum(len(s["text"]) for s in chunk) or 1
        pos = 0
        for s in chunk:
            start = offset + int(len(pcm) * pos / total)
            chapters.append({"start_sec": start // BYTES_PER_SEC,
                             "title": s["title"]})
            pos += len(s["text"]) + 2
        offset += len(pcm)
        pcms.append(pcm)
    return pcms, chapters


# --- episode assembly ---------------------------------------------------------

def assemble(segment_pcms: list[bytes], titles: list[str], out_stem: Path,
             chapters: list[dict] | None = None) -> dict:
    """Concatenate PCM -> one episode file. Returns {"path", "mime", "bytes",
    "duration_sec", "chapters"}. Chapters default to one per PCM entry
    (aligned to its start); pass precomputed `chapters` when PCM chunks and
    chapter marks don't correspond 1:1 (synthesize_script)."""
    if chapters is None:
        chapters = []
        offset = 0
        for pcm, title in zip(segment_pcms, titles):
            chapters.append({"start_sec": offset // BYTES_PER_SEC,
                             "title": title})
            offset += len(pcm)
    pcm_all = b"".join(segment_pcms)
    duration = round(len(pcm_all) / BYTES_PER_SEC)
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("ffmpeg"):
        path = out_stem.with_suffix(".mp3")
        _encode_mp3(pcm_all, path)
        _write_id3_chapters(path, chapters, duration)
        mime = "audio/mpeg"
    else:
        path = out_stem.with_suffix(".wav")
        path.write_bytes(_wav(pcm_all))
        mime = "audio/wav"
    return {"path": path, "mime": mime, "bytes": path.stat().st_size,
            "duration_sec": duration, "chapters": chapters}


def _encode_mp3(pcm: bytes, path: Path) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le",
         "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "-",
         "-b:a", f"{MP3_KBPS}k", str(path)],
        input=pcm, capture_output=True)
    if proc.returncode != 0 or not path.exists():
        raise TTSError("ffmpeg encode failed: "
                       + proc.stderr.decode("utf-8", "replace")[:300])


def _write_id3_chapters(path: Path, chapters: list[dict],
                        duration_sec: int) -> None:
    """Per-paper chapter marks (ID3v2 CHAP/CTOC) so podcast apps can skip
    between papers. Best-effort — a chapterless episode still plays."""
    try:
        from mutagen.id3 import ID3, CHAP, CTOC, TIT2, CTOCFlags
        try:
            tags = ID3(str(path))
        except Exception:
            tags = ID3()
        ids = []
        for i, ch in enumerate(chapters):
            end = (chapters[i + 1]["start_sec"] if i + 1 < len(chapters)
                   else duration_sec)
            cid = f"chp{i}"
            ids.append(cid)
            tags.add(CHAP(element_id=cid, start_time=ch["start_sec"] * 1000,
                          end_time=end * 1000,
                          sub_frames=[TIT2(encoding=3, text=[ch["title"]])]))
        tags.add(CTOC(element_id="toc", flags=CTOCFlags.TOP_LEVEL
                      | CTOCFlags.ORDERED, child_element_ids=ids,
                      sub_frames=[TIT2(encoding=3, text=["Papers"])]))
        tags.save(str(path))
    except Exception as e:
        print(f"[tts] chapter tags skipped: {e}", file=sys.stderr)


def _wav(pcm: bytes) -> bytes:
    hdr = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE",
                      b"fmt ", 16, 1, 1, SAMPLE_RATE, BYTES_PER_SEC, 2, 16,
                      b"data", len(pcm))
    return hdr + pcm


def wav_to_pcm(data: bytes) -> bytes:
    """Strip a 16-bit mono WAV container -> raw PCM (nlm engine downloads
    WAV). Falls back to returning the payload past a standard 44-byte header."""
    import io
    import wave
    try:
        with wave.open(io.BytesIO(data)) as w:
            return w.readframes(w.getnframes())
    except Exception:
        return data[44:] if data[:4] == b"RIFF" else data


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--say", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--voice")
    a = ap.parse_args()
    pcm = synthesize(a.say, a.voice)
    info = assemble([pcm], ["Test"], Path(a.out).with_suffix(""))
    print(f"wrote {info['path']} ({info['bytes']} bytes, "
          f"{info['duration_sec']}s, {info['mime']})")
