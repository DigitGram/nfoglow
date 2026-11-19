#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""Builds the app icon and the NFO file icon (SVG + PNG sizes) into data/icons.
Run it after changing the design: python3 tools/make_icons.py"""
from pathlib import Path

import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

APP_ID = "io.github.digitgram.NfoGlow"
OUT = Path(__file__).resolve().parent.parent / "data" / "icons" / "hicolor"
LETTERS = {  # 5 x 5 pixel font, as in the old scene logos
    "N": ["#...#", "##..#", "#.#.#", "#..##", "#...#"],
    "F": ["#####", "#....", "####.", "#....", "#...."],
    "O": [".###.", "#...#", "#...#", "#...#", ".###."],
}


def pixels(word, x0, y0, size):
    """The word as <rect>s, one per pixel (slightly overlapping, so no seams)."""
    out = []
    for i, letter in enumerate(word):
        for r, line in enumerate(LETTERS[letter]):
            for c, on in enumerate(line):
                if on == "#":
                    x, y = x0 + (i * 6 + c) * size, y0 + r * size
                    out.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{size + .3:.2f}" height="{size + .3:.2f}"/>')
    return "".join(out)


def ramp(x0, y, cell, h, color, cells):
    """A row of shade cells (alphas), like ░▒▓█▓▒░."""
    return "".join(f'<rect x="{x0 + i * cell:.2f}" y="{y}" width="{cell + .2:.2f}" height="{h}" fill="{color}" '
                   f'opacity="{a}"/>' for i, a in enumerate(cells))


APP = f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- NfoGlow app icon: glowing pixel letters "NFO" with the classic shade ramp on a dark CRT tile. -->
<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <defs>
    <linearGradient id="tile" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#2a3160"/><stop offset="1" stop-color="#0d0f22"/>
    </linearGradient>
    <linearGradient id="ink" gradientUnits="userSpaceOnUse" x1="0" y1="46" x2="0" y2="74">
      <stop offset="0" stop-color="#b9f0ff"/><stop offset=".55" stop-color="#3fb6ff"/><stop offset="1" stop-color="#2a6bff"/>
    </linearGradient>
    <filter id="glow" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="4"/></filter>
  </defs>
  <rect x="8" y="10" width="112" height="112" rx="26" fill="#000" opacity=".25"/>
  <rect x="8" y="8" width="112" height="112" rx="26" fill="url(#tile)"/>
  <rect x="8.5" y="8.5" width="111" height="111" rx="25.5" fill="none" stroke="#fff" stroke-opacity=".12"/>
  {ramp(24, 26, 10, 7, "#3fb6ff", (.2, .45, .75, 1, 1, .75, .45, .2))}
  <g fill="#3fb6ff" filter="url(#glow)" opacity=".9">{pixels("NFO", 17.25, 46, 5.5)}</g>
  <g fill="url(#ink)">{pixels("NFO", 17.25, 46, 5.5)}</g>
  <g fill="#9aa6d6" opacity=".55">
    <rect x="30" y="88" width="68" height="4" rx="2"/><rect x="38" y="97" width="52" height="4" rx="2"/>
  </g>
</svg>
"""

FILE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- File-type icon for NFO files (text/x-nfo): a page with block-art letters. -->
<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <defs>
    <linearGradient id="page" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#f0efed"/>
    </linearGradient>
  </defs>
  <path d="M32 10H76L104 38V114a8 8 0 0 1-8 8H32a8 8 0 0 1-8-8V18a8 8 0 0 1 8-8z" fill="#000" opacity="0.12"/>
  <path d="M32 8H76L104 36V112a8 8 0 0 1-8 8H32a8 8 0 0 1-8-8V16a8 8 0 0 1 8-8z"
        fill="url(#page)" stroke="#c0bfbc" stroke-width="2"/>
  <path d="M76 8V28a8 8 0 0 0 8 8H104z" fill="#deddda" stroke="#c0bfbc" stroke-width="2" stroke-linejoin="round"/>
  {ramp(36, 46, 7, 5, "#1046a0", (.25, .5, .75, 1, 1, .75, .5, .25))}
  <g fill="#1046a0">{pixels("NFO", 38.5, 58, 3)}</g>
  <g fill="#9a9996"><rect x="38" y="81" width="52" height="4" rx="2"/><rect x="44" y="91" width="40" height="4" rx="2"/>
    <rect x="38" y="101" width="52" height="4" rx="2"/></g>
</svg>
"""


def write(svg, kind, name, sizes):
    path = OUT / "scalable" / kind / f"{name}.svg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg)
    for s in sizes:
        png = OUT / f"{s}x{s}" / kind / f"{name}.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        GdkPixbuf.Pixbuf.new_from_file_at_size(str(path), s, s).savev(str(png), "png", [], [])


if __name__ == "__main__":
    write(APP, "apps", APP_ID, (48, 64, 128, 256, 512))
    write(FILE, "mimetypes", APP_ID + "-nfo", (48, 128))   # app-id prefix: Flatpak exports only such icons
    print("icons written to", OUT)
