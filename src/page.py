# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""The page: one NFO laid out in a monospace grid and drawn with cairo. Block characters become exact rectangles
(cached as an image and only coloured per frame), text stays crisp, and the effects that belong to the NFO
(glow, colour ramp, colour cycling, stars, modem build-up) are drawn here too.
This cairo drawing makes the PNG/PDF export; the window shows the same picture through gpu.py, which places the
images made here (blocks, glow) and the shared numbers (bars, cycling, pulse) on the graphics card."""
import math
import random
import re

import cairo
import gi
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import GLib, Pango, PangoCairo  # noqa: E402

from core import (BASE_PX, BLOCKS, C64_CYCLE, DEFAULTS, FO, FONT, GLYPH_ART, SQUARE, VGA, ZOOM_MAX, ZOOM_MIN, _CTRL,  # noqa: E402
                  _hex, clean_text, is_art, theme_colors)
from decode import decode, is_ansi, parse_ansi, read  # noqa: E402
from overlays import crt_static  # noqa: E402


def _add_dos_font():
    """Make the bundled DOS font known to Pango (installed: next to the code; in a checkout: data/fonts). Only for
    NfoGlow, it is not installed for other programs. False when the file is missing."""
    from pathlib import Path
    here = Path(__file__).resolve().parent
    path = next((p for p in (here / "fonts" / "PxPlus_IBM_VGA_8x16.ttf",
                             here.parent / "data" / "fonts" / "PxPlus_IBM_VGA_8x16.ttf") if p.is_file()), None)
    if path is None:
        return False
    try:
        return PangoCairo.FontMap.get_default().add_font_file(str(path))
    except (AttributeError, GLib.Error):   # Pango before 1.56: through fontconfig
        import ctypes
        import ctypes.util
        fc = ctypes.util.find_library("fontconfig")
        if not fc or not ctypes.CDLL(fc).FcConfigAppFontAddFile(None, str(path).encode()):
            return False
        try:
            PangoCairo.FontMap.get_default().config_changed()
        except AttributeError:
            pass
        return True


DOS_FONT_READY = _add_dos_font()

# web and e-mail; the lookbehind starts an address only at the start of a word, else a long line takes minutes
LINK_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"']+|(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.I)   # old NFOs shout: WWW.GROUP.COM
WOBBLE = {"low": .15, "mid": .3, "high": .45}   # how far the logo sways, in character heights (more is no logo)
SMOOTH = {"low": (3, 0), "mid": (3, 3), "high": (3, 10)}   # (Scale2x steps, blur passes): how smooth the edges get
MAX_IMAGE = 32767              # cairo cannot make an image wider or higher than this


class TooBig(OSError):
    """The page is too big for a PNG (a PDF has no such limit)."""


def flicker(t):
    """How bright the neon sign is at t seconds (1 = fully): mostly steady, now and then a short stutter."""
    period = 3.3
    k = int(t // period)
    if (math.sin(k * 12.9898) * 43758.5453) % 1 < .4:   # no stutter in this stretch
        return 1.0
    local = t - k * period - (math.sin(k * 78.233) * 43758.5453) % 1 * (period - .6)
    return (.15, .6, .25, .85, .4, .7)[int(local * 12)] if 0 <= local < .5 else 1.0


class Page:
    """One rendered document. cfg is the shared settings dict (theme, font, soft, copy_text_only)."""

    def __init__(self, cfg, zoom=1.0):
        self.cfg, self.zoom = cfg, zoom
        self.time, self.level = 0.0, None   # animation clock (s) and music loudness 0..1 (None: no music)
        self.reveal = None                  # modem build-up: how many characters are shown so far (None: all)
        self.plain = False                  # text-only view: a calm page, the theme's colours and no effect at all
        self.set_text("")

    def set_text(self, text, colors=None):
        if colors is None:
            text = re.sub(r"\r+\n|\r", "\n", text.rstrip("\x1a")).translate(_CTRL)   # also \r\r\n, which some NFOs use; \x1a ends a DOS file
            lines = [line.expandtabs(8).rstrip() for line in text.split("\n")]
            while lines and not lines[-1]:
                lines.pop()
            if len(lines) > 5 and not any(lines[1::2]):   # double-spaced: every second line empty (nfoview does the same)
                lines = lines[::2]
        else:
            lines = text
        self.lines, self.colors, self.rows, self.links = lines, colors, [], {}
        self.sel, self.matches, self.current = None, [], -1
        logo = []
        for r, line in enumerate(lines):
            t, g, blocks = [], [], []
            for c, ch in enumerate(line):
                cp = ord(ch)
                if cp in BLOCKS:
                    blocks.append((c, *BLOCKS[cp]))
                    t.append(" ")
                    g.append(" ")
                elif cp in GLYPH_ART:   # box drawing and shapes: art colour, drawn by the font, sharp
                    t.append(" ")
                    g.append(ch)
                else:
                    t.append(ch)
                    g.append(" ")
            tl, gl = "".join(t), "".join(g)
            self.rows.append((tl if tl.strip() else None, gl if gl.strip() else None, blocks))
            logo.append(any(ord(line[b[0]]) != SQUARE for b in blocks))   # ■ alone is a bullet, not a logo
            for m in LINK_RE.finditer(line):
                url = m.group().rstrip(".,;:!?)]}")
                target = url if url.lower().startswith(("http://", "https://", "www.")) else "mailto:" + url
                self.links.setdefault(r, []).append((m.start(), m.start() + len(url), target))
        self.cols = max((len(line) for line in lines), default=0)
        # each run of rows with block graphics gets its own colour ramp: the logo a full one, a bar further down too
        self.group = {}
        top = None
        for r, art in enumerate([*logo, False]):
            if art and top is None:
                top = r
            elif not art and top is not None:
                self.group.update(dict.fromkeys(range(top, r), (top, r)))
                top = None
        self.set_zoom(self.zoom)

    def font(self):
        fd = Pango.FontDescription.from_string(f"{self.cfg.get('font') or FONT}, Monospace")
        fd.set_absolute_size(BASE_PX * self.zoom * Pango.SCALE)
        return fd

    def set_zoom(self, z):
        """Also call after a font change: it re-measures the cell."""
        self.zoom, self._fx = max(ZOOM_MIN, min(ZOOM_MAX, z * 100)) / 100, {}
        cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
        cr.set_font_options(FO)
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(self.font())
        lay.set_text("M" * 100, -1)
        log = lay.get_extents()[1]
        self.cw, self.ch = log.width / Pango.SCALE / 100, math.ceil(log.height / Pango.SCALE)
        self.padx, self.pady = self.cw * 2, self.ch * 1.5
        self.width = math.ceil(self.cols * self.cw + 2 * self.padx)
        self.height = math.ceil(len(self.rows) * self.ch + 2 * self.pady)

    def link_at(self, r, c):
        return next((u for a, b, u in self.links.get(r, ()) if a <= c < b), None)

    def selected_text(self):
        if not self.sel:
            return ""
        (r0, c0), (r1, c1) = sorted(self.sel)
        parts = [self.lines[r][c0 if r == r0 else 0:(c1 + 1) if r == r1 else None] for r in range(r0, r1 + 1)]
        raw = "\n".join(p.rstrip() for p in parts)
        if self.cfg.get("copy_text_only"):
            return clean_text(parts) or raw   # only art selected: that is what was meant, not the whole NFO
        return raw

    def find(self, query):
        """Case-insensitive search; fills self.matches with (row, start, end)."""
        self.matches, q = [], query.lower()
        for r, line in enumerate(self.lines if q else ()):
            low, i = line.lower(), line.lower().find(q)
            while i >= 0:
                self.matches.append((r, i, i + len(q)))
                i = low.find(q, i + 1)
        self.current = 0 if self.matches else -1

    # ------------------------------------------------------------ drawing

    def _colors(self):
        bg, tx, art, link, _dark = theme_colors(self.cfg)
        return (VGA[0], VGA[7], art, link) if self.colors else (bg, tx, art, link)

    def _draw_blocks(self, cr, x0, y0, art, lo, hi, ramp=None, pattern=None):
        """The block graphics of rows lo..hi-1; ramp: colours for a top-to-bottom ramp per group of art rows;
        pattern: one cairo pattern for all blocks (the colour cycling)."""
        cw, ch, ramps = self.cw, self.ch, {}
        for r in range(lo, hi):
            ya = y0 + r * ch
            source = pattern
            if ramp and not pattern and r in self.group:
                top, end = self.group[r]
                if top not in ramps:
                    ramps[top] = cairo.LinearGradient(0, y0 + top * ch, 0, y0 + end * ch)
                    for i, color in enumerate(ramp):
                        ramps[top].add_color_stop_rgb(i / max(len(ramp) - 1, 1), *color)
                source = ramps[top]
            for c, rects, alpha in self.rows[r][2]:
                xa, w = x0 + round(c * cw), round((c + 1) * cw) - round(c * cw)
                for a, b, c2, d in rects:   # shared integer edges: no seams between neighbours
                    cr.rectangle(xa + round(a * w), ya + round(b * ch),
                                 round(c2 * w) - round(a * w), round(d * ch) - round(b * ch))
                if source is None:
                    cr.set_source_rgba(*(self.colors[r][c][0] if self.colors else art), alpha)
                    cr.fill()
                elif alpha >= 1:
                    cr.set_source(source)
                    cr.fill()
                else:   # a shade (░▒▓) in ramp colours
                    cr.save()
                    cr.clip()
                    cr.set_source(source)
                    cr.paint_with_alpha(alpha)
                    cr.restore()

    def _block_layer(self, cr, art, ramp, white, scale=None):
        """The sharp block graphics, drawn once into an image at the screen's resolution and then reused every frame:
        thousands of rectangles become one copy (white: a stencil that the colour cycling colours in).
        None for pages too big to keep in memory. scale: pixels per point, else taken from cr."""
        if scale is None:
            scale = _pixel_scale(cr)
        scale = round(scale, 3)
        w, h = math.ceil(self.cols * self.cw), math.ceil(len(self.rows) * self.ch)
        if not w or not h or w * h * scale * scale > 24e6 or max(w, h) * scale > MAX_IMAGE:   # 24e6: about 100 MB
            return None
        color = (1.0, 1.0, 1.0) if white else art
        smooth = SMOOTH.get(self.cfg.get("smooth_amount", "mid"), SMOOTH["mid"]) if self.cfg.get("smooth") and not self.colors \
            and not self.plain else 0
        key = ("layer", self.zoom, scale, color, None if white else ramp and tuple(ramp), smooth)
        if self._fx.get("layer-key") != key:   # only the current one: a new colour replaces the old image
            layer = cairo.ImageSurface(cairo.FORMAT_ARGB32, math.ceil(w * scale), math.ceil(h * scale))
            layer.set_device_scale(scale, scale)
            lc = cairo.Context(layer)
            lc.set_antialias(cairo.ANTIALIAS_NONE)
            if smooth:
                self._smooth_blocks(lc, layer, scale, color, None if white else ramp, smooth)
            else:
                self._draw_blocks(lc, 0, 0, color, 0, len(self.rows), None if white else ramp)
            self._fx["layer-key"], self._fx["layer"] = key, layer
        return self._fx["layer"]

    def _art_pixels(self):
        """The blocks of the art (shades too) as pixel art, a list of rows of 0 and 1 bytes, cached with the page: a pixel is
        half a cell high and a cell wide, or half a cell wide when some block (▌ ▐ ▖ ...) needs it. Returns
        (rows, pixels per cell across)."""
        if "art-pixels" not in self._fx:
            wide = any(x % 1 for row in self.rows for _c, rects, _a in row[2] for rect in rects for x in rect[::2])
            gx, h = 2 if wide else 1, len(self.rows) * 2
            grid = [bytearray(self.cols * gx) for _ in range(h)]
            for r, row in enumerate(self.rows):
                for c, rects, _alpha in row[2]:
                    for x0, y0, x1, y1 in rects:
                        for y in range(round((2 * r) + 2 * y0), round(2 * r + 2 * y1)):   # a thin ▁ is a whole pixel row
                            xa = round((c + x0) * gx)
                            grid[y][xa:max(xa + 1, round((c + x1) * gx))] = b"\1" * max(1, round((c + x1) * gx) - xa)
            self._fx["art-pixels"] = (grid, gx)
        return self._fx["art-pixels"]

    def _smooth_blocks(self, lc, layer, scale, color, ramp, amount):
        """The block graphics with smooth edges, for those who hate pixels. The art is read as the pixel art it is
        and enlarged by Scale2x (EPX) as often as the amount says: every step of a staircase between two pixels becomes a
        diagonal, round shapes become round. The enlarged pixels are then scaled to the screen smoothly (bilinear)
        and cut off at half again, with an edge of one or two device pixels of anti-aliasing. Shades (░▒▓) belong to
        the outline and fade softly into the whole blocks inside it. Only cairo and bytes, no extra library."""
        pw, ph = layer.get_width(), layer.get_height()
        grid, gx = self._art_pixels()
        steps, passes = amount
        steps = min(steps, max(0, int(math.log2(max(1.0, 16e6 / max(1, len(grid) * len(grid[0])))) / 2)))   # a big page: fewer
        for _ in range(steps):
            grid = _scale2x(grid)
        n = 2 ** steps
        gw, gh = len(grid[0]), len(grid)
        full = cairo.ImageSurface(cairo.FORMAT_A8, gw, gh)   # alpha only: a quarter of the bytes to push around
        stride = full.get_stride()
        full.get_data()[:] = b"".join(bytes(r) + bytes(stride - gw) for r in grid).translate(bytes([0, 255]) + bytes(254))
        full.mark_dirty()
        # halved (each pixel the average of 2 x 2): the finest steps of Scale2x become anti-aliasing, the blur
        # below costs a quarter
        small = cairo.ImageSurface(cairo.FORMAT_A8, (gw + 1) // 2, (gh + 1) // 2)
        hc = cairo.Context(small)
        hc.scale(.5, .5)
        hc.set_source_surface(full, 0, 0)
        hc.get_source().set_filter(cairo.FILTER_BILINEAR)
        hc.paint()
        for _ in range(passes):   # a little blur closes the thin necks of a diagonal: [1 2 1] / 4 across and down,
            for dx, dy in ((.5, 0), (0, .5)):   # as two bilinear copies half a sample off
                nxt = cairo.ImageSurface(cairo.FORMAT_A8, small.get_width(), small.get_height())
                nc = cairo.Context(nxt)
                nc.set_operator(cairo.OPERATOR_ADD)
                for sign in (1, -1):
                    sp = cairo.SurfacePattern(small)
                    sp.set_filter(cairo.FILTER_BILINEAR)
                    sp.set_extend(cairo.EXTEND_PAD)
                    sp.set_matrix(cairo.Matrix(x0=-sign * dx, y0=-sign * dy))
                    nc.set_source(sp)
                    nc.paint_with_alpha(.5)
                small = nxt
        sx, sy = self.cw * scale / gx / n * 2, self.ch * scale / 2 / n * 2   # device pixels per sample
        blur = cairo.ImageSurface(cairo.FORMAT_A8, pw, ph)   # to the screen's pixels, bilinear
        bc = cairo.Context(blur)
        bc.scale(sx, sy)
        sp = cairo.SurfacePattern(small)
        sp.set_filter(cairo.FILTER_BILINEAR)
        sp.set_extend(cairo.EXTEND_PAD)
        bc.set_source(sp)
        bc.paint()
        blur.flush()
        # the cut: an edge blurred by sigma rises by about .4 / sigma per device pixel; steepened to ramp over about
        # 1.4 pixels (sigma in samples: the halving, the passes and the bilinear scaling, roughly)
        gain = max(1.0, 1.8 * max(sx, sy) * math.sqrt(.5 * passes + .3))
        table = bytes(max(0, min(255, round(((i / 255 - .5) * gain + .5) * 255))) for i in range(256))
        data = blur.get_data()
        data[:] = bytes(data).translate(table)
        blur.mark_dirty()
        shades = self._shade_pixels(gx)
        if shades is not None:   # the shades (░▒▓) are part of the outline, and inside it they fade softly
            bc = cairo.Context(blur)   # into the whole blocks
            bc.scale(self.cw * scale / gx, self.ch * scale / 2)
            sp = cairo.SurfacePattern(shades)
            sp.set_filter(cairo.FILTER_BILINEAR)
            sp.set_extend(cairo.EXTEND_PAD)
            bc.set_source(sp)
            bc.set_operator(cairo.OPERATOR_IN)
            bc.paint()
        shape = blur
        lc.save()
        lc.scale(1 / scale, 1 / scale)   # the pixels of the image
        outline = cairo.SurfacePattern(shape)
        if ramp:   # each group of art rows its own gradient, a row more than the blocks for the rounded edge
            for top, end in set(self.group.values()):
                grad = cairo.LinearGradient(0, self.ch * top * scale, 0, self.ch * end * scale)
                for i, c in enumerate(ramp):
                    grad.add_color_stop_rgb(i / max(len(ramp) - 1, 1), *c)
                lc.save()
                lc.rectangle(0, (top - 1) * self.ch * scale, pw, (end - top + 2) * self.ch * scale)
                lc.clip()
                lc.set_source(grad)
                lc.mask(outline)
                lc.restore()
        else:
            lc.set_source_rgb(*color)
            lc.mask(outline)
        lc.restore()

    def _shade_pixels(self, gx):
        """How strong each pixel of the art is (see _art_pixels): 1, and the alpha of a shade (░▒▓) on its cells;
        None when there are no shades."""
        cells = [(r, c, rects, alpha) for r, row in enumerate(self.rows) for c, rects, alpha in row[2] if alpha < 1]
        if not cells:
            return None
        img = cairo.ImageSurface(cairo.FORMAT_A8, self.cols * gx, len(self.rows) * 2)
        cr = cairo.Context(img)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.scale(gx, 2)
        for r, c, rects, alpha in cells:
            for x0, y0, x1, y1 in rects:
                cr.rectangle(c + x0, r + y0, x1 - x0, y1 - y0)
            cr.set_source_rgba(0, 0, 0, alpha)
            cr.fill()
        return img

    def _paint_blurred(self, cr, x0, y0, art, ramp, k, alpha=1.0, pattern=None):
        """The blocks rendered at 1/k size and scaled back up bilinearly: soft edges, or with a big k a halo.
        The small copy is cached; it keeps a margin so a halo is not cut off at the edge of the art.
        With a pattern (colour cycling) the cached copy is white and only used as a mask, so a moving pattern
        costs no new blur per frame. Returns False (and draws nothing) for pages too big for one cairo image."""
        blurred = self._blurred((1.0, 1.0, 1.0) if pattern else art, None if pattern else ramp, k)
        if blurred is None:
            return False
        small, m = blurred
        layer = cairo.SurfacePattern(small)
        layer.set_filter(cairo.FILTER_BILINEAR)
        layer.set_matrix(cairo.Matrix(xx=1 / k, yy=1 / k, x0=-(x0 - m) / k, y0=-(y0 - m) / k))   # page -> small copy
        if pattern:   # the moving colours, shaped by the blurred blocks
            cr.push_group()
            cr.set_source(pattern)
            cr.mask(layer)
            cr.pop_group_to_source()
        else:
            cr.set_source(layer)
        cr.paint_with_alpha(alpha)
        return True

    def _blurred(self, art, ramp, k):
        """(small copy of the blocks at 1/k size, margin m in page points), cached; None when too big for an image.
        Scaled back up by k, it covers the art from (x0 - m, y0 - m)."""
        key = ("blur", self.zoom, art, tuple(ramp) if ramp else None, round(k, 2))   # an empty ramp list is no key
        if key not in self._fx:
            old = [x for x in self._fx if isinstance(x, tuple) and x[0] == "blur"]
            if len(old) > 6:   # old strengths and colours
                for x in old:
                    del self._fx[x]
            m = math.ceil(2 * k)
            w, h = math.ceil(self.cols * self.cw) + 2 * m, math.ceil(len(self.rows) * self.ch) + 2 * m
            # 150e6: an NFO of 160 columns at the highest zoom still glows; a page with one very long line no longer
            # freezes the window for seconds while it is blurred (it gets sharp blocks instead)
            if max(w, h) > MAX_IMAGE or w * h > 150e6:
                self._fx[key] = None
                return None
            full = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)   # exact pixels first: no seams
            self._draw_blocks(cairo.Context(full), m, m, art, 0, len(self.rows), ramp)
            small = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(math.ceil(w / k), 1), max(math.ceil(h / k), 1))
            sc = cairo.Context(small)
            sc.scale(1 / k, 1 / k)
            sc.set_source_surface(full, 0, 0)
            sc.get_source().set_filter(cairo.FILTER_GOOD)
            sc.paint()
            self._fx[key] = (small, m)
        return self._fx[key]

    def glow_parts(self):
        """What the glow draws, shared by the cairo and the GPU drawing: ("halo", [(k, alpha)...]) for neon,
        ("soft", k) for soft edges, or None."""
        if not (self.cfg.get("soft") and not self.colors and self.rows):
            return None
        tight = max(2.0, self.cw * self.cfg.get("glow", 3) / 6)
        if self.cfg.get("glow_mode") == "halo":
            beat = 1.0
            if self.cfg.get("pulse"):   # with music: the loudness; without: a slow breath
                music = self.level is not None and self.cfg.get("pulse_mode", "beat") == "beat"
                beat = .35 + .8 * self.level if music else .7 + .3 * math.sin(self.time * 4)
            if self.cfg.get("neon_flicker"):
                beat *= flicker(self.time)
            return "halo", [(tight * 3, min(1, .7 * beat)), (tight, min(1, .8 * beat))]
        return "soft", max(1.25, self.cw * self.cfg.get("glow", 3) / 9)

    def cycle_bands(self, ramp):
        """The colour cycling as (colours, period, hard edges, shift): bands of period/len(colours) points that move
        up (or down) through the art by shift points (self.time in seconds)."""
        ch = self.ch
        if self.cfg.get("cycle_palette") == "ramp":
            colors = [*(ramp or [_hex(c) for c in DEFAULTS["ramp_colors"]])]
            colors += colors[-2:0:-1]   # there and back: no hard edge where the pattern repeats
            band, hard = ch * 2, False
        else:
            colors, band, hard = C64_CYCLE, ch / 3, True   # thin stripes like on the C64
        period = band * len(colors)
        shift = self.time * ch * 2.5   # 2.5 rows a second
        return colors, period, hard, (shift if self.cfg.get("cycle_dir") == "up" else -shift) % period

    def run_rects(self, x0, y0, r, a, b, skip_art):
        """The rectangles that cover the cells a..b-1 of row r, art cells left out when skip_art."""
        line, start = self.lines[r], None
        for c in range(a, b + 1):
            inside = c < b and not (skip_art and c < len(line) and is_art(line[c]))
            if inside and start is None:
                start = c
            elif not inside and start is not None:
                yield x0 + start * self.cw, y0 + r * self.ch, (c - start) * self.cw, self.ch
                start = None

    def selection_rows(self, lo, hi):
        """The marked cells of rows lo..hi as (row, a, b): with "copy text only" just what gets copied."""
        if not self.sel:
            return
        (r0, c0), (r1, c1) = sorted(self.sel)
        text_only = self.cfg.get("copy_text_only")
        for r in range(max(lo, r0), min(hi, r1 + 1)):
            a, end = c0 if r == r0 else 0, (c1 + 1) if r == r1 else max(len(self.lines[r]), 1)
            if text_only:   # mark only what gets copied: from the first to the last text character, art left out,
                if not clean_text([self.lines[r]], dedent=False):   # and no row that "text only" leaves out ("_")
                    continue
                text = [i for i in range(a, min(end, len(self.lines[r])))
                        if not self.lines[r][i].isspace() and not is_art(self.lines[r][i])]
                if not text:
                    continue
                a, end = text[0], text[-1] + 1
            yield r, a, end

    def _cycle(self, ramp):
        """The colour cycling as a cairo pattern: bands that move up through the art, endlessly."""
        colors, period, hard, shift = self.cycle_bands(ramp)
        p = cairo.LinearGradient(0, 0, 0, period)
        for i, color in enumerate(colors):
            if hard:
                p.add_color_stop_rgb(i / len(colors), *color)
                p.add_color_stop_rgb((i + 1) / len(colors) - 1e-6, *color)
            else:
                p.add_color_stop_rgb(i / len(colors), *color)
        if not hard:
            p.add_color_stop_rgb(1, *colors[0])
        p.set_extend(cairo.EXTEND_REPEAT)
        p.set_matrix(cairo.Matrix(y0=shift))
        return p

    def paint(self, cr, ox=0, background=True):
        """The page as exported: no search matches, no selection (the window draws those, gpu._under).
        background=False: the caller has drawn it (and the stars)."""
        bg, tx, _art, _link = self._colors()
        if background:
            cr.set_source_rgb(*bg)
            cr.paint()
            self.stars(cr, self.width, self.height)
        if self.reveal is None:
            self._paint_page(cr, ox)
            return
        # modem build-up: everything before the current character, then a block cursor
        r, c = self._reveal_cell()
        x0, y0 = round(ox + self.padx), round(self.pady)
        cr.save()
        cr.rectangle(0, 0, self.width + ox * 2, y0 + r * self.ch)
        cr.rectangle(0, y0 + r * self.ch, x0 + c * self.cw, self.ch)
        cr.clip()
        self._paint_page(cr, ox)
        cr.restore()
        cr.set_source_rgb(*tx)
        cr.rectangle(x0 + c * self.cw, y0 + r * self.ch, self.cw, self.ch)
        cr.fill()

    def _reveal_cell(self):
        """(row, column) of the character the modem build-up has reached."""
        left = int(self.reveal)
        for r, line in enumerate(self.lines):
            if left <= len(line):
                return r, left
            left -= len(line) + 1   # +1: the line break
        return len(self.lines), 0

    def total_chars(self):
        return sum(len(line) + 1 for line in self.lines)

    def stars(self, cr, w, h):
        """A starfield of w x h (the window, or the page in an export): three layers drifting left, the near ones
        faster and brighter; or warp stars flying at you. Nothing when off, for ANSI art and in the text-only view."""
        if not self.cfg.get("stars") or self.colors or self.plain:
            return
        color = self._colors()[1]
        if self.cfg.get("stars_mode") == "warp":
            self._warp(cr, w, h, color)
            return
        if getattr(self, "_star_key", None) != (w, h):
            rnd = random.Random(1987)
            n = max(30, w * h // 9000)
            self._starlist = [(rnd.random(), rnd.random() * h, layer) for layer in (0, 1, 2) for _ in range(n)]
            self._star_key = (w, h)
        _, cy0, _, cy1 = cr.clip_extents()
        for layer in (0, 1, 2):
            speed, size, alpha = (8, 25, 60)[layer] * self.zoom, (1, 1.5, 2)[layer] * max(1, self.zoom), (.35, .6, .95)[layer]
            cr.set_source_rgba(*color, alpha)
            for xf, y, lay in self._starlist:
                if lay == layer and cy0 <= y <= cy1:
                    cr.rectangle((xf * w - self.time * speed) % w, y, size, size)
            cr.fill()

    def _wobble(self, cr, layer, x0, top, x1, bottom, y0):
        """The wobbling logo of the old demos: every 2-pixel strip of a block of art slides sideways on a sine wave
        that runs up through it. The text stays still. The layer covers x0..x1 and
        top..bottom of the page."""
        amplitude, step = self.ch * WOBBLE.get(self.cfg.get("wobble_amount"), WOBBLE["mid"]), 2
        still = None   # rows without art in a run: drawn in one go, not strip by strip

        def lay(y, height, dx):   # a filled rectangle, not a clip (see paint)
            cr.set_source_surface(layer, x0 + dx, top)
            cr.rectangle(x0, y, x1 - x0, height)
            cr.fill()
        for y in range(math.floor(top), math.ceil(bottom) + step, step):
            if y < bottom and int((y - y0) // self.ch) not in self.group:
                still = y if still is None else still
                continue
            if still is not None:
                lay(still, y - still, 0)
                still = None
            if y < bottom:
                lay(y, step, amplitude * math.sin(y / (self.ch * .75) + self.time * 4))

    def warp_streaks(self, w, h):
        """Warp stars: they fly out of the middle towards you, each with a streak that grows as it comes closer.
        [(x0, y0, x1, y1, near)] for the stars in the window; near: 0 far away .. 1 right in front of you."""
        if getattr(self, "_warp_key", None) != (w, h):
            rnd = random.Random(1987)
            self._warplist = [(rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.random()) for _ in range(max(60, w * h // 2500))]
            self._warp_key = (w, h)
        cx, cy, reach = w / 2, h / 2, min(w, h) / 4
        out = []
        for x, y, z0 in self._warplist:
            z = (z0 - self.time * .35) % 1 + .02   # 1: far away, near 0: right in front of you
            x1, y1 = cx + x / z * reach, cy + y / z * reach
            if -50 < x1 < w + 50 and -50 < y1 < h + 50:   # flown out of the window: nothing to draw
                out.append((cx + x / (z + .06) * reach, cy + y / (z + .06) * reach, x1, y1, 1 - z))   # from where it was
        return out

    def _warp(self, cr, w, h, color):
        for x0, y0, x1, y1, near in self.warp_streaks(w, h):
            cr.set_source_rgba(*color, min(1, near * 1.3))
            cr.set_line_width(max(.6, near * 2.4))
            cr.move_to(x0, y0)
            cr.line_to(x1, y1)
            cr.stroke()

    def _paint_page(self, cr, ox=0):
        bg, tx, art, link = self._colors()
        # whole-pixel origin: cells then start on pixel edges, so neighbouring blocks leave no seam
        cw, ch, x0, y0 = self.cw, self.ch, round(ox + self.padx), round(self.pady)
        _, cy0, _, cy1 = cr.clip_extents()
        lo, hi = max(0, int((cy0 - y0) / ch)), min(len(self.rows), int((cy1 - y0) / ch) + 1)
        if self.colors:   # ANSI background colours
            cr.save()
            cr.set_antialias(cairo.ANTIALIAS_NONE)
            for r in range(lo, hi):
                for c, (_f, b) in enumerate(self.colors[r]):
                    if b != VGA[0]:
                        cr.set_source_rgb(*b)
                        cr.rectangle(x0 + round(c * cw), y0 + r * ch, round((c + 1) * cw) - round(c * cw), ch)
                        cr.fill()
            cr.restore()
        # Glow: "soft" draws only blurred blocks (soft edges); "halo" puts a wide and a tight blurred copy behind
        # sharp blocks, like neon. ANSI art is pixel art made for exact cells: it never glows.
        ramp = [_hex(c) for c in self.cfg.get("ramp_colors", ())] if self.cfg.get("ramp") and not self.colors else None
        # the animations (self.time is set by the UI each frame) work on NFOs; ANSI art keeps its own colours
        pattern = self._cycle(ramp) if self.cfg.get("cycle") and not self.colors else None
        wobble = self.cfg.get("wobble") and not self.colors and self.group
        if wobble:   # glow and blocks go into a layer that is then laid down in shifted strips; the layer covers
            ex0, ey0, ex1, ey1 = cr.clip_extents()   # the window, from the first to the last row of art (and glow)
            groups = set(self.group.values())
            ey0 = max(ey0, y0 + (min(self.group) - 2) * ch)
            ey1 = min(ey1, y0 + (max(self.group) + 3) * ch)
            wobble = ey1 > ey0
        if wobble:   # an image of its own and no clipping: cairo crashes replaying GTK's recording of a group
            # painted through many clips (cairo-clip.c, _cairo_clip_intersect_clip)
            k = _pixel_scale(cr)
            strip = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, math.ceil((ex1 - ex0) * k)),
                                       max(1, math.ceil((ey1 - ey0) * k)))
            strip.set_device_scale(k, k)
            outer, cr = cr, cairo.Context(strip)
            cr.translate(-ex0, -ey0)
            for t, e in groups:   # only the blocks of art and room for their glow (a clip in our own image is safe)
                cr.rectangle(ex0, y0 + (t - 2) * ch, ex1 - ex0, (e - t + 4) * ch)
            cr.clip()
        glow = self.glow_parts()
        if glow and glow[0] == "halo":
            # the halo keeps the art colour even while the blocks cycle: a cached image, no colouring per frame
            for k, alpha in glow[1]:
                self._paint_blurred(cr, x0, y0, art, ramp, k, alpha)
        # soft edges replace the sharp blocks; a page too long for them gets sharp blocks instead
        if not (glow and glow[0] == "soft" and self._paint_blurred(cr, x0, y0, art, ramp, glow[1], 1.0, pattern)):
            layer = self._block_layer(cr, art, ramp, pattern is not None)
            if layer is None:   # a page too big to keep as an image: draw the blocks directly
                cr.save()
                cr.set_antialias(cairo.ANTIALIAS_NONE)   # with display scaling (125 %, 150 %) edges snap to pixels too
                self._draw_blocks(cr, x0, y0, art, lo, hi, ramp, pattern)
                cr.restore()
            else:
                stencil = cairo.SurfacePattern(layer)
                stencil.set_filter(cairo.FILTER_NEAREST)   # pixel for pixel: crisp, no seams
                stencil.set_matrix(cairo.Matrix(x0=-x0, y0=-y0))
                if pattern:   # colour cycling: the moving colours through the block stencil
                    cr.set_source(pattern)
                    cr.mask(stencil)
                else:
                    cr.set_source(stencil)
                    cr.paint()
        if wobble:
            cr = outer
            self._wobble(cr, strip, ex0, ey0, ex1, ey1, y0)
        if self.cfg.get("text_glow") and not self.plain:   # the text-only view shows the colours, no effect
            self._text_glow(cr, x0, y0, lo, hi, tx, art, link)
        self._text_rows(cr, x0, y0, lo, hi, tx, art, link)

    def _text_rows(self, cr, x0, y0, lo, hi, tx, art, link):
        cr.set_font_options(FO)
        # the text layouts are built once per row and reused every frame (only their drawing is repeated)
        key = ("text", self.zoom, self.cfg.get("font"), link)
        if self._fx.get("text-key") != key:
            self._fx["text-key"], self._fx["text"] = key, {}
        layouts = self._fx["text"]
        for r in range(lo, hi):
            if r not in layouts:
                layouts[r] = [(self._layout(cr, s, r, link, is_text), color)
                              for s, color, is_text in ((self.rows[r][0], tx, True), (self.rows[r][1], art, False)) if s]
            for lay, color in layouts[r]:
                PangoCairo.update_layout(cr, lay)
                cr.move_to(x0, y0 + r * self.ch)
                cr.set_source_rgb(*color)
                PangoCairo.show_layout(cr, lay)

    def _text_glow(self, cr, x0, y0, lo, hi, tx, art, link):
        """A soft halo behind the text, like phosphor: the text drawn into an image, blurred (shrunk and scaled back
        up) and laid under the real text. Left out for a page too big for one image, like the glow of the blocks."""
        ex0, ey0, ex1, ey1 = cr.clip_extents()
        scale = _pixel_scale(cr)
        w, h = math.ceil(ex1 - ex0), math.ceil(ey1 - ey0)
        if w < 1 or h < 1 or w * h * scale * scale > 24e6 or max(w, h) * scale > MAX_IMAGE:
            return
        layer = cairo.ImageSurface(cairo.FORMAT_ARGB32, math.ceil(w * scale), math.ceil(h * scale))
        layer.set_device_scale(scale, scale)
        lc = cairo.Context(layer)
        lc.translate(-ex0, -ey0)
        self._text_rows(lc, x0, y0, lo, hi, tx, art, link)
        for k, alpha in ((max(2.0, self.ch * .2), .7), (max(4.0, self.ch * .5), .5)):
            small = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, math.ceil(w / k)), max(1, math.ceil(h / k)))
            sc = cairo.Context(small)
            sc.scale(1 / k, 1 / k)
            sc.set_source_surface(layer, 0, 0)
            sc.get_source().set_filter(cairo.FILTER_GOOD)
            sc.paint()
            cr.save()
            cr.translate(ex0, ey0)
            cr.scale(k, k)
            cr.set_source_surface(small, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_BILINEAR)
            cr.paint_with_alpha(alpha)
            cr.restore()

    def _layout(self, cr, s, r, link, is_text):
        """A Pango layout for one row's text (or its line graphics), with ANSI colours or link colours."""
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(self.font())
        attrs = Pango.AttrList()
        offs = [0]
        for chx in s:
            offs.append(offs[-1] + len(chx.encode()))
        if self.colors:   # one attribute per run of equal foreground colour
            row, c = self.colors[r], 0
            while c < len(s):
                e = c
                while e < len(s) and row[e][0] == row[c][0]:
                    e += 1
                _attr(attrs, Pango.attr_foreground_new(*_rgb16(row[c][0])), offs[c], offs[e])
                c = e
        elif is_text:
            for a, b, _u in self.links.get(r, ()):
                _attr(attrs, Pango.attr_foreground_new(*_rgb16(link)), offs[a], offs[b])
                _attr(attrs, Pango.attr_underline_new(Pango.Underline.SINGLE), offs[a], offs[b])
        lay.set_attributes(attrs)
        lay.set_text(s, -1)
        return lay

    def export(self, path):
        """PNG, or PDF (vector, text stays selectable) when path ends in .pdf."""
        pdf = path.lower().endswith(".pdf")
        if not pdf and (max(self.width, self.height) > MAX_IMAGE or self.width * self.height > 100e6):   # 100e6: 400 MB
            raise TooBig(f"the page is {self.width} x {self.height} pixels, a PNG can have {MAX_IMAGE}; save a PDF")
        s = cairo.PDFSurface(path, max(self.width, 1), max(self.height, 1)) if pdf else self.render()
        cr = cairo.Context(s)
        if pdf:
            self.paint(cr)
        if self.cfg.get("crt"):
            crt_static(cr, self.width, self.height, pattern=self.cfg.get("crt_mask", "lines"))
        if pdf:
            s.finish()
        else:
            s.write_to_png(path)

    def render(self):
        """The whole page as an image surface."""
        s = cairo.ImageSurface(cairo.FORMAT_RGB24, max(self.width, 1), max(self.height, 1))
        self.paint(cairo.Context(s))
        return s


def _scale2x(g):
    """Scale2x (EPX) of a picture of 0 and 1 bytes: every pixel becomes four, and where two neighbours at a corner
    agree and the other two do not, the corner takes their value: a one-pixel staircase turns into a diagonal.
    A whole row at a time as one big number (each byte 0 or 1, so the bit operations work byte by byte)."""
    h, w = len(g), len(g[0])
    big = lambda b: int.from_bytes(b, "big")
    one, zero = big(b"\1" * w), bytes(w)
    rows = [big(r) for r in g]
    out = []
    for y in range(h):
        p, a, d = rows[y], rows[y - 1] if y else 0, rows[y + 1] if y + 1 < h else 0
        if not (p or a or d):
            out.extend((bytearray(2 * w), bytearray(2 * w)))
            continue
        row = g[y]
        b, c = big(row[1:] + b"\0"), big(b"\0" + row[:-1])   # the right and the left neighbour

        def eq(x, z):
            return one ^ x ^ z
        tl = p ^ ((a ^ p) & eq(c, a) & (c ^ d) & (a ^ b))
        tr = p ^ ((b ^ p) & eq(a, b) & (a ^ c) & (b ^ d))
        bl = p ^ ((c ^ p) & eq(d, c) & (d ^ b) & (c ^ a))
        br = p ^ ((d ^ p) & eq(b, d) & (b ^ a) & (d ^ c))
        for left, right in ((tl, tr), (bl, br)):
            line = bytearray(2 * w)
            line[0::2] = left.to_bytes(w, "big") if left else zero
            line[1::2] = right.to_bytes(w, "big") if right else zero
            out.append(line)
    return out


def _pixel_scale(cr):
    """Device pixels per page point of cr: the display scale times the context's own scale."""
    m = cr.get_matrix()
    return cr.get_target().get_device_scale()[0] * math.hypot(m.xx, m.yx)


def _rgb16(c):
    return [int(min(1.0, max(0.0, v)) * 65535) for v in c]   # bad ANSI values can be above 1


def _attr(attrs, a, start, end):
    a.start_index, a.end_index = start, end
    attrs.insert(a)


def load(path, cfg, zoom=1.0, enc="auto", text_only=False):
    """Read a file into a new Page. Returns (page, encoding label, byte size)."""
    data, _name = read(path)
    page = Page(cfg, zoom)
    fill(page, data, enc, text_only)
    return page, page.label, len(data)


def fill(page, data, enc="auto", text_only=False):
    """Decode data into page (ANSI art gets colours); sets page.label to the encoding shown to the user."""
    text, label, width = decode(data, enc)
    if is_ansi(text):
        lines, colors = parse_ansi(text, width)
        if text_only:
            page.set_text(clean_text(lines, dedent=False))
        else:
            page.set_text(lines, colors)
        page.label = f"ANSI · {label}"
    else:
        page.set_text(clean_text(text.split("\n"), dedent=False) if text_only else text)
        page.label = label
