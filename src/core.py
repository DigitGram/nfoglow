# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""What every part of NfoGlow shares: version and app id, the settings file, the colour themes and palettes,
the table of block characters, and turning a line into plain text. No GTK here."""
import base64
import json
import os
import re
import textwrap
import time
import zlib

import cairo
from gi.repository import GLib

__version__ = "1.1.4"
APP_ID = "io.github.digitgram.NfoGlow"
AUTHOR = "DigitGram"
COPYRIGHT = "© 2026 DigitGram"
WEBSITE = "https://github.com/DigitGram/nfoglow"

BASE_PX = 16          # font size at 100 % zoom
FONT = "DejaVu Sans Mono"
DOS_FONT = "PxPlus IBM VGA 8x16"   # the IBM VGA text font, bundled (data/fonts: CC BY-SA 4.0, by VileR)

CONFIG = os.path.join(GLib.get_user_config_dir(), "nfoglow", "settings.json")
# zoom: the default zoom in percent; 100 % is the natural size (the DOS font then has its 8 x 16 pixels)
# glow: strength 1..5; glow_mode: "soft" (soft edges) or "halo" (neon light behind sharp blocks);
# ramp: colour ramp over the block graphics, top to bottom of each block of art; crt: scanlines (drawn by the UI);
# custom: the colours of the "Custom" theme; recent: last opened files
ZOOM_MIN, ZOOM_MAX = 30, 250   # percent; beyond 250 % nothing gets sharper, only bigger
DEFAULTS = {"theme": "light", "font": FONT, "zoom": 100, "soft": True, "glow": 3,
            "encoding": "auto", "language": "auto", "copy_text_only": True,
            "custom": {"bg": "#ffffff", "text": "#1a1a1a", "art": "#1046a0", "link": "#0b57d0"}, "recent": [],
            "remember_recent": True, "glow_mode": "halo", "ramp": True,
            "ramp_colors": ["#73f0ff", "#4d8cff", "#d94dff"], "crt": False,
            "cycle": False, "cycle_palette": "c64", "pulse": False, "crt_live": False,
            "music": False, "music_dir": "", "music_shuffle": True, "volume": 60, "music_fade": True,
            "random_on_start": False, "cycle_dir": "down", "sidebar": False,
            "stars": False, "scroller": False, "scroller_text": "",
            "wobble": False, "wobble_amount": "mid", "stars_mode": "drift", "music_info": True,
            "maximized": False, "pulse_mode": "beat", "opening": "off", "text_glow": False,
            "neon_flicker": False, "sheen": False, "sparkle": False, "sparkle_amount": "some", "chroma": False,
            "crt_mask": "lines", "smooth": False, "smooth_amount": "mid",
            "update_check": False, "update_last": 0}   # weekly check at start: off until the user switches it on


COLOUR = re.compile(r"#[0-9a-fA-F]{6}")


def load_settings(choices=None):
    """choices: {setting: allowed values} (the UI's lists). A value not among them goes back to its default: a
    hand-edited file or another version's option must not stop the start."""
    try:
        with open(CONFIG, encoding="utf-8") as f:
            saved = json.load(f)
        cfg = {**DEFAULTS, **{k: v for k, v in saved.items() if type(v) is type(DEFAULTS.get(k))}}
        for k, allowed in (choices or {}).items():
            if cfg[k] not in allowed:
                cfg[k] = DEFAULTS[k]
        cfg["recent"] = [p for p in cfg["recent"] if isinstance(p, str)]
        cfg["volume"] = max(0, min(100, cfg["volume"]))   # above 100 the player would amplify
        if not (all(isinstance(c, str) and COLOUR.fullmatch(c)   # a hand-edited file must not stop the start
                    for c in (*cfg["custom"].values(), *cfg["ramp_colors"]))
                and len(cfg["ramp_colors"]) == 3):
            cfg["custom"], cfg["ramp_colors"] = DEFAULTS["custom"], DEFAULTS["ramp_colors"]
        return cfg
    except (OSError, ValueError, AttributeError):
        return dict(DEFAULTS)


def save_settings(cfg):
    try:
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG + ".tmp", "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=1)
        os.replace(CONFIG + ".tmp", CONFIG)   # never leaves a half-written file
    except OSError:
        pass   # settings are a convenience; the viewer keeps working


# ----------------------------------------------------------------------------- update check
# Opt-in and never automatic beyond a notice: one GET to GitHub's "latest release", no data sent, nothing downloaded or installed.
# Updating stays "run the signed install.sh again". Not offered in a Flatpak: its store brings the updates.
RELEASES_API = "https://api.github.com/repos/DigitGram/nfoglow/releases/latest"
UPDATE_INTERVAL = 7 * 24 * 3600


def update_check_offered():
    return not os.path.exists("/.flatpak-info")


def version_tuple(text):
    """"v1.2.1" -> (1, 2, 1); None if it does not look like a version."""
    parts = re.fullmatch(r"v?(\d+(?:\.\d+)*)", text.strip())
    return tuple(int(n) for n in parts[1].split(".")) if parts else None


def latest_release(timeout=5):
    """(version, page) of the newest release, or raises OSError/ValueError (offline, rate limit, odd answer)."""
    import urllib.request
    request = urllib.request.Request(RELEASES_API, headers={"Accept": "application/vnd.github+json", "User-Agent": f"NfoGlow/{__version__}"})
    with urllib.request.urlopen(request, timeout=timeout) as answer:
        data = json.load(answer)
    tag, page = data["tag_name"], data["html_url"]
    if not isinstance(tag, str) or version_tuple(tag) is None or not str(page).startswith("https://github.com/DigitGram/"):
        raise ValueError("unexpected answer")
    return tag.lstrip("v"), page


def newer_release():
    """(version, page) if a newer release exists, else None; raises like latest_release()."""
    version, page = latest_release()
    return (version, page) if version_tuple(version) > version_tuple(__version__) else None


def update_due(cfg, now=None):
    """True when the weekly check is switched on in `cfg` and the last one is over a week ago."""
    return update_check_offered() and cfg["update_check"] and (now or time.time()) - cfg["update_last"] >= UPDATE_INTERVAL


LOOK_PREFIX = "nfoglow:1:"   # the 1 is the format: a later one is read by its own prefix, the old ones stay readable


def look_code(cfg, keys):
    """The look (the settings in keys) as one line of text to share. Compressed JSON in base64, after the prefix.
    A Custom theme brings its colours along, and so does the DOS font (a switch: any other font of yours stays out)."""
    look = {k: cfg[k] for k in keys}
    look["dos_font"] = cfg["font"] == DOS_FONT
    if cfg["theme"] == "custom":
        look["custom"] = cfg["custom"]
    raw = zlib.compress(json.dumps(look, separators=(",", ":")).encode(), 9)
    return LOOK_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def read_look_code(text, keys, choices):
    """The look in a shared code as {setting: value}, or None when the text is no look code. A code comes from
    outside, so it must never break the window: only the settings in keys are taken, each checked like
    load_settings does, and choices ({setting: allowed values}) hold the lists. A value that does not fit (a later
    version's new option, say) is left out, so the setting stays as it is."""
    text = text.strip()
    if not text.startswith(LOOK_PREFIX) or len(text) > 4000:
        return None
    body = text[len(LOOK_PREFIX):]
    try:
        unzip = zlib.decompressobj()
        data = json.loads(unzip.decompress(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)), 20000))
        if unzip.unconsumed_tail or not isinstance(data, dict):
            return None
    except (ValueError, zlib.error):   # a bad base64, zlib or JSON; also bad UTF-8
        return None
    colours = lambda v: all(isinstance(c, str) and COLOUR.fullmatch(c) for c in v)
    look = {}
    for k in keys:
        v = data.get(k)
        if type(v) is not type(DEFAULTS[k]) or (k in choices and v not in choices[k]):
            continue
        if (k == "glow" and not 1 <= v <= 5) or (k == "ramp_colors" and not (len(v) == 3 and colours(v))):
            continue
        look[k] = v
    if isinstance(data.get("dos_font"), bool):
        look["dos_font"] = data["dos_font"]
    custom = data.get("custom")
    if look.get("theme") == "custom" and isinstance(custom, dict) and set(custom) == set(DEFAULTS["custom"]) \
            and colours(custom.values()):
        look["custom"] = custom
    return look or None


def _hex(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))

# name: (background, text, art, link, dark theme; the window itself follows the desktop)
THEMES = {k: (*map(_hex, v[:4]), v[4]) for k, v in {
    "light":    ("#ffffff", "#1a1a1a", "#1046a0", "#0b57d0", False),
    "bw":       ("#ffffff", "#000000", "#000000", "#0000cc", False),   # black on white, as NFOs long looked in plain viewers
    "dark":     ("#14151a", "#d8dae0", "#6ea8ff", "#8ab4ff", True),
    "amber":    ("#0c0802", "#ffb000", "#ff8c00", "#ffd27a", True),
    "terminal": ("#050805", "#3dff70", "#1fbf4f", "#9dffb8", True),
    "paper":    ("#f3ead6", "#3b3226", "#8b3a1e", "#a0522d", False),
    "c64":      ("#352879", "#a59ff0", "#7c70da", "#d2cdff", True),   # the blue screen, its light blue a bit lighter to read
}.items()}
C64_BORDER = "#6c5eb5"   # the light blue border around the C64 screen (the theme shows it around the view)
# the C64 palette ("Pepto") and the bands the C64 demos cycled through their logos
C64 = {k: _hex(v) for k, v in {"black": "#000000", "white": "#ffffff", "red": "#68372b", "cyan": "#70a4b2",
                                "purple": "#6f3d86", "green": "#588d43", "blue": "#352879", "yellow": "#b8c76f",
                                "orange": "#6f4f25", "lightred": "#9a6759", "lightgreen": "#9ad284",
                                "lightblue": "#6c5eb5", "grey": "#959595"}.items()}
C64_CYCLE = [C64[k] for k in ("blue", "lightblue", "cyan", "white", "cyan", "lightblue", "blue", "purple",
                              "lightred", "yellow", "white", "yellow", "lightred", "purple")]
# the classic VGA text-mode palette, in ANSI order (black, red, green, brown, blue, magenta, cyan, grey, then bright)
VGA = [_hex(h) for h in ("#000000", "#aa0000", "#00aa00", "#aa5500", "#0000aa", "#aa00aa", "#00aaaa", "#aaaaaa",
                         "#555555", "#ff5555", "#55ff55", "#ffff55", "#5555ff", "#ff55ff", "#55ffff", "#ffffff")]

FO = cairo.FontOptions()  # fractional advances keep the monospace grid exact
FO.set_hint_metrics(cairo.HINT_METRICS_OFF)
FO.set_hint_style(cairo.HINT_STYLE_NONE)
FO.set_antialias(cairo.ANTIALIAS_GRAY)  # subpixel AA gives coloured fringes on art lines

# U+2580..259F block elements -> ([(x0, y0, x1, y1) as cell fractions], alpha)
_Q = {"UL": (0, 0, .5, .5), "UR": (.5, 0, 1, .5), "LL": (0, .5, .5, 1), "LR": (.5, .5, 1, 1)}
BLOCKS = {0x2580: ([(0, 0, 1, .5)], 1), 0x2588: ([(0, 0, 1, 1)], 1), 0x2590: ([(.5, 0, 1, 1)], 1),
          0x2594: ([(0, 0, 1, .125)], 1), 0x2595: ([(.875, 0, 1, 1)], 1)}
for _n in range(1, 8):
    BLOCKS[0x2580 + _n] = ([(0, 1 - _n / 8, 1, 1)], 1)
for _cp in range(0x2589, 0x2590):
    BLOCKS[_cp] = ([(0, 0, (0x2590 - _cp) / 8, 1)], 1)
for _i, _a in enumerate((.25, .5, .75)):
    BLOCKS[0x2591 + _i] = ([(0, 0, 1, 1)], _a)
for _cp, _q in zip(range(0x2596, 0x25A0), "LL|LR|UL|UL LL LR|UL LR|UL UR LL|UL UR LR|UR|UR LL|UR LL LR".split("|")):
    BLOCKS[_cp] = ([_Q[k] for k in _q.split()], 1)
BLOCKS[0x25A0] = ([(.125, .28, .875, .72)], 1)   # ■, the square dot of CP437: in the art colours like the blocks
SQUARE = 0x25A0

# What DOS drew for the control codes 1..31 (CP437 has symbols there, NFOs use them as bullets and arrows). Tab, line
# feed and carriage return stay what they are; NUL was a blank.
DOS_GLYPHS = "☺☻♥♦♣♠•◘○◙♂♀♪♫☼►◄↕‼¶§▬↨↑↓→←∟↔▲▼"
_CTRL = {0: " ", **{i: DOS_GLYPHS[i - 1] for i in range(1, 32) if i not in (9, 10, 13)}}


def is_dark(bg):
    """Whether a background colour is dark (by its perceived brightness)."""
    return 0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2] < .5


def theme_colors(cfg):
    """(background, text, art, link, dark) of the configured theme; "custom" comes from cfg["custom"]."""
    if cfg.get("theme") == "custom":
        c = {**DEFAULTS["custom"], **cfg.get("custom", {})}
        bg, tx, art, link = (_hex(c[k]) for k in ("bg", "text", "art", "link"))
        return bg, tx, art, link, is_dark(bg)
    return THEMES.get(cfg.get("theme"), THEMES["light"])


# drawn by the font in the art colour: box drawing (═║╔), geometric shapes (▪ ▲ ► ○ ◘, which CP437 has too and
# NFOs use as dots and arrows) and the two CP437 dots ∙ and · (scattered around logos, dotted lines). The block
# elements in between (█ ▀ ░) are in BLOCKS and drawn as rectangles.
GLYPH_ART = {*range(0x2500, 0x2600), 0x2219, 0xB7}


def is_art(ch):
    cp = ord(ch)
    return cp in BLOCKS or cp in GLYPH_ART


def clean_text(lines, dedent=True):
    """Lines without art characters: for "text only" view and for copying.
    Blank runs collapse to one line; dedent keeps the relative indentation, else every line is stripped.
    A line without a single word of two letters or digits ("%    %", "+  +", "o", "\\__ |_/ /": ASCII used as art, logos
    in slashes and underscores) goes too; a rule of one repeated sign ("-----") stays, and so does letter-spaced text
    (four or more single letters with one space between them)."""
    out = []
    for line in lines:
        # art, no-break spaces (CP437 255, used as gaps in the art) and control codes (CP437 ◘ ▬ ...) become spaces
        line = "".join(" " if is_art(ch) or ch == "\xa0" or (ch < " " and ch != "\t") else ch for ch in line).rstrip()
        rule = len(set(line.strip())) == 1 and len(line.strip()) > 3   # "-----"
        spaced = re.search(r"(?<![^\W_])[^\W_]( [^\W_]){3,}(?![^\W_])", line)   # "F o r e v e r": letter-spaced text
        if not re.search(r"[^\W_]{2}", line) and not rule and not spaced:   # "_" is no letter here; a rule "-----" stays
            line = ""
        if not dedent:
            line = line.strip()
        if line or (out and out[-1]):
            out.append(line)
    while out and not out[-1]:
        out.pop()
    text = "\n".join(out)
    return textwrap.dedent(text) if dedent else text
