# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""The NFO view drawn by the graphics card. Instead of painting every frame with cairo on the processor, the view
hands GTK a scene: images of the blocks and the glow (made once by page.py, then only placed, faded and masked),
gradients for the colour cycling, the text as Pango layouts (GTK keeps the glyphs on the card),
and clips and shifts for the wobble, the glitch and the modem build-up. The graphics card puts it together.
PNG and PDF export keep the cairo drawing in page.py, which shows the same picture."""
import math

import cairo
import gi
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk, Pango, PangoCairo  # noqa: E402

from core import C64, FO, VGA, _hex, is_dark  # noqa: E402
from overlays import OPENING_END, dos_screen, loader_screen, mask_tile, paint_c64_screen, scroller_letters  # noqa: E402
from page import WOBBLE  # noqa: E402

WHITE = (1.0, 1.0, 1.0)
PHASES = 48   # positions of the wobble wave: it turns 4 radians a second, about one position per frame at 30 fps


def rect(x, y, w, h):
    return Graphene.Rect().init(x, y, max(w, 0), max(h, 0))


def clip(snap, x, y, w, h, scale):
    """A clip on whole device pixels: a clip edge inside a pixel (2 points at 125 % are 2.5 pixels) makes the
    graphics card draw the clip as a mask, which is many times slower."""
    x1, y1 = round((x + w) * scale) / scale, round((y + h) * scale) / scale
    x, y = round(x * scale) / scale, round(y * scale) / scale
    snap.push_clip(rect(x, y, x1 - x, y1 - y))


def point(x, y):
    return Graphene.Point().init(x, y)


def rgba(c, alpha=1.0):
    r = Gdk.RGBA()
    r.red, r.green, r.blue, r.alpha = c[0], c[1], c[2], alpha
    return r


def stops(pairs):
    out = []
    for offset, color in pairs:
        s = Gsk.ColorStop()
        s.offset, s.color = offset, rgba(color)
        out.append(s)
    return out


def astops(pairs):
    """Colour stops with alpha: (offset, colour, alpha)."""
    out = []
    for offset, color, alpha in pairs:
        s = Gsk.ColorStop()
        s.offset, s.color = offset, rgba(color, alpha)
        out.append(s)
    return out


def to_texture(surface):
    """A cairo ARGB32 image as a texture for the graphics card."""
    surface.flush()
    return Gdk.MemoryTexture.new(surface.get_width(), surface.get_height(), Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED,
                                 GLib.Bytes.new(bytes(surface.get_data())), surface.get_stride())


def texture(page, surface):
    """to_texture(), made once per image (kept with the page's caches)."""
    cache = page._fx.setdefault("gpu-tex", {})
    hit = cache.get(id(surface))
    if hit and hit[0] is surface:
        return hit[1]
    if len(cache) > 12:   # images of old colours and strengths
        cache.clear()
    tex = to_texture(surface)
    cache[id(surface)] = (surface, tex)
    return tex


_BAKE = None   # the view's bake() for this frame (see view)


def cached(page, name, key, build):
    """A render node that only changes with key (the text, the selection): built once, then reused every frame."""
    nodes = page._fx.setdefault("gpu-nodes", {})
    if nodes.get(name, (None,))[0] != key:
        snap = Gtk.Snapshot()
        build(snap)
        nodes[name] = (key, snap.to_node())
    return nodes[name][1]


def append(snap, node):
    if node is not None:
        snap.append_node(node)


# ------------------------------------------------------------ window

class Drawn(Gtk.Widget):
    """A widget drawn by draw(snapshot, width, height): the scroller strip over the view."""
    __gtype_name__ = "NfoGlowDrawn"

    def __init__(self, draw, **props):
        super().__init__(**props)
        self._draw = draw

    def do_snapshot(self, snap):
        self._draw(snap, self.get_width(), self.get_height())


def loader(snap, w, h, t, name, scale):
    """The C64 tape loader over the window (overlays.loader_screen): the blue screen drawn in its own 320 x 200
    pixels with the 8 x 8 font, enlarged by a whole number of device pixels, in its light blue border, which
    flickers with coloured stripes while it loads."""
    import random
    lines, cursor, stripes = loader_screen(t, name)
    if stripes:   # a new set of stripes every frame, as the bits come in
        rnd, y, colors = random.Random(int(t * 30)), 0, list(C64.values())
        while y < h:
            height = rnd.randint(2, 14)
            snap.append_color(rgba(rnd.choice(colors)), rect(0, y, w, height))
            y += height
    else:
        snap.append_color(rgba(C64["lightblue"]), rect(0, 0, w, h))
    border = max(12, min(w, h) * .07)
    pixel = max(1, math.floor(min((w - 2 * border) / 320, (h - 2 * border) / 200) * scale)) / scale
    x = round((w - 320 * pixel) / 2 * scale) / scale
    y = round((h - 200 * pixel) / 2 * scale) / scale
    key = (tuple(lines), cursor)
    if _LOADER.get("key") != key:
        screen = cairo.ImageSurface(cairo.FORMAT_ARGB32, 320, 200)
        paint_c64_screen(cairo.Context(screen), lines, cursor, C64["lightblue"], C64["blue"])
        _LOADER["key"], _LOADER["texture"] = key, to_texture(screen)
    snap.append_scaled_texture(_LOADER["texture"], Gsk.ScalingFilter.NEAREST, rect(x, y, 320 * pixel, 200 * pixel))


_DOS = {}


def dos(snap, w, h, t, name, family, info):
    """The DOS boot over the window (overlays.dos_screen): black, grey letters in the page font, an underscore cursor."""
    lines, cursor = dos_screen(t, name, info)
    snap.append_color(rgba((0, 0, 0)), rect(0, 0, w, h))
    size = max(12.0, min(22.0, h / 30))
    if _DOS.get("key") != (family, size):
        cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
        cr.set_font_options(FO)
        fd = Pango.FontDescription.from_string(f"{family}, Monospace")
        fd.set_absolute_size(size * Pango.SCALE)
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(fd)
        lay.set_text("M" * 10, -1)
        extents = lay.get_extents()[1]
        _DOS.update(key=(family, size), cr=cr, fd=fd, advance=extents.width / Pango.SCALE / 10,
                    line=extents.height / Pango.SCALE)
    grey = rgba(VGA[7])
    pad = size * 1.2
    for row, text in enumerate(lines):
        if text:
            lay = PangoCairo.create_layout(_DOS["cr"])
            lay.set_font_description(_DOS["fd"])
            lay.set_text(text, -1)
            snap.save()
            snap.translate(point(pad, pad + row * _DOS["line"]))
            snap.append_layout(lay, grey)
            snap.restore()
    if cursor:
        row, col = cursor
        thick = max(2.0, size * .12)
        snap.append_color(grey, rect(pad + col * _DOS["advance"], pad + (row + 1) * _DOS["line"] - thick * 1.5,
                                     _DOS["advance"], thick))


_LOADER = {}
_LETTERS = {}


def scroller(snap, w, h, t, text, family, size):
    """The sine scroller (overlays.scroller_letters): one cached layout per letter, placed with a shadow."""
    if _LETTERS.get("key") != (family, size):
        _LETTERS.clear()
        _LETTERS["key"] = (family, size)
        cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
        cr.set_font_options(FO)
        _LETTERS["cr"] = cr
    shadow = rgba((0, 0, 0), .6)
    for ch, x, y, color in scroller_letters(w, h, t, text, size):
        if ch not in _LETTERS:
            lay = PangoCairo.create_layout(_LETTERS["cr"])
            fd = Pango.FontDescription.from_string(f"{family}, Monospace Bold")
            fd.set_absolute_size(size * Pango.SCALE)
            lay.set_font_description(fd)
            lay.set_text(ch, -1)
            _LETTERS[ch] = lay
        snap.save()
        snap.translate(point(x + 2, y + 2))
        snap.append_layout(_LETTERS[ch], shadow)
        snap.translate(point(-2, -2))
        snap.append_layout(_LETTERS[ch], rgba(color))
        snap.restore()


def stars(page, snap, w, h, scale, cache):
    """The starfield over the whole window. Drifting stars: three images (one per layer) made once for the window
    size, then slid left and wrapped round; warp stars: drawn with cairo (lines that change every frame)."""
    if not page.cfg.get("stars") or page.colors or page.plain:
        return
    color = page._colors()[1]
    if page.cfg.get("stars_mode") == "warp":
        _warp(page, snap, w, h, color)
        return
    key = (w, h, scale, color, page.zoom)
    if cache.get("key") != key:
        page.stars(cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)), w, h)   # makes page._starlist
        cache["key"], cache["layers"] = key, []
        for layer in (0, 1, 2):
            s = cairo.ImageSurface(cairo.FORMAT_ARGB32, math.ceil(w * scale), math.ceil(h * scale))
            s.set_device_scale(scale, scale)
            cr = cairo.Context(s)
            size, alpha = (1, 1.5, 2)[layer] * max(1, page.zoom), (.35, .6, .95)[layer]
            cr.set_source_rgba(*color, alpha)
            for xf, y, lay in page._starlist:
                if lay == layer:
                    cr.rectangle(xf * w, y, size, size)
            cr.fill()
            cache["layers"].append(to_texture(s))
    for layer, tex in enumerate(cache["layers"]):
        off = (page.time * (8, 25, 60)[layer] * page.zoom) % w
        for dx in (-off, w - off):
            snap.append_texture(tex, rect(dx, 0, w, h))


def _warp(page, snap, w, h, color):
    """The warp stars, painted with cairo into an image of half the window's size and laid down enlarged: the
    streaks are soft anyway. At full size the window was painted and sent to the graphics card every frame (about
    40 % of a CPU core); as paths or as single turned rectangles it cost as much again on the processor."""
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, math.ceil(w / 2)), max(1, math.ceil(h / 2)))
    cr = cairo.Context(s)
    cr.scale(.5, .5)
    page._warp(cr, w, h, color)
    snap.append_scaled_texture(to_texture(s), Gsk.ScalingFilter.LINEAR, rect(0, 0, s.get_width() * 2, s.get_height() * 2))


def view(page, snap, w, h, sx, sy, ox, scale, glitch, star_cache, grid=(0.0, 0.0), opening=None, bake=None):
    """One frame of the view, w x h, scrolled to (sx, sy); the page is centred by ox. grid: how far the view's
    corner lies past a whole device pixel of the window (in points); the page is moved back onto the pixels.
    opening: (effect, seconds) while the CRT power-on, the dither fade-in, the neon flicker-on or the code rain runs.
    bake(node): draws a node once into an image and returns a node that shows it (the view does it with its
    renderer): the text glow is blurred once that way instead of every frame."""
    global _BAKE
    _BAKE = bake
    chroma = page.cfg.get("chroma") and not page.plain
    mask = page.cfg.get("crt") and page.cfg.get("crt_mask", "lines") != "lines" and not page.plain
    out = Gtk.Snapshot() if chroma or mask else snap
    if opening and opening[0] == "crt":
        scene = Gtk.Snapshot()
        _scene(page, scene, w, h, sx, sy, ox, scale, glitch, star_cache, grid, None)
        _power_on(out, scene.to_node(), w, h, opening[1], scale)
    else:
        _scene(page, out, w, h, sx, sy, ox, scale, glitch, star_cache, grid, opening)
    if not (chroma or mask):
        return
    node = out.to_node()
    if mask:   # the colour mask multiplied with the picture: one repeated tile, cheap for the graphics card
        snap.push_blend(Gsk.BlendMode.MULTIPLY)
    if chroma:
        _fringe(snap, node, w, h, scale, page._colors()[0])
    else:
        append(snap, node)
    if mask:
        snap.pop()
        tex, tw, th = _mask_texture(page.cfg["crt_mask"])
        tw, th = tw / scale, th / scale   # one pixel of the tile is one device pixel
        snap.push_repeat(rect(0, 0, w, h), rect(0, 0, tw, th))
        snap.append_scaled_texture(tex, Gsk.ScalingFilter.NEAREST, rect(0, 0, tw, th))
        snap.pop()
        snap.pop()


_MASKS = {}


def _mask_texture(kind):
    """The tile of a colour mask (overlays.mask_tile) as a texture, made once."""
    if kind not in _MASKS:
        tile = mask_tile(kind)
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, len(tile[0]), len(tile))
        data, stride = s.get_data(), s.get_stride()
        for y, row in enumerate(tile):
            for x, (r, g, b) in enumerate(row):
                data[y * stride + x * 4:y * stride + x * 4 + 4] = bytes((round(b * 255), round(g * 255), round(r * 255), 255))
        s.mark_dirty()
        _MASKS[kind] = (to_texture(s), len(tile[0]), len(tile))
    return _MASKS[kind]


def _luma_to(channel):
    """A colour matrix that turns the picture's brightness into one colour channel (0 red, 2 blue), the others 0.
    GSK multiplies the colour as a row vector: float 4*i + j is how much input i goes into output j."""
    f = [0.0] * 16
    for i, k in enumerate((.18, .35, .07)):   # brightness, at 60 %: the picture keeps its own colour
        f[4 * i + channel] = k
    f[15] = 1
    m = Graphene.Matrix()
    m.init_from_float(f)
    return m


LUMA = None


def _fringe(snap, node, w, h, scale, bg):
    """The colour fringe of an old tube: red seams on one side of every edge, blue on the other. The seams are the
    difference between the picture's brightness shifted a little and unshifted, drawn in red and blue, so they show on
    any theme (a green terminal has almost no red or blue to split). Added on dark themes, taken off on light ones."""
    global LUMA
    if LUMA is None:
        LUMA = [(_luma_to(c), Graphene.Vec4().init(0, 0, 0, 0)) for c in (0, 2)]
    shift = max(1, round(2 * scale)) / scale   # two device pixels: one was too faint to notice at 100 % zoom
    mode = Gsk.BlendMode.SCREEN if is_dark(bg) else Gsk.BlendMode.DIFFERENCE

    def ghost(i, dx):
        matrix, offset = LUMA[i]
        snap.save()
        snap.translate(point(dx, 0))
        snap.push_color_matrix(matrix, offset)
        snap.append_color(rgba(bg), rect(-shift, 0, w + 2 * shift, h))   # no bare stripe at the window's edges
        append(snap, node)
        snap.pop()
        snap.restore()

    def seam(i, dx):
        snap.push_blend(Gsk.BlendMode.DIFFERENCE)
        ghost(i, dx)
        snap.pop()
        ghost(i, 0)
        snap.pop()
    clip(snap, 0, 0, w, h, scale)
    snap.push_blend(mode)                       # (picture + red) + blue
    snap.push_blend(mode)                       # picture + red
    append(snap, node)
    snap.pop()
    seam(0, -shift)
    snap.pop()
    snap.pop()
    seam(1, shift)
    snap.pop()
    snap.pop()


def _scene(page, snap, w, h, sx, sy, ox, scale, glitch, star_cache, grid, opening):
    bg = page._colors()[0]
    snap.append_color(rgba(bg), rect(0, 0, w, h))
    stars(page, snap, w, h, scale, star_cache)
    sx, sy = round(sx * scale) / scale, round(sy * scale) / scale   # whole device pixels: crisp blocks and text
    snap.save()
    snap.translate(point(-sx - grid[0], -sy - grid[1]))
    dither = opening and opening[0] == "dither"
    rain = opening and opening[0] == "rain"
    if glitch is None and page.reveal is None and not dither and not rain:
        content(page, snap, sx, sy, w, h, ox, scale, opening)
    else:
        sub = Gtk.Snapshot()
        content(page, sub, sx, sy, w, h, ox, scale, opening)
        node = sub.to_node()
        if page.reveal is not None:
            _modem(page, snap, node, sx, ox, w, scale)
        elif dither:
            _dither(page, snap, node, sx, sy, w, h, opening[1], scale)
        elif rain:
            _rain(page, snap, node, sx, sy, w, h, ox, opening[1], scale)
        else:
            _glitch(snap, node, sx, sy, w, h, glitch, scale)
    snap.restore()


def _power_on(snap, node, w, h, t, scale):
    """The CRT power-on: black, then a bright line that widens across the screen, then the picture grows out of it
    from the middle, overexposed at first."""
    snap.append_color(rgba((0, 0, 0)), rect(0, 0, w, h))
    line_from, grow_from = .12, .42
    if t < line_from:
        return
    cy, px = h / 2, 1 / scale
    if t < grow_from:
        width = w * ((t - line_from) / (grow_from - line_from)) ** .6
        snap.append_color(rgba((.8, .88, 1), .22), rect((w - width) / 2, cy - 3 * px, width, 6 * px))
        snap.append_color(rgba((.95, .98, 1)), rect((w - width) / 2, cy - px, width, 2 * px))
        return
    u = min(1.0, (t - grow_from) / (OPENING_END["crt"] - grow_from))
    grown = 1 - (1 - u) ** 3
    height = max(2 * px, h * grown)
    clip(snap, 0, cy - height / 2, w, height, scale)
    snap.save()
    snap.translate(point(0, cy))
    snap.scale(1, max(grown, .002))
    snap.translate(point(0, -cy))
    append(snap, node)
    snap.restore()
    snap.append_color(rgba((.88, .94, 1), .55 * (1 - u) ** 2), rect(0, cy - height / 2, w, height))
    snap.pop()


_DITHER = {}
BAYER = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))   # which of 16 pixels light up at a level


def _dither_texture(level):
    """A 4 x 4 pixel pattern with level (.25, .5, .75) of its pixels set, like the shades ░ ▒ ▓."""
    if level not in _DITHER:
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4)
        cr = cairo.Context(s)
        cr.set_source_rgb(1, 1, 1)
        for y in range(4):
            for x in range(4):
                if BAYER[y][x] < level * 16:
                    cr.rectangle(x, y, 1, 1)
        cr.fill()
        _DITHER[level] = to_texture(s)
    return _DITHER[level]


def _dither(page, snap, node, sx, sy, w, h, t, scale):
    """The dither fade-in: a wave runs down the window; behind it the page is there in steps of ░ ▒ ▓ and then whole.
    Each band of one text row is drawn through a pattern of its level (a mask), so single pixels light up."""
    span = h * .5   # how tall the zone of steps is
    front = min(1.0, t / (OPENING_END["dither"] * .8)) * (h + span)   # the wave is through at 80 % of the time
    band = max(8.0, page.ch)
    whole, steps = 0.0, []
    for k in range(math.ceil(h / band)):
        u = (front - k * band) / span
        if u >= 1:
            whole = (k + 1) * band
        elif u > 0:
            steps.append((k, math.ceil(u * 4) / 4))
    if whole:
        clip(snap, sx, sy, w, min(whole, h), scale)
        append(snap, node)
        snap.pop()
    tile = 4 / scale   # one pattern pixel is one device pixel
    for k, level in steps:
        if level >= 1:
            continue
        clip(snap, sx, sy + k * band, w, band, scale)
        snap.push_mask(Gsk.MaskMode.ALPHA)
        snap.push_repeat(rect(sx, sy + k * band, w, band), rect(0, 0, tile, tile))
        snap.append_scaled_texture(_dither_texture(level), Gsk.ScalingFilter.NEAREST, rect(0, 0, tile, tile))
        snap.pop()
        snap.pop()
        append(snap, node)
        snap.pop()
        snap.pop()


def _neon(p, snap, node, x0, sx, sy, w, h, t, scale):
    """The neon flicker-on: the art in vertical slices, each with its own start; from there it stutters between dark,
    dim and bright, more and more often bright, until it stays on. (A slice is about half a letter.)"""
    slice_w = max(p.cw * 4, 24.0)
    n = max(1, math.ceil(p.cols * p.cw / slice_w))
    for i in range(n):
        left, right = (sx if i == 0 else x0 + i * slice_w), (sx + w if i == n - 1 else x0 + (i + 1) * slice_w)
        u = (t - (.12 + .85 * ((math.sin(i * 12.9898) * 43758.5453) % 1))) / .55
        if u >= 1:
            a = 1.0
        elif u <= 0:
            continue
        else:
            phase = (u * 9) % 1
            a = 1.0 if phase < .25 + .7 * u else (.35 if phase < .6 + .4 * u else 0.0)
        if a <= 0:
            continue
        clip(snap, left, sy, right - left, h, scale)
        if a < 1:
            snap.push_opacity(a)
        append(snap, node)
        if a < 1:
            snap.pop()
        snap.pop()


RAIN_GLYPHS = "01" * 24 + "23456789ABCDEF"   # mostly ones and zeros, now and then a hex digit
RAIN_SHADES = 8    # from the bright head down to the faint end of the trail
RAIN_TRAIL = 12    # characters of trail behind the head


def _rain_glyphs(p, scale):
    """The digits of the code rain as small images, one per digit and shade, in the colour of the art; the head is
    lighter on dark themes. Made once per font, zoom and colours."""
    bg, _tx, art, _link = p._colors()
    key = (p.cfg.get("font"), p.zoom, scale, art, bg)
    cache = p._fx.get("gpu-rain")
    if cache and cache[0] == key:
        return cache[1]
    dark = is_dark(bg)
    head = tuple(v + (1 - v) * .75 for v in art) if dark else art
    w, h = max(1, math.ceil(p.cw * scale)), max(1, math.ceil(p.ch * scale))
    out = {}
    for g in set(RAIN_GLYPHS):
        for shade in range(RAIN_SHADES):
            s = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
            cr = cairo.Context(s)
            cr.scale(scale, scale)
            cr.set_font_options(FO)
            lay = PangoCairo.create_layout(cr)
            lay.set_font_description(p.font())
            lay.set_text(g, -1)
            cr.set_source_rgba(*(head if shade == 0 else art), (1 - shade / RAIN_SHADES) ** 1.4)
            PangoCairo.show_layout(cr, lay)
            out[g, shade] = to_texture(s)
    p._fx["gpu-rain"] = (key, out)
    return out


def _hash(*n):
    """A steady pseudo-random number 0..1 from a few numbers (the same every frame)."""
    return (math.sin(sum(v * k for v, k in zip(n, (12.9898, 78.233, 37.719)))) * 43758.5453) % 1


def _rain(p, snap, node, sx, sy, w, h, ox, t, scale):
    """The code rain: digits fall in every character column of the NFO, a bright one at the head and a fading trail
    behind it; above the trail the page is there. Each column has its own start and speed and is through before the
    end. The page is drawn once, through a mask of the parts already rained in: clipping it column by column made the
    graphics card draw the whole page once per column, which stuttered with heavy styles such as Demoscene."""
    cw, ch = p.cw, p.ch
    x0, y0 = round(ox + p.padx), round(p.pady)
    glyphs = _rain_glyphs(p, scale)
    trail = RAIN_TRAIL * ch
    tick = int(t * 16)   # the digits near the head change quickly, the rest of the trail slowly
    timing = p._fx.get("gpu-rain-timing")
    if timing is None or len(timing) != p.cols:   # seconds per column: done by 2.2 s, the effect runs 2.4 s
        timing = p._fx["gpu-rain-timing"] = [(_hash(c) * .9, .8 + _hash(c, 1) * .5) for c in range(p.cols)]
    # only over the NFO's own columns: the NFO rains in, and a wide window does not cost three times the work
    first, last = max(0, math.floor((sx - x0) / cw)), min(p.cols, math.ceil((sx + w - x0) / cw))
    heads = []
    for c in range(first, last):
        start, fall = timing[c]
        u = (t - start) / fall
        if u > 0:
            heads.append((c, sy + min(u, 1.0) * (h + trail)))
    snap.push_mask(Gsk.MaskMode.ALPHA)
    for c, head in heads:
        if head - trail > sy:   # the page above the trail; the outer columns also open the margins beside them
            left = sx if c == 0 else round((x0 + c * cw) * scale) / scale
            right = sx + w if c == p.cols - 1 else round((x0 + (c + 1) * cw) * scale) / scale
            snap.append_color(rgba(WHITE), rect(left, sy, right - left, round((head - trail - sy) * scale) / scale))
    snap.pop()
    append(snap, node)
    snap.pop()
    count = len(RAIN_GLYPHS)
    for c, head in heads:
        x, row = x0 + c * cw, math.floor((head - y0) / ch)
        for k in range(RAIN_TRAIL):
            y = y0 + (row - k) * ch
            if y + ch < sy or y > sy + h:
                continue
            g = RAIN_GLYPHS[int(_hash(c, row - k, tick if k < 2 else tick // 5) * count)]
            snap.append_texture(glyphs[g, k * RAIN_SHADES // RAIN_TRAIL], rect(x, y, cw, ch))


def _modem(page, snap, node, sx, ox, w, scale):
    """The modem build-up: the page up to the current character, then a block cursor."""
    r, c = page._reveal_cell()
    x0, y0 = round(ox + page.padx), round(page.pady)
    for area in ((sx, 0, w, y0 + r * page.ch), (sx, y0 + r * page.ch, x0 + c * page.cw - sx, page.ch)):
        clip(snap, *area, scale)
        append(snap, node)
        snap.pop()
    snap.append_color(rgba(page._colors()[1]), rect(x0 + c * page.cw, y0 + r * page.ch, page.cw, page.ch))


def _glitch(snap, node, sx, sy, w, h, glitch, scale):
    """The glitch on open: the page torn into shifted strips, like a crackling loader (as in the cairo view)."""
    import random
    append(snap, node)
    rnd = random.Random(int(glitch * 25))
    for _ in range(12):
        y, height, dx = sy + rnd.random() * h, rnd.uniform(3, 36), rnd.uniform(-48, 48)
        clip(snap, sx, y, w, height, scale)
        snap.save()
        snap.translate(point(dx, 0))
        append(snap, node)
        snap.restore()
        snap.pop()
    snap.append_color(rgba(WHITE, .12 * rnd.random()), rect(sx, sy, w, h))


# ------------------------------------------------------------ page

def content(page, snap, sx, sy, w, h, ox, scale, opening=None):
    """The page in page coordinates, the visible part sx, sy, w x h: as page._paint_page draws it with cairo."""
    p = page
    bg, tx, art, link = p._colors()
    # the page starts on a whole device pixel: the block images then map pixel for pixel onto the screen
    ch, x0, y0 = p.ch, round((ox + p.padx) * scale) / scale, round(p.pady * scale) / scale
    lo, hi = max(0, int((sy - y0) / ch)), min(len(p.rows), int((sy + h - y0) / ch) + 1)
    sel_key = (p.sel, id(p.matches), len(p.matches), p.current, p.cfg.get("copy_text_only"))
    append(snap, cached(p, "under", (lo, hi, x0, sel_key, art, id(p.lines)), lambda s: _under(p, s, x0, y0, lo, hi)))
    ramp = [_hex(c) for c in p.cfg.get("ramp_colors", ())] if p.cfg.get("ramp") and not p.colors else None
    cycle = bool(p.cfg.get("cycle")) and not p.colors
    wobble = p.cfg.get("wobble") and not p.colors and p.group
    if wobble:
        top = max(sy, y0 + (min(p.group) - 2) * ch)
        bottom = min(sy + h, y0 + (max(p.group) + 3) * ch)
        wobble = bottom > top
    neon = opening is not None and opening[0] == "neon"
    sheen = p.cfg.get("sheen") and not p.colors and not p.plain and p.rows
    # the neon flicker-on lights the art only (the text is there); the gleam is masked by the art
    art_snap = Gtk.Snapshot() if neon or sheen else snap
    place = _placer(art_snap)
    if wobble:
        # the wobble repeats: at 30 frames a second the wave goes through PHASES positions. Each image of the art
        # (glow, blocks) is laid out in strips once per position and scroll place, and that is reused; the cycling
        # colours and the pulse wrap it every frame as usual
        phase = round(p.time * 4 / (2 * math.pi) * PHASES) % PHASES
        strips = _strips(p, sy, h, top, bottom, y0, scale, phase * 2 * math.pi / PHASES)
        nodes = p._fx.setdefault("gpu-wobble", {})

        def wobbled(tex, filt, x, y, bw, bh):
            key = (id(tex), filt, x, y, bw, bh, phase, sx, sy, w, h, scale, p.cfg.get("wobble_amount"))
            if key not in nodes:
                if len(nodes) > 4 * PHASES:   # an old scroll place or size
                    nodes.clear()
                sub = Gtk.Snapshot()
                for ys, hs, dx in strips:   # on whole device pixels already
                    clip(sub, sx, ys, w, hs, scale)
                    sub.append_texture(tex, rect(x + dx, y, bw, bh))
                    sub.pop()
                nodes[key] = (tex, sub.to_node())   # the texture is kept with it, so its id stays unique
            append(art_snap, nodes[key][1])
        place = wobbled
    _art(p, art_snap, place, x0, y0, lo, hi, sx, sy, w, h, art, ramp, cycle, scale)
    if neon or sheen:
        art_node = art_snap.to_node()
        if neon:
            _neon(p, snap, art_node, x0, sx, sy, w, h, opening[1], scale)
        else:
            append(snap, art_node)
        if sheen and art_node is not None:
            _sheen(p, snap, art_node, x0, sx, sy, w, h)
    if p.cfg.get("sparkle") and not p.colors and not p.plain:
        _sparkle(p, snap, x0, y0, lo, hi, bg, art, scale)
    key = (lo, hi, x0, p.zoom, p.cfg.get("font"), tx, art, link, id(p.lines))
    text = cached(p, "text", key, lambda s: _text(p, s, x0, y0, lo, hi, tx, art, link))
    if p.cfg.get("text_glow") and not p.plain:   # the text blurred twice, wide and tight, under the sharp text
        append(snap, cached(p, "text-glow", (key, scale, _BAKE is not None), lambda s: _text_glow(s, text, ch)))
    append(snap, text)


def _text_glow(snap, text, ch):
    """The blurred text, made into an image once (it only changes with the text): blurring it every frame cost more
    than everything else together, three times over with the colour fringe."""
    glow = Gtk.Snapshot()
    for radius, alpha in ((max(2.0, ch * .2), .7), (max(4.0, ch * .5), .5)):
        glow.push_opacity(alpha)
        glow.push_blur(radius)
        append(glow, text)
        glow.pop()
        glow.pop()
    node = glow.to_node()
    append(snap, _BAKE(node) if _BAKE and node is not None else node)


SHEEN_EVERY, SHEEN_SWEEP = 6.0, 1.4   # seconds: a gleam every 6 s, crossing the art in 1.4 s


def _sheen(p, snap, art_node, x0, sx, sy, w, h):
    """The gleam: now and then a slanted band of light sweeps across the art from left to right. The art is the
    mask, so only the blocks (and faintly their glow) light up, never the background."""
    u = (p.time % SHEEN_EVERY) / SHEEN_SWEEP
    if u >= 1:
        return
    band, slant = max(5 * p.cw, 36.0), h * .35   # the band leans: its top runs ahead of its bottom
    left, right = max(sx, x0) - band - slant, min(sx + w, x0 + p.cols * p.cw) + band + slant
    cx, cy = left + (right - left) * u, sy + h / 2
    snap.push_mask(Gsk.MaskMode.ALPHA)
    append(snap, art_node)
    snap.pop()
    snap.append_linear_gradient(rect(sx, sy, w, h), point(cx - band / 2, cy + band * .2),
                                point(cx + band / 2, cy - band * .2),
                                astops(((0, WHITE, 0), (.42, WHITE, .5), (.5, WHITE, .75), (.58, WHITE, .5), (1, WHITE, 0))))
    snap.pop()


SPARKLES = {"few": 4, "some": 8, "many": 16}   # glints at a time
SPARKLE_LIFE = .8   # seconds each one lasts


def _art_cells(p):
    """All cells of the page that hold a block of art, by row: [(row, column)], made once per page."""
    cells = p._fx.get("gpu-art-cells")
    if cells is None:
        cells = p._fx["gpu-art-cells"] = [(r, b[0]) for r, row in enumerate(p.rows) for b in row[2]]
    return cells


def _sparkle(p, snap, x0, y0, lo, hi, bg, art, scale):
    """Glints: a few blocks of the visible art light up as a small four-pointed star that grows and fades, each in
    its own rhythm; then the next one somewhere else."""
    import bisect
    cells = _art_cells(p)
    first, last = bisect.bisect_left(cells, (lo, -1)), bisect.bisect_left(cells, (hi, -1))
    if last <= first:
        return
    dark = is_dark(bg)
    color = WHITE if dark else tuple(v * .6 for v in art)
    px = 1 / scale
    for k in range(SPARKLES.get(p.cfg.get("sparkle_amount"), 8)):
        phase = p.time / SPARKLE_LIFE + k * .618 * 3
        turn, u = math.floor(phase), phase % 1
        r, c = cells[first + int(_hash(k, turn) * (last - first))]
        glow = math.sin(u * math.pi) ** 2
        if glow < .02:
            continue
        cx, cy = x0 + (c + .5) * p.cw, y0 + (r + .5) * p.ch
        arm, thick = p.ch * (.35 + .55 * glow), max(px, p.cw * .14)
        snap.append_radial_gradient(rect(cx - arm, cy - arm, 2 * arm, 2 * arm), point(cx, cy), arm * .6, arm * .6, 0, 1,
                                    astops(((0, color, .55 * glow), (1, color, 0))))
        snap.append_linear_gradient(rect(cx - arm, cy - thick / 2, 2 * arm, thick), point(cx - arm, cy),
                                    point(cx + arm, cy), astops(((0, color, 0), (.5, color, glow), (1, color, 0))))
        snap.append_linear_gradient(rect(cx - thick / 2, cy - arm, thick, 2 * arm), point(cx, cy - arm),
                                    point(cx, cy + arm), astops(((0, color, 0), (.5, color, glow), (1, color, 0))))


def still_layer(snap, w, h, widget, key, paint):
    """A layer painted once with cairo (paint(cr, w, h)), kept as a texture at the screen's pixels until its size or
    key changes. A cairo layer (Gtk.DrawingArea) is uploaded to the graphics card again on every redraw of the
    window; a texture stays there."""
    native = widget.get_native()
    scale = native.get_surface().get_scale() if native and native.get_surface() else widget.get_scale_factor()
    full = (w, h, scale, key)
    cache = widget.__dict__.setdefault("_still", {})
    if cache.get("key") != full:
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, math.ceil(w * scale)), max(1, math.ceil(h * scale)))
        s.set_device_scale(scale, scale)
        paint(cairo.Context(s), w, h)
        cache["key"], cache["tex"] = full, to_texture(s)
    snap.append_texture(cache["tex"], rect(0, 0, math.ceil(w * scale) / scale, math.ceil(h * scale) / scale))


_NOISE = {}


NOISE_ALPHA = 16   # of 255: faint grain

def noise(snap, w, h, t, flicker=0.0):
    """Picture noise for the living tube: a tile of grey grain, laid over the window from a new place every frame.
    The faintness is in the tile itself: the opacity of the widget is not applied to a repeated texture by the
    Vulkan renderer of GTK 4.24, which covered the whole window in grain."""
    import random
    if "tex" not in _NOISE:
        rnd, size = random.Random(7), 128
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
        data = s.get_data()
        for i in range(size * size):
            v = rnd.randrange(256) * NOISE_ALPHA // 255   # premultiplied
            data[i * 4:i * 4 + 4] = bytes((v, v, v, NOISE_ALPHA))
        s.mark_dirty()
        _NOISE["tex"], _NOISE["size"] = to_texture(s), size
    if flicker:   # the brightness flicker of the tube, as black at an alpha
        snap.append_color(rgba((0, 0, 0), flicker), rect(0, 0, w, h))
    size = _NOISE["size"]
    ox, oy = _hash(int(t * 30)) * size, _hash(int(t * 30), 1) * size
    # the tile laid down side by side: a repeat node with a new offset every frame made the Vulkan renderer draw the
    # pattern through an extra image each time (about a third of a CPU core)
    for x in range(-int(ox), w, size):
        for y in range(-int(oy), h, size):
            snap.append_texture(_NOISE["tex"], rect(x, y, size, size))


def _placer(snap):
    def place(tex, filt, x, y, bw, bh):
        snap.append_texture(tex, rect(x, y, bw, bh))
    return place


def _under(p, snap, x0, y0, lo, hi):
    """What lies under the art and the text and only changes with the selection: ANSI backgrounds (a rectangle per
    run of equal colour), search matches, the selection."""
    cw, ch, art = p.cw, p.ch, p._colors()[2]
    if p.colors:
        for r in range(lo, hi):
            row, c = p.colors[r], 0
            while c < len(row):
                e = c
                while e < len(row) and row[e][1] == row[c][1]:
                    e += 1
                if row[c][1] != VGA[0]:
                    snap.append_color(rgba(row[c][1]), rect(x0 + round(c * cw), y0 + r * ch,
                                                            round(e * cw) - round(c * cw), ch))
                c = e
    for i, (r, a, b) in enumerate(p.matches):
        if lo <= r < hi:
            snap.append_color(rgba((1, .75, 0), .9 if i == p.current else .4), rect(x0 + a * cw, y0 + r * ch,
                                                                                     (b - a) * cw, ch))
    color = rgba(VGA[7] if p.colors else art, .3)
    for r, a, end in p.selection_rows(lo, hi):
        for x, y, rw, rh in p.run_rects(x0, y0, r, a, end, p.cfg.get("copy_text_only")):
            snap.append_color(color, rect(x, y, rw, rh))


def _cycling(p, snap, ramp, bounds):
    """The colour cycling bands over bounds (to be masked by the blocks)."""
    colors, period, hard, shift = p.cycle_bands(ramp)
    n = len(colors)
    if hard:
        pairs = [pair for i, c in enumerate(colors) for pair in ((i / n, c), ((i + 1) / n - 1e-6, c))]
    else:
        pairs = [(i / n, c) for i, c in enumerate(colors)] + [(1, colors[0])]
    snap.append_repeating_linear_gradient(bounds, point(0, -shift), point(0, period - shift), stops(pairs))


def _art(p, snap, place, x0, y0, lo, hi, sx, sy, w, h, art, ramp, cycle, scale):
    """Glow and blocks: cached images placed (by place), faded (the pulse) and, for the colour cycling, used as a
    mask over moving colour bands. The fade and the mask wrap all strips of a wobbling logo at once."""
    glow = p.glow_parts()
    if glow and glow[0] == "halo":   # the halo keeps the art colour while the blocks cycle
        for k, alpha in glow[1]:
            _blur(p, snap, place, x0, y0, art, ramp, k, alpha, sx, w)
    if glow and glow[0] == "soft":
        if _blur(p, snap, place, x0, y0, WHITE if cycle else art, None if cycle else ramp, glow[1], 1.0, sx, w,
                 cycle, ramp):
            return
    layer = p._block_layer(None, art, ramp, cycle, scale)
    if layer is None:   # a page too big to keep as an image: the visible blocks drawn with cairo (no wobble)
        cr = snap.append_cairo(rect(sx, sy, w, h))
        cr.set_antialias(cairo.ANTIALIAS_NONE)
        p._draw_blocks(cr, x0, y0, art, lo, hi, ramp, p._cycle(ramp) if cycle else None)
        return
    s = layer.get_device_scale()[0]
    bounds = (x0, y0, layer.get_width() / s, layer.get_height() / s)
    _masked(p, snap, place, texture(p, layer), Gsk.ScalingFilter.NEAREST, bounds, cycle, ramp, sx, w)


def _masked(p, snap, place, tex, filt, bounds, cycling, ramp, sx, w):
    """Place one image of the art; cycling: as the mask of the moving colour bands. The bands run across the
    whole width, so a sideways wobble of the mask needs no other bands."""
    if not cycling:
        place(tex, filt, *bounds)
        return
    snap.push_mask(Gsk.MaskMode.ALPHA)
    place(tex, filt, *bounds)
    snap.pop()
    _cycling(p, snap, ramp, rect(sx, bounds[1], w, bounds[3]))
    snap.pop()


def _blur(p, snap, place, x0, y0, color, ramp, k, alpha, sx, w, cycling=False, cycle_ramp=None):
    """A blurred copy of the blocks (made once, at 1/k size) scaled up smoothly; cycling: as the mask of the cycling
    colours (from cycle_ramp). False when the page is too big for it."""
    blurred = p._blurred(color, ramp, k)
    if blurred is None:
        return False
    small, m = blurred
    bounds = (x0 - m, y0 - m, small.get_width() * k, small.get_height() * k)
    if alpha < 1:
        snap.push_opacity(alpha)
    _masked(p, snap, place, texture(p, small), Gsk.ScalingFilter.LINEAR, bounds, cycling, cycle_ramp, sx, w)
    if alpha < 1:
        snap.pop()
    return True


def _strips(p, sy, h, top, bottom, y0, scale, phase):
    """The wobbling logo as [(y, height, dx)]: strips of 2 device pixels over the rows of art between top and bottom,
    each shifted sideways on a sine wave at phase (as page._wobble); rows without art, and everything above and
    below the logo, in still pieces. All edges and shifts lie on whole device pixels (see clip); neighbours that
    move alike are one strip."""
    amplitude = p.ch * WOBBLE.get(p.cfg.get("wobble_amount"), WOBBLE["mid"])
    first, last = math.floor(top * scale), math.ceil(bottom * scale)
    pieces = [(sy, first / scale - sy, 0.0), (last / scale, sy + h - last / scale, 0.0)]
    for d in range(first, last, 2):
        y = d / scale
        dx = 0.0
        if int((y - y0) // p.ch) in p.group:
            dx = round(amplitude * math.sin(y / (p.ch * .75) + phase) * scale) / scale
        height = min(d + 2, last) / scale - y
        if pieces[-1][2] == dx and abs(pieces[-1][0] + pieces[-1][1] - y) < 1e-9:
            pieces[-1] = (pieces[-1][0], pieces[-1][1] + height, dx)
        else:
            pieces.append((y, height, dx))
    return [piece for piece in pieces if piece[1] > 0]


def _text(p, snap, x0, y0, lo, hi, tx, art, link):
    """The text and the line graphics of rows lo..hi as Pango layouts (the same layouts as in the cairo drawing)."""
    layouts = p._fx.setdefault("gpu-layouts", {})
    key = (p.cfg.get("font"), link)
    if layouts.get("key") != key:
        layouts.clear()
        layouts["key"] = key
    cr = p._fx.get("gpu-cr")
    if cr is None:   # the layouts measure like the cairo text: same font options, no hinting
        cr = p._fx["gpu-cr"] = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
        cr.set_font_options(FO)
    for r in range(lo, hi):
        if r not in layouts:
            layouts[r] = [(p._layout(cr, s, r, link, is_text), color)
                          for s, color, is_text in ((p.rows[r][0], tx, True), (p.rows[r][1], art, False)) if s]
        for lay, color in layouts[r]:
            snap.save()
            snap.translate(point(x0, y0 + r * p.ch))
            snap.append_layout(lay, rgba(color))
            snap.restore()
