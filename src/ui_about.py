# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""Artwork of the About dialog. Code-Cat: the pixel cat behind the easter egg (five quick clicks on the logo).

This file is the core of TrustCopy and HashTally without their shared scene "check", plus one parameter: nyan(lines=False) leaves out the
speed lines when a scene draws its own trail. It holds the cat, her drawing and her movement, the stage (a popover over the logo)
What she does is a scene, a function scene(stage) -> (draw(cr, t), duration in seconds); the
scenes are in ui_about_art.py."""
import math
import random
import time

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from i18n import _

P = 4  # screen pixels per sprite pixel (files, folders, ...)
CP = 3  # ... and per cat pixel
COLORS = {}  # the colours of the sprites a scene draws: letter -> (r, g, b); scenes add theirs
OUTLINE, GREY, STRIPE, WHITE, CHEEK, ORANGE = (.1, .1, .15), (.62, .62, .68), (.36, .36, .42), (1, 1, 1), (1, .55, .65), (.9, .6, .1)
CAT_W, CAT_H = 24 * CP, 16 * CP


def lerp(a, b, f):
    return a + (b - a) * f


def clamp(v):
    return max(0.0, min(1.0, v))


def jump(f, a, b, lift):
    """Position at f (0..1) of a hop from a to b that rises `lift` pixels in the middle."""
    return lerp(a[0], b[0], f), lerp(a[1], b[1], f) - lift * 4 * f * (1 - f)


def rects(cr, x, y, flip, scale, color, *boxes):
    """Fill boxes (x, y, w, h in cat pixels); flip mirrors them inside the 24 wide cat."""
    cr.set_source_rgb(*color)
    for bx, by, bw, bh in boxes:
        if flip:
            bx = 24 - bx - bw
        cr.rectangle(x + bx * scale, y + by * scale, bw * scale + 0.5, bh * scale + 0.5)
        cr.fill()


def nyan(cr, x, y, flip=False, t=0.0, eating=False, run=False, alert=False, sx=1.0, sy=1.0, air=False, rot=0.0, swipe=False, carry=None, sleep=False, lines=True):
    """The cat: a grey tabby with white paws and muzzle, a big cute head (big eyes, blush, pink ears). Faces right unless flipped.
    run: trotting (diagonal leg pairs, bobbing body, speed lines); air: legs stretched out; alert: exclamation marks;
    sx, sy: squash and stretch around the paws; rot: nose up in radians; swipe: a paw strikes at the file; carry: (art, scale) of a sprite in her mouth; sleep: eyes shut."""
    f, k = flip, CP
    cr.save()
    cr.translate(x + CAT_W / 2, y + CAT_H)
    cr.rotate(rot if flip else -rot)
    cr.scale(sx, sy)
    cr.translate(-x - CAT_W / 2, -y - CAT_H)
    ph = t * 17 if run and not air else 0.0
    bob = 1 if run and not air and math.sin(2 * ph) > 0.2 else 0  # the body rises between the footfalls
    yb = y - bob * k
    yh = yb + (2 * k if eating else 0)  # head dips when it bites
    if run and lines:
        for n, ly in enumerate((6, 9, 12)):
            off = (int(t / 0.08) + n) % 3
            rects(cr, x, y, f, k, GREY, (-9 - off, ly, 5, 1))
    for r in range(9):  # tail: a wave runs up from its root
        dx = round((2.0 if run else 1.3) * math.sin(t * 6 + r * 0.55))
        rects(cr, x, yb, f, k, OUTLINE, (dx, 2 + r, 3, 1))
        rects(cr, x, yb, f, k, STRIPE if r in (2, 5) else GREY, (1 + dx, 2 + r, 1, 1))
    for i, dx in enumerate((4, 8, 14, 18)):  # legs with white paws; opposite corners move together
        p = ph + (math.pi if i in (1, 2) else 0)
        lift = round(max(0.0, math.sin(p)) * 2) if run else 0
        shift = (1 if dx > 10 else -1) if air else (round(math.cos(p) * 1.4) if run else 0)
        rects(cr, x, y, f, k, OUTLINE, (dx - 1 + shift, 11 + lift, 4, 5 - lift))
        rects(cr, x, y, f, k, GREY, (dx + shift, 11 + lift, 2, 2))
        rects(cr, x, y, f, k, WHITE, (dx + shift, 13 + lift, 2, 2 - lift))
    rects(cr, x, yb, f, k, OUTLINE, (3, 5, 14, 9), (2, 6, 16, 7))  # body
    rects(cr, x, yb, f, k, GREY, (4, 6, 12, 7), (3, 7, 14, 5))
    rects(cr, x, yb, f, k, STRIPE, (6, 6, 1, 2), (9, 6, 1, 3), (12, 6, 1, 2))
    rects(cr, x, yb, f, k, WHITE, (5, 11, 8, 2))  # belly
    if carry:  # held in the mouth: drawn first, so the head covers the end that is gripped
        art, cs = carry
        sprite(cr, art, x + (3 * k - len(art[0]) * P * cs if f else 21 * k), yh + 6 * k, cs)
    rects(cr, x, yh, f, k, OUTLINE, (12, 4, 11, 11), (11, 5, 13, 9), (12, 2, 3, 3), (20, 2, 3, 3))  # head with ears
    rects(cr, x, yh, f, k, GREY, (13, 5, 9, 9), (12, 6, 11, 7), (13, 3, 1, 2), (21, 3, 1, 2))
    rects(cr, x, yh, f, k, CHEEK, (14, 3, 1, 2), (20, 3, 1, 2))  # inner ears
    rects(cr, x, yh, f, k, STRIPE, (16, 5, 1, 2), (18, 5, 1, 2), (20, 5, 1, 1))  # forehead stripes
    rects(cr, x, yh, f, k, WHITE, (15, 11, 5, 3), (16, 10, 3, 1))  # muzzle
    rects(cr, x, yh, f, k, CHEEK, (12, 10, 2, 2), (21, 10, 2, 2))  # blush
    if sleep or (int(t * 10) % 27 == 0 and not alert):  # asleep, or a blink
        rects(cr, x, yh, f, k, OUTLINE, (14, 9, 2, 1), (20, 9, 2, 1))
    else:
        rects(cr, x, yh, f, k, OUTLINE, (14, 7, 2, 3), (20, 7, 2, 3))  # eyes
        rects(cr, x, yh, f, k, WHITE, (14, 7, 1, 1), (20, 7, 1, 1), (15, 9, 1, 1), (21, 9, 1, 1))  # sparkles
    rects(cr, x, yh, f, k, CHEEK, (17, 10, 2, 1))  # nose
    if eating or alert:
        rects(cr, x, yh, f, k, OUTLINE, (16, 11, 4, 3))  # open mouth with a tongue
        rects(cr, x, yh, f, k, CHEEK, (17, 13, 2, 1))
    else:
        rects(cr, x, yh, f, k, OUTLINE, (16, 11, 1, 1), (17, 12, 2, 1), (19, 11, 1, 1))
    if swipe:  # a white paw claws at the paper in front of the face
        rects(cr, x, yh, f, k, OUTLINE, (21, 9, 5, 4))
        rects(cr, x, yh, f, k, WHITE, (22, 10, 3, 2))
    if alert:
        rects(cr, x, yh, f, k, ORANGE, (15, -4, 1, 2), (15, -1, 1, 1), (21, -4, 1, 2), (21, -1, 1, 1))
    cr.restore()


def shadow(cr, x, y):
    """Soft shadow of a cat standing on the ground (x, y: the cat's top left)."""
    cr.save()
    cr.translate(x + CAT_W / 2, y + CAT_H)
    cr.scale(CAT_W / 2, 5)
    cr.arc(0, 0, 1, 0, 2 * math.pi)
    cr.restore()
    cr.set_source_rgba(0, 0, 0, 0.18)
    cr.fill()


def sprite(cr, art, x, y, scale=1.0):
    for r, row in enumerate(art):
        for c, ch in enumerate(row):
            if ch in COLORS:
                cr.set_source_rgb(*COLORS[ch])
                cr.rectangle(x + c * P * scale, y + r * P * scale, P * scale + 0.5, P * scale + 0.5)
                cr.fill()


class Stage:
    """Where things are: the popover is centred on the logo, with room above it and a strip of ground below."""

    def __init__(self, size):
        self.size, self.above = size, 56
        self.w, self.h = size + 300, self.above + size + 40
        self.lx, self.ly = (self.w - size) / 2, self.above  # the logo's top left
        self.ground, self.top = self.ly + size, self.ly + 6  # its bottom, and the line she stands on up there
        self.sit_y, self.out_y = self.top - CAT_H, self.ground - CAT_H  # the cat's top when standing on the logo / on the ground


def play(logo, scene):
    """Run `scene` over `logo` (a Gtk.Image); ignores further calls while it runs."""
    if getattr(logo, "cat_busy", False):
        return
    logo.cat_busy = True
    stage = Stage(logo.get_pixel_size() if logo.get_pixel_size() > 0 else 128)
    draw, duration = scene(stage)
    start = time.monotonic()

    def tick():
        area.queue_draw()
        if time.monotonic() - start < duration:
            return GLib.SOURCE_CONTINUE
        pop.popdown()
        pop.unparent()
        logo.cat_busy = False
        return GLib.SOURCE_REMOVE

    area = Gtk.DrawingArea(content_width=stage.w, content_height=stage.h)
    area.set_draw_func(lambda a, cr, aw, ah: draw(cr, time.monotonic() - start))
    pop = Gtk.Popover(child=area, has_arrow=False, autohide=False, can_target=False, position=Gtk.PositionType.BOTTOM)
    pop.add_css_class("k-cat")
    pop.set_parent(logo)
    pop.set_offset(0, -stage.above - stage.size)  # BOTTOM puts the popover under the logo: lift it so the logo sits in its middle
    pop.popup()
    GLib.timeout_add(16, tick)


def hint(logo, text=None):
    """A small note over the logo for a moment (None: take the old one away); a new note replaces the one before."""
    old = getattr(logo, "cat_hint", None)
    logo.cat_hint = None
    if old:
        old.popdown()
        old.unparent()
    if not text:
        return
    pop = Gtk.Popover(child=Gtk.Label(label=text), autohide=False, can_target=False, position=Gtk.PositionType.TOP)
    pop.set_parent(logo)
    pop.popup()
    logo.cat_hint = pop

    def gone():
        if logo.cat_hint is pop:
            hint(logo)
        return GLib.SOURCE_REMOVE
    GLib.timeout_add(1200, gone)


def attach(dialog, scenes):
    """Five quick clicks on the logo in an Adw.AboutDialog play one of `scenes`, never the same twice in a row; the cat then joins the credits."""
    def first_image(widget):
        if isinstance(widget, Gtk.Image):
            return widget
        child = widget.get_first_child()
        while child:
            if (found := first_image(child)):
                return found
            child = child.get_next_sibling()

    logo = first_image(dialog)
    if not logo:
        return  # libadwaita changed its layout: no egg, no harm
    unlocked, last = [], []
    clicks, last_click = 0, 0.0   # our own count: GTK's n_press starts over after 0.4 s or when the pointer moves a little

    def clicked(gesture, n_press, *a):
        nonlocal clicks, last_click
        now = time.monotonic()
        clicks = clicks + 1 if now - last_click < 1.5 else 1   # slow clicking (one every 1.5 s at most) counts too
        last_click, n = now, clicks
        if n in (2, 3, 4):  # like Android's developer options: a note counts down the last clicks
            hint(logo, (_("3 more clicks …"), _("2 more clicks …"), _("1 more click …"))[n - 2])
        if n == 5:
            clicks = 0
            hint(logo)
            scene = random.choice([sc for sc in scenes if sc not in last] or scenes)
            last[:] = [scene]
            play(logo, scene)
            if not unlocked:
                unlocked.append(1)
                dialog.add_credit_section(_("Mascot"), ["Code-Cat"])
    click = Gtk.GestureClick()
    click.connect("pressed", clicked)
    logo.add_controller(click)
