#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Generate PNG logo assets from the Echo mark (option B, 2026-08-09 logo choice).

The canonical mark is the inline SVG in app/templates/base.html; this renders
pixel equivalents for contexts that can't take SVG (email clients, legacy
favicon, apple-touch). Pillow-only (dev dependency, not in server requirements)
— arcs get round caps by stamping cap circles at arc endpoints.

Usage: python3 tools/gen_logo_assets.py   (writes into app/static/)
"""
import math
from PIL import Image, ImageDraw

BRAND = (37, 99, 235, 255)          # --brand light #2563eb
S = 8                                # supersample factor

def cap(d, cx, cy, r, color):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)

def echo(size, stroke, dot_r, radii_alpha, pad_ratio=0.0):
    """Draw the Echo mark: centre dot + arcs with a gap at the bottom.
    radii_alpha: list of (radius_frac, alpha) outward."""
    px = size * S
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = px / 2
    unit = px * (1 - pad_ratio) / 64.0   # design grid = 64
    cy_design = cy + 0 * unit
    # centre dot
    cap(d, cx, cy_design, dot_r * unit, BRAND)
    w = stroke * unit
    for r_frac, alpha in radii_alpha:
        r = r_frac * unit
        color = BRAND[:3] + (int(255 * alpha),)
        bbox = [cx - r, cy_design - r, cx + r, cy_design + r]
        # gap at bottom: draw clockwise 135deg -> 45deg (the long way, 270deg)
        d.arc(bbox, start=135, end=45, fill=color, width=int(w))
        for a in (135, 45):
            cap(d, cx + r * math.cos(math.radians(a)),
                   cy_design + r * math.sin(math.radians(a)), w / 2, color)
    return img.resize((size, size), Image.LANCZOS)

def write(img, name):
    img.save(f"app/static/{name}")
    print("wrote app/static/" + name, img.size)

# email header: full two-arc mark, generous size, displayed ~28px
write(echo(112, stroke=4, dot_r=4.5, radii_alpha=[(17, 1.0), (25.5, 0.55)]), "logo-email.png")
# legacy favicon: simplified 16px-safe variant (dot + one arc, heavier stroke)
write(echo(32, stroke=7, dot_r=8, radii_alpha=[(25.5, 1.0)]), "favicon-32.png")
# apple-touch: full mark with padding
write(echo(180, stroke=4, dot_r=4.5, radii_alpha=[(17, 1.0), (25.5, 0.55)], pad_ratio=0.12), "apple-touch-icon.png")
