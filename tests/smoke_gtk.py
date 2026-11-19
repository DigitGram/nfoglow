# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""Smoke test of the whole window: open a file and use every part of the UI once; fails on any Python exception.

Run it on a hidden display, so no window shows up on your desktop, and with no sound:
    xvfb-run -a env -u WAYLAND_DISPLAY GDK_BACKEND=x11 python3 tests/smoke_gtk.py
"""
import faulthandler
import json
import os
import sys
import tempfile
import traceback
faulthandler.dump_traceback_later(90, exit=True)   # a hang (e.g. no window came up) fails instead of waiting
from pathlib import Path

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()   # never touch the real settings
os.environ["ADW_DEBUG_COLOR_SCHEME"] = "prefer-dark"   # a desktop in dark mode: a reset picks the Dark theme
# start like a returning user: effects sidebar open (it reports its state while the window is built)
os.makedirs(os.path.join(os.environ["XDG_CONFIG_HOME"], "nfoglow"))
with open(os.path.join(os.environ["XDG_CONFIG_HOME"], "nfoglow", "settings.json"), "w") as f:
    f.write('{"sidebar": true, "maximized": true}')   # maximize() on a window manager-less display: must not break
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import music  # noqa: E402
from i18n import _  # noqa: E402
import ui_app  # noqa: E402
from gi.repository import Adw, Gio, GLib, Gst, Gtk  # noqa: E402
from ui_common import ANIMATIONS, OPENINGS, SUB_SETTINGS  # noqa: E402

DEMO = str(ROOT / "docs" / "demo.nfo")
errors = []
sys.excepthook = lambda *exc: (errors.append("".join(traceback.format_exception(*exc))), print(errors[-1], flush=True))   # errors in GTK callbacks

_player = music.Player.__init__


def silent_player(self):   # the smoke test never plays on the speakers
    _player(self)
    self.bin.set_property("audio-sink", Gst.ElementFactory.make("fakesink"))


music.Player.__init__ = silent_player


alerts = []   # the questions the app asks, to look at them
_choose = Adw.AlertDialog.choose
Adw.AlertDialog.choose = lambda d, *a: (alerts.append(d), _choose(d, *a))[1]


class Smoke(ui_app.App):
    def do_activate(self):
        w = ui_app.Window(self)
        w.set_default_size(640, 600)   # narrow: the sidebar collapses over the NFO
        w.present()
        out = tempfile.mkdtemp()
        def remembered_sidebar():   # neither the start nor folding it in a narrow window may forget it
            if not self.cfg["sidebar"]:
                raise AssertionError("the sidebar was open when NfoGlow closed, but the setting got lost")
        def press_reset_of(title):   # the Reset button in the preferences row with this title
            def walk(widget):
                if isinstance(widget, Adw.ActionRow) and widget.get_title() == _(title):
                    return widget.get_last_child()
                child = widget.get_first_child()
                while child:
                    found = walk(child)
                    if found:
                        return found
                    child = child.get_next_sibling()
            row = walk(w.get_visible_dialog())
            button = row and next(b for b in iter_children(row) if isinstance(b, Gtk.Button))
            button.emit("clicked")

        def iter_children(widget):
            child = widget.get_first_child()
            while child:
                yield child
                yield from iter_children(child)
                child = child.get_next_sibling()

        def custom_colors_are_default():
            if self.cfg["custom"] != ui_app.core.DEFAULTS["custom"] or self.cfg["theme"] != "paper":
                raise AssertionError(f"reset of the custom colors: {self.cfg['custom']}, theme {self.cfg['theme']}")

        def every_choice_has_its_gear():
            """Each row on the effect pages of the preferences (not a switch, not inside a folded row) belongs to a
            switch with a gear (SUB_SETTINGS) or is set in the sidebar itself; and every such switch has its gear."""
            in_sidebar = {"glow_mode", "glow", "opening"}   # the glow buttons, the strength slider, the opening choice
            subs = {k for keys in SUB_SETTINGS.values() for k in keys}
            by_row = {}
            for key, row in self._rows.items():   # one row can carry two settings (the ramp: its switch and colours)
                by_row.setdefault(id(row), set()).add(key)
            dialog = w.get_visible_dialog()
            for page in iter_children(dialog):
                if not isinstance(page, Adw.PreferencesPage) or page.get_title() not in (_("Effects"), _("Animation"),
                                                                                         _("Music")):
                    continue
                for row in iter_children(page):
                    if (not isinstance(row, Adw.PreferencesRow) or isinstance(row, Adw.SwitchRow)
                            or row.get_ancestor(Adw.ExpanderRow) not in (None, row)
                            or isinstance(row.get_parent(), Adw.ExpanderRow) or type(row) is Adw.PreferencesRow):
                        continue
                    keys = by_row.get(id(row), set())
                    if not keys & (subs | in_sidebar):
                        raise AssertionError(f"a setting in the preferences without a gear in the sidebar: "
                                             f"{', '.join(keys) or row.get_title()} on {page.get_title()}")
            for switch, keys in SUB_SETTINGS.items():
                if keys[0] not in self._rows:
                    raise AssertionError(f"the gear of {switch} leads to {keys[0]}, which has no row in the preferences")
            gears = [b for b in iter_children(w) if isinstance(b, Gtk.Button)
                     and b.get_icon_name() == "emblem-system-symbolic" and b.get_ancestor(Adw.ActionRow)]
            if len(gears) != len(SUB_SETTINGS):
                raise AssertionError(f"{len(gears)} gears in the sidebar, {len(SUB_SETTINGS)} expected")

        def every_effect_is_in_sidebar_and_preferences():
            """Each on/off effect has a switch in the sidebar (or is set behind the gear of one) and a row in the
            preferences."""
            in_sidebar = {getattr(r, "action", None) for r in iter_children(w)}
            behind_gears = {k for keys in SUB_SETTINGS.values() for k in keys}
            for key in ui_app.BOOL_ACTIONS:
                if key.replace("_", "-") not in in_sidebar and key not in behind_gears:
                    raise AssertionError(f"{key}: no switch in the effects sidebar")
                if key not in self._rows:
                    raise AssertionError(f"{key}: no row in the preferences")

        def moving_effects_get_the_clock():
            """An effect that moves must start the frame clock, or it stands still on the screen."""
            self.apply_style("neon")
            for key in ANIMATIONS:
                if not isinstance(self.cfg[key], bool):
                    continue
                self.apply_style("neon")
                if not self.cfg[key]:
                    self.activate_action(key.replace("_", "-"), None)   # as a click on its switch (Live CRT brings the tube)
                if not (w._animating_page() or w._overlay_moving()):
                    raise AssertionError(f"{key} is on, but nothing runs the frame clock")
            self.apply_style("neon")

        def reset_question_is_wide():   # a wide box, not a narrow tower
            box = alerts[-1].get_extra_child()
            if box.get_width() < 400:
                raise AssertionError(f"the reset question is only {box.get_width()} px wide")

        def look_on_disk():
            with open(ui_app.core.CONFIG, encoding="utf-8") as f:
                return {k: v for k, v in json.load(f).items() if k in ui_app.LOOK}

        def disk_is(expected, why):   # a rolled look is shown, but only "Keep" writes it to the settings file
            def check():
                if look_on_disk() != expected():
                    raise AssertionError(why)
            return check
        saved, other, font = {}, [], []

        def closed_window_stops_watching():   # else it reloads its file on every change, though nobody sees it
            if not (other[0]._monitor.is_cancelled() and other[0].path is None):
                raise AssertionError("a closed window still watches its file")
        def undid_style():   # Undo takes back a whole style click, and also a kept random look
            if self._style() != "neon":
                raise AssertionError(f"Undo should be back at the Neon style, not {self._style()!r}")
        def gpu_matches_cairo():   # the window (graphics card) shows what the export (cairo) draws
            import cairo
            import gpu
            from gi.repository import Graphene
            p, W, H = w.page, 700, 500
            p.time = 0.0   # the animations (stars, sparkle, sheen) move with it: compare one fixed moment, not a random one
            snap = ui_app.Gtk.Snapshot()
            gpu.view(p, snap, W, H, 0, 0, 0, 1.0, None, {})
            png = os.path.join(out, "gpu.png")
            w.get_renderer().render_texture(snap.to_node(), Graphene.Rect().init(0, 0, W, H)).save_to_png(png)
            a = cairo.ImageSurface.create_from_png(png)
            b = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
            cr = cairo.Context(b)
            cr.set_source_rgb(*p._colors()[0])
            cr.paint()
            p.stars(cr, W, H)
            p.paint(cr, 0, background=False)
            da, db = bytes(a.get_data()), bytes(b.get_data())
            off = sum(1 for i in range(0, len(da), 4) if max(abs(da[i + j] - db[i + j]) for j in range(3)) > 40)
            if off > len(da) / 4 * .01:
                raise AssertionError(f"window and export differ in {off} pixels")
        def wheel_leaves_the_slider():   # scrolling the sidebar over the strength slider must not change the glow
            glow = w.strength.get_value()
            ours = [c for c in w.strength.observe_controllers() if isinstance(c, ui_app.Gtk.EventControllerScroll)
                    and c.get_propagation_phase() == ui_app.Gtk.PropagationPhase.CAPTURE]
            if not ours:
                raise AssertionError("the slider has no wheel catcher of its own")
            ours[0].emit("scroll", 0.0, 3.0)
            if w.strength.get_value() != glow:
                raise AssertionError("the mouse wheel moved the strength slider")
        def scroller_names_the_file():
            if "{ hello demo.nfo" not in w._scroller_text():
                raise AssertionError(w._scroller_text())
        def ended():
            if w.loading is not None or w.view.opening is not None or w.page.reveal is not None:
                raise AssertionError("an effect on opening did not end")
        steps = [
            remembered_sidebar,
            lambda: w.load(DEMO),
            lambda: w.activate_action("win.toggle-effects", None),
            wheel_leaves_the_slider,
            *[(lambda s=s: self.activate_action("style", GLib.Variant("s", s))) for s in ui_app.STYLES],
            gpu_matches_cairo,   # in the last style, with every effect of it
            lambda: [self.activate_action(a, None) for a in ("stars", "scroller", "wobble")],
            *[step for k in OPENINGS if k != "off" for step in (   # every effect runs through to its end
                  lambda k=k: (self.change("opening", k), w.replay_opening()), *[lambda: None] * 28, ended)],
            lambda: self.activate_action("theme", GLib.Variant("s", "c64")),
            lambda: None if self.cfg["ramp_colors"] == list(ui_app.THEME_RAMPS["c64"]) else (_ for _ in ()).throw(
                AssertionError("the C64 theme did not bring its colour ramp")),
            lambda: self.change("opening", "loader"),
            lambda: w.load(DEMO),               # opens with the tape loader on the C64 screen ...
            lambda: None if w.loading is not None else (_ for _ in ()).throw(AssertionError("no tape loader")),
            lambda: w._key(None, ui_app.Gdk.KEY_space, 0, 0),   # ... which a key skips
            lambda: None if w.loading is None else (_ for _ in ()).throw(AssertionError("loader not skipped")),
            lambda: self.activate_action("style", GLib.Variant("s", "neon")),
            lambda: self.activate_action("style", GLib.Variant("s", "demoscene")),
            lambda: self.activate_action("undo", None),
            undid_style,
            lambda: self.change("scroller_text", "{ hello {name}"),
            scroller_names_the_file,
            lambda: self.change("wobble_amount", "high"),
            lambda: saved.update(look_on_disk()),
            lambda: self.activate_action("roll-look", None),
            disk_is(lambda: saved, "a rolled look was written to the settings before Keep"),
            lambda: self.activate_action("keep-look", None),
            disk_is(lambda: {k: self.cfg[k] for k in ui_app.LOOK}, "Keep did not write the rolled look"),
            lambda: self.activate_action("undo", None),
            undid_style,
            lambda: (saved.clear(), saved.update(look_on_disk())),
            lambda: self.activate_action("roll-look", None),
            lambda: self.activate_action("undo-look", None),
            disk_is(lambda: saved, "Back did not leave the settings as they were"),
            # a change at the sidebar is a trial too: not on disk until Keep, and Keep/Back only while it differs
            lambda: (w.split.set_show_sidebar(True), saved.clear(), saved.update(look_on_disk()),
                     self.change("sheen", not self.cfg["sheen"])),
            disk_is(lambda: saved, "a change at the sidebar was written before Keep"),
            lambda: None if self.lookup_action("keep-look").get_enabled() else (_ for _ in ()).throw(
                AssertionError("no Keep after a change at the sidebar")),
            lambda: self.change("sheen", not self.cfg["sheen"]),   # changed back by hand: nothing left to keep
            lambda: None if not self.lookup_action("keep-look").get_enabled() else (_ for _ in ()).throw(
                AssertionError("Keep is still on after the change was taken back")),
            lambda: self.change("sheen", not self.cfg["sheen"]),
            lambda: self.activate_action("undo-look", None),
            disk_is(lambda: saved, "Back after a change at the sidebar left the settings changed"),
            lambda: self.change("sheen", not self.cfg["sheen"]),
            lambda: self.activate_action("keep-look", None),
            disk_is(lambda: {k: self.cfg[k] for k in ui_app.LOOK}, "Keep did not write the change"),
            lambda: (w.split.set_show_sidebar(False), self.change("sheen", not self.cfg["sheen"])),   # shut: saved at once
            disk_is(lambda: {k: self.cfg[k] for k in ui_app.LOOK}, "a change with the sidebar shut was not saved"),
            lambda: w.split.set_show_sidebar(True),
            lambda: (font.clear(), font.append(self.cfg["font"]), self.toggle_dos_font()),   # the other font is copied
            lambda: (saved.clear(), saved.update({k: self.cfg[k] for k in ui_app.LOOK}), w.activate_action("win.copy-look", None)),
            lambda: self.toggle_dos_font(),   # ... and the one we started with is back
            lambda: self.activate_action("style", GLib.Variant("s", "demoscene")),
            lambda: w.activate_action("win.paste-look", None),   # reads the clipboard: the result shows in the next step
            lambda: None if {k: self.cfg[k] for k in ui_app.LOOK} == saved else (_ for _ in ()).throw(
                AssertionError("Paste look did not bring the copied look back (the DOS font too)")),
            lambda: self.activate_action("undo", None),   # the paste was one step on the Undo list, the font included
            lambda: None if {k: self.cfg[k] for k in ui_app.LOOK} != saved and self.cfg["font"] == font[0] else (
                _ for _ in ()).throw(AssertionError("Undo did not take back the pasted look and font")),
            lambda: self.activate_action("music", None),
            lambda: self.activate_action("music", None),
            lambda: w.activate_action("win.view", GLib.Variant("s", "text")),
            lambda: w.activate_action("win.view", GLib.Variant("s", "art")),
            lambda: (w.search.set_search_mode(True), w.entry.set_text("release"), w.step(1), w.search.set_search_mode(False)),
            lambda: [w.activate_action(a, None) for a in ("win.zoom-in", "win.zoom-out", "win.fit-width", "win.fit-width",
                                                         "win.zoom-reset", "win.select-all", "win.copy", "win.copy-all", "win.reload")],
            lambda: (w.browse(1), w.browse(-1)),
            lambda: (other.append(ui_app.Window(self)), other[0].load(DEMO), other[0].present(), other[0].close()),
            closed_window_stops_watching,
            lambda: w.present(),
            lambda: (w.page.export(f"{out}/a.png"), w.page.export(f"{out}/a.pdf")),
            lambda: self.preferences(),
            every_choice_has_its_gear,
            every_effect_is_in_sidebar_and_preferences,
            moving_effects_get_the_clock,
            lambda: w.get_visible_dialog().close(),
            lambda: (self.preferences(), self._confirm_reset(w.get_visible_dialog())),
            reset_question_is_wide,
            lambda: (alerts[-1].close(), w.get_visible_dialog().close()),
            lambda: (self.change("theme", "paper"), self.change("custom", {"bg": "#000000", "text": "#111111",
                                                                           "art": "#222222", "link": "#333333"}),
                     self.preferences()),
            lambda: press_reset_of("Back to the default colors"),
            custom_colors_are_default,
            lambda: w.get_visible_dialog().close(),
            lambda: self.shortcuts(),
            lambda: w.get_visible_dialog().close(),
            lambda: self.about(),
            lambda: w.get_visible_dialog().close(),
            lambda: self.change("font", ui_app.core.FONT),   # a rolled look may have kept the VGA font: start without it
            lambda: self.activate_action("dos-font", None),
            lambda: None if self.cfg["recent"] and self.cfg["font"] == ui_app.core.DOS_FONT else (_ for _ in ()).throw(
                AssertionError("before the reset: a recent file and the DOS font were expected")),
            lambda: self.reset(),
            lambda: None if not self.cfg["recent"] and self.cfg["font"] == ui_app.core.FONT
            and not self.lookup_action("dos-font").get_state().unpack() else (_ for _ in ()).throw(
                AssertionError("a reset should empty the recent files and switch the DOS font off")),
            lambda: None if self.cfg["theme"] == "dark" else (_ for _ in ()).throw(
                AssertionError("a reset on a dark desktop should pick the Dark theme")),
            lambda: self.quit(),
        ]

        def run(i=0):
            try:
                steps[i]()
            except Exception:
                errors.append(f"step {i}: {traceback.format_exc()}")
            if i + 1 < len(steps):
                GLib.timeout_add(150, lambda: run(i + 1) and False)
            return False
        GLib.timeout_add(300, run)


app = Smoke()
app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
app.run([sys.argv[0]])
if errors:
    print("\n".join(errors))
    sys.exit(1)
print("smoke test passed")
