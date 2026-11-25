# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""Layers that belong to the window, not to the NFO: the CRT look (scanlines, vignette, the living tube's roll bar,
flicker and round corners) and the demoscene sine scroller. The window keeps them in place while the NFO scrolls;
exports draw the CRT look over the whole page."""
import math
import os
import time
import unicodedata

import cairo

from core import C64_CYCLE


def mask_tile(kind):
    """The colour mask of a tube as rows of (r, g, b) factors per pixel, multiplied with the picture: the dots of a
    shadow mask in staggered triads, or the red, green and blue stripes of an aperture grille (Trinitron)."""
    red, green, blue = (1, .62, .62), (.62, 1, .62), (.62, .62, 1)
    if kind == "stripes":
        return [[red, green, blue]]
    gap = (.5, .5, .5)
    dots = [red, red, green, green, blue, blue]
    shifted = dots[3:] + dots[:3]
    return [dots, dots, [gap] * 6, shifted, shifted, [gap] * 6]


def paint_mask(cr, w, h, kind):
    """The colour mask over w x h of what cr holds (for the export; the window lets the graphics card do it)."""
    tile = mask_tile(kind)
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, len(tile[0]), len(tile))
    data = s.get_data()
    for y, row in enumerate(tile):
        for x, (r, g, b) in enumerate(row):
            i = y * s.get_stride() + x * 4
            data[i:i + 4] = bytes((round(b * 255), round(g * 255), round(r * 255), 255))
    s.mark_dirty()
    pattern = cairo.SurfacePattern(s)
    pattern.set_extend(cairo.EXTEND_REPEAT)
    pattern.set_filter(cairo.FILTER_NEAREST)
    cr.save()
    cr.set_operator(cairo.OPERATOR_MULTIPLY)
    cr.set_source(pattern)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    cr.restore()


def crt_static(cr, w, h, round_corners=False, pattern="lines"):
    """The still part of the tube: scanlines every third pixel row (or, for the export, a colour mask: pattern
    "dots" or "stripes"; None draws neither, the window lays the mask on with the graphics card), a vignette and,
    for the "living" tube, round corners (they fake the curved glass without bending the picture, so clicks stay
    where they are). The window draws this once; only the roll bar and the flicker move, and those are just shifted
    and faded, not redrawn."""
    if pattern == "lines":
        cr.set_source_rgba(0, 0, 0, .28)
        for y in range(0, h, 3):
            cr.rectangle(0, y, w, 1)
        cr.fill()
    elif pattern:
        paint_mask(cr, w, h, pattern)
    vignette = cairo.RadialGradient(w / 2, h / 2, min(w, h) * .35, w / 2, h / 2, max(w, h) * .75)
    vignette.add_color_stop_rgba(0, 0, 0, 0, 0)
    vignette.add_color_stop_rgba(1, 0, 0, 0, .5)
    cr.set_source(vignette)
    cr.paint()
    if not round_corners:
        return
    r = min(w, h) * .06   # dark outside a rounded rectangle: the edge of the tube
    cr.save()
    cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    cr.rectangle(0, 0, w, h)
    cr.new_sub_path()
    cr.arc(w - r, r, r, -math.pi / 2, 0)
    cr.arc(w - r, h - r, r, 0, math.pi / 2)
    cr.arc(r, h - r, r, math.pi / 2, math.pi)
    cr.arc(r, r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()
    cr.set_source_rgba(0, 0, 0, .92)
    cr.fill()
    cr.restore()


def crt_roll_y(t, h):
    """Where the roll bar is: down the screen every ~11 s."""
    return ((t * .12) % 1.3 - .15) * h


def crt_roll_bar(cr, w, height):
    bar = cairo.LinearGradient(0, 0, 0, height)
    for stop, a in ((0, 0), (.5, .07), (1, 0)):
        bar.add_color_stop_rgba(stop, 1, 1, 1, a)
    cr.set_source(bar)
    cr.rectangle(0, 0, w, height)
    cr.fill()


def crt_flicker(t):
    """How dark the flicker makes the picture right now: irregular, but never jumpy."""
    return max(0.0, .025 + .025 * math.sin(t * 61) * math.sin(t * 17))


def scroller_size(h):
    """Letter size of the sine scroller for a window h pixels high; its strip is 3.4 times as high."""
    return max(18, min(42, h / 14))


def scroller_letters(w, h, t, text, size):
    """The demoscene sine scroller along the bottom of an area w x h, as (letter, x, y, colour) of the letters in
    view: each rides its own wave and has its own colour from the C64 cycle (drawn by gpu.scroller)."""
    advance = size * .62
    widths = [advance * (2 if unicodedata.east_asian_width(ch) in "WF" else 1) for ch in text]   # CJK letters are wide
    start = w - (t * 140) % (w + sum(widths))   # 140 px a second, from the right edge to gone on the left
    base = h - size * 2.2
    x = start
    for i, ch in enumerate(text):
        if -widths[i] <= x <= w and ch != " ":
            yield ch, x, base + size * .6 * math.sin(x / 90 + t * 3), C64_CYCLE[(i + int(t * 8)) % len(C64_CYCLE)]
        x += widths[i]


LOADER_END = 2.4   # seconds of the tape loader on opening
OPENING_END = {"loader": LOADER_END, "crt": 1.1, "dither": 1.6, "neon": 1.7, "rain": 2.4, "fade": .3}   # seconds of the other effects
def opening_end(kind, name=""):
    """How many seconds the effect on opening runs (the DOS boot has a script of its own)."""
    if kind != "dos":
        return OPENING_END[kind]
    _kind, start, _text, seconds = _dos_steps(name, (0, 0))[-1]   # the last command typed, Enter, a moment
    return start + seconds + .65


def _dos_83(name):
    """The file name the way DOS 6 shows it: upper case, eight letters and a three letter extension (long names are
    cut to six letters and ~1)."""
    stem, ext = os.path.splitext(name)
    clean = lambda part: "".join(ch if ch.isalnum() and ch.isascii() or ch in "_-!#$%&'()@^{}~" else "_"
                                 for ch in part.upper().replace(" ", ""))
    stem, ext = clean(stem) or "NFO", clean(ext.lstrip("."))[:3]
    return (stem if len(stem) <= 8 else stem[:6] + "~1"), ext


def _dos_steps(name, info):
    """The DOS boot as [(kind, start, text, seconds)]: "line" shows a line of output at start, "type" types a command
    after the prompt in the given seconds. Boot message, VER, DIR of the file, TYPE of the file. info: (file size,
    modification time) for the listing."""
    stem, ext = _dos_83(name)
    size, mtime = info
    when = time.localtime(mtime or time.time())
    hour = when.tm_hour % 12 or 12
    listing = (f"{stem:<8} {ext:<3} {size:>13,} {when.tm_mon:02d}-{when.tm_mday:02d}-{when.tm_year % 100:02d} "
               f"{hour:>2}:{when.tm_min:02d}{'a' if when.tm_hour < 12 else 'p'}")
    steps, t = [], .15

    def out(*lines, wait=.0):
        nonlocal t
        for text in lines:
            steps.append(("line", t, text, 0.0))
        t += wait

    def command(text, pause=.22):
        nonlocal t
        seconds = max(.25, min(.9, len(text) / 22))   # about 22 letters a second, a long one in under a second
        steps.append(("type", t, text, seconds))
        t += seconds + pause

    out("Starting MS-DOS...", wait=.4)
    out("", "HIMEM is testing extended memory...done.", "", wait=.4)
    command("VER")
    out("", "MS-DOS Version 6.22", "", wait=.25)
    command(f"DIR {stem}.{ext}" if ext else f"DIR {stem}")
    out("", " Volume in drive C is NFOGLOW", " Directory of C:\\", "", listing, f"        1 file(s) {size:>16,} bytes",
        f"{412319744:>26,} bytes free", "", wait=.3)
    command(f"TYPE {stem}.{ext}" if ext else f"TYPE {stem}", pause=.3)
    return steps


def dos_screen(t, name, info=(0, 0)):
    """The DOS boot at t seconds: (lines, cursor (row, column) or None)."""
    prompt, lines, cursor = "C:\\>", [], None
    for kind, start, text, seconds in _dos_steps(name, info):
        if t < start:
            break
        if kind == "line":
            lines.append(text)
            continue
        typed = len(text) if t >= start + seconds else int((t - start) / seconds * len(text))
        lines.append(prompt + text[:typed])
        if typed < len(text):
            return lines, (len(lines) - 1, len(prompt) + typed)   # still typing: the cursor stays on
        cursor = (len(lines) - 1, len(prompt) + typed)
    if cursor and t >= opening_end("dos", name) - .35:
        lines.append("")   # Enter after the last command
        return lines, (len(lines) - 1, 0)
    return lines, (cursor if int(t * 2.5) % 2 == 0 else None) if cursor else None


def loader_screen(t, name):
    """The C64 loader at t seconds: (lines of text, cursor (row, column) or None, stripes in the border).
    READY., the LOAD command typed, SEARCHING, LOADING with the coloured stripes of a tape loader, READY. again."""
    stem = "".join(ch for ch in os.path.splitext(name)[0].upper() if " " <= ch <= "~")[:16] or "NFO"   # 16 like on a disk
    typed = f'LOAD"{stem}",8,1'
    blink = (1 if int(t * 3.3) % 2 == 0 else None)   # the cursor blinks while it waits
    lines = ["READY."]
    if t < .35:
        return lines, blink and (1, 0), False
    shown = min(len(typed), int((t - .35) / .6 * len(typed)) + 1)
    lines.append(typed[:shown])
    if t < .95:
        return lines, (1, shown), False
    lines += ["", f"SEARCHING FOR {stem}"]
    if t < 1.15:
        return lines, None, False
    lines.append("LOADING")
    if t < 2.05:
        return lines, None, True
    lines.append("READY.")
    return lines, blink and (len(lines), 0), False


# An 8 x 8 pixel font of our own in the style of the old home computers (two pixels wide strokes), for the tape
# loader. Rows top to bottom, "#" a pixel; the eighth row stays empty. Characters it lacks are shown as "?".
_FONT8 = r"""
A ..####.. .##..##. .##..##. .######. .##..##. .##..##. .##..##.
B .#####.. .##..##. .##..##. .#####.. .##..##. .##..##. .#####..
C ..####.. .##..##. .##..... .##..... .##..... .##..##. ..####..
D .####... .##.##.. .##..##. .##..##. .##..##. .##.##.. .####...
E .######. .##..... .##..... .####... .##..... .##..... .######.
F .######. .##..... .##..... .####... .##..... .##..... .##.....
G ..####.. .##..##. .##..... .##.###. .##..##. .##..##. ..####..
H .##..##. .##..##. .##..##. .######. .##..##. .##..##. .##..##.
I ..####.. ...##... ...##... ...##... ...##... ...##... ..####..
J ...####. ....##.. ....##.. ....##.. ....##.. .##.##.. ..###...
K .##..##. .##.##.. .####... .###.... .####... .##.##.. .##..##.
L .##..... .##..... .##..... .##..... .##..... .##..... .######.
M .##...## .###.### .####### .##.#.## .##...## .##...## .##...##
N .##..##. .###.##. .######. .######. .##.###. .##..##. .##..##.
O ..####.. .##..##. .##..##. .##..##. .##..##. .##..##. ..####..
P .#####.. .##..##. .##..##. .#####.. .##..... .##..... .##.....
Q ..####.. .##..##. .##..##. .##..##. .##..##. ..####.. ....###.
R .#####.. .##..##. .##..##. .#####.. .####... .##.##.. .##..##.
S ..####.. .##..##. .##..... ..####.. .....##. .##..##. ..####..
T .######. ...##... ...##... ...##... ...##... ...##... ...##...
U .##..##. .##..##. .##..##. .##..##. .##..##. .##..##. ..####..
V .##..##. .##..##. .##..##. .##..##. .##..##. ..####.. ...##...
W .##...## .##...## .##...## .##.#.## .####### .###.### .##...##
X .##..##. .##..##. ..####.. ...##... ..####.. .##..##. .##..##.
Y .##..##. .##..##. .##..##. ..####.. ...##... ...##... ...##...
Z .######. .....##. ....##.. ...##... ..##.... .##..... .######.
0 ..####.. .##..##. .##.###. .###.##. .##..##. .##..##. ..####..
1 ...##... ..###... ...##... ...##... ...##... ...##... .######.
2 ..####.. .##..##. .....##. ....##.. ..##.... .##..... .######.
3 ..####.. .##..##. .....##. ...###.. .....##. .##..##. ..####..
4 ....##.. ...###.. ..####.. .##.##.. .######. ....##.. ....##..
5 .######. .##..... .#####.. .....##. .....##. .##..##. ..####..
6 ..####.. .##..... .##..... .#####.. .##..##. .##..##. ..####..
7 .######. .....##. ....##.. ...##... ..##.... ..##.... ..##....
8 ..####.. .##..##. .##..##. ..####.. .##..##. .##..##. ..####..
9 ..####.. .##..##. .##..##. ..#####. .....##. .....##. ..####..
. ........ ........ ........ ........ ........ ...##... ...##...
, ........ ........ ........ ........ ...##... ...##... ..##....
" .##.##.. .##.##.. .##.##.. ........ ........ ........ ........
' ...##... ...##... ..##.... ........ ........ ........ ........
: ........ ...##... ...##... ........ ...##... ...##... ........
! ...##... ...##... ...##... ...##... ........ ........ ...##...
? ..####.. .##..##. .....##. ....##.. ...##... ........ ...##...
* ........ .##..##. ..####.. .######. ..####.. .##..##. ........
- ........ ........ ........ .######. ........ ........ ........
_ ........ ........ ........ ........ ........ ........ ########
/ ......## .....##. ....##.. ...##... ..##.... .##..... ##......
( ....##.. ...##... ..##.... ..##.... ..##.... ...##... ....##..
) ..##.... ...##... ....##.. ....##.. ....##.. ...##... ..##....
+ ........ ...##... ...##... .######. ...##... ...##... ........
= ........ ........ .######. ........ .######. ........ ........
"""
FONT8 = {row[0]: row[2:].split() for row in _FONT8.strip("\n").split("\n")}


def paint_c64_screen(cr, lines, cursor, ink, paper):
    """The C64 screen in its own pixels: 320 x 200, 40 x 25 characters of 8 x 8, lines from the top, the cursor
    a block at (row, column)."""
    cr.set_source_rgb(*paper)
    cr.paint()
    cr.set_source_rgb(*ink)
    for row, text in enumerate(lines[:25]):
        for col, ch in enumerate(text[:40]):
            if ch == " ":
                continue
            for y, bits in enumerate(FONT8.get(ch, FONT8["?"])):
                x = bits.find("#")
                while x >= 0:   # a run of set pixels is one rectangle
                    end = x
                    while end < 8 and bits[end] == "#":
                        end += 1
                    cr.rectangle(col * 8 + x, row * 8 + y, end - x, 1)
                    x = bits.find("#", end)
    if cursor:
        cr.rectangle(cursor[1] * 8, cursor[0] * 8, 8, 8)
    cr.fill()
