# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""The NFO view: shows the page (drawn by the graphics card, see gpu.py), scrolls itself (only as big as the
window), selects text by dragging (and keeps scrolling past the edge) and opens links on a click."""
import math

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Graphene", "1.0")
from gi.repository import GLib, GObject, Graphene, Gtk  # noqa: E402

import gpu  # noqa: E402

EDGE = 32   # px inside the view's edge where dragging a selection already scrolls


class View(Gtk.Widget, Gtk.Scrollable):
    """Shows the page; selection by dragging, links by clicking.

    The view is only as big as the window and scrolls itself (Gtk.Scrollable): a frame of an animation then builds
    one window full, never the whole NFO."""
    __gtype_name__ = "NfoGlowView"
    hadjustment = GObject.Property(type=Gtk.Adjustment)
    vadjustment = GObject.Property(type=Gtk.Adjustment)
    hscroll_policy = GObject.Property(type=Gtk.ScrollablePolicy, default=Gtk.ScrollablePolicy.MINIMUM)
    vscroll_policy = GObject.Property(type=Gtk.ScrollablePolicy, default=Gtk.ScrollablePolicy.MINIMUM)

    def __init__(self, page):
        super().__init__(focusable=True, overflow=Gtk.Overflow.HIDDEN)   # nothing beyond its edges (C64 border)
        self.page = page
        for name in ("hadjustment", "vadjustment"):
            self.connect(f"notify::{name}", self._adjustment_set)
        self._scroll, self._overshoot = None, (0, 0, 0, 0)
        self.glitch = None   # seconds into the glitch on open, or None
        self.opening = None  # (effect, seconds) while the CRT power-on, dither fade-in, neon flicker-on or code rain runs
        self._stars = {}     # the starfield images for the current window size
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._begin)
        drag.connect("drag-update", self._update)
        drag.connect("drag-end", self._end)
        self.add_controller(drag)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda _c, x, y: self.set_cursor_from_name(
            "pointer" if self.page.link_at(*self.cell(x, y)) else "text"))
        self.add_controller(motion)
        self.refresh()

    def _adjustment_set(self, *_a):
        for adj in (self.hadjustment, self.vadjustment):
            if adj is not None and not getattr(adj, "_nfoglow", False):
                adj._nfoglow = True
                adj.connect("value-changed", lambda *a: self.queue_draw())
        self._configure()

    def _configure(self):
        """Tell the scroll bars how big the page is and how much of it fits."""
        for adj, total, shown in ((self.hadjustment, self.page.width, self.get_width()),
                                  (self.vadjustment, self.page.height, self.get_height())):
            if adj is not None:
                upper = max(total, shown)
                adj.configure(min(adj.get_value(), upper - shown), 0, upper, 40, shown * .9, shown)

    def scrolled(self):
        return (self.hadjustment.get_value() if self.hadjustment else 0,
                self.vadjustment.get_value() if self.vadjustment else 0)

    def do_size_allocate(self, width, height, baseline):
        self._configure()

    def do_snapshot(self, snap):
        native = self.get_native()
        scale, grid = self.get_scale_factor(), (0.0, 0.0)
        if native and native.get_surface():
            # where the view starts in the window's pixels: at 125 % it can lie on half a pixel, then the page is
            # moved by that fraction, so the blocks sit on whole pixels and stay sharp
            scale = native.get_surface().get_scale()
            ok, at = self.compute_point(native, Graphene.Point().init(0, 0))
            dx, dy = native.get_surface_transform()
            if ok:
                grid = tuple(((v + d) * scale) % 1 / scale for v, d in ((at.x, dx), (at.y, dy)))
        w, h, root = self.get_width(), self.get_height(), self.get_root()
        if native and getattr(root, "_overlay_moving", None) and root._overlay_moving() and not root._animating_page():
            # the page stands still, but the tube or the scroller over it move: GTK then puts the whole window together
            # again every frame, glow, blur and colour fringe included. So the page is drawn once into an image (on
            # whole device pixels) and only that image is laid down each frame.
            sub = Gtk.Snapshot()
            gpu.view(self.page, sub, w, h, *self.scrolled(), self.offset(), scale, self.glitch, self._stars, (0.0, 0.0),
                     self.opening)
            node = sub.to_node()
            if node is None:
                return
            pw, ph = math.ceil(w * scale) + 1, math.ceil(h * scale) + 1
            scaled = Gtk.Snapshot()
            scaled.scale(scale, scale)
            scaled.append_node(node)
            tex = native.get_renderer().render_texture(scaled.to_node(), Graphene.Rect().init(0, 0, pw, ph))
            snap.append_texture(tex, Graphene.Rect().init(-grid[0], -grid[1], pw / scale, ph / scale))
            return
        gpu.view(self.page, snap, w, h, *self.scrolled(), self.offset(), scale, self.glitch, self._stars, grid,
                 self.opening, bake=lambda node: self._bake(node, scale))

    def _bake(self, node, scale):
        """The node drawn once into an image at the screen's pixels, and a node that shows that image in its place."""
        bounds = node.get_bounds()
        pw, ph = math.ceil(bounds.get_width() * scale), math.ceil(bounds.get_height() * scale)
        if pw < 1 or ph < 1:
            return node
        scaled = Gtk.Snapshot()
        scaled.scale(scale, scale)
        scaled.translate(Graphene.Point().init(-bounds.get_x(), -bounds.get_y()))
        scaled.append_node(node)
        tex = self.get_native().get_renderer().render_texture(scaled.to_node(), Graphene.Rect().init(0, 0, pw, ph))
        out = Gtk.Snapshot()
        out.append_texture(tex, Graphene.Rect().init(bounds.get_x(), bounds.get_y(), pw / scale, ph / scale))
        return out.to_node()

    def refresh(self):
        self._configure()
        self.queue_draw()

    def offset(self):
        """The page is centred when the window is wider."""
        return max(0, (self.get_width() - self.page.width) / 2)

    def cell(self, x, y):
        """The (row, column) under a point of the view (window coordinates)."""
        sx, sy = self.scrolled()
        x, y = x + sx, y + sy
        p, n = self.page, len(self.page.rows)
        if not n:
            return 0, 0
        r = min(max(int((y - p.pady) // p.ch), 0), n - 1)
        c = min(max(int((x - self.offset() - p.padx) // p.cw), 0), max(len(p.lines[r]) - 1, 0))
        return r, c

    def _begin(self, _g, x, y):
        if hasattr(self.get_root(), "skip_opening"):   # a click ends an effect on opening
            self.get_root().skip_opening()
        if self._scroll is not None:   # the last drag's timer can still be pending: two would scroll twice as fast
            GLib.source_remove(self._scroll)
        self._start, self._scroll = self.cell(x, y), None
        self.grab_focus()

    def _update(self, g, dx, dy):
        _ok, x, y = g.get_start_point()
        x, y = x + dx, y + dy
        self._select_to(x, y)
        # near or past an edge of the view (left and right only matter when zoomed in): keep scrolling (and
        # selecting) while the pointer stays there. The zone inside the edge is for a maximized window, whose
        # bottom edge is the screen's: the pointer cannot get past it. A drag only scrolls towards where it goes,
        # so one that starts near an edge and moves away does not scroll first; a click (under 4 px) never does.
        def past(v, size, moved):
            if abs(moved) < 4:
                return 0
            if v < EDGE and (v < 0 or moved < 0):
                return v - EDGE
            if v > size - EDGE and (v > size or moved > 0):
                return v - (size - EDGE)
            return 0
        self._overshoot = (x, y, past(x, self.get_width(), dx), past(y, self.get_height(), dy))
        if (self._overshoot[2] or self._overshoot[3]) and self._scroll is None:
            self._scroll = GLib.timeout_add(30, self._autoscroll)

    def _select_to(self, x, y):
        self.page.sel = (self._start, self.cell(x, y))
        self.queue_draw()

    def _autoscroll(self):
        x, y, out_x, out_y = self._overshoot
        if not out_x and not out_y:
            self._scroll = None
            return False
        point, moved = [], False
        for adj, pos, out, size in ((self.hadjustment, x, out_x, self.get_width()),
                                    (self.vadjustment, y, out_y, self.get_height())):
            if out and adj is not None:
                before = adj.get_value()
                adj.set_value(before + max(-60, min(60, out / 3)))   # the closer to the edge and beyond, the faster, up to 60 px per tick
                moved = moved or adj.get_value() != before
            point.append(min(max(pos, 0), size))   # select up to the edge of what is shown, not beyond it
        if not moved:   # nothing left to scroll (a page that fits, or its end): no redrawing 33 times a second; a move of the pointer starts it again
            self._scroll = None
            return False
        self._select_to(*point)
        return True

    def _end(self, _g, dx, dy):
        self._overshoot = (0, 0, 0, 0)   # stops the auto-scroll
        if abs(dx) < 4 and abs(dy) < 4:   # a click, not a drag
            self.page.sel = None
            self.queue_draw()
            url = self.page.link_at(*self._start)
            if url:
                uri = url if url.lower().startswith(("http", "mailto:")) else "https://" + url
                Gtk.UriLauncher(uri=uri).launch(self.get_root(), None, None)
