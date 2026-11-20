# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""The preferences dialog (General, Effects, Animation, Music). A mixin of App: its methods use the app's settings."""
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, GObject, Graphene, Gtk, Pango  # noqa: E402

import core  # noqa: E402
import i18n  # noqa: E402
import music  # noqa: E402
from i18n import N_, _  # noqa: E402
from ui_common import (SUB_SETTINGS, CRT_MASKS, CUSTOM_COLORS, CYCLE_DIRECTIONS, CYCLE_PALETTES, ENCODINGS, GLOW_MODES,  # noqa: E402
                       MUSIC_ORDER, PULSE_MODES, SPARKLE_AMOUNTS, STARS_MODES, THEME_NAMES, THEME_RAMPS, WOBBLE_AMOUNTS, opening_row,
                       slider)


class SettingsDialog:
    """Mixed into App. Every row changes one setting through App.change, which saves and shows it everywhere."""

    def preferences(self, *a, show=None):
        """The dialog with four pages; each row changes its setting at once. show: a setting whose row to bring into
        view and light up briefly (the gear beside a switch in the effects sidebar)."""
        self._rows = {}
        d = Adw.PreferencesDialog(title=_("Preferences"))   # else libadwaita titles it in the system language
        surprise, glow, colors, motion, logo, scroll, opening, retro = self._effects()
        behave, reset = self._behavior(d)
        # General first (the dialog opens there): behavior, look, and the reset at the very end
        for title, icon, groups in ((_("General"), "preferences-system-symbolic", (behave, *self._appearance(), *self._updates(), reset)),
                                    (_("Effects"), "preferences-color-symbolic", (surprise, glow, colors, retro)),
                                    (_("Animation"), "media-playback-start-symbolic", (motion, logo, scroll, opening)),
                                    (_("Music"), "audio-x-generic-symbolic", (self._music(),))):
            page = Adw.PreferencesPage(title=title, icon_name=icon)
            for group in groups:
                page.add(group)
            d.add(page)
        self.grey_out_dependents()
        d.present(self.get_active_window())
        row = self._rows.get(show)
        if row is not None:
            d.set_visible_page(row.get_ancestor(Adw.PreferencesPage))
            GLib.timeout_add(250, self._point_at, row)   # once the dialog is laid out and has set its own focus

    def _point_at(self, row):
        """Scroll a row of the preferences into view, give it the focus and let it light up and fade."""
        scrolled = row.get_ancestor(Gtk.ScrolledWindow)
        if scrolled is not None:
            ok, at = row.compute_point(scrolled.get_child(), Graphene.Point().init(0, 0))
            if ok:
                adj = scrolled.get_vadjustment()
                adj.set_value(min(max(0, at.y - adj.get_page_size() / 3), adj.get_upper() - adj.get_page_size()))
        if isinstance(row, Adw.ExpanderRow):   # the colours of the ramp: open, so they can be picked at once
            row.set_expanded(True)
        row.grab_focus()
        row.add_css_class("flash")
        GLib.timeout_add(1800, lambda: (row.remove_css_class("flash"), False)[1])
        return False

    def _replay_opening(self):
        w = self.get_active_window()
        if hasattr(w, "replay_opening"):
            w.replay_opening()

    def _appearance(self):
        """Theme and its custom colours, font, default zoom."""
        cfg = self.cfg
        look = Adw.PreferencesGroup(title=_("Appearance"))
        theme_row = self._combo(_("Theme"), THEME_NAMES, "theme")
        look.add(theme_row)
        colors = Adw.ExpanderRow(title=_("Custom colors"), subtitle=_("Picking a color switches to the Custom theme"))
        buttons = {}
        for key, label in CUSTOM_COLORS.items():
            rgba = Gdk.RGBA()
            rgba.parse(cfg["custom"].get(key, core.DEFAULTS["custom"][key]))
            button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), rgba=rgba, valign=Gtk.Align.CENTER)
            button.connect("notify::rgba", self._custom_color, key, theme_row)
            buttons[key] = button
            row = Adw.ActionRow(title=_(label))
            row.add_suffix(button)
            colors.add_row(row)
        back = Adw.ActionRow(title=_("Back to the default colors"))
        reset = Gtk.Button(label=_("Reset"), valign=Gtk.Align.CENTER)
        reset.connect("clicked", lambda _b: self._reset_custom(buttons))
        back.add_suffix(reset)
        colors.add_row(back)
        look.add(colors)
        mono = Gtk.CustomFilter.new(lambda f: (f.get_family() if isinstance(f, Pango.FontFace) else f).is_monospace())
        font = Gtk.FontDialogButton(dialog=Gtk.FontDialog(filter=mono), level=Gtk.FontLevel.FAMILY,
                                    font_desc=Pango.FontDescription.from_string(cfg["font"]), valign=Gtk.Align.CENTER)
        font.connect("notify::font-desc", lambda b, _p: self.change("font", b.get_font_desc().get_family()))
        row = Adw.ActionRow(title=_("Font"), subtitle=_("Monospace fonts only"))
        row.add_suffix(font)
        look.add(row)
        zoom = Adw.SpinRow.new_with_range(core.ZOOM_MIN, core.ZOOM_MAX, 10)
        zoom.set_title(_("Default zoom"))
        zoom.set_subtitle(_("In percent; Ctrl+0 goes back to it"))
        zoom.set_value(cfg["zoom"])
        zoom.connect("notify::value", lambda r, _p: self.change("zoom", int(r.get_value())))
        look.add(zoom)
        return (look,)

    def _effects(self):
        """Random look, glow, colour ramp, animation, on-opening effects and the CRT look."""
        cfg = self.cfg
        glow = Adw.PreferencesGroup(title=_("Glow"))
        glow.add(self._switch(_("Glow"), _("Light on the block graphics"), "soft"))
        glow.add(self._combo(_("Style"), GLOW_MODES, "glow_mode"))
        strength = slider(1, 5, 1, cfg["glow"])
        strength.set_size_request(180, -1)
        for v in range(1, 6):
            strength.add_mark(v, Gtk.PositionType.BOTTOM, None)
        strength.connect("value-changed", lambda sc: self.change("glow", round(sc.get_value())))
        row = Adw.ActionRow(title=_("Strength"))
        row.add_suffix(strength)
        glow.add(row)
        self._rows["glow"] = row
        glow.add(self._switch(_("Text glow"), _("Soft light around the text, like phosphor on an old monitor"), "text_glow"))
        flicker = self._switch(_("Flicker"), _("Flickers now and then, like an old sign; needs Neon"), "neon_flicker")
        self.lookup_action("neon-flicker").bind_property("enabled", flicker, "sensitive", GObject.BindingFlags.SYNC_CREATE)
        glow.add(flicker)
        # the pulse is a beat of the neon glow (to the music, or breathing without it), so it sits with the glow
        pulse = self._switch(_("Pulse"), _("The neon glow beats to the music, or breathes without it"), "pulse")
        self.lookup_action("pulse").bind_property("enabled", pulse, "sensitive", GObject.BindingFlags.SYNC_CREATE)
        glow.add(pulse)
        glow.add(self._combo(_("Pulse rhythm"), PULSE_MODES, "pulse_mode"))   # breathing also while music plays
        ramp = Adw.ExpanderRow(title=_("Color ramp"), subtitle=_("Each block of art runs from the top to the bottom color"),
                               show_enable_switch=True, enable_expansion=cfg["ramp"])
        ramp.connect("notify::enable-expansion", lambda r, _p: self.change("ramp", r.get_enable_expansion()))
        self._rows["ramp_colors"] = self._rows["ramp"] = ramp   # the switch is the row's own
        self._ramp_buttons = []   # they follow when a theme brings its own ramp
        for i, label in enumerate((N_("Top"), N_("Middle"), N_("Bottom"))):
            rgba = Gdk.RGBA()
            rgba.parse(cfg["ramp_colors"][i])
            button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), rgba=rgba, valign=Gtk.Align.CENTER)
            button.connect("notify::rgba", self._ramp_color, i)
            self._ramp_buttons.append(button)
            row = Adw.ActionRow(title=_(label))
            row.add_suffix(button)
            ramp.add_row(row)
        back = Adw.ActionRow(title=_("Back to the theme’s colors"))   # the ramp that comes with the theme
        reset = Gtk.Button(label=_("Reset"), valign=Gtk.Align.CENTER)
        reset.connect("clicked", lambda _b: self.change("ramp_colors", list(THEME_RAMPS.get(
            self.cfg["theme"], core.DEFAULTS["ramp_colors"]))))
        back.add_suffix(reset)
        ramp.add_row(back)
        colors_group = Adw.PreferencesGroup(title=_("Colors"))
        colors_group.add(ramp)
        retro = Adw.PreferencesGroup(title=_("Retro"))
        retro.add(self._switch(_("CRT screen"), _("Scanlines and dark corners, like an old monitor"),
                               "crt"))
        retro.add(self._combo(_("Pattern"), CRT_MASKS, "crt_mask"))
        retro.add(self._switch(_("Live CRT"), _("A roll bar, flicker, noise and round corners"),
                               "crt_live"))
        retro.add(self._switch(_("Color fringe"), _("Red and blue edges, like an old tube or a VHS tape"), "chroma"))
        dos = Adw.SwitchRow(title=_("DOS font"), subtitle=_("The IBM VGA font, as NFOs looked under DOS"),
                            active=self.cfg["font"] == core.DOS_FONT, sensitive=self.lookup_action("dos-font").get_enabled())
        dos.connect("notify::active", lambda r, _p: r.get_active() != (self.cfg["font"] == core.DOS_FONT)
                    and self.toggle_dos_font())
        retro.add(dos)
        surprise = Adw.PreferencesGroup(title=_("Random look"))
        surprise.add(self._switch(_("A new look at every start"),
                                  _("Each start shows a surprise look, only for this time; “Keep” in the effects sidebar makes it your look"),
                                  "random_on_start"))
        motion = Adw.PreferencesGroup(title=_("Colors in motion"), description=_("Like the demos of the C64 days"))
        motion.add(self._switch(_("Color cycling"), _("Colors move through the block graphics"), "cycle"))
        motion.add(self._combo(_("Cycling colors"), CYCLE_PALETTES, "cycle_palette"))
        motion.add(self._combo(_("Cycling direction"), CYCLE_DIRECTIONS, "cycle_dir"))
        logo = Adw.PreferencesGroup(title=_("Logo and stars"))
        logo.add(self._switch(_("Wobble"), _("The logo sways in a wave; the text stays still"), "wobble"))
        logo.add(self._combo(_("Wobble strength"), WOBBLE_AMOUNTS, "wobble_amount"))
        logo.add(self._switch(_("Starfield"), _("Stars behind the NFO"), "stars"))
        logo.add(self._combo(_("Stars"), STARS_MODES, "stars_mode"))
        logo.add(self._switch(_("Gleam"), _("A light sweeps across the art now and then"), "sheen"))
        logo.add(self._switch(_("Sparkle"), _("Single blocks of the art glint"), "sparkle"))
        logo.add(self._combo(_("How much sparkle"), SPARKLE_AMOUNTS, "sparkle_amount"))
        scroll = Adw.PreferencesGroup(title=_("Scroller"))
        scroll.add(self._switch(_("Sine scroller"), _("A wavy running text along the bottom"), "scroller"))
        text = Adw.EntryRow(title=_("Scroller text ({name} becomes the file name; empty: a greeting)"),
                            text=cfg["scroller_text"], show_apply_button=True)
        text.connect("apply", lambda r: self.change("scroller_text", r.get_text()))
        self._rows["scroller_text"] = text
        scroll.add(text)
        opening = Adw.PreferencesGroup(title=_("On opening"))
        self._rows["opening"] = opening_row(cfg, self.change, self._replay_opening)
        opening.add(self._rows["opening"])
        return surprise, glow, colors_group, motion, logo, scroll, opening, retro

    def _music(self):
        """Music on or off, the folder, the order, the volume and the fade-in."""
        cfg = self.cfg
        sound = Adw.PreferencesGroup(title=_("Music"), description=_(
            "Supported formats: MOD, XM, S3M, IT, OGG, MP3, FLAC, WAV"))
        if not music.available():
            sound.set_description(_("Music needs GStreamer, which is not installed."))
        sound.add(self._switch(_("Music"), _("Plays while NfoGlow is open"), "music"))
        folder = Adw.ActionRow(title=_("Music folder"), use_markup=False)   # a path may contain "&"
        self._rows["music_dir"] = folder
        def show_folder():
            folder.set_subtitle(self.cfg["music_dir"] or _("None: the built-in chiptunes by Stennish"))
        show_folder()
        pick = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                          tooltip_text=_("Choose a folder with MOD, XM, S3M, IT, OGG, MP3, FLAC or WAV files"))
        def picked(dialog, result):
            try:
                self.change("music_dir", dialog.select_folder_finish(result).get_path())
            except GLib.Error:
                return   # cancelled
            show_folder()
        pick.connect("clicked", lambda b: Gtk.FileDialog().select_folder(b.get_root(), None, picked))
        own = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                         tooltip_text=_("Back to the built-in chiptunes"))
        own.connect("clicked", lambda b: (self.change("music_dir", ""), show_folder()))
        folder.add_suffix(pick)
        folder.add_suffix(own)
        sound.add(folder)
        order = Adw.ComboRow(title=_("Order"), model=Gtk.StringList.new([_(v) for v in MUSIC_ORDER.values()]),
                             selected=0 if cfg["music_shuffle"] else 1)
        order.connect("notify::selected", lambda r, _p: self.change("music_shuffle", r.get_selected() == 0))
        sound.add(order)
        self._rows["music_shuffle"] = order
        volume = slider(0, 100, 5, cfg["volume"])
        volume.set_size_request(180, -1)
        volume.connect("value-changed", lambda sc: self.change("volume", round(sc.get_value())))
        row = Adw.ActionRow(title=_("Volume"))
        row.add_suffix(volume)
        self._rows["volume"] = row
        sound.add(row)
        sound.add(self._switch(_("Show the track name"), _("A short note at the bottom when a new track starts"),
                               "music_info"))
        sound.add(self._switch(_("Fade in and out"), _("The music starts quietly, and every track ends softly"),
                               "music_fade"))
        return sound

    def _behavior(self, dialog):
        """Copying, recent files, encoding, language, and resetting everything."""
        behave = Adw.PreferencesGroup(title=_("Behavior"))
        behave.add(self._switch(_("Copy text only"), _("Selecting and copying leave out block and line graphics"),
                                "copy_text_only"))
        behave.add(self._switch(_("Remember recent files"), _("Turning it off also clears the list"),
                                "remember_recent"))
        behave.add(self._combo(_("Encoding"), ENCODINGS, "encoding"))
        behave.add(self._combo(_("Language"), {"auto": N_("System default"), **i18n.languages()}, "language"))
        reset = Gtk.Button(label=_("Reset"), valign=Gtk.Align.CENTER, css_classes=["destructive-action"])
        reset.connect("clicked", lambda *a: self._confirm_reset(dialog))
        row = Adw.ActionRow(title=_("Reset settings"), subtitle=_("Back to the default values."))
        row.add_suffix(reset)
        info = Adw.PreferencesGroup(title=_("Other"))
        info.add(row)
        return behave, info

    def _updates(self):
        """A switch for the weekly check at start (off by default) and a row that checks right now and then says what it found.
        A newer release found at the start is already shown here."""
        if not core.update_check_offered():
            return ()
        group = Adw.PreferencesGroup(title=_("Updates"))
        group.add(self._switch(_("Check for updates weekly"),
                               _("Asks GitHub once a week for the newest version. Nothing is sent and nothing is installed."), "update_check"))
        self._update_row = Adw.ActionRow()
        self._update_button = Gtk.Button(valign=Gtk.Align.CENTER)
        self._update_button.connect("clicked", self._update_clicked)
        self._update_row.add_suffix(self._update_button)
        self._update_row.set_activatable_widget(self._update_button)
        self._show_update_state()
        group.add(self._update_row)
        return (group,)

    def _show_update_state(self):
        found = self.update_found
        self._update_button.set_sensitive(True)
        if found:
            self._update_row.set_title(_("Update available: {version}").format(version=found[0]))
            self._update_button.set_label(_("Release notes"))
        else:
            self._update_row.set_title(_("Installed version: {version}").format(version=core.__version__))
            self._update_button.set_label(_("Check now"))
            return
        self._update_row.set_subtitle(_("Installed version: {version}").format(version=core.__version__))

    def _update_clicked(self, button):
        if self.update_found:
            Gtk.UriLauncher(uri=self.update_found[1]).launch(self.get_active_window(), None, None)
            return
        button.set_sensitive(False)

        def work():
            try:
                found, error = core.newer_release(), None
            except (OSError, ValueError, KeyError) as e:
                found, error = None, e
            GLib.idle_add(self._update_checked, found, error)
        threading.Thread(target=work, daemon=True).start()

    def _update_checked(self, found, error):
        if error:
            self._update_button.set_sensitive(True)
            self.get_active_window().toast(_("Could not check for updates. Are you online?"))
            return
        self.update_found = found
        self._show_update_state()
        if not found:   # up to date: the row says so
            self._update_row.set_title(_("NfoGlow is up to date."))
            self._update_row.set_subtitle(_("Installed version: {version}").format(version=core.__version__))

    def _ramp_color(self, button, _p, i):
        c = button.get_rgba()
        colors = list(self.cfg["ramp_colors"])
        colors[i] = "#%02x%02x%02x" % tuple(round(v * 255) for v in (c.red, c.green, c.blue))
        self.change("ramp_colors", colors)

    def _confirm_reset(self, prefs):
        """The question before everything is reset: a warning triangle beside the text."""
        dialog = Adw.AlertDialog.new(_("Reset all settings?"), None)
        box = Gtk.Box(spacing=16, halign=Gtk.Align.CENTER, margin_top=6)
        box.append(Gtk.Image(icon_name="dialog-warning-symbolic", pixel_size=48, css_classes=["warning"]))
        box.append(Gtk.Label(label=_("The look, the language and everything else go back to their defaults.") + "\n\n" + _("Are you really sure?"),
                             xalign=0, wrap=True, hexpand=True))
        # as wide as its content (set_content_width crashes): a wide box instead of a narrow tower
        box.set_size_request(min(480, (prefs.get_width() or 544) - 64), -1)
        dialog.set_extra_child(box)
        dialog.add_response("no", _("Cancel"))
        dialog.add_response("yes", _("Reset"))
        dialog.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("no")
        dialog.choose(prefs, None, lambda dl, res: dl.choose_finish(res) == "yes" and self.reset(prefs))

    def _reset_custom(self, buttons):
        """The custom colors back to the defaults; the theme stays as it is (picking a color would switch to Custom)."""
        self._resetting_colors = True
        for key, button in buttons.items():
            rgba = Gdk.RGBA()
            rgba.parse(core.DEFAULTS["custom"][key])
            button.set_rgba(rgba)
        self._resetting_colors = False
        self.change("custom", dict(core.DEFAULTS["custom"]))

    def _custom_color(self, button, _p, key, theme_row):
        if getattr(self, "_resetting_colors", False):
            return
        c = button.get_rgba()
        self.change("custom", {**self.cfg["custom"],
                               key: "#%02x%02x%02x" % tuple(round(v * 255) for v in (c.red, c.green, c.blue))})
        self.change("theme", "custom")
        theme_row.set_selected(list(THEME_NAMES).index("custom"))

    def grey_out_dependents(self):
        """A choice that belongs to a switch is grey while that switch is off; the ramp's colours are the switch's own
        row. The glow style and strength follow the glow, the pulse rhythm the pulse (which needs the neon style)."""
        parents = {**{k: v for k, v in SUB_SETTINGS.items() if k != "ramp"}, "soft": ("glow_mode", "glow")}
        for parent, keys in parents.items():
            for key in keys:
                self._rows[key].set_sensitive(self.cfg[parent])
        self._rows["pulse_mode"].set_sensitive(self.cfg["pulse"] and self.lookup_action("pulse").get_enabled())

    def _combo(self, title, options, key):
        keys = list(options)
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new([_(v) for v in options.values()]),
                           selected=keys.index(self.cfg[key]) if self.cfg[key] in keys else 0)
        row.connect("notify::selected", lambda r, _p: self.change(key, keys[r.get_selected()]))
        self._rows[key] = row
        return row

    def _switch(self, title, subtitle, key):
        row = Adw.SwitchRow(title=title, subtitle=subtitle, active=self.cfg[key])
        row.connect("notify::active", lambda r, _p: self.change(key, r.get_active()))
        self._rows[key] = row
        return row
