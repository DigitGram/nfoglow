# Developing NfoGlow

## How it works

The installer copies `src/` to `~/.local/share/nfoglow/` (with the translations, the built-in music and the DOS font),
links `~/.local/bin/nfoglow`, and registers a desktop entry, the file types (`.nfo`, `.diz`, `.ans`, `.srr`) and the
icons. A checkout runs as it is: `python3 src/nfoglow.py FILE`. The installed program runs with the system's
`/usr/bin/python3`; the checkout and the Flatpak keep `env python3`.

Python 3 with GTK 4 and libadwaita; no packages from pip. The page is laid out and drawn with cairo (`page.py`), which
also makes the PNG and PDF export. The window shows the same page through the graphics card (`gpu.py`), so the effects
cost little while an NFO is open. Everything that moves runs on one frame clock that is stopped while nothing moves.

## Project layout

Everything is in `src/`:

| File | What it does |
| --- | --- |
| `nfoglow.py` | Starts the app; also `--png` and `--version` |
| `core.py` | Version, settings file, themes and palettes, the block-character table (no GTK) |
| `decode.py` | Bytes to text: CP437 and UTF-8, broken encodings, ANSI, ZIP and `.srr` (no GTK) |
| `page.py` | The page and everything drawn on it: blocks, text, glow and the animations (cairo; PNG/PDF) |
| `gpu.py` | The same page for the window, put together by the graphics card |
| `overlays.py` | What lies over the window: scanlines, the live CRT, the sine scroller and the tape loader and DOS boot |
| `music.py` | The music player (GStreamer, loaded only when music is on) |
| `i18n.py` | Translations from `po/*.po` |
| `ui_app.py` | The application: actions, settings changes, styles, random look |
| `ui_window.py` | A window: loading, browsing, search, zoom, the animation clock |
| `ui_view.py` | The NFO view: scrolling, selecting, links |
| `ui_sidebar.py`, `ui_settings.py` | The effects sidebar and the preferences dialog |
| `ui_common.py` | Names and tables the UI parts share |
| `ui_about.py`, `ui_about_art.py` | Artwork of the About dialog |

Besides: `data/` (desktop entry, file types, metainfo, icons, the built-in music and the DOS font, each with its
licence), `po/` (translations), `flatpak/` (the Flatpak recipe), `tools/` (`update_pot.py` rewrites `po/nfoglow.pot`
after UI texts changed, `make_icons.py` builds the icons), `scripts/release-notes.sh`.

## Running the tests

```sh
python3 -m pyflakes src tests tools      # needs python3-pyflakes
python3 tests/test_core.py               # decoding, drawing, settings, look codes, translations, music loop
shellcheck install.sh tests/install_test.sh
tests/install_test.sh                    # installs into a throw-away home, starts it, removes it again
```

The test of the whole window opens a file and uses every part of the UI once. Run it on a hidden display, never on
your desktop, with no sound, and without a Wayland session leaking in:

```sh
xvfb-run -a env -u WAYLAND_DISPLAY GDK_BACKEND=x11 python3 tests/smoke_gtk.py
```

`tests/test_core.py` needs GStreamer and `ffmpeg` for the check that the built-in music loops without a gap; without
them that check is skipped. CI runs the tests on Ubuntu 24.04 and 26.04.

## Trying it by hand

Open `docs/demo.nfo`: it has the block art, the text, a link and the colours that show most effects. Settings live in
`~/.config/nfoglow/settings.json`; start with `XDG_CONFIG_HOME=$(mktemp -d)` to try the first start without touching
your own.

## Translating

Copy `po/nfoglow.pot` to `po/<language>.po` and translate it; the file is read at runtime, no build step. After
changing texts in the code, run `python3 tools/update_pot.py`. A test checks that every language translates every
message.

## Flatpak

`flatpak/io.github.digitgram.NfoGlow.yml` builds the Flatpak on the GNOME 51 runtime; see "Flatpak" in the README.
It builds libopenmpt and the GStreamer plugin for tracker music itself, because the runtime has none.
