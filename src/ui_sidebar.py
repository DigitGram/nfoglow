# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""The effects sidebar beside the NFO: theme, styles, the folded fine-tuning, music and the random look."""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, GObject, Gtk  # noqa: E402

import math  # noqa: E402

import music  # noqa: E402
from core import theme_colors  # noqa: E402
from i18n import N_, _  # noqa: E402
from ui_common import OPENINGS, STYLES, SUB_SETTINGS, THEME_NAMES, opening_row, slider  # noqa: E402


class EffectsSidebar:
    """Mixed into Window."""

    def _swatches(self):
        """The themes as round colour swatches (each shows its background, art and text colour) and the chosen
        theme's name under them: all eight in one row (they fit the narrowest sidebar at 22 pixels), and the colours
        say more than the names."""
        row = Gtk.Grid(column_spacing=2, column_homogeneous=True)
        self._swatch_areas = []
        for i, (key, name) in enumerate(THEME_NAMES.items()):
            area = Gtk.DrawingArea(content_width=22, content_height=22, can_target=False)
            area.set_draw_func(self._draw_swatch, key)
            button = Gtk.ToggleButton(child=area, action_name="app.theme", action_target=GLib.Variant("s", key),
                                      tooltip_text=_(name), css_classes=["swatch", "flat"], halign=Gtk.Align.CENTER)
            button.update_property([Gtk.AccessibleProperty.LABEL], [_(name)])
            row.attach(button, i, 0, 1, 1)
            self._swatch_areas.append(area)
        self._theme_name = Gtk.Label(label=_(THEME_NAMES.get(self.cfg["theme"], "")), css_classes=["dim-label"])
        return row, self._theme_name

    def _draw_swatch(self, _area, cr, w, h, key):
        bg, tx, art, _link, _dark = theme_colors({**self.cfg, "theme": key})
        r = min(w, h) / 2
        cr.arc(w / 2, h / 2, r - .5, 0, 2 * math.pi)
        cr.set_source_rgb(*bg)
        cr.fill_preserve()
        cr.set_source_rgba(.5, .5, .5, .55)   # an edge that shows on light and dark sidebars
        cr.set_line_width(1)
        cr.stroke()
        cr.set_source_rgb(*art)   # a little block of art ...
        cr.rectangle(w * .26, h * .3, w * .2, h * .4)
        cr.fill()
        cr.set_source_rgb(*tx)    # ... and two lines of text beside it
        for y in (.36, .56):
            cr.rectangle(w * .52, h * y, w * .24, h * .08)
        cr.fill()

    def _show_theme(self):
        """After a change of the theme or the custom colours."""
        self._theme_name.set_label(_(THEME_NAMES.get(self.cfg["theme"], "")))
        for area in self._swatch_areas:
            area.queue_draw()

    def show_summaries(self):
        """Under each folded section, the effects in it that are on ("Off" when none is)."""
        for expander, summary in getattr(self, "_summaries", ()):
            names = summary()
            expander.set_subtitle(", ".join(names) if names else _("Off"))

    def _effects_sidebar(self):
        """The effects beside the NFO. Every control is bound to the same action as the menu and the preferences, so
        they all stay in step whatever changes a setting (a click here, the preferences, a random look)."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=12, margin_bottom=12,
                      margin_start=12, margin_end=12)

        def group(title, *widgets, into=box, beside=None):
            """A heading (with a button at its right end if given), then the widgets in order: button grids as they
            are, rows in a boxed list."""
            section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            heading = Gtk.Label(label=title, xalign=0, hexpand=True, css_classes=["heading"])
            if beside:
                head = Gtk.Box(spacing=8)
                head.append(heading)
                head.append(beside)
                section.append(head)
            else:
                section.append(heading)
            rows = None
            for w in widgets:
                if isinstance(w, Gtk.ListBoxRow):
                    if rows is None:
                        rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
                        section.append(rows)
                    rows.append(w)
                else:
                    section.append(w)
                    rows = None
            into.append(section)

        def switch(action, label, subtitle=None):
            """A switch row. If settings belong to it (SUB_SETTINGS: the colours of the cycling, the strength of the
            wobble ...), a gear beside it, while it is on, opens the preferences at the first one and lights it up."""
            more = SUB_SETTINGS.get(action.split(".", 1)[1].replace("-", "_"), (None,))[0]
            sw = Gtk.Switch(action_name=action, valign=Gtk.Align.CENTER)
            row = Adw.ActionRow(title=_(label), subtitle=_(subtitle) if subtitle else None, activatable_widget=sw)
            if more:
                gear = Gtk.Button(icon_name="emblem-system-symbolic", valign=Gtk.Align.CENTER,
                                  css_classes=["flat", "circular"], tooltip_text=_("More settings"))
                gear.update_property([Gtk.AccessibleProperty.LABEL], [_("More settings")])
                gear.connect("clicked", lambda *_a: self.app.preferences(show=more))
                self.app.lookup_action(action.split(".", 1)[1]).bind_property(
                    "state", gear, "visible", GObject.BindingFlags.SYNC_CREATE, lambda _b, v: v.unpack())
                row.add_suffix(gear)
            row.add_suffix(sw)
            row.action = action.split(".", 1)[1]   # for the summary of its section
            return row

        def choices(action, options, columns):
            grid = Gtk.Grid(column_spacing=6, row_spacing=6, column_homogeneous=True)
            for i, (key, label) in enumerate(options.items()):
                grid.attach(Gtk.ToggleButton(label=_(label), action_name=action, action_target=GLib.Variant("s", key)),
                            i % columns, i // columns, 1, 1)
            return grid

        group(_("Theme"), *self._swatches())
        group(_("Style"), choices("app.style", {k: v[0] for k, v in STYLES.items()}, 3))
        # every effect on its own, in sections that fold: one open at a time, the styles above are enough for most
        styles = choices("app.glow-style", {"off": N_("Off"), "soft": N_("Soft"), "halo": N_("Neon")}, 3)
        styles.set_margin_top(8)
        styles.set_margin_bottom(8)
        styles.set_margin_start(12)
        styles.set_margin_end(12)
        self.strength = slider(1, 5, 1, self.cfg["glow"])
        self.strength.set_hexpand(True)
        for v in range(1, 6):
            self.strength.add_mark(v, Gtk.PositionType.BOTTOM, None)
        self.strength.connect("value-changed", lambda sc: self.app.change("glow", round(sc.get_value())))
        self.app.lookup_action("glow-style").bind_property(   # no strength to set when there is no glow
            "state", self.strength, "sensitive", GObject.BindingFlags.SYNC_CREATE, lambda _b, v: v.unpack() != "off")
        strength = Adw.ActionRow(title=_("Strength"))
        strength.add_suffix(self.strength)
        self.opening_row = opening_row(self.cfg, self.app.change, self.replay_opening, describe=False)
        sections, self._summaries = [], []

        def section(title, icon, first, *rows, names=None):
            """A section that folds; under its title the effects that are on, so nobody has to open it to see: the
            switches in it that are on, by their own titles (so a new switch is in its summary without more ado),
            after what first() returns; names can give a switch another name (the tube by its pattern)."""
            switches = [r for r in rows if hasattr(r, "action")]

            def summary():
                on = [(names or {}).get(r.action, r.get_title)() for r in switches
                      if self.app.lookup_action(r.action).get_state().unpack()]
                return [*first(), *on]
            expander = Adw.ExpanderRow(title=_(title), icon_name=icon, subtitle_lines=1)
            for row in rows:
                expander.add_row(row if isinstance(row, Gtk.ListBoxRow)
                                 else Gtk.ListBoxRow(child=row, activatable=False, selectable=False))
            expander.connect("notify::expanded", lambda r, _p: r.get_expanded() and
                             [o.set_expanded(False) for o in sections if o is not r])
            sections.append(expander)
            self._summaries.append((expander, summary))
            return expander

        glow_names = {"off": N_("Off"), "soft": N_("Soft"), "halo": N_("Neon")}
        section(N_("Glow"), "display-brightness-symbolic", lambda: [_(glow_names[self.app._glow_style()])],
                styles, strength, switch("app.ramp", N_("Color ramp")), switch("app.text-glow", N_("Text glow")),
                switch("app.neon-flicker", N_("Flicker"), N_("Flickers now and then, like an old sign; needs Neon")),
                switch("app.pulse", N_("Pulse"), N_("Neon glow to the beat; needs Neon")))
        section(N_("Animation"), "media-playback-start-symbolic", list,
                switch("app.cycle", N_("Color cycling")),
                switch("app.wobble", N_("Wobble")),
                switch("app.stars", N_("Starfield")),
                switch("app.scroller", N_("Sine scroller")),
                switch("app.sheen", N_("Gleam"), N_("A light sweeps across the art now and then")),
                switch("app.sparkle", N_("Sparkle"), N_("Single blocks of the art glint")))
        section(N_("Retro"), "video-display-symbolic", list,
                switch("app.crt", N_("CRT screen")),   # its gear leads to the pattern
                switch("app.crt-live", N_("Live CRT"), N_("A roll bar, flicker, noise and round corners")),
                switch("app.chroma", N_("Color fringe"), N_("Red and blue edges, like an old tube or a VHS tape")),
                switch("app.dos-font", N_("DOS font"), N_("The IBM VGA font, as NFOs looked under DOS")))
        section(N_("On opening"), "document-open-symbolic",
                lambda: [_(OPENINGS.get(self.cfg["opening"], OPENINGS["off"]))], self.opening_row)
        sound = switch("app.music", N_("Music"))
        sound.set_sensitive(music.available())
        section(N_("Sound"), "audio-x-generic-symbolic", list, sound)
        self.show_summaries()
        fine = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        for expander in sections:
            fine.append(expander)
        # the undo of the whole look sits with the effects it mostly undoes, not beside the dice
        undo = Gtk.Button(icon_name="edit-undo-symbolic", action_name="app.undo", css_classes=["flat", "circular"],
                          valign=Gtk.Align.CENTER, tooltip_text=_("Undo: back to the look before your last change"))
        undo.update_property([Gtk.AccessibleProperty.LABEL], [_("Undo")])
        group(_("Effects and sound"), fine, beside=undo)

        # the buttons below stay in view: outside the scrolled settings, so "Colors and more" cannot hide below the fold
        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=10, margin_bottom=12,
                         margin_start=12, margin_end=12)
        roll = Gtk.Button(child=Adw.ButtonContent(icon_name="media-playlist-shuffle-symbolic", label=_("Random look")),
                          action_name="app.roll-look", tooltip_text=_("Roll a new look (not saved yet)"),
                          css_classes=["pill"])
        settings = Gtk.Button(icon_name="emblem-system-symbolic", action_name="app.preferences", css_classes=["circular"],
                              valign=Gtk.Align.CENTER, tooltip_text=_("Colors and more…"))
        settings.update_property([Gtk.AccessibleProperty.LABEL], [_("Colors and more…")])
        roll.set_hexpand(True)
        row = Gtk.Box(spacing=8)
        row.append(roll)
        row.append(settings)
        footer.append(row)
        # only while the look differs from the saved one (a roll, or any change here): keep it, or go back
        note = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["card"])
        note.append(Gtk.Label(label=_("This look is not saved yet."), wrap=True, margin_top=10, margin_start=10,
                              margin_end=10))
        buttons = Gtk.Box(spacing=6, homogeneous=True, margin_bottom=10, margin_start=10, margin_end=10)
        buttons.append(Gtk.Button(label=_("Keep"), action_name="app.keep-look", css_classes=["suggested-action"],
                                  tooltip_text=_("Save this look as your settings")))
        buttons.append(Gtk.Button(label=_("Back"), action_name="app.undo-look",
                                  tooltip_text=_("Back to the look in your settings")))
        note.append(buttons)
        reveal = Gtk.Revealer(child=note)
        self.app.lookup_action("keep-look").bind_property("enabled", reveal, "reveal-child",
                                                         GObject.BindingFlags.SYNC_CREATE)
        footer.append(reveal)
        scrolled = Gtk.ScrolledWindow(child=box, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["background"])
        outer.append(scrolled)
        outer.append(Gtk.Separator())
        outer.append(footer)
        return outer
