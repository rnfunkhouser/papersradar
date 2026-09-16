#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Generate the podcast cover art (app/static/podcast-cover.png) — a radar
motif: dark navy field, concentric rings, a brightening sweep wedge and a few
"paper" blips. Pure stdlib (zlib + struct), deterministic, no fonts.

    python3 tools/make_cover.py [--size 1400]
"""
from __future__ import annotations

import argparse
import math
import struct
import sys
import zlib
from pathlib import Path

BG = (13, 27, 56)            # dark navy
RING = (58, 92, 150)
SWEEP = (26, 86, 219)        # brand #1a56db
BLIP = (224, 236, 255)
BLIPS = [(0.62, 0.30), (0.40, 0.62), (0.71, 0.75), (0.30, 0.38)]


def pixel(x: float, y: float, size: int) -> tuple[int, int, int]:
    cx = cy = size / 2
    dx, dy = x - cx, y - cy
    r = math.hypot(dx, dy) / (size / 2)          # 0 center -> 1 corner-ish
    if r > 0.98:
        return BG
    col = list(BG)
    # sweep wedge: brightness decays behind the leading edge at 45 deg
    ang = (math.atan2(dy, dx) + 2 * math.pi) % (2 * math.pi)
    lead = math.pi / 4
    behind = (lead - ang) % (2 * math.pi)
    if behind < 1.9 and r < 0.92:
        glow = (1 - behind / 1.9) ** 2 * (1 - r * 0.35)
        col = [int(c + (s - c) * glow * 0.85) for c, s in zip(col, SWEEP)]
    # concentric rings every 0.184 of the radius
    for ring_r in (0.184, 0.368, 0.552, 0.736, 0.92):
        if abs(r - ring_r) < 0.004:
            m = 0.75
            col = [int(c + (rr - c) * m) for c, rr in zip(col, RING)]
    # crosshair lines
    if (abs(dx) < size * 0.0015 or abs(dy) < size * 0.0015) and r < 0.92:
        col = [int(c + (rr - c) * 0.45) for c, rr in zip(col, RING)]
    # blips
    for bx, by in BLIPS:
        d = math.hypot(x - bx * size, y - by * size)
        if d < size * 0.013:
            m = max(0.0, 1 - d / (size * 0.013))
            col = [int(c + (b - c) * m) for c, b in zip(col, BLIP)]
    return tuple(col)


def write_png(path: Path, size: int) -> None:
    rows = []
    for y in range(size):
        row = bytearray(b"\x00")                 # filter type 0
        for x in range(size):
            row += bytes(pixel(x + 0.5, y + 0.5, size))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data)))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--size", type=int, default=1400)
    a = ap.parse_args()
    out = Path(__file__).resolve().parent.parent / "app" / "static" / "podcast-cover.png"
    write_png(out, a.size)
    print(f"wrote {out} ({out.stat().st_size} bytes, {a.size}x{a.size})",
          file=sys.stderr)
