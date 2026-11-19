# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""A window: header bar, search bar, the view with its overlays, loading and browsing files, zoom, and the frame
clock that drives the animations."""
import os

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

import core  # noqa: E402
import gpu  # noqa: E402
import music  # noqa: E402
import overlays  # noqa: E402
from decode import BROWSE_SUFFIXES, read  # noqa: E402
from i18n import N_, _  # noqa: E402
from page import Page, TooBig, fill  # noqa: E402
from ui_common import ENCODINGS, FILE_ACTIONS, LOOK_CHOICES, LOOK_SHARED, OPENINGS, ZOOM_STEPS  # noqa: E402
from ui_sidebar import EffectsSidebar  # noqa: E402
from ui_view import View  # noqa: E402


C64_FRAME = 0.075   # the light blue border of the C64 theme: this share of the window width on every side, like the
#                    original (about 8 % of the screen width), so it keeps its proportions at any zoom or window size

class Window(EffectsSidebar, Adw.ApplicationWindow):
    """One window showing one file (self.page). It reacts to settings through setting_changed() and runs the frame
    clock only while something moves (_animate_update)."""

    def __init__(self, app):
        super().__init__(application=app, default_width=860, default_height=900, title="NfoGlow")
        self.app, self.cfg, self.path, self.data, self.text_only = app, app.cfg, None, None, False
        self._tick, self._last_frame, self._reveal_from, self._glitch_from = None, 0, None, None   # the frame clock
        self.loading, self._loading_from, self.boot_kind = None, None, "loader"   # seconds into the tape loader or the
        self._opening_from = None                                                  # DOS boot on opening, or None
        self.name, self._monitor, self._reread_pending = "", None, False
        self.page = Page(self.cfg, self.cfg["zoom"] / 100)
        self.view = View(self.page)
        self.scroller = Gtk.ScrolledWindow(child=self.view, vexpand=True)
        wheel = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        wheel.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        wheel.connect("scroll", self._wheel)
        self.scroller.add_controller(wheel)

        self.search = self._search_bar()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self.search)
        # CRT look: a layer over the view, so the scanlines and dark corners stay put while the NFO scrolls
        # layers fixed to the window, from the bottom up. Only the scroller strip is redrawn each frame; the tube is
        # drawn once, its roll bar is only moved, and its flicker and grain are thin layers redrawn in a moment.
        self.strip = gpu.Drawn(lambda snap, w, h: gpu.scroller(
            snap, w, h, self.page.time, self._scroller_text(), self.cfg["font"],
            overlays.scroller_size(self.scroller.get_height())), can_target=False, valign=Gtk.Align.END)
        # the still tube as a texture, made once per size: drawn as a cairo layer, GTK sent the whole picture to the
        # graphics card again whenever anything over it changed (the grain, ten times a second: a third of a CPU core)
        self.crt = gpu.Drawn(lambda snap, w, h: gpu.still_layer(
            snap, w, h, self.crt, (self.cfg["crt_live"], self.cfg["crt_mask"]), lambda cr, w, h: overlays.crt_static(
                cr, w, h, self.cfg["crt_live"], "lines" if self.cfg["crt_mask"] == "lines" else None)),
            can_target=False)
        self.rollbar = gpu.Drawn(lambda snap, w, h: gpu.still_layer(snap, w, h, self.rollbar, None, overlays.crt_roll_bar),
                                 can_target=False)
        self.roll_layer = Gtk.Fixed(can_target=False)
        self.roll_layer.put(self.rollbar, 0, 0)
        # the flicker (black at a changing alpha) and the grain of the living tube in one layer, redrawn every frame:
        # a second layer over the whole window that changed at other moments cost about half a CPU core
        self._flicker_alpha = 0.0
        self.noise = gpu.Drawn(lambda snap, w, h: gpu.noise(snap, w, h, self.page.time, self._flicker_alpha),
                               can_target=False, visible=False)
        self.screen = screen = Gtk.Overlay(child=self.scroller, vexpand=True)
        # the tape loader and the DOS boot lie over everything while they run; a click skips them
        self.loader = gpu.Drawn(self._draw_boot, visible=False)
        skip = Gtk.GestureClick()
        skip.connect("pressed", lambda *a: self.skip_opening())
        self.loader.add_controller(skip)
        for layer in (self.strip, self.roll_layer, self.noise, self.crt, self.loader):   # tube, loader on top
            screen.add_overlay(layer)
        box.append(screen)
        open_button = Gtk.Button(label=_("Open…"), halign=Gtk.Align.CENTER, action_name="win.open",
                                 css_classes=["pill", "suggested-action"])
        empty = Adw.StatusPage(icon_name=core.APP_ID, title=_("No NFO open"), child=open_button,
                               description=_("Drop a file here or press Ctrl+O."))
        self.stack = Gtk.Stack()
        self.stack.add_named(empty, "empty")
        self.stack.add_named(box, "page")
        self.toasts = Adw.ToastOverlay(child=self.stack)

        self.title = Adw.WindowTitle(title="NfoGlow")
        self.bar = Adw.HeaderBar(title_widget=self.title)
        # left: Open and the view (art or text); right: search, the effects sidebar and the main menu.
        # Everything else lives in the sidebar, which pushes the NFO aside instead of covering it.
        self.bar.pack_start(Adw.SplitButton(icon_name="document-open-symbolic", tooltip_text=_("Open (Ctrl+O)"),
                                            action_name="win.open", menu_model=app.recent_menu,
                                            dropdown_tooltip=_("Recent files")))
        views = Gtk.Box(css_classes=["linked"])
        for target, label, tip in (("art", N_("Art"), N_("The NFO with its graphics")),
                                   ("text", N_("Text"), N_("Only the text, without the graphics (Ctrl+T)"))):
            views.append(Gtk.ToggleButton(label=_(label), tooltip_text=_(tip), action_name="win.view",
                                          action_target=GLib.Variant("s", target)))
        self.bar.pack_start(views)
        self.bar.pack_end(self._main_menu())
        self.split = Adw.OverlaySplitView(content=self.toasts, sidebar=self._effects_sidebar(),
                                          sidebar_position=Gtk.PackType.END, show_sidebar=self.cfg["sidebar"],
                                          min_sidebar_width=270, max_sidebar_width=320)
        # remember only what the user did: a narrow window folds the sidebar away by itself (also while the window
        # is first laid out), and when it is wide again the sidebar comes back if it was open
        self.split.connect("notify::show-sidebar",
                           lambda sp, _p: sp.get_collapsed() or app.change("sidebar", sp.get_show_sidebar()))
        if self.cfg["maximized"]:   # the window opens as the last one was left
            self.maximize()
        self.connect("notify::maximized", lambda w, _p: app.change("maximized", w.is_maximized()))
        self.split.connect("notify::collapsed",
                           lambda sp, _p: sp.get_collapsed() or sp.set_show_sidebar(self.cfg["sidebar"]))
        effects = Gtk.ToggleButton(icon_name="preferences-color-symbolic", tooltip_text=_("Effects (F9)"))
        self.split.bind_property("show-sidebar", effects, "active",   # from the split view: it holds the saved state
                                 GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        self.bar.pack_end(effects)
        find = Gtk.ToggleButton(icon_name="edit-find-symbolic", tooltip_text=_("Search (Ctrl+F)"))
        find.bind_property("active", self.search, "search-mode-enabled",
                           GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        self.bar.pack_end(find)
        view = Adw.ToolbarView(content=self.split)
        view.add_top_bar(self.bar)
        self.set_content(view)
        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 720sp"))
        narrow.add_setter(self.split, "collapsed", True)   # small windows: the sidebar lies over the NFO instead
        self.add_breakpoint(narrow)

        for name, cb in (("open", self.open_dialog), ("save-png", lambda *a: self.export(".png")),
                         ("save-pdf", lambda *a: self.export(".pdf")), ("reload", lambda *a: self.reread()),
                         ("copy", self.copy), ("copy-all", self.copy_all),
                         ("copy-look", self.copy_look), ("paste-look", self.paste_look),
                         ("select-all", self.select_all), ("zoom-in", lambda *a: self.zoom_step(1)),
                         ("zoom-out", lambda *a: self.zoom_step(-1)),
                         ("zoom-reset", lambda *a: self.zoom_to(self.cfg["zoom"])),
                         ("search", lambda *a: self.search.set_search_mode(True)),
                         ("toggle-effects", lambda *a: self.split.set_show_sidebar(not self.split.get_show_sidebar()))):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", cb)
            self.add_action(a)
        for name, cb in (("text-only", self._toggle_text_only), ("fit-width", self._toggle_fit)):
            a = Gio.SimpleAction.new_stateful(name, None, GLib.Variant("b", False))   # a check mark in the menu
            a.connect("activate", cb)
            self.add_action(a)
        a = Gio.SimpleAction.new_stateful("view", GLib.VariantType("s"), GLib.Variant("s", "art"))
        a.connect("activate", lambda _a, v: self._set_text_only(v.unpack() == "text"))
        self.add_action(a)
        self._zoom_before_fit = None
        self._margin = 0   # the C64 border now around the view
        self._animate_update()
        # keep fitting while the window is resized
        self.scroller.get_hadjustment().connect("notify::page-size", self._resized)
        for name in (*FILE_ACTIONS, "view"):
            self.lookup_action(name).set_enabled(False)   # until a file is open
        drop = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop.connect("drop", lambda _d, f, *a: self.load(f.get_path()) or True)
        self.add_controller(drop)
        keys = Gtk.EventControllerKey()   # on the view: only while it has the focus, and before the search bar
        keys.connect("key-pressed", self._key)   # (which grabs typed text) and never inside dialogs
        self.view.add_controller(keys)
        self.connect("close-request", self._closed)   # not "destroy": the monitor holds the window, so that never comes


    def _closed(self, *_a):
        """A closed window stops watching its file; a reload still waiting for its 200 ms then does nothing."""
        if self._monitor:
            self._monitor.cancel()
        self.path, self._siblings_of = None, None
        return False   # go on closing

    def toast(self, text, timeout=5):
        """A short message at the bottom of the window; plain text, so a file name with "<" or "&" shows as it is."""
        self.toasts.add_toast(Adw.Toast(use_markup=False, title=text, timeout=timeout))

    # ------------------------------------------------------------ building blocks
    def _main_menu(self):
        zoom_section, view, share, app = Gio.Menu(), Gio.Menu(), Gio.Menu(), Gio.Menu()
        item = Gio.MenuItem()
        item.set_attribute_value("custom", GLib.Variant("s", "zoom"))
        zoom_section.append_item(item)
        view.append(_("Fit width"), "win.fit-width")
        view.append(_("Reload"), "win.reload")
        if music.available():   # a check mark, like the switch in the sidebar
            view.append(_("Music"), "app.music")
        enc = Gio.Menu()
        for k, v in ENCODINGS.items():
            enc.append(_(v), f"app.encoding::{k}")
        view.append_submenu(_("Encoding"), enc)
        export, look = Gio.Menu(), Gio.Menu()
        export.append(_("Copy to clipboard"), "win.copy-all")
        export.append(_("Save as PNG…"), "win.save-png")
        export.append(_("Save as PDF…"), "win.save-pdf")
        look.append(_("Copy look"), "win.copy-look")
        look.append(_("Paste look"), "win.paste-look")
        share.append_submenu(_("Export"), export)
        share.append_submenu(_("Look"), look)
        app.append(_("Keyboard shortcuts"), "app.shortcuts")
        app.append(_("Preferences"), "app.preferences")
        app.append(_("About NfoGlow"), "app.about")
        menu = Gio.Menu()
        for section in (zoom_section, view, share, app):
            menu.append_section(None, section)
        pop = Gtk.PopoverMenu.new_from_model(menu)
        row = Gtk.Box(spacing=6, margin_start=12, margin_end=12)
        row.append(Gtk.Button(icon_name="zoom-out-symbolic", action_name="win.zoom-out", css_classes=["flat", "circular"],
                              tooltip_text=_("Zoom out (Ctrl+−)")))
        self.zoom_label = Gtk.Button(label="", action_name="win.zoom-reset", css_classes=["flat"], hexpand=True,
                                     tooltip_text=_("Default zoom (Ctrl+0)"))
        row.append(self.zoom_label)
        row.append(Gtk.Button(icon_name="zoom-in-symbolic", action_name="win.zoom-in", css_classes=["flat", "circular"],
                              tooltip_text=_("Zoom in (Ctrl++)")))
        self.zoom_save = Gtk.Button(label=_("Save as default"), margin_start=12, margin_end=12, margin_bottom=4,
                                    tooltip_text=_("Open every NFO at this zoom from now on"))
        self.zoom_save.connect("clicked", lambda b: (self.app.change("zoom", round(self.page.zoom * 100)), pop.popdown()))
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        column.append(row)
        column.append(self.zoom_save)
        pop.add_child(column, "zoom")
        self._show_zoom()
        return Gtk.MenuButton(icon_name="open-menu-symbolic", popover=pop, primary=True, tooltip_text=_("Main menu"))

    def _search_bar(self):
        self.entry = Gtk.SearchEntry(placeholder_text=_("Search"), hexpand=True)
        self.count = Gtk.Label(css_classes=["dim-label", "numeric"])
        prev = Gtk.Button(icon_name="go-up-symbolic", tooltip_text=_("Previous match (Shift+Enter)"))
        nxt = Gtk.Button(icon_name="go-down-symbolic", tooltip_text=_("Next match (Enter)"))
        prev.connect("clicked", lambda *a: self.step(-1))
        nxt.connect("clicked", lambda *a: self.step(1))
        self.entry.connect("search-changed", lambda *a: self.find())
        self.entry.connect("activate", lambda *a: self.step(1))
        self.entry.connect("next-match", lambda *a: self.step(1))
        self.entry.connect("previous-match", lambda *a: self.step(-1))
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, _code, state: (kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter)
                     and state & Gdk.ModifierType.SHIFT_MASK and (self.step(-1) or True)) or False)
        self.entry.add_controller(keys)
        row = Gtk.Box(spacing=6)
        for w in (self.entry, self.count, prev, nxt):
            row.append(w)
        bar = Gtk.SearchBar(child=Adw.Clamp(child=row, maximum_size=520), key_capture_widget=self)
        bar.connect_entry(self.entry)
        bar.connect("notify::search-mode-enabled", lambda b, _p: b.get_search_mode() or self.find(""))
        return bar

    # ------------------------------------------------------------ file

    def load(self, path, resize=True, remember=True):
        if not path:   # a Gio.File without a local path: a web link dropped from a browser, an sftp:// argument
            self.toast(_("Only files on this computer can be opened."))
            return
        try:
            self.data, self.name = read(path)
        except OSError as e:
            self.toast(_("Cannot open {name}: {error}").format(name=os.path.basename(path), error=e.strerror or e))
            return
        self.path, self._siblings_of = path, None   # the folder is listed again for a newly loaded file
        for name in (*FILE_ACTIONS, "view"):
            self.lookup_action(name).set_enabled(True)
        self._watch(path)
        if remember:   # not when a new window only shows the same file again (language change, reset)
            self.app.add_recent(path)
        self.reload()
        self.view.grab_focus()
        self.scroller.get_vadjustment().set_value(0)
        if not self.text_only:
            self.start_opening()
        if resize and not self._fitting():   # with "fit width" the window decides the zoom, not the other way round
            self._size_to_page()

    def _watch(self, path):
        """Reload when the file changes on disk (handy while drawing an NFO in an editor)."""
        if self._monitor:
            self._monitor.cancel()
        self._monitor = Gio.File.new_for_path(path).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self._monitor.connect("changed", self._file_changed)

    def _file_changed(self, _m, _f, _other, event):
        if event in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED) \
                and not self._reread_pending:
            self._reread_pending = True   # editors write in several steps: wait for the last one
            GLib.timeout_add(200, self._reread_later)

    def _reread_later(self):
        self._reread_pending = False
        self.reread(quiet=True)
        return False

    def reread(self, quiet=False):
        """Read the file again and keep the scroll position."""
        if not self.path:
            return
        try:
            self.data, self.name = read(self.path)
        except OSError as e:
            if not quiet:
                self.toast(_("Cannot open {name}: {error}").format(
                    name=os.path.basename(self.path), error=e.strerror or e))
            return
        top = self.scroller.get_vadjustment().get_value()
        self.reload()
        GLib.idle_add(lambda: self.scroller.get_vadjustment().set_value(top) and False)

    def _siblings(self):
        """The NFO and SRR files in the folder of the open file, sorted by name."""
        if not self.path:
            return []
        if self._siblings_of != self.path:   # cached: on a network share the listing took a quarter second per toggle
            folder = os.path.dirname(self.path)
            try:
                names = sorted((n for n in os.listdir(folder) if n.lower().endswith(BROWSE_SUFFIXES)), key=str.lower)
            except OSError:
                names = []
            self._siblings_cache, self._siblings_of = [os.path.join(folder, n) for n in names], self.path
        return self._siblings_cache

    def browse(self, step):
        files = self._siblings()
        i = files.index(self.path) + step if self.path in files else -1
        if 0 <= i < len(files):
            self.load(files[i], resize=False)   # a jumping window while browsing would be annoying
        else:
            self.error_bell()

    def _key(self, _c, keyval, _code, state):
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK):
            return False
        if self.skip_opening():   # any key ends the effect on opening
            return True
        adj = self.scroller.get_vadjustment()
        page = adj.get_page_size() * .9
        if keyval in (Gdk.KEY_Left, Gdk.KEY_Right):
            self.browse(1 if keyval == Gdk.KEY_Right else -1)
        elif keyval == Gdk.KEY_space:
            adj.set_value(adj.get_value() + (-page if state & Gdk.ModifierType.SHIFT_MASK else page))
        elif keyval in (Gdk.KEY_Page_Down, Gdk.KEY_Page_Up):
            adj.set_value(adj.get_value() + (page if keyval == Gdk.KEY_Page_Down else -page))
        elif keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            adj.set_value(adj.get_value() + (self.page.ch if keyval == Gdk.KEY_Down else -self.page.ch) * 3)
        elif keyval in (Gdk.KEY_Home, Gdk.KEY_End):
            adj.set_value(0 if keyval == Gdk.KEY_Home else adj.get_upper())
        else:
            return False
        return True

    def _size_to_page(self):
        """Window as big as the NFO, within 90 % of the screen; tiny or empty files get a minimum size."""
        if self.is_maximized() or self.is_fullscreen():
            return
        display = self.get_display()
        monitor = (self.get_surface() and display.get_monitor_at_surface(self.get_surface())) \
            or display.get_monitors().get_item(0)
        screen = monitor.get_geometry() if monitor else None
        header = self.bar.get_height() or 47   # not measured yet before the first show
        c64 = self.cfg["theme"] == "c64"   # the border around the C64 screen
        width = int(self.page.width / (1 - 2 * C64_FRAME)) if c64 else self.page.width
        height = self.page.height + header + (2 * round(C64_FRAME * width) if c64 else 0)
        if screen:
            width, height = min(width, int(screen.width * .9)), min(height, int(screen.height * .9))
        self.set_default_size(max(width, 600), max(height, 420))

    def reload(self):
        fill(self.page, self.data, self.cfg["encoding"], self.text_only)
        self.view.refresh()
        self.stack.set_visible_child_name("page")
        self.set_title(self.name)
        self.title.set_title(self.name)
        files = self._siblings()
        position = f"{files.index(self.path) + 1} / {len(files)} · " if len(files) > 1 and self.path in files else ""
        self.title.set_subtitle(f"{position}{self.page.cols} × {len(self.page.rows)} · {self.page.label} · "
                                f"{len(self.data) / 1024:.1f} KB")
        if self.search.get_search_mode():
            self.find()
        if self._fitting():
            self._fit()

    def setting_changed(self, key):
        if key == "zoom":
            self._show_zoom()   # the "Save as default" button follows, also in the other windows
        self.show_summaries()
        if key == "opening":   # the choice in the sidebar follows a change made in the preferences
            keys = list(OPENINGS)
            self.opening_row.set_selected(keys.index(self.cfg[key]) if self.cfg[key] in keys else 0)
            return
        # settings that change nothing on the page; "sidebar" even comes while the window is still being built
        if key in ("recent", "remember_recent", "zoom", "language", "music", "music_dir", "music_shuffle", "volume",
                   "sidebar", "music_fade", "random_on_start", "music_info", "maximized"):
            return
        self._animate_update()
        if key == "encoding" and self.data is not None:
            self.reload()
        elif key == "font":
            self.page.set_zoom(self.page.zoom)
            self.view.refresh()
        else:
            self.page._fx.clear()
            self.view.queue_draw()
        if key == "glow" and round(self.strength.get_value()) != self.cfg["glow"]:
            self.strength.set_value(self.cfg["glow"])
        if key in ("theme", "custom"):
            self._show_theme()
        if key in ("crt", "crt_live", "crt_mask", "scroller", "scroller_text"):
            self.crt.queue_draw()   # else the last frame of the living tube (roll bar, corners) stays on screen

    def open_dialog(self, *a):
        nfo = Gtk.FileFilter(name=_("NFO, ANSI, SRR and ZIP files"))
        for suffix in ("nfo", "diz", "asc", "ans", "txt", "zip", "srr"):
            nfo.add_suffix(suffix)
        every = Gtk.FileFilter(name=_("All files"))
        every.add_pattern("*")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(nfo)
        filters.append(every)
        Gtk.FileDialog(filters=filters).open(self, None, self._opened)

    def _opened(self, dialog, result):
        try:
            self.load(dialog.open_finish(result).get_path())
        except GLib.Error:
            pass   # cancelled

    def export(self, suffix):
        name = os.path.splitext(self.name.split(" › ")[-1])[0] + suffix
        Gtk.FileDialog(initial_name=name).save(self, None, self._saved)

    def _saved(self, dialog, result):
        try:
            path = dialog.save_finish(result).get_path()
        except GLib.Error:
            return
        try:
            self.page.export(path)
        except TooBig:
            self.toast(_("This NFO is too long for a PNG. Save it as a PDF instead."))
        except Exception as e:   # cairo raises its own error types for full disks and bad paths
            self.toast(_("Could not save the image: {error}").format(error=e))

    # ------------------------------------------------------------ view

    def _toggle_text_only(self, *a):
        self._set_text_only(not self.text_only)

    def _set_text_only(self, on):
        self.text_only = on
        self.lookup_action("text-only").set_state(GLib.Variant("b", on))
        self.lookup_action("view").set_state(GLib.Variant("s", "text" if on else "art"))
        self.page.plain = on   # text only: a calm page, without stars, scroller and tube
        self.page.reveal, self.view.glitch, self.view.opening = None, None, None
        self._end_loader()
        self.reload()
        self._animate_update()

    # ------------------------------------------------------------ animation

    def _scroller_text(self):
        text = self.cfg["scroller_text"].strip() or _(
            "NfoGlow presents {name} ... greetings to everyone who still draws by hand ... "
            "F9 opens the effects ... ")
        text = text.replace("{name}", self.name)   # not format(): a "{" typed by the user must not break it
        return "   " + text.replace("\n", " ") + "   "

    def _move_overlays(self, t):
        width, height = self.screen.get_width(), self.screen.get_height()   # the tube: the C64 border too
        if self.strip.get_visible():
            strip = int(overlays.scroller_size(self.scroller.get_height()) * 3.4)
            if self.strip.get_height() != strip:
                self.strip.set_size_request(-1, strip)
            self.strip.queue_draw()
        if self.roll_layer.get_visible():
            bar = max(1, int(height * .14))
            if self.rollbar.get_width() != width or self.rollbar.get_height() != bar:
                self.rollbar.set_size_request(width, bar)
            self.roll_layer.move(self.rollbar, 0, overlays.crt_roll_y(t, height))
            # flicker and grain cover the whole picture, so each change redraws all of it: 10 times a second is enough
            # for both and costs a third of 30 (the roll bar is small and moves every frame)
            if int(t * 10) != getattr(self, "_grain_tick", None):
                self._grain_tick = int(t * 10)
                self._flicker_alpha = round(overlays.crt_flicker(t) * 100) / 100
                self.noise.queue_draw()

    def _overlay_moving(self):
        return not self.text_only and (self.cfg["scroller"] or (self.cfg["crt"] and self.cfg["crt_live"]))

    def _animating_page(self):
        cfg = self.cfg
        pulse = (cfg["pulse"] or cfg["neon_flicker"]) and cfg["soft"] and cfg["glow_mode"] == "halo"
        if self.page.reveal is not None or self.view.glitch is not None or self.loading is not None \
                or self.view.opening is not None:
            return True   # an effect on opening
        return not self.text_only and self.page.colors is None and (
            cfg["cycle"] or pulse or cfg["stars"] or cfg["sparkle"]
            or ((cfg["wobble"] or cfg["sheen"]) and self.page.group))

    def _animate_update(self):
        """Run the frame clock only while something moves; GTK stops it by itself while the window is hidden."""
        art, cfg = not self.text_only, self.cfg
        c64 = cfg["theme"] == "c64"   # the C64 screen has its light blue border around it (CSS in ui_app)
        if self.screen.has_css_class("c64") != c64:
            (self.screen.add_css_class if c64 else self.screen.remove_css_class)("c64")
        self._apply_frame()
        self.strip.set_visible(art and cfg["scroller"] and self.path is not None)
        self.crt.set_visible(art and cfg["crt"])
        self.crt.queue_draw()   # round corners only for the living tube
        self.roll_layer.set_visible(art and cfg["crt"] and cfg["crt_live"])
        self.noise.set_visible(art and cfg["crt"] and cfg["crt_live"])
        needed = self._animating_page() or self._overlay_moving()
        if needed and self._tick is None:
            self._tick = self.view.add_tick_callback(self._frame)
        elif not needed and self._tick is not None:
            self.view.remove_tick_callback(self._tick)
            self._tick = None
            self.page.time = 0.0
            self.view.queue_draw()

    def _frame(self, _widget, clock):
        t = clock.get_frame_time() / 1e6
        # 30 frames a second are plenty for this and spare the CPU. The screen ticks every 16.7 ms, a little early or
        # late: without the margin a tick just under 1/30 s is skipped, the frame comes at 50 ms, and motion stutters
        if t - self._last_frame < 1 / 30 - .004:
            return True
        self._last_frame = t
        self.page.time, self.page.level = t, self.app.music_level()
        if self.loading is not None:   # the tape loader or the DOS boot
            self._loading_from = self._loading_from or t
            self.loading = t - self._loading_from
            self.loader.queue_draw()
            if self.loading >= overlays.opening_end(self.boot_kind, self.name):
                self._end_loader()
            return True
        opening = self.page.reveal is not None or self.view.glitch is not None or self.view.opening is not None
        if self.page.reveal is not None:   # modem build-up: at least 2400 characters a second, never over 4 s
            self._reveal_from = self._reveal_from or t
            total = self.page.total_chars()
            self.page.reveal = (t - self._reveal_from) * max(2400, total / 4)
            if self.page.reveal >= total:
                self.page.reveal = None
        if self.view.glitch is not None:
            self._glitch_from = self._glitch_from or t
            self.view.glitch = t - self._glitch_from
            if self.view.glitch > .7:
                self.view.glitch = None
        if self.view.opening is not None:   # CRT power-on, dither fade-in, neon flicker-on, code rain
            self._opening_from = self._opening_from or t
            kind, seconds = self.view.opening[0], t - self._opening_from
            self.view.opening = (kind, seconds) if seconds < overlays.opening_end(kind) else None
        opened = opening and self.page.reveal is None and self.view.glitch is None and self.view.opening is None   # ended
        if self._animating_page() or opened:
            self.view.queue_draw()
        if self._overlay_moving():
            self._move_overlays(t)
        if opened:
            self._animate_update()   # the build-up or glitch is over: maybe nothing moves any more
        return True

    def start_opening(self):
        """Start the effect chosen for opening a file."""
        kind = self.cfg["opening"]
        self.page.reveal = 0.0 if kind == "modem" else None
        self.view.glitch = 0.0 if kind == "glitch" else None
        self.view.opening = (kind, 0.0) if kind in ("crt", "dither", "neon", "rain") else None
        self.loading, self.boot_kind = (0.0 if kind in ("loader", "dos") else None), kind
        self._reveal_from = self._glitch_from = self._loading_from = self._opening_from = None
        self.loader.set_visible(self.loading is not None)
        self.loader.queue_draw()
        self._animate_update()

    def replay_opening(self):
        """The effect on opening once more, from the top of the file (the button next to the choice)."""
        if self.path and not self.text_only:
            self.scroller.get_vadjustment().set_value(0)
            self.start_opening()

    def skip_opening(self):
        """A click or a key ends an effect on opening (not the short glitch). True if one was running."""
        busy = self.loading is not None or self.page.reveal is not None or self.view.opening is not None
        self.page.reveal, self.view.opening = None, None
        self._end_loader()
        if busy:
            self.view.queue_draw()
            self._animate_update()
        return busy

    def _draw_boot(self, snap, w, h):
        if self.boot_kind == "dos":
            try:
                mtime = os.stat(self.path).st_mtime
            except (OSError, TypeError):
                mtime = None
            gpu.dos(snap, w, h, self.loading or 0.0, self.name, self.cfg["font"],
                    (len(self.data) if self.data else 0, mtime))
        else:
            gpu.loader(snap, w, h, self.loading or 0.0, self.name,
                       self.get_surface().get_scale() if self.get_surface() else 1)

    def _end_loader(self):
        if self.loading is not None:
            self.loading = None
            self.loader.set_visible(False)
            self._animate_update()   # maybe nothing moves any more

    def copy(self, *a):
        text = self.page.selected_text()
        if not text:
            text = core.clean_text(self.page.lines) if self.cfg["copy_text_only"] else "\n".join(self.page.lines)
        self.get_clipboard().set(text)
        self.toast(_("Copied to the clipboard"), 1)

    def copy_all(self, *a):
        """The whole NFO, art and all, as text: whatever "copy text only" says (Ctrl+C is for the selection)."""
        self.get_clipboard().set("\n".join(self.page.lines))
        self.toast(_("Copied to the clipboard"), 1)

    def copy_look(self, *a):
        """The look as a line of text, to post or send; Paste look reads it again."""
        self.get_clipboard().set(core.look_code(self.cfg, LOOK_SHARED))
        self.toast(_("Look copied to the clipboard"), 2)

    def paste_look(self, *a):
        self.get_clipboard().read_text_async(None, self._look_pasted)

    def _look_pasted(self, clipboard, result):
        try:
            text = clipboard.read_text_finish(result)
        except GLib.Error:   # nothing on the clipboard, or not text
            text = None
        look = core.read_look_code(text or "", LOOK_SHARED, LOOK_CHOICES)
        if look:
            self.app.apply_look(look)
        self.toast(_("Look applied (Ctrl+Z undoes it)") if look else _("The clipboard holds no NfoGlow look code"), 2)

    def select_all(self, *a):
        p = self.page
        if p.rows:
            p.sel = ((0, 0), (len(p.rows) - 1, max(len(p.lines[-1]) - 1, 0)))
            self.view.queue_draw()

    def _resized(self, *a):
        self._apply_frame()   # the C64 border follows the window width
        if self._fitting():
            self._fit()

    def _apply_frame(self):
        c64 = self.cfg["theme"] == "c64"
        frame = round(C64_FRAME * self.screen.get_width()) if c64 else 0
        if frame == self._margin:
            return
        self._margin = frame
        for widget in (self.scroller, self.strip):   # the scroller runs inside the border too
            for side in ("top", "bottom", "start", "end"):
                getattr(widget, f"set_margin_{side}")(frame)

    def zoom_to(self, percent, fitting=False):
        if not fitting and self._fitting():   # zooming by hand ends "fit width"
            self.lookup_action("fit-width").set_state(GLib.Variant("b", False))
        self.page.set_zoom(percent / 100)
        self.view.refresh()
        self._show_zoom()

    def _show_zoom(self):
        self.zoom_label.set_label(f"{round(self.page.zoom * 100)} %")
        # only after a change by hand: with fit width the zoom follows the window, which is no value to keep
        fit = self.lookup_action("fit-width")   # none yet while the menu is built
        self.zoom_save.set_visible(not (fit and fit.get_state().unpack()) and round(self.page.zoom * 100) != self.cfg["zoom"])

    def zoom_step(self, direction):
        now = round(self.page.zoom * 100)
        steps = [s for s in ZOOM_STEPS if (s > now if direction > 0 else s < now)]
        if steps:
            self.zoom_to(steps[0] if direction > 0 else steps[-1])

    def _fitting(self):
        return self.lookup_action("fit-width").get_state().unpack()

    def _toggle_fit(self, action, _v):
        """On: zoom so the NFO fills the width (and follow window resizes). Off: back to the zoom before."""
        if self._fitting():
            action.set_state(GLib.Variant("b", False))
            self.zoom_to(self._zoom_before_fit or self.cfg["zoom"])
        else:
            self._zoom_before_fit = round(self.page.zoom * 100)
            action.set_state(GLib.Variant("b", True))
            self._fit()
            self._show_zoom()

    def _fit(self):
        width = self.scroller.get_width()
        if not (width and self.page.width):
            return
        now = round(self.page.zoom * 100)
        pct = max(core.ZOOM_MIN, min(core.ZOOM_MAX, int(now * width / self.page.width)))
        # font widths do not grow exactly in proportion, so step to the largest zoom that still fits
        self.page.set_zoom(pct / 100)
        while pct < core.ZOOM_MAX and self.page.width <= width:
            pct += 1
            self.page.set_zoom(pct / 100)
        while pct > core.ZOOM_MIN and self.page.width > width:
            pct -= 1
            self.page.set_zoom(pct / 100)
        if pct != now:   # unchanged: no redraw, which also stops resize -> zoom -> resize loops
            self.zoom_to(pct, fitting=True)
        else:
            self.page.set_zoom(now / 100)

    def _wheel(self, ctl, _dx, dy):
        if not ctl.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK:
            return False
        self.zoom_step(-1 if dy > 0 else 1)
        return True

    # ------------------------------------------------------------ search

    def find(self, text=None):
        self.page.find(self.entry.get_text() if text is None else text)
        self._show_match()

    def step(self, direction):
        if self.page.matches:
            self.page.current = (self.page.current + direction) % len(self.page.matches)
            self._show_match()

    def _show_match(self):
        p = self.page
        if p.matches:
            self.count.set_label(f"{p.current + 1} / {len(p.matches)}")
            r, a, _b = p.matches[p.current]
            for adj, pos in ((self.scroller.get_vadjustment(), p.pady + r * p.ch),
                             (self.scroller.get_hadjustment(), self.view.offset() + p.padx + a * p.cw)):
                if not adj.get_value() <= pos <= adj.get_value() + adj.get_page_size() - p.ch:
                    adj.set_value(pos - adj.get_page_size() / 3)
        else:
            self.count.set_label(_("No matches") if self.entry.get_text() else "")
        self.view.queue_draw()
