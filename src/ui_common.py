# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""Names and tables the parts of the window share: themes, styles, effects, colour sets, zoom steps; and the
sliders."""
from pathlib import Path

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from i18n import N_, _  # noqa: E402

THEME_NAMES = {"light": N_("Light"), "dark": N_("Dark"), "bw": N_("Black & White"), "amber": N_("Amber"), "terminal": N_("Terminal"),
               "paper": N_("Paper"), "c64": N_("C64"), "custom": N_("Custom")}
GLOW_MODES = {"soft": N_("Soft edges"), "halo": N_("Neon")}
CUSTOM_COLORS = {"bg": N_("Background"), "text": N_("Text"), "art": N_("Block graphics"), "link": N_("Links")}
ENCODINGS = {"auto": N_("Automatic"), "cp437": "CP437 (DOS)", "cp850": "CP850", "latin-1": "Latin-1", "utf-8": "UTF-8"}
BOOL_ACTIONS = ("ramp", "crt", "crt_live", "cycle", "pulse", "music", "stars", "scroller",
                "wobble", "text_glow", "neon_flicker", "sheen", "sparkle", "chroma")
# the effects that move: switched on, they need the frame clock (the window test checks that they get it)
ANIMATIONS = ("cycle", "pulse", "stars", "scroller", "wobble", "wobble_amount", "stars_mode",
              "neon_flicker", "sheen", "sparkle", "crt_live")
# styles: a few looks that set all the effects at once; the theme is left alone. Its button lights up while
# every effect matches it.
STYLES = {
    "classic": (N_("Classic"), {"soft": False, "ramp": False, "cycle": False, "pulse": False,
                                "crt": False, "crt_live": False, "stars": False, "scroller": False, "wobble": False,
                                "text_glow": False, "neon_flicker": False, "sheen": False, "sparkle": False, "chroma": False}),
    "soft": (N_("Soft"), {"soft": True, "glow_mode": "soft", "ramp": False, "cycle": False,
                          "pulse": False, "crt": False, "crt_live": False, "stars": False, "scroller": False,
                          "wobble": False, "text_glow": False, "neon_flicker": False, "sheen": False, "sparkle": False, "chroma": False}),
    "neon": (N_("Neon"), {"soft": True, "glow_mode": "halo", "ramp": True, "cycle": False,
                          "pulse": False, "crt": False, "crt_live": False, "stars": False, "scroller": False, "wobble": False,
                          "text_glow": False, "neon_flicker": False, "sheen": False, "sparkle": False, "chroma": False}),
    "tube": (N_("Tube"), {"soft": True, "glow_mode": "soft", "crt_mask": "dots", "ramp": False, "cycle": False,
                          "pulse": False, "crt": True, "crt_live": True, "stars": False, "scroller": False, "wobble": False,
                          "text_glow": True, "neon_flicker": False, "sheen": False, "sparkle": False, "chroma": True}),
    "retrowave": (N_("Retrowave"), {"soft": True, "glow_mode": "halo", "crt_mask": "lines", "ramp": True, "cycle": False,
                                    "pulse": False, "crt": True, "crt_live": True, "stars": True, "scroller": False,
                                    "wobble": False, "text_glow": True, "neon_flicker": True, "sheen": False, "sparkle": False, "chroma": True}),
    "demoscene": (N_("Demoscene"), {"soft": True, "glow_mode": "halo", "ramp": False, "cycle": True,
                                  "pulse": True, "crt": False, "crt_live": False, "stars": True, "scroller": True, "wobble": True,
                                  "text_glow": False, "neon_flicker": False, "sheen": True, "sparkle": True, "chroma": False}),
}
CYCLE_DIRECTIONS = {"down": N_("Down"), "up": N_("Up")}
CYCLE_PALETTES = {"c64": N_("C64 colors"), "ramp": N_("Color ramp colors")}
WOBBLE_AMOUNTS = {"low": N_("Gentle"), "mid": N_("Medium"), "high": N_("Strong")}
CRT_MASKS = {"lines": N_("Scanlines"), "dots": N_("Shadow mask"), "stripes": N_("Aperture grille")}
# the settings that belong to a switch of the effects sidebar and are set in the preferences. While the switch is on,
# a gear beside it opens the preferences at the first of them. The window test checks that every other choice on the
# effect pages of the preferences is listed here, so a new one cannot be left without its gear.
SUB_SETTINGS = {"ramp": ("ramp_colors",), "cycle": ("cycle_palette", "cycle_dir"), "wobble": ("wobble_amount",),
                "stars": ("stars_mode",), "scroller": ("scroller_text",), "sparkle": ("sparkle_amount",),
                "crt": ("crt_mask", "crt_live"), "music": ("music_dir", "music_shuffle", "volume", "music_info", "music_fade"),
                "pulse": ("pulse_mode",)}
SPARKLE_AMOUNTS = {"few": N_("Few"), "some": N_("Some"), "many": N_("Many")}
STARS_MODES = {"drift": N_("Drifting"), "warp": N_("Warp flight")}
OPENINGS = {"off": N_("None"), "modem": N_("Modem build-up"), "glitch": N_("Glitch"), "loader": N_("Tape loader"),
            "crt": N_("CRT power-on"), "dos": N_("DOS boot"), "dither": N_("Dither fade-in"),
            "neon": N_("Neon flicker-on"), "rain": N_("Code rain")}
OPENING_INFO = {
    "off": N_("Opens at once"),
    "modem": N_("The NFO appears line by line, like over a 2400 baud BBS; a click or key skips it"),
    "glitch": N_("A short flicker of torn lines, like a crackling loader"),
    "loader": N_("A C64 screen types LOAD and loads with colored stripes in its border; a click or key skips it"),
    "crt": N_("A bright line grows into the picture, like a tube TV switching on; a click or key skips it"),
    "dos": N_("A DOS prompt boots, lists the file and types it out; a click or key skips it"),
    "dither": N_("The picture builds up in dithered steps, like ░ ▒ ▓ █; a click or key skips it"),
    "neon": N_("The art flickers on like a neon sign; a click or key skips it"),
    "rain": N_("Ones and zeros rain down the window and leave the NFO behind; a click or key skips it")}
PULSE_MODES = {"beat": N_("To the music"), "breathe": N_("Breathing")}
MUSIC_ORDER = {True: N_("Random"), False: N_("In order")}
# what the dice change: the look, never the behaviour (encoding, language, music, ...)
LOOK = ("theme", "soft", "glow_mode", "glow", "ramp", "ramp_colors", "cycle", "cycle_palette", "pulse",
        "crt", "crt_live", "stars", "stars_mode", "scroller", "wobble", "wobble_amount", "text_glow",
        "neon_flicker", "cycle_dir", "pulse_mode", "opening", "sheen", "sparkle", "sparkle_amount", "chroma", "crt_mask", "font")
# what a look code carries: the font is left out (any font name would come from outside); the code tells only whether
# the bundled DOS font is on
LOOK_SHARED = tuple(k for k in LOOK if k != "font")
# the settings of a look that are picked from a list (a look code is checked against these)
LOOK_CHOICES = {"theme": THEME_NAMES, "glow_mode": GLOW_MODES, "cycle_palette": CYCLE_PALETTES,
                "wobble_amount": WOBBLE_AMOUNTS, "stars_mode": STARS_MODES, "cycle_dir": CYCLE_DIRECTIONS,
                "pulse_mode": PULSE_MODES, "opening": OPENINGS, "sparkle_amount": SPARKLE_AMOUNTS, "crt_mask": CRT_MASKS}
# the colour ramp that comes with each theme (top, middle, bottom of a block of art); Custom keeps your own
THEME_RAMPS = {"light": ("#1046a0", "#5b2bb5", "#b5179e"), "bw": ("#000000", "#3d3d3d", "#808080"),   # black to grey
               "dark": ("#73f0ff", "#4d8cff", "#d94dff"),
               "amber": ("#ffe08a", "#ffb000", "#ff6a00"), "terminal": ("#c8ffd8", "#3dff70", "#12a64a"),
               "paper": ("#b5651d", "#8b3a1e", "#5c1f12"), "c64": ("#9ee8f0", "#7c70da", "#b66fcf")}
RAMPS_DARK = [("#73f0ff", "#4d8cff", "#d94dff"), ("#fff36b", "#ff9a2e", "#e8322b"), ("#a6fff2", "#2ec4e8", "#2b4fe8"),
              ("#e8ff6b", "#5cff6e", "#1fae73"), ("#ffd36b", "#ff6b8b", "#8a4dff"), ("#ffffff", "#a6d8ff", "#4d7dff"),
              ("#fff2b0", "#e8b93a", "#a8661f"), ("#70a4b2", "#6c5eb5", "#6f3d86")]   # synthwave, fire, ocean, ...
RAMPS_LIGHT = [("#1046a0", "#5b2bb5", "#b5179e"), ("#1f7a3a", "#127a7a", "#1046a0"), ("#b5281b", "#c2560f", "#8a1f5c"),
               ("#3a2bb5", "#1046a0", "#127a7a")]   # dark enough to stand out on a light page
# the keyboard shortcuts dialog: (group, [(keys, what they do)]); keys are joined by "+", alternatives by " / ".
# Key names that differ between languages are translated (Ctrl is Strg in German).
CTRL = N_("Ctrl")
SHORTCUTS = (
    (N_("General"), (((CTRL, "O"), N_("Open")), ((CTRL, ","), N_("Preferences")),
                     ((CTRL, "?"), N_("Keyboard shortcuts")), ((CTRL, "W"), N_("Close the window")),
                     ((CTRL, "Q"), N_("Quit")))),
    (N_("View"), (((CTRL, "T"), N_("Art or text only")), (("F9",), N_("Effects sidebar")),
                  ((CTRL, "Z"), N_("Undo the last change to the look")), ((CTRL, "M"), N_("Music on or off")),
                  ((CTRL, "+"), N_("Zoom in")), ((CTRL, "−"), N_("Zoom out")), ((CTRL, "0"), N_("Default zoom")),
                  ((CTRL, N_("Mouse wheel")), N_("Zoom")), (("F5",), N_("Reload")))),
    (N_("Moving around"), ((("←", ), N_("Previous NFO in the folder")), (("→",), N_("Next NFO in the folder")),
                           ((N_("Space"),), N_("Page down")), ((N_("Shift"), N_("Space")), N_("Page up")),
                           (("↑",), N_("Scroll up")), (("↓",), N_("Scroll down")),
                           ((N_("Home"),), N_("Top")), ((N_("End"),), N_("Bottom")))),
    (N_("Text"), (((CTRL, "F"), N_("Search")), ((N_("Enter"),), N_("Next match")),
                  ((N_("Shift"), N_("Enter")), N_("Previous match")), ((CTRL, "C"), N_("Copy")),
                  ((CTRL, "A"), N_("Select all")), ((CTRL, "S"), N_("Save as PNG")))),
)
FILE_ACTIONS = ("save-png", "save-pdf", "reload", "copy", "copy-all", "select-all", "fit-width", "search", "text-only")
ZOOM_STEPS = tuple(range(30, 251, 10))   # = core.ZOOM_MIN..ZOOM_MAX
ICONS = Path(__file__).resolve().parent.parent / "data" / "icons"   # running from a checkout


def slider(lo, hi, step, value):
    """A slider that only a click or drag moves: the mouse wheel scrolls the page around it, so scrolling down a
    list never changes a value by accident."""
    scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
    scale.set_value(value)
    scale.set_draw_value(False)
    wheel = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
    wheel.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)   # before the slider itself sees the wheel

    def scroll(ctl, _dx, dy):
        page = scale.get_ancestor(Gtk.ScrolledWindow)
        if page:
            adj = page.get_vadjustment()
            px = dy if ctl.get_unit() == Gdk.ScrollUnit.SURFACE else dy * adj.get_page_size() ** (2 / 3)  # as GTK does
            adj.set_value(adj.get_value() + px)
        return True
    wheel.connect("scroll", scroll)
    scale.add_controller(wheel)
    return scale


def opening_row(cfg, change, replay, describe=True):
    """The choice of the effect on opening and a button to play it now. describe: its description under the title
    (in the narrow sidebar the subtitle shows the chosen effect instead)."""
    keys = list(OPENINGS)
    now = cfg["opening"] if cfg["opening"] in OPENINGS else "off"
    row = Adw.ComboRow(title=_("Opening effect"), model=Gtk.StringList.new([_(v) for v in OPENINGS.values()]),
                       selected=keys.index(now), use_subtitle=not describe)
    # the description, or in the narrow sidebar the chosen effect's name (also set by hand: use_subtitle
    # shows nothing until the choice first changes)
    row.set_subtitle(_(OPENING_INFO[now] if describe else OPENINGS[now]))
    row.set_subtitle_lines(3)
    play = Gtk.Button(icon_name="media-playback-start-symbolic", valign=Gtk.Align.CENTER,
                      css_classes=["flat", "circular"], tooltip_text=_("Play the effect now"))
    play.update_property([Gtk.AccessibleProperty.LABEL], [_("Play the effect now")])
    play.connect("clicked", lambda *_a: replay())
    play.set_visible(now != "off")   # nothing to play for "None"

    def picked(r, _p):
        key = keys[r.get_selected()]
        play.set_visible(key != "off")
        r.set_subtitle(_(OPENING_INFO[key] if describe else OPENINGS[key]))
        change("opening", key)
    row.connect("notify::selected", picked)
    row.add_suffix(play)
    return row


def ramp_for_theme(theme, current):
    """The colour ramp that comes with a theme, or None: the theme has none (Custom), or the ramp was set by hand
    (one of the ready-made ramps, of a theme or of the random look, is taken as not set by hand)."""
    own = THEME_RAMPS.get(theme)
    made = [list(r) for r in (*THEME_RAMPS.values(), *RAMPS_DARK, *RAMPS_LIGHT)]
    return list(own) if own and list(current) in made else None
