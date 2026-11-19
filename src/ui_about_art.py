# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""NfoGlow's Code-Cat scenes (SCENES; one is picked at random): the chase (a mouse, with the colour ramp as her trail), the tube (she
switches on a CRT) and the scroller (she reads a demoscene scroller with her own name in it). The core is in ui_about.py."""
import math

import cairo
import gi

gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo

from ui_about import CAT_W, COLORS, CP, clamp, jump, lerp, nyan, shadow, sprite

RAMP = [(.45, .94, 1), (.3, .55, 1), (.85, .3, 1)]   # the colour ramp of the window; the app sets it before the dialog opens
DARK = (.1, .1, .15)


def ramp(k):
    """The colour k (0..1) of the way through the ramp."""
    k = clamp(k) * (len(RAMP) - 1)
    i = min(int(k), len(RAMP) - 2)
    return tuple(a + (b - a) * (k - i) for a, b in zip(RAMP[i], RAMP[i + 1]))


# The way in and out that the tube and the scroller share: she comes out from behind the logo, winds up, jumps onto it, sits there,
# and at the end leaps off to the right.
T_OUT, T_JUMP, T_LAND, LEAP = 1.3, 1.7, 2.2, 0.6


def arrive(cr, st, t, sit_x):
    """Until T_LAND: out from behind the logo, the wind-up and the jump onto it. False once she sits."""
    if t >= T_LAND:
        return False
    x0 = st.lx + st.size + 28
    if t < T_OUT:  # only what is right of the logo's edge shows
        cr.save()
        cr.rectangle(st.lx + st.size, 0, st.w, st.h)
        cr.clip()
        x = lerp(st.lx + st.size - CAT_W + 20, x0, t / T_OUT)
        shadow(cr, x, st.out_y)
        nyan(cr, x, st.out_y, t=t, run=True)
        cr.restore()
    elif t < T_JUMP:
        shadow(cr, x0, st.out_y)
        c = clamp((t - T_JUMP + 0.25) / 0.25) * 0.3
        nyan(cr, x0, st.out_y, flip=True, t=t, alert=True, sx=1 + c * 0.6, sy=1 - c, rot=math.sin(t * 45) * 0.06 * c / 0.3)
    else:
        f = (t - T_JUMP) / 0.5
        x, y = jump(f, (x0, st.out_y), (sit_x, st.sit_y), 24)
        nyan(cr, x, y, flip=True, t=t, run=True, air=True, sx=1 - 0.15 * math.sin(math.pi * f), sy=1 + 0.25 * math.sin(math.pi * f), rot=0.4 * math.cos(math.pi * f))
    return True


def sit(cr, st, t, sit_x, t_leap, flip, lift=0.0, squash=0.0, rot=0.0, **look):
    """Sitting on the logo: the landing squash, her breathing, and from 0.3 s before t_leap the crouch. Then the leap off to the right until t_leap + LEAP."""
    if t >= t_leap:
        f = clamp((t - t_leap) / LEAP)
        x, y = jump(f, (sit_x, st.sit_y), (st.lx + st.size + 160, st.out_y), 30)
        nyan(cr, x, y, t=t, run=True, air=f <= 0.9, sx=1 - 0.12 * math.sin(math.pi * f), sy=1 + 0.25 * math.sin(math.pi * f), rot=0.45 * math.cos(math.pi * f))
        return
    tau = t - T_LAND
    land = 0.3 * math.exp(-9 * tau) * math.cos(22 * tau)
    crouch = clamp((t - t_leap + 0.3) / 0.3) ** 2
    s = land + crouch * 0.32 + squash + 0.025 * math.sin(t * 3.5)
    nyan(cr, sit_x, st.sit_y - lift, flip=flip and crouch == 0, t=t, sx=1 + s * 0.6, sy=1 - s, rot=rot - 0.05 * crouch, **look)


def hop(t, t0, height=24):
    """(lift, squash) of a hop of joy (or of fright, a lower one) that starts at t0."""
    if not t0 <= t < t0 + 0.4:
        return 0.0, 0.0
    f = (t - t0) / 0.4
    return height * 4 * f * (1 - f), -0.18 * math.sin(math.pi * f)


# ---------------------------------------------------------------------------------------------------------------------------------
# Chase: a mouse dashes along the ground in front of the logo, the cat after her, and her trail is the colour ramp. Back again the other
# way. She never catches it.
MW, MH = 14, 10   # the mouse in its own pixels
MOUSE = {}


def mouse_sprite(frame):
    """The mouse running to the right in MW x MH pixels; frame 0 stretches the legs, 1 tucks them."""
    m = cairo.ImageSurface(cairo.FORMAT_ARGB32, MW, MH)
    cr = cairo.Context(m)
    cr.set_antialias(cairo.ANTIALIAS_NONE)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)

    def ellipse(cx, cy, rx, ry, color):
        for g, c in ((1, DARK), (0, color)):
            cr.save()
            cr.translate(cx, cy)
            cr.scale(rx + g, ry + g)
            cr.arc(0, 0, 1, 0, 2 * math.pi)
            cr.restore()
            cr.set_source_rgb(*c)
            cr.fill()

    cr.set_source_rgb(.95, .7, .75)   # the tail flicks
    cr.set_line_width(1)
    cr.move_to(3, 6)
    cr.line_to(1, 6 - frame)
    cr.line_to(0, 3 + frame)
    cr.stroke()
    for a, b in (((4, 8), (2, 9)), ((9, 8), (11, 9))) if frame == 0 else (((4, 8), (5, 9)), ((9, 8), (9, 9))):
        cr.set_source_rgb(*DARK)
        cr.set_line_width(2)
        cr.move_to(*a)
        cr.line_to(*b)
        cr.stroke()
    ellipse(7, 5.5, 4.2, 2.8, (.8, .8, .85))   # body, head, ear, nose and eye
    ellipse(11, 5.5, 2.2, 1.8, (.8, .8, .85))
    ellipse(9.5, 3, 1.4, 1.4, (1, .6, .7))
    for x, y, color in ((13, 5, (1, .55, .65)), (11, 4, DARK)):
        cr.set_source_rgb(*color)
        cr.rectangle(x, y, 1, 1)
        cr.fill()
    m.flush()
    return m


def mouse(cr, x, y, flip, t):
    """The mouse with its top left at x, y."""
    frame = int(t * 14) % 2
    if frame not in MOUSE:
        MOUSE[frame] = mouse_sprite(frame)
    cr.save()
    cr.translate(x + (MW * CP if flip else 0), y - frame * CP)
    cr.scale(-CP if flip else CP, CP)
    pattern = cairo.SurfacePattern(MOUSE[frame])
    pattern.set_filter(cairo.FILTER_NEAREST)
    cr.set_source(pattern)
    cr.paint()
    cr.restore()


def trail(cr, x, y, flip, t):
    """The ramp behind the cat at x, y: six stripes that wave in steps and fade out. Her body is its source."""
    length, band = 110, 4
    for d in range(0, length, 6):
        k = d / length
        wave = 3 * (1 if math.sin(t * 12 - d / 14) > 0 else -1)
        for i in range(6):
            cr.set_source_rgba(*ramp(i / 5), (1 - k) ** 1.5)
            bx = x + 21 * CP + d if flip else x + 3 * CP - d - 6
            cr.rectangle(bx, y + 16 + i * band + wave, 6, band)
            cr.fill()


def chase(st):
    w, ground = st.w, st.ground
    speed, lag = 230.0, 0.75
    legs = ((0.2, 1), (3.6, -1))   # when the mouse starts, and which way

    def draw(cr, t):
        for start, d in legs:
            for who, begin, width in (("mouse", start, MW * CP), ("cat", start + lag, CAT_W)):
                run = (t - begin) * speed
                if not 0 <= run <= w + width:
                    continue
                x = run - width if d > 0 else w - run
                if who == "mouse":
                    mouse(cr, x, ground - MH * CP, d < 0, t)
                else:
                    shadow(cr, x, st.out_y)
                    trail(cr, x, st.out_y, d < 0, t)
                    nyan(cr, x, st.out_y, flip=d < 0, t=t, run=True, lines=False)

    return draw, 3.6 + lag + (w + CAT_W) / speed + 0.1


# ---------------------------------------------------------------------------------------------------------------------------------
# Tube: a little CRT rises from behind the logo. The cat sits down beside it, taps the switch, the picture jumps on as a bright line
# that opens up, shows block art in the ramp colours with a glow, flickers and gets her scared, and goes off in a dot.
LETTERS = (("X...X", "XX..X", "X.X.X", "X..XX", "X...X"), ("XXXXX", "X....", "XXXX.", "X....", "X...."),
           (".XXX.", "X...X", "X...X", "X...X", ".XXX."))   # N, F, O
TEXT_LINES = (36, 30, 38, 24, 33)
M_W, M_H, S_X, S_Y, S_W, S_H = 56, 52, 5, 5, 46, 32   # the tube and its screen
C_RISE, C_PRESS, C_ON, C_FLICK, C_OFF, C_SINK, C_LEAP, C_END = 0.3, 2.45, 2.8, 4.5, 5.6, 6.1, 6.5, 7.3


def screen_picture(cr, t):
    """The picture of the screen in its own 46 x 32 pixels."""
    cr.set_source_rgb(.02, .03, .05)
    cr.paint()
    cr.save()
    for c, letter in enumerate(LETTERS):
        for r, row in enumerate(letter):
            for q, ch in enumerate(row):
                if ch == "X":
                    cr.set_source_rgb(*ramp(r / 4))
                    cr.rectangle(2 + (c * 6 + q) * 2.5, 4 + r * 2.5, 2.5, 2.5)
                    cr.fill()
    for i, width in enumerate(TEXT_LINES):
        cr.set_source_rgb(.45, .62, .7)
        cr.rectangle(4, 20 + i * 2.4, width, 1.4)
        cr.fill()
    cr.set_source_rgba(0, 0, 0, .3)   # scanlines
    for y in range(0, S_H, 2):
        cr.rectangle(0, y, S_W, 1)
    cr.fill()
    if C_FLICK <= t < C_FLICK + 0.5:   # flicker and a bright band that rolls down
        cr.set_source_rgba(0, 0, 0, .55 * (math.sin(t * 70) > 0))
        cr.paint()
        cr.set_source_rgba(1, 1, 1, .25)
        cr.rectangle(0, ((t - C_FLICK) * 3 % 1) * S_H, S_W, 5)
        cr.fill()
    cr.restore()


def tube(st):
    size, lx, top = st.size, st.lx, st.top
    sit_x = lx + size - CAT_W + 6
    mx = lx + 4

    def monitor_top(t):
        up = 1 - (1 - clamp((t - C_RISE) / 0.7)) ** 3
        return top - M_H * lerp(up, 0, clamp((t - C_SINK) / 0.4) ** 2)

    def power(t):
        """(width, height, brightness) of the lit part of the screen, 0..1; the line, the opening and the dot of a CRT."""
        on, off = t - C_ON, t - C_OFF
        if on < 0:
            return 0, 0, 0
        if off >= 0:
            if off < 0.2:
                return 1, lerp(1, 0.06, off / 0.2), 1
            if off < 0.35:
                return lerp(1, 0.06, (off - 0.2) / 0.15), 0.06, 1
            return 0.06, 0.06, max(0.0, 1 - (off - 0.35) / 0.15)
        if on < 0.12:
            return on / 0.12, 0.06, 1
        return 1, lerp(0.06, 1, clamp((on - 0.12) / 0.28)), 1

    def monitor(cr, t):
        y = monitor_top(t)
        if y >= top - 1:
            return
        cr.save()
        cr.rectangle(mx - 24, 0, M_W + 48, top)   # comes from behind the logo
        cr.clip()
        pw, ph, bright = power(t)
        if bright:   # the glow around the screen, a soft frame of the ramp's middle colour
            pulse = 0.8 + 0.2 * math.sin(t * 5)
            for i in range(5):
                cr.set_source_rgba(*ramp(.5), .09 * pulse * bright)
                cr.rectangle(mx + S_X - 3 * (i + 1), y + S_Y - 3 * (i + 1), S_W + 6 * (i + 1), S_H + 6 * (i + 1))
                cr.fill()
        cr.set_source_rgb(*DARK)   # neck, base, body
        cr.rectangle(mx + 22, y + 44, 12, 6)
        cr.rectangle(mx + 14, y + 49, 28, 3)
        cr.fill()
        cr.set_source_rgb(.3, .32, .38)
        cr.rectangle(mx, y, M_W, 45)
        cr.fill()
        cr.set_source_rgb(.45, .47, .54)
        cr.rectangle(mx + 2, y + 2, M_W - 4, 1)
        cr.fill()
        cr.set_source_rgb(*(0.3, 0.9, 0.4) if bright else (0.55, 0.2, 0.2))   # the power light
        cr.rectangle(mx + M_W - 8, y + 39, 3, 3)
        cr.fill()
        cr.set_source_rgb(.03, .04, .06)
        cr.rectangle(mx + S_X, y + S_Y, S_W, S_H)
        cr.fill()
        if bright:
            lw, lh = S_W * pw, max(2.0, S_H * ph)
            cr.save()
            cr.rectangle(mx + S_X + (S_W - lw) / 2, y + S_Y + (S_H - lh) / 2, lw, lh)
            cr.clip()
            if ph < 0.1:
                cr.set_source_rgba(1, 1, 1, bright)
                cr.paint()
            else:
                cr.translate(mx + S_X, y + S_Y)
                screen_picture(cr, t)
            cr.restore()
        cr.restore()

    def draw(cr, t):
        monitor(cr, t)
        if arrive(cr, st, t, sit_x):
            return
        lift, squash = (hop(t, C_FLICK, 12) if t < C_OFF else hop(t, C_OFF + 0.35)) if t < C_LEAP else (0.0, 0.0)
        scared = C_FLICK <= t < C_FLICK + 0.6
        pawing = C_PRESS <= t < C_PRESS + 0.4 and int((t - C_PRESS) / 0.12) % 2 == 0
        sit(cr, st, t, sit_x, C_LEAP, True, lift, squash, swipe=pawing, alert=scared, rot=0.07 * math.sin(t * 45) * scared)

    return draw, C_END


# ---------------------------------------------------------------------------------------------------------------------------------
# Scroller: a demoscene sine scroller wanders over the logo. She sits and reads along, and hops for joy when her own name comes by.
TEXT = "GREETINGS FROM CODE-CAT"
NAME = TEXT.index("CODE-CAT")
FONT = "Monospace Bold 12"
SCROLL_START, SCROLL_SPEED = 1.5, 150.0
COLORS["p"] = (1.0, 0.45, 0.6)
HEART = (".pp.pp.", "ppppppp", "ppppppp", ".ppppp.", "..ppp..", "...p...")
HEARTS = 1.2   # seconds that the hearts rise


def scroller(st):
    sit_x = st.lx + (st.size - CAT_W) / 2
    layout = PangoCairo.create_layout(cairo.Context(cairo.ImageSurface(cairo.FORMAT_A8, 1, 1)))
    layout.set_font_description(Pango.FontDescription(FONT))
    layout.set_text("M", -1)
    cw = layout.get_pixel_size()[0]
    head_x = sit_x + 36
    reaches = lambda i, x: SCROLL_START + (st.w + i * cw - x) / SCROLL_SPEED   # when letter i is at x
    t_name = reaches(NAME, head_x)
    t_turn = reaches(len(TEXT) // 2, head_x)
    t_leap = t_name + 1.5
    t_end = max(t_leap + LEAP + 0.3, reaches(len(TEXT), 0))

    def draw(cr, t):
        for i, ch in enumerate(TEXT):
            x = st.w + i * cw - SCROLL_SPEED * (t - SCROLL_START)
            if ch == " " or x < -cw or x > st.w:
                continue
            y = 5 + 4 * math.sin(x / 30 + t * 6)
            layout.set_text(ch, -1)
            for dx, color in ((1, (0, 0, 0, .55)), (0, (*ramp(i / (len(TEXT) - 1)), 1))):
                cr.set_source_rgba(*color)
                cr.move_to(x + dx, y + dx)
                PangoCairo.show_layout(cr, layout)
        if arrive(cr, st, t, sit_x):
            return
        lift, squash = hop(t, t_name if t < t_name + 0.45 else t_name + 0.45)   # two hops of joy
        squash += 0.04 * math.sin(t * 6) * (t < t_name)   # until then she nods along with the wave
        happy = t_name <= t < t_name + HEARTS   # eyes shut with joy, hearts drift up from her head
        sit(cr, st, t, sit_x, t_leap, t >= t_turn, lift, squash, sleep=happy)
        if happy:
            for i in range(3):
                f = ((t - t_name) / HEARTS + i / 3) % 1.0
                k = 0.45 + 0.3 * f
                sprite(cr, HEART, sit_x + CAT_W * 0.27 + (14 + 26 * f) * (1 if i % 2 else -1) * (0.4 if i == 2 else 1) - 3.5 * 4 * k, st.sit_y + 6 - 16 * f, k)

    return draw, t_end


SCENES = (chase, tube, scroller)
