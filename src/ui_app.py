# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""The application: its actions, the one place where settings change (App.change), styles and the random look,
the recent files, the music and the about dialog. One App can have several windows."""
import copy
import os
import random
import threading
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

import core  # noqa: E402
import i18n  # noqa: E402
import music  # noqa: E402
from i18n import _  # noqa: E402
from ui_common import (BOOL_ACTIONS, ENCODINGS, ICONS, LOOK, LOOK_CHOICES, OPENINGS, RAMPS_DARK, RAMPS_LIGHT, SHORTCUTS, STYLES, SUB_SETTINGS,  # noqa: E402
                       THEME_RAMPS, ramp_for_theme)
from page import DOS_FONT_READY  # noqa: E402
from ui_settings import SettingsDialog  # noqa: E402
from ui_window import Window  # noqa: E402


class App(SettingsDialog, Adw.Application):
    """The application. All settings live in one dict, self.cfg, shared by every window; change() is the only way to
    alter one: it saves the file, updates the actions (the switches and menus follow them) and tells each window."""

    def __init__(self):
        super().__init__(application_id=core.APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.first_start = not os.path.exists(core.CONFIG)
        self.cfg = core.load_settings({**LOOK_CHOICES, "encoding": ENCODINGS})
        i18n.set_language(self.cfg["language"])
        self.recent_menu = Gio.Menu()   # shared by the Open buttons of all windows
        self.player = None              # music.Player, made when music is first switched on
        self._announced = None          # track note waiting for a window
        self.saved_look = None          # while a rolled look is shown: the look in the settings, to keep on disk
        self.looks_before = []          # for Undo: the look before each change by hand (a style click is one change)
        self._undoing = False
        self.update_found = None        # (version, page) of a newer release, once one was found

    def do_startup(self):
        Adw.Application.do_startup(self)
        GLib.set_application_name("NfoGlow")
        css = Gtk.CssProvider()   # the C64 theme's border, and the colour swatches of the themes in the sidebar
        css.load_from_string(f".c64 {{ background-color: {core.C64_BORDER}; }} "
                             ".swatch { padding: 3px; min-width: 0; min-height: 0; border-radius: 999px; } "
                             ".swatch:checked { box-shadow: inset 0 0 0 2px @accent_color; background: none; } "
                             # a row of the preferences that the gear in the sidebar points at lights up and fades
                             "@keyframes nfoglow-flash { from { background-color: alpha(@accent_bg_color, .5); } "
                             "to { background-color: transparent; } } "
                             ".flash { animation: nfoglow-flash 1.6s ease-out; } "
                             "popover.k-cat > contents { background: none; border: none; box-shadow: none; padding: 0; }")
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        if self.first_start:
            self.cfg["theme"] = self._system_theme()
            self.cfg["ramp_colors"] = list(THEME_RAMPS[self.cfg["theme"]])
        if ICONS.is_dir():
            Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(str(ICONS))
        for name, cb in (("about", self.about), ("preferences", self.preferences), ("quit", lambda *a: self.quit()),
                         ("shortcuts", self.shortcuts),
                         ("clear-recent", lambda *a: self._set_recent([]))):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", cb)
            self.add_action(a)
        a = Gio.SimpleAction.new("open-recent", GLib.VariantType("s"))
        a.connect("activate", lambda _a, path: self.open_path(path.unpack()))
        self.add_action(a)
        self._fill_recent()
        for key, kind in (("theme", "s"), ("encoding", "s"), *((k, "b") for k in BOOL_ACTIONS)):
            a = Gio.SimpleAction.new_stateful(key.replace("_", "-"),   # action names cannot contain "_"
                                              GLib.VariantType(kind) if kind == "s" else None,
                                              GLib.Variant(kind, self.cfg[key]))
            a.connect("activate", self._on_setting_action)
            self.add_action(a)
        a = Gio.SimpleAction.new_stateful("glow-style", GLib.VariantType("s"), GLib.Variant("s", self._glow_style()))
        a.connect("activate", self._on_glow_style)
        self.add_action(a)
        # the DOS font is a font like any other (the font setting); the switch only puts it in or takes it out again
        a = Gio.SimpleAction.new_stateful("dos-font", None, GLib.Variant("b", self.cfg["font"] == core.DOS_FONT))
        a.connect("activate", lambda *_a: self.toggle_dos_font())
        a.set_enabled(DOS_FONT_READY)
        self.add_action(a)
        a = Gio.SimpleAction.new_stateful("style", GLib.VariantType("s"), GLib.Variant("s", self._style()))
        a.connect("activate", lambda _a, v: self.apply_style(v.unpack()))
        self.add_action(a)
        for name, cb in (("roll-look", lambda *a: self.roll_look()), ("keep-look", lambda *a: self.keep_look()),
                         ("undo-look", lambda *a: self.undo_look()), ("undo", lambda *a: self.undo())):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", cb)
            self.add_action(a)
        if self.cfg["random_on_start"]:
            self.roll_look()
        self._show_look_state()
        self._allow_pulse()
        for act, keys in (("win.open", "<Ctrl>o"), ("win.save-png", "<Ctrl>s"), ("win.copy", "<Ctrl>c"),
                          ("win.select-all", "<Ctrl>a"), ("win.search", "<Ctrl>f"), ("win.text-only", "<Ctrl>t"),
                          ("win.zoom-in", "<Ctrl>plus <Ctrl>equal <Ctrl>KP_Add"),
                          ("win.zoom-out", "<Ctrl>minus <Ctrl>KP_Subtract"), ("win.zoom-reset", "<Ctrl>0 <Ctrl>KP_0"),
                          ("win.reload", "F5 <Ctrl>r"), ("win.toggle-effects", "F9"), ("app.undo", "<Ctrl>z"), ("app.music", "<Ctrl>m"),
                          ("app.preferences", "<Ctrl>comma"), ("app.shortcuts", "<Ctrl>question"), ("window.close", "<Ctrl>w"), ("app.quit", "<Ctrl>q")):
            self.set_accels_for_action(act, keys.split())
        self._apply_music()

    def do_shutdown(self):
        if self.player:
            self.player.stop()
        Adw.Application.do_shutdown(self)

    def _apply_music(self):
        """Music on or off, from the folder (or the built-in chiptunes) in the chosen order."""
        if self.cfg["music"] and music.available():
            try:
                if not self.player:
                    self.player = music.Player()
                    self.player.on_track = self._announce
            except RuntimeError:   # GStreamer without its basic plugins: no music, but no crash either
                self.change("music", False)
                return
            self.player.play(self.cfg["music_dir"], self.cfg["music_shuffle"], self.cfg["volume"] / 100,
                             self.cfg["music_fade"])
        elif self.player:
            self.player.stop(fade=self.cfg["music_fade"])

    def _announce(self, path, number, count):
        """A short message at the bottom of the window: which track starts now."""
        if not self.cfg["music_info"]:
            return
        if self.player.builtin:
            name = _("Stennish – chiptune {number} of {count}").format(number=number, count=count)
        else:
            name = os.path.splitext(os.path.basename(path))[0].replace("_", " ")
        self._announced = "♪ " + name   # the current track, also for a window that opens later (first start)
        self._show_announced()

    def _show_announced(self):
        w = self.get_active_window()
        if self._announced and isinstance(w, Window):
            w.toast(self._announced, 3)
            self._announced = None

    def music_level(self):
        """Loudness 0..1 of the music, or None when none plays (the pulse then breathes on its own)."""
        return self.player.level() if self.player and self.player.playing else None

    def weekly_update_check(self):
        """At the first window, if the user switched the weekly check on and it is due: look in the background, say so only when
        there is news. The date is saved whatever the answer, so an offline start does not retry on every launch."""
        if getattr(self, "_update_checked_once", False) or not core.update_due(self.cfg):
            return
        self._update_checked_once = True
        self.change("update_last", int(time.time()))

        def work():
            try:
                found = core.newer_release()
            except (OSError, ValueError, KeyError):
                return
            if found:
                GLib.idle_add(self._update_found, found)
        threading.Thread(target=work, daemon=True).start()

    def _update_found(self, found):
        """A toast that stays until dismissed, with a button to the release page."""
        self.update_found = found
        window = self.get_active_window()
        if isinstance(window, Window):
            toast = Adw.Toast(use_markup=False, title=_("NfoGlow {version} is available").format(version=found[0]),
                              button_label=_("Release notes"), timeout=0)
            toast.connect("button-clicked", lambda t: Gtk.UriLauncher(uri=found[1]).launch(window, None, None))
            window.toasts.add_toast(toast)

    def do_activate(self):
        (self.get_active_window() or Window(self)).present()
        GLib.idle_add(self._show_announced)
        self.weekly_update_check()

    def do_open(self, files, n, hint):
        for f in files:
            w = self.get_active_window()
            if not (w and w.path is None):   # reuse an empty window
                w = Window(self)
            w.load(f.get_path())
            w.present()
        GLib.idle_add(self._show_announced)
        self.weekly_update_check()

    def open_path(self, path):
        """From the recent list: into the active window."""
        w = self.get_active_window() or Window(self)
        w.load(path)
        w.present()

    def add_recent(self, path):
        if not self.cfg["remember_recent"]:
            return
        self._set_recent([path, *(p for p in self.cfg["recent"] if p != path)][:10])

    def _set_recent(self, paths):
        self.change("recent", paths)
        self._fill_recent()

    def _fill_recent(self):
        self.recent_menu.remove_all()
        files = Gio.Menu()
        for path in self.cfg["recent"]:
            item = Gio.MenuItem.new(os.path.basename(path).replace("_", "__"), None)   # "_" would be a mnemonic
            item.set_action_and_target_value("app.open-recent", GLib.Variant("s", path))
            files.append_item(item)
        if not self.cfg["recent"]:
            files.append(_("No recent files"), None)   # no action: shown greyed out
        self.recent_menu.append_section(_("Recent files"), files)
        if self.cfg["recent"]:
            self.recent_menu.append(_("Clear list"), "app.clear-recent")
    def _on_setting_action(self, action, value):
        key = action.get_name().replace("-", "_")
        self.change(key, value.unpack() if value is not None else not self.cfg[key])
        if key == "crt_live" and self.cfg["crt_live"]:
            self.change("crt", True)   # the living tube is a kind of CRT look
        if key == "crt" and not self.cfg["crt"]:
            self.change("crt_live", False)
        if key in BOOL_ACTIONS and key != "music":   # every effect of the sidebar
            self._show_art()

    def _style(self):
        """The style whose effects all match the settings, or "" (then no style button is lit)."""
        return next((k for k, (_l, look) in STYLES.items() if all(self.cfg[x] == v for x, v in look.items())), "")

    def apply_style(self, name):
        for key, value in STYLES[name][1].items():
            self.change(key, value)
        self._show_art()

    def _allow_pulse(self):
        """Pulsing is a beat of the neon halo, so it can only be switched on together with that style."""
        for name in ("pulse", "neon-flicker"):
            self.lookup_action(name).set_enabled(self._glow_style() == "halo")

    def _glow_style(self):
        """"off", "soft" or "halo": the two glow settings as one choice for the effects sidebar."""
        return self.cfg["glow_mode"] if self.cfg["soft"] else "off"

    def _on_glow_style(self, _action, value):
        style = value.unpack()
        if style != "off":
            self.change("glow_mode", style)
        self.change("soft", style != "off")
        self._show_art()

    def _show_art(self):
        """Trying an effect in text-only mode: bring the art back, or the click would seem to do nothing."""
        w = self.get_active_window()
        if isinstance(w, Window) and w.text_only:
            w._set_text_only(False)

    def toggle_dos_font(self):
        """On: the IBM VGA font. Off: back to the standard font."""
        self.change("font", core.FONT if self.cfg["font"] == core.DOS_FONT else core.DOS_FONT)

    def change(self, key, value, rolled=False):
        """Change one setting, save it and show it everywhere. rolled: part of a random look, not saved."""
        if self.cfg.get(key) == value:
            return   # also the echo of a widget that only follows a change (the strength slider after a roll)
        if key in LOOK and not rolled and not self._undoing:
            self._remember_look()
        if self.saved_look is None and key in LOOK and not rolled and self._sidebar_open():
            self.saved_look = {k: self.cfg[k] for k in LOOK}   # a change at the sidebar is a trial until it is kept
        self.cfg[key] = value
        self._save()
        if key in LOOK:
            self._show_look_state()
        action = self.lookup_action(key.replace("_", "-"))
        if action:
            action.set_state(GLib.Variant(action.get_state().get_type_string(), value))
        if key == "font":
            self.lookup_action("dos-font").set_state(GLib.Variant("b", value == core.DOS_FONT))
        if key in ("soft", "glow_mode"):
            self.lookup_action("glow-style").set_state(GLib.Variant("s", self._glow_style()))
            self._allow_pulse()
        if key in LOOK and self.lookup_action("style"):
            self.lookup_action("style").set_state(GLib.Variant("s", self._style()))
        if getattr(self, "_rows", None) and (key in ("soft", "glow_mode") or key in SUB_SETTINGS):   # after _allow_pulse
            self.grey_out_dependents()
        if key == "remember_recent" and not value:
            self._set_recent([])   # turning it off also forgets what is already listed
        if key == "language":
            GLib.idle_add(self._rebuild, True)   # not from inside the drop-down's own signal
            return
        if key == "theme" and not rolled and not self._undoing:   # a theme brings its colour ramp along
            ramp = ramp_for_theme(value, self.cfg["ramp_colors"])
            if ramp:
                self.change("ramp_colors", ramp)
        if key == "ramp_colors":   # the colour buttons in the preferences follow
            for button, color in zip(getattr(self, "_ramp_buttons", ()), value):
                rgba = Gdk.RGBA()
                rgba.parse(color)
                button.set_rgba(rgba)
        if key in ("music", "music_dir", "music_shuffle"):
            self._apply_music()
        if key == "volume" and self.player:
            self.player.set_volume(value / 100)
        for w in self.get_windows():
            if isinstance(w, Window):
                w.setting_changed(key)

    def _system_theme(self):
        """Dark or Light, as the desktop is set; for the first start and after a reset. The window itself always
        follows the desktop (the libadwaita default), whatever the theme: the theme colours the page only."""
        style = Adw.StyleManager.get_default()
        return "dark" if style.get_dark() else "light"

    def _rebuild(self, reopen_prefs=False):
        """A new language: replace every window by a new one showing the same file."""
        i18n.set_language(self.cfg["language"])
        prefs_on = None
        for old in list(self.get_windows()):
            if isinstance(old, Window):
                new = Window(self)
                if old.path:
                    new.load(old.path, remember=False)
                new.present()
                dialog = old.get_visible_dialog()
                if dialog:   # with a dialog open, close() only closes the dialog and the old window stays
                    if isinstance(dialog, Adw.PreferencesDialog):
                        prefs_on = new
                    dialog.force_close()
                old.close()   # through close-request: it stops watching the file
        if prefs_on and reopen_prefs:   # the preferences come back, now in the new language
            self.preferences(parent=prefs_on, show="language")
        return False

    def shortcuts(self, *a):
        """The keyboard shortcuts, grouped, in a small dialog."""
        page = Adw.PreferencesPage()
        for title, rows in SHORTCUTS:
            group = Adw.PreferencesGroup(title=_(title))
            for keys, what in rows:
                row = Adw.ActionRow(title=_(what))
                row.add_suffix(Gtk.Label(label="+".join(_(k) for k in keys), css_classes=["dim-label", "monospace"]))
                group.add(row)
            page.add(group)
        view = Adw.ToolbarView(content=page)
        view.add_top_bar(Adw.HeaderBar())
        Adw.Dialog(title=_("Keyboard shortcuts"), child=view, content_width=460, content_height=620).present(
            self.get_active_window())

    def about(self, *a):
        d = Adw.AboutDialog(
            application_name="NfoGlow", application_icon=core.APP_ID, version=core.__version__,
            developer_name=core.AUTHOR, developers=[core.AUTHOR], copyright=core.COPYRIGHT,
            license_type=Gtk.License.GPL_3_0, website=core.WEBSITE, issue_url=core.WEBSITE + "/issues",
            comments=_("A viewer for NFO and ANSI art, the way the scene meant it: crisp block graphics with an "
                       "optional soft glow, CP437 out of the box, clickable links and a text-only view."))
        d.add_acknowledgement_section(_("Inspired by"), ["iNFekt https://github.com/syndicodefront/infekt"])
        d.add_acknowledgement_section(_("Thank you for the music"),
                                      ["Stennish https://soundcloud.com/autistgamer1337/sets/chiptunes"])
        d.add_credit_section(_("Music (CC BY 4.0)"), ["Stennish https://soundcloud.com/autistgamer1337/sets/chiptunes"])
        d.present(self.get_active_window())
        import ui_about   # imported late: nothing of it runs unless the About dialog is opened
        import ui_about_art
        ui_about_art.RAMP = [core._hex(c) for c in self.cfg["ramp_colors"]]   # her trail and the tube's picture use the ramp
        ui_about.attach(d, ui_about_art.SCENES)

    def _sidebar_open(self):
        """Only what is changed with the sidebar in view is a trial: it is where Keep and Back are. A change made
        with the sidebar shut (the preferences by Ctrl+,) is saved at once, or it would be lost without a sign."""
        return any(getattr(w, "split", None) and w.split.get_show_sidebar()
                   for w in self.get_windows() if isinstance(w, Window))

    def _save(self):
        """Write the settings; a look that is still on trial (rolled or changed by hand) is not written until kept."""
        core.save_settings({**self.cfg, **self.saved_look} if self.saved_look is not None else self.cfg)

    # ------------------------------------------------------------ random look

    def roll_look(self):
        """A new random look (theme, glow, colours, animation, tube, opening), shown at once but not saved."""
        self._remember_look()   # one step on the Undo list, like a change by hand
        if self.saved_look is None:
            self.saved_look = {k: self.cfg[k] for k in LOOK}
        r = random.Random()
        theme = r.choice(("dark", "dark", "dark", "amber", "terminal", "light", "paper", "c64"))
        style = r.choices(("off", "soft", "halo"), (1, 3, 5))[0]
        light = not core.THEMES[theme][4]
        crt = r.random() < .3
        look = {"theme": theme, "soft": style != "off", "glow": r.randint(2, 5),
                "ramp": r.random() < .6, "ramp_colors": list(r.choice(RAMPS_LIGHT if light else RAMPS_DARK)),
                "cycle": r.random() < .3, "cycle_palette": r.choice(("c64", "ramp")),
                "wobble": r.random() < .25, "wobble_amount": r.choice(("low", "mid", "high")), "stars_mode": r.choice(("drift", "warp")),
                "stars": r.random() < .25, "scroller": r.random() < .2,
                "pulse": style == "halo" and r.random() < .35, "crt": crt, "crt_live": crt and r.random() < .5,
                "text_glow": r.random() < .3,
                "cycle_dir": r.choice(("down", "up")), "pulse_mode": r.choice(("beat", "breathe")),
                "opening": "off" if r.random() < .5 else r.choice([k for k in OPENINGS if k != "off"]),
                "sheen": r.random() < .2, "sparkle": r.random() < .2, "sparkle_amount": r.choice(("few", "some", "many")), "chroma": crt and r.random() < .5,
                "crt_mask": r.choice(("lines", "lines", "dots", "stripes")),
                "smooth": r.random() < 1 / 6, "smooth_amount": r.choice(("low", "mid", "high")),   # rarely: some love their pixels
                # the VGA font now and then; a font of your own stays unless the VGA font is on
                "font": core.DOS_FONT if r.random() < .25 else core.FONT if self.cfg["font"] == core.DOS_FONT else self.cfg["font"]}
        look["neon_flicker"] = style == "halo" and not look["pulse"] and r.random() < .25   # both beat the same glow
        if style != "off":
            look["glow_mode"] = style
        self._undoing = True   # half a roll may equal the saved look: that must not end the trial
        try:
            for key, value in look.items():
                self.change(key, value, rolled=True)
        finally:
            self._undoing = False
        self._show_look_state()

    def apply_look(self, look):
        """A look from a shared code: all of it is one step on the Undo list (see _remember_look). The Custom
        colours come first, the theme before the ramp, so that a ramp in the code wins over the theme's own.
        Like a rolled look it is on trial until kept (the Keep card), whether or not the sidebar is open."""
        self._remember_look()
        if self.saved_look is None:
            self.saved_look = {k: self.cfg[k] for k in LOOK}
        if "custom" in look:
            self.change("custom", look["custom"])
        if look.get("dos_font") is not None and look["dos_font"] != (self.cfg["font"] == core.DOS_FONT):
            self.toggle_dos_font()   # on: the VGA font; off: back to the standard one, a font of the user's own stays
        for key in LOOK:
            if key in look:
                self.change(key, look[key])

    def keep_look(self):
        """The look on trial (rolled or changed by hand) becomes the settings."""
        self.saved_look = None
        self._save()
        self._show_look_state()

    def undo_look(self):
        """Back to the look in the settings; the one left stays one step on the Undo list."""
        self._remember_look()
        self._undoing = True   # saved_look stays set until the end, so these changes start no new trial
        try:
            for key, value in (self.saved_look or {}).items():
                self.change(key, value)
        finally:
            self._undoing = False
        self.saved_look = None
        self._show_look_state()

    def _remember_look(self, look=None):
        """Put the look as it is now (or the given one) on the Undo list; the changes of one click (a style sets
        many settings) all come before the main loop runs again, so they count as one."""
        if getattr(self, "_grouping", False):
            return
        self._grouping = True
        GLib.idle_add(lambda: setattr(self, "_grouping", False))
        self.looks_before = [*self.looks_before[-49:], copy.deepcopy(look or {k: self.cfg[k] for k in LOOK})]
        self._show_look_state()

    def undo(self):
        """Back to the look before the last change by hand."""
        if not self.looks_before:
            return
        self._undoing = True
        try:
            for key, value in self.looks_before.pop().items():
                self.change(key, value)
        finally:
            self._undoing = False
        self._show_look_state()

    def _show_look_state(self):
        """Keep and Back (the card in the sidebar) only while the look differs from the one in the settings."""
        trial = self.saved_look is not None and any(self.cfg[k] != self.saved_look[k] for k in LOOK)
        if not trial and not self._undoing:
            self.saved_look = None   # nothing differs any more: the next change starts a new trial
        self.lookup_action("keep-look").set_enabled(trial)
        self.lookup_action("undo-look").set_enabled(trial)
        if self.lookup_action("undo"):
            self.lookup_action("undo").set_enabled(bool(self.looks_before))

    def reset(self, prefs=None):
        """Everything back to the defaults, the list of recent files emptied too."""
        self.saved_look, self.looks_before = None, []
        self._show_look_state()
        self.cfg.clear()   # the windows share this dict, so it is changed in place
        self.cfg.update({**core.DEFAULTS, "custom": dict(core.DEFAULTS["custom"]), "recent": [],
                         "theme": self._system_theme()})
        self.cfg["ramp_colors"] = list(THEME_RAMPS[self.cfg["theme"]])
        self._save()
        for key in ("theme", "encoding", *BOOL_ACTIONS):
            action = self.lookup_action(key.replace("_", "-"))
            action.set_state(GLib.Variant(action.get_state().get_type_string(), self.cfg[key]))
        self.lookup_action("glow-style").set_state(GLib.Variant("s", self._glow_style()))
        self.lookup_action("style").set_state(GLib.Variant("s", self._style()))
        self.lookup_action("dos-font").set_state(GLib.Variant("b", False))   # the font is back to the standard one
        self._fill_recent()
        self._allow_pulse()
        if prefs:
            prefs.close()
        self._apply_music()
        GLib.idle_add(self._rebuild)   # new windows show every default (zoom, language, ...) at once
