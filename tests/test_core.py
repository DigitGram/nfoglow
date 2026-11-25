# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""Run: python3 -m pytest tests  (or python3 tests/test_core.py)"""
import ast
import re
import sys
import tempfile

import cairo
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import core  # noqa: E402
import decode  # noqa: E402
import overlays  # noqa: E402
import page as pages  # noqa: E402
import i18n  # noqa: E402

CFG = {"theme": "light", "soft": True, "copy_text_only": True}


def test_a_flatpak_file_from_the_document_portal_gets_its_real_path():
    import os
    with tempfile.TemporaryDirectory() as folder:
        real = Path(folder, "a.nfo")
        real.write_text("x")
        portal = f"/run/user/{os.getuid()}/doc/abcd1234/a.nfo"
        assert decode.real_path(str(real)) == str(real)   # an ordinary path stays
        getxattr, os.getxattr = os.getxattr, lambda path, name: str(real).encode()
        try:
            assert decode.real_path(portal) == str(real)
            os.getxattr = lambda path, name: (folder + "/missing.nfo").encode()   # not readable in the sandbox: keep the portal path
            assert decode.real_path(portal) == portal
        finally:
            os.getxattr = getxattr
        assert decode.real_path(portal) == portal   # no such portal file here: no attribute, the path stays


def test_decode_cp437_and_utf8():
    assert decode.decode(b"\xdb\xdb\xb0 hi")[:2] == ("██░ hi", "CP437")
    assert decode.decode("█ hi".encode())[:2] == ("█ hi", "UTF-8")
    assert decode.decode(b"\xef\xbb\xbfhi")[0] == "hi"


def test_decode_strips_sauce_and_reads_width():
    sauce = bytearray(b"SAUCE00" + b" " * 121)
    sauce[96:98] = (160).to_bytes(2, "little")
    text, _label, width = decode.decode(b"art\x1aCOMNTcomment" + bytes(sauce))
    assert (text, width) == ("art", 160)


def test_ansi_colours_and_cursor():
    lines, colors = decode.parse_ansi("\x1b[1;31mA\x1b[0m\x1b[2CB\r\n\x1b[44mC")
    assert lines == ["A  B", "C"]
    assert colors[0][0][0] == core.VGA[9]        # bold red = bright red
    assert colors[1][0][1] == core.VGA[4]        # blue background
    assert decode.parse_ansi("\x1b[38;2;255;0;0mX")[1][0][0][0] == (1.0, 0.0, 0.0)


def test_hostile_ansi_stays_small():
    """A SAUCE width of 65535 and a cursor jump to the right edge on 10000 rows: 140 KB that once meant 655 million
    cells. The lines stop at MAX_CELLS."""
    sauce = bytearray(128)
    sauce[:7], sauce[96:98] = b"SAUCE00", (65535).to_bytes(2, "little")
    data = b"\x1b[B\x1b[65534CX" * 10000 + b"\x1a" + bytes(sauce)
    text, _label, width = decode.decode(data)
    lines, colors = decode.parse_ansi(text, width)
    assert width == 65535 and lines and sum(map(len, lines)) <= decode.MAX_CELLS
    assert len(colors) == len(lines)
    assert decode.parse_ansi("\x1b[" + "9" * 5000 + "mX")[0] == ["X"]   # a number too long for int()


def test_export_leaves_out_search_and_refuses_a_too_long_png():
    page = pages.Page(CFG, 0.8)
    page.set_text("hello world\nhello again")
    before = bytes(page.render().get_data())
    page.find("hello")
    page.sel = ((0, 0), (1, 4))
    assert bytes(page.render().get_data()) == before   # marks are for the window only
    page.set_text("line\n" * 2300)
    assert page.height > pages.MAX_IMAGE
    out = Path(tempfile.mkdtemp())
    try:
        page.export(str(out / "long.png"))
        raise AssertionError("a PNG over 32767 px cannot be made")
    except pages.TooBig:
        pass
    page.export(str(out / "long.pdf"))   # the PDF has no such limit
    assert (out / "long.pdf").stat().st_size > 0


def test_line_endings_crlf_cr_and_the_double_cr_of_some_nfos():
    for eol in ("\n", "\r\n", "\r", "\r\r\n"):
        page = pages.Page(CFG, 0.8)
        page.set_text(eol.join(["one", "", "three"]))
        assert page.lines == ["one", "", "three"], repr(eol)


def test_a_double_spaced_nfo_loses_its_extra_blank_lines():
    page = pages.Page(CFG, 0.8)
    page.set_text("\r\n\r\n".join(["one", "two", "", "four", "five", "six"]))   # "" is a real blank line: kept as one
    assert page.lines == ["one", "two", "", "four", "five", "six"]
    page.set_text("\n\n".join(["one", "two", "three", "four", "five", "six"]))
    assert page.lines == ["one", "two", "three", "four", "five", "six"]
    page.set_text("a\n\nb")   # a short text keeps its blank line
    assert page.lines == ["a", "", "b"]
    page.set_text("a\n\nb\nc\n\nd\ne\nf")   # blank lines that are not every second one stay
    assert page.lines == ["a", "", "b", "c", "", "d", "e", "f"]


def test_dos_symbols_in_plain_text():
    page = pages.Page(CFG, 0.8)
    page.set_text("\x04 UNLEASHED \x04\n\x1b\x1a\x00\x10 ok\x1a")   # the file ends with the DOS end-of-file code
    assert page.lines == ["♦ UNLEASHED ♦", "←→ ► ok"]


def test_text_only_and_copy_skip_art():
    lines = ["██ ║ Title: x ║", "", "", "▓▓▓", "   more"]
    assert core.clean_text(lines, dedent=False) == "Title: x\n\nmore"
    page = pages.Page(CFG)
    page.set_text("\n".join(lines))
    page.sel = ((0, 0), (0, 14))
    assert page.selected_text() == "Title: x"
    old_mac = pages.Page(CFG)
    pages.fill(old_mac, b"Title: x\rmore text", text_only=True)   # old Mac line ends: still two lines
    assert old_mac.lines == ["Title: x", "more text"]


def test_page_links_search_and_render():
    page = pages.Page(CFG, 0.8)
    page.set_text((ROOT / "docs" / "demo.nfo").read_bytes().decode("cp437"))
    assert any(u == "https://github.com/DigitGram/nfoglow" for links in page.links.values() for _a, _b, u in links)
    page.find("release")   # only "Release......", the spaced heading does not match
    assert len(page.matches) == 1
    surface = page.render()
    assert (surface.get_width(), surface.get_height()) == (page.width, page.height)


def test_no_seams_between_blocks_without_glow():
    """Neighbouring █ must touch: no lighter line between them, also with fractional display scaling."""
    import cairo
    for scale, ox in ((1.0, 0), (1.0, 10.5), (1.25, 0), (1.5, 3.3)):
        page = pages.Page({"theme": "light", "soft": False}, 0.8)
        page.set_text("\n".join(["█" * 12] * 6))
        w, h = int(page.width * scale) + 20, int(page.height * scale)
        s = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
        cr = cairo.Context(s)
        cr.scale(scale, scale)
        page.paint(cr, ox)
        s.flush()
        data, stride = s.get_data(), s.get_stride()
        art = tuple(round(v * 255) for v in core.THEMES["light"][2])
        x0, y0 = (ox + page.padx) * scale, page.pady * scale
        for y in range(int(y0) + 2, int(y0 + 6 * page.ch * scale) - 2):
            for x in range(int(x0) + 2, int(x0 + 12 * page.cw * scale) - 2):
                b, g, r = data[y * stride + x * 4:y * stride + x * 4 + 3]
                assert (r, g, b) == art, f"seam at x={x} y={y} (scale {scale}, offset {ox}): {(r, g, b)}"


def test_double_encoded_cp437_is_repaired():
    art = ("\xdb" * 12 + "\xb0\xb1\xb2 Title: x").encode("latin-1")   # CP437 bytes
    broken = art.decode("latin-1").encode("utf-8")                   # read as Latin-1, saved as UTF-8
    text, label, _w = decode.decode(broken)
    assert text.startswith("█" * 12 + "░▒▓") and label == "CP437 ← UTF-8"
    assert decode.decode("Café ñandú".encode())[:2] == ("Café ñandú", "UTF-8")   # real accents stay
    german = "Größe: 4,7 GB, Straße der Ärzte, Übersetzung. Grüße, Spaß, Maße, heißt, außerdem, Schließen, Übergabe."
    assert decode.decode(german.encode())[:2] == (german, "UTF-8")   # ß Ä Ö Ü would be ▀ ─ ╓ ▄ in CP437


def test_huge_pages_stay_cheap():
    """A newline flood stays within MAX_ROWS; one very long line on a long page gets no glow and no PNG."""
    assert len(decode.parse_ansi("\x1b[0m" + "\n" * 50000 + "x")[0]) == decode.MAX_ROWS
    page = pages.Page(CFG)
    page.set_text("\n".join(["█ logo", *["text"] * 1400, "x" * 2000]))
    assert page.height <= pages.MAX_IMAGE and page._blurred(core.THEMES["light"][2], None, 5.0) is None
    try:
        page.export(str(Path(tempfile.mkdtemp()) / "wide.png"))
        raise AssertionError("a PNG of hundreds of megapixels must be refused")
    except pages.TooBig:
        pass


def test_email_links():
    page = pages.Page(CFG)
    page.set_text("mail: group@example.org.")
    assert page.link_at(0, 7) == "mailto:group@example.org"
    page.set_text("httpd@example.org")   # an address, though it starts like a web link
    assert page.link_at(0, 0) == "mailto:httpd@example.org"
    page.set_text("WWW.GROUP.COM or HTTP://GROUP.COM")   # old NFOs write them in capitals
    assert page.link_at(0, 0) == "WWW.GROUP.COM" and page.link_at(0, 20) == "HTTP://GROUP.COM"
    import time
    start = time.time()
    page.set_text("a" * 200_000)   # one long line: the search for addresses once took the square of its length
    assert time.time() - start < 5


def test_zip(tmp_path=None):
    import zipfile
    with tempfile.TemporaryDirectory() as d:
        z = Path(d) / "release.zip"
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("sample/file_id.diz", b"diz")
            f.writestr("Release.NFO", b"\xdb nfo")
        data, name = decode.read(str(z))
        assert data == b"\xdb nfo" and name == "release.zip › Release.NFO"   # .nfo wins over .diz
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("dir/.nfo", b"dot")   # a name that is only the ending
        assert decode.read(str(z)) == (b"dot", "release.zip › .nfo")
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("readme.txt", b"x")
        (Path(d) / "movie.nfo").write_bytes(bytes(decode.MAX_MEMBER + 1))   # too big to be an NFO: not read whole
        for bad in (z, Path(d) / "broken.zip", Path(d) / "movie.nfo"):
            if bad.name == "broken.zip":
                bad.write_bytes(b"not a zip")
            try:
                decode.read(str(bad))
                raise AssertionError("expected OSError")
            except OSError:
                pass


def test_pdf_export_and_custom_theme():
    cfg = {**CFG, "theme": "custom", "custom": {"bg": "#000000", "text": "#ffffff", "art": "#ff0000", "link": "#00ff00"}}
    assert core.theme_colors(cfg)[2] == (1.0, 0.0, 0.0) and core.theme_colors(cfg)[4] is True   # dark background
    page = pages.Page(cfg)
    page.set_text("██ hello")
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "x.pdf"
        page.export(str(out))
        assert out.read_bytes()[:5] == b"%PDF-"


def _block(kind, flags, body, extra=b""):
    """A RAR/SRR block: CRC (dummy), type, flags, header size, then the rest of the header and the data."""
    return b"\x00\x00" + bytes([kind]) + flags.to_bytes(2, "little") + (7 + len(body)).to_bytes(2, "little") + body + extra


def test_srr():
    app = b"pyReScene 0.7"
    def stored(name, data):
        return _block(0x6A, 0x8000, len(data).to_bytes(4, "little") + len(name).to_bytes(2, "little") + name, data)
    srr = (b"ii" + _block(0x69, 1, len(app).to_bytes(2, "little") + app)[2:]   # an SRR starts with "iii"
           + stored(b"group-release.sfv", b"file 12345678") + stored(b"group-release.nfo", b"\xdb\xdb NFO")
           + _block(0x71, 0x8000, b"\x10\x00\x00\x00" + b"\x05\x00part1", b""))
    assert decode.srr_files(srr) == {"group-release.sfv": b"file 12345678", "group-release.nfo": b"\xdb\xdb NFO"}
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "Group-Release.srr"
        path.write_bytes(srr)
        assert decode.read(str(path)) == (b"\xdb\xdb NFO", "Group-Release.srr › group-release.nfo")


def _pixel(surface, x, y):
    surface.flush()
    i = int(y) * surface.get_stride() + int(x) * 4
    b, g, r = surface.get_data()[i:i + 3]
    return r, g, b


def test_colour_ramp_restarts_for_each_block_of_art():
    cfg = {"theme": "dark", "soft": False, "ramp": True, "ramp_colors": ["#ff0000", "#00ff00", "#0000ff"]}
    page = pages.Page(cfg, 1.0)
    page.set_text("\n".join(["█" * 8] * 6 + [""] + ["█" * 8] * 6))   # two blocks of art with a gap
    surface = page.render()
    x = round(page.padx) + 4 * page.cw
    for first_row in (0, 7):
        top = _pixel(surface, x, round(page.pady) + first_row * page.ch + 1)
        bottom = _pixel(surface, x, round(page.pady) + (first_row + 6) * page.ch - 2)
        assert top[0] > 200 and top[2] < 60, top          # starts red
        assert bottom[2] > 200 and bottom[0] < 60, bottom   # ends blue


def test_neon_halo_glows_around_but_keeps_blocks_crisp():
    page = pages.Page({"theme": "dark", "soft": True, "glow_mode": "halo", "glow": 3}, 1.0)
    page.set_text("\n".join(["   " + "█" * 6] * 4))
    surface = page.render()
    art = tuple(round(v * 255) for v in core.THEMES["dark"][2])
    bg = tuple(round(v * 255) for v in core.THEMES["dark"][0])
    x0, y = round(page.padx) + 3 * page.cw, round(page.pady) + 2 * page.ch
    assert _pixel(surface, x0 + 2 * page.cw, y) == art     # inside: exactly the art colour
    beside = _pixel(surface, x0 - 4, y)
    assert sum(beside) > sum(bg) + 30, (beside, bg)        # just left of the art: lit by the halo


def test_crt_look_is_in_the_export():
    page = pages.Page({"theme": "light", "soft": False, "crt": True}, 1.0)
    page.set_text("hello")
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "crt.png"
        page.export(str(out))
        s = cairo.ImageSurface.create_from_png(str(out))
        x = s.get_width() // 2
        assert sum(_pixel(s, x, 3)) < sum(_pixel(s, x, 4)) - 60   # row 3 is a scanline, row 4 is not


def test_animations_change_with_time():
    text = "\n".join(["   " + "█" * 10] * 6)
    def frame(cfg, t):
        page = pages.Page({"theme": "dark", "soft": False, **cfg}, 1.0)
        page.set_text(text)
        page.time = t
        surface = page.render()
        return [_pixel(surface, round(page.padx) + x * page.cw, round(page.pady) + y * page.ch / 2)
                for x in (1, 5) for y in range(12)]
    for cfg in ({"cycle": True}, {"cycle": True, "cycle_palette": "ramp"},
                {"soft": True, "glow_mode": "halo", "cycle": True}):
        assert frame(cfg, 0.0) != frame(cfg, 0.5), cfg      # it moves
        assert frame(cfg, 0.25) == frame(cfg, 0.25), cfg    # and the same moment looks the same


def test_wobble_moves_the_logo_but_not_the_text():
    text = "\n".join(["   " + "█" * 10] * 6) + "\n\n   Release info here"
    def frame(t, amount="mid"):
        page = pages.Page({"theme": "dark", "soft": True, "glow_mode": "halo", "wobble": True,
                           "wobble_amount": amount}, 1.0)
        page.set_text(text)
        page.time = t
        surface = page.render()
        rows = surface.get_stride()
        data = bytes(surface.get_data())
        split = round(page.pady + 7 * page.ch) * rows   # the art above, the text line below
        return data[:split], data[split:]
    (art0, text0), (art1, text1) = frame(0.0), frame(0.3)
    assert art0 != art1 and text0 == text1
    assert frame(0.3, "low")[0] != frame(0.3, "high")[0]   # the strength setting counts
    assert frame(0.3, "x")[0] == frame(0.3)[0]   # a hand-edited value: medium, no error (--png reads the file unchecked)


def test_warp_stars_fly():
    page = pages.Page({"theme": "dark", "stars": True, "stars_mode": "warp"}, 1.0)
    page.set_text("hello")
    shots = []
    for t in (0.0, 0.5):
        page.time = t
        s = cairo.ImageSurface(cairo.FORMAT_RGB24, 300, 200)
        page.stars(cairo.Context(s), 300, 200)
        shots.append(bytes(s.get_data()))
    assert shots[0] != shots[1] and any(shots[0])


def test_pulse_can_breathe_while_music_plays():
    page = pages.Page({"soft": True, "glow_mode": "halo", "pulse": True, "pulse_mode": "breathe"}, 1.0)
    page.set_text("\u2588\u2588")
    page.level, page.time = 1.0, 0.0
    breath = page.glow_parts()[1]
    page.cfg["pulse_mode"] = "beat"
    assert page.glow_parts()[1] != breath   # to the music the loud level counts; breathing ignores it


def test_a_broken_settings_file_falls_back_to_default_colours():
    import json
    old, path = core.CONFIG, Path(tempfile.mkdtemp()) / "settings.json"
    core.CONFIG = str(path)
    try:
        for saved in ({"ramp_colors": ["#fff"]}, {"ramp_colors": ["#73f0ff", "red", "#d94dff"]}, {"custom": {"bg": 5}},
                      {"custom": {"bg": "#12345"}}):
            path.write_text(json.dumps({"zoom": 90, **saved}))
            cfg = core.load_settings()
            assert cfg["ramp_colors"] == core.DEFAULTS["ramp_colors"] and cfg["custom"] == core.DEFAULTS["custom"], saved
            assert cfg["zoom"] == 90   # the rest of the file still counts
        path.write_text(json.dumps({"ramp_colors": ["#000000", "#111111", "#222222"]}))
        assert core.load_settings()["ramp_colors"][0] == "#000000"   # a good file is left alone
        import ui_common
        choices = {**ui_common.LOOK_CHOICES, "encoding": ui_common.ENCODINGS}
        path.write_text(json.dumps({"recent": [1, "/a.nfo"], "encoding": "ebcdic", "glow_mode": "x", "wobble_amount": "x",
                                    "theme": "amber", "volume": 5000}))
        cfg = core.load_settings(choices)   # values no list of the UI knows: back to the defaults, the good ones stay
        assert (cfg["recent"], cfg["encoding"], cfg["glow_mode"], cfg["wobble_amount"], cfg["theme"], cfg["volume"]) \
            == (["/a.nfo"], "auto", "halo", "mid", "amber", 100)
    finally:
        core.CONFIG = old


def test_every_opening_effect_has_a_name_a_description_and_an_end():
    import ui_common
    assert set(ui_common.OPENINGS) == set(ui_common.OPENING_INFO)
    for kind in ui_common.OPENINGS:
        if kind in ("off", "modem", "glitch"):
            continue   # these end by themselves (the window times modem and glitch)
        assert 1 < overlays.opening_end(kind, "demo.nfo") < (5 if kind == "dos" else 3), kind
    name, info = "00-plain_white_ts-all_that_we_needed.nfo", (4650, 1730000000)
    end = overlays.opening_end("dos", name)
    assert 3 < end < 5
    boot = overlays.dos_screen(end - .5, name, info)[0]
    assert boot[0] == "Starting MS-DOS..." and "MS-DOS Version 6.22" in boot and "C:\\>VER" in boot
    assert any(line.startswith("00-PLA~1 NFO") and "4,650" in line for line in boot)   # DOS 8.3 name, size
    assert boot[-1] == "C:\\>TYPE 00-PLA~1.NFO" and overlays.dos_screen(end, name, info)[0][-1] == ""   # then Enter
    assert overlays._dos_83("demo.nfo") == ("DEMO", "NFO")


def test_tape_loader_runs_its_script():
    """READY., LOAD typed letter by letter, SEARCHING, LOADING with stripes, READY. (16 letters of the name, like
    on a C64 disk)."""
    lines, cursor, stripes = overlays.loader_screen(0.65, "00-plain_white_ts-all_that_we_needed.nfo")
    assert lines[0] == "READY." and lines[1].startswith('LOAD"00-PLAIN') and cursor == (1, len(lines[1]))
    assert not stripes and len(lines[1]) < len('LOAD"00-PLAIN_WHITE_TS",8,1')   # still typing
    lines, cursor, stripes = overlays.loader_screen(1.5, "demo.nfo")
    assert lines[-2:] == ["SEARCHING FOR DEMO", "LOADING"] and stripes and cursor is None
    lines, _cursor, stripes = overlays.loader_screen(2.2, "demo.nfo")
    assert lines[-1] == "READY." and not stripes and overlays.LOADER_END > 2.2


def test_sine_scroller_gives_wide_letters_room():
    text = "ab日本"
    xs = [x for _ch, x, _y, _c in overlays.scroller_letters(500, 300, 1.0, text, 30)]
    assert len(xs) == 4 and abs((xs[2] - xs[1]) - 30 * .62) < 1e-6 and abs((xs[3] - xs[2]) - 30 * .62 * 2) < 1e-6


def test_loader_font_is_8_by_8():
    assert all(len(rows) == 7 and all(len(r) == 8 and set(r) <= set(".#") for r in rows)
               for rows in overlays.FONT8.values())   # the eighth row stays empty, as the gap between lines
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, 320, 200)
    overlays.paint_c64_screen(cairo.Context(s), ["READY."], (1, 0), (1, 1, 1), (0, 0, 0))
    assert _pixel(s, 9, 0) == (255, 255, 255) and _pixel(s, 3, 9) == (255, 255, 255)   # "R", then the cursor


def test_neon_flickers_now_and_then():
    levels = [pages.flicker(t / 20) for t in range(1200)]   # a minute
    assert min(levels) < .3 and max(levels) == 1.0 and 0.05 < sum(1 for v in levels if v < 1) / len(levels) < .3
    page = pages.Page({"soft": True, "glow_mode": "halo", "neon_flicker": True}, 1.0)
    page.set_text("\u2588\u2588")
    dark = next(t / 20 for t in range(1200) if pages.flicker(t / 20) < .3)
    page.time = dark
    dim = page.glow_parts()[1]
    page.cfg["neon_flicker"] = False
    assert dim[0][1] < page.glow_parts()[1][0][1] / 2   # the halo is much dimmer in the stutter


def test_text_glow_puts_light_around_the_text():
    def pixels(glow):
        page = pages.Page({"theme": "dark", "text_glow": glow}, 1.0)
        page.set_text("Hello, glow")
        s = page.render()
        bg = tuple(round(v * 255) for v in core.THEMES["dark"][0])
        return sum(1 for y in range(s.get_height()) for x in range(0, s.get_width(), 2) if _pixel(s, x, y) != bg)
    assert pixels(True) > pixels(False) * 1.3


def test_living_tube_has_round_corners():
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, 400, 300)
    cr = cairo.Context(s)
    cr.set_source_rgb(1, 1, 1)
    cr.paint()
    overlays.crt_static(cr, 400, 300, round_corners=True)
    assert sum(_pixel(s, 1, 1)) < 60 and sum(_pixel(s, 200, 151)) > 300   # dark corner, bright middle


def test_music_fades():
    """Quiet at the start, softly out at the end of a track and when switched off (silent: nothing plays)."""
    import music
    player = music.Player()
    player.fade, player._in, player._left = True, 1.0, lambda: 1.5
    assert abs(player._fades() - 0.5) < 1e-9          # 1.5 s before the end of the track: half
    player._off = 0.5
    assert abs(player._fades() - 0.25) < 1e-9         # and switching off on top of that
    player._left, player._off, player._in = lambda: None, None, 0.0
    assert player._fades() == 0.0                     # the very start: silent, then it rises
    player.playing = True
    player.stop(fade=True)
    assert player.playing and player._off == 1.0      # still playing while it fades out
    player.stop()
    assert not player.playing


def test_pulse_follows_what_is_heard():
    """The loudness is measured about a second before the sound is heard: it waits for the playback clock."""
    import music
    player = music.Player()
    player.playing, clock = True, [0]
    player._now = lambda: clock[0]
    player._levels.extend([(1_000_000_000, -60.0, None), (2_000_000_000, -8.0, None)])
    clock[0] = 500_000_000
    assert player.level() == 0.0      # nothing heard yet, although both are already measured
    clock[0] = 1_500_000_000
    assert player.level() == 0.0      # silence
    clock[0] = 2_500_000_000
    assert player.level() > .8        # the loud window after it: a beat
    player.stop()


def test_built_in_tracks_pulse_on_their_beat_grid():
    import music
    grids = music.grids()
    assert grids, "data/music/beats.json is missing"
    assert all(n.endswith(".ogg") for n in grids)
    grid = next(iter(grids.values()))
    for beat in (0.0, 2.0, 10.5, 47.5):                               # a beat flashes, whatever the loudness
        assert grid.at(beat) > .7
        assert grid.at(beat + .15) < grid.at(beat)                    # and fades towards the next
    assert grid.at(.25) < grid.at(0.0) * .5                           # the eighth between two beats is softer
    player = music.Player()
    player.playing, player.builtin, player._current = True, True, next(iter(grids))
    player._now = lambda: 10**12
    player._levels.append((1, -60.0, 12.0))                           # silent, but on a beat of the grid
    assert player.level() > .7
    player.stop()


def test_the_pulse_jumps_on_beats_not_on_loudness():
    import music
    def run(dbs):
        beat = music.Beat()
        return [beat.feed(db) for db in dbs]
    kick = [-8, -10, -13, -16, -19, -22] + [-30] * 14   # a kick every 0.5 s (20 windows of 25 ms)
    pulse = run(kick * 8)
    assert min(pulse[i] for i in range(40, 160, 20)) > .8           # every kick flashes
    assert max(pulse[i] for i in range(50, 160, 20)) < .35          # and it has faded half way to the next
    tone = run([-60] * 10 + [-12] * 80)                              # a long, loud tone
    assert max(tone[10:12]) > .8 and tone[-1] < .05                  # one flash, then rest
    melody = run(([-20] * 4 + [-17] * 4) * 20)                       # small steps: notes, no beat
    assert max(melody[40:]) < .5
    assert max(run([-60] * 40)) == 0.0                               # silence


def test_built_in_music_loops_without_a_gap():
    """Record what the player puts out for the first built-in track (faster than real time, silently) and compare
    it sample by sample with intro + loop (0:00-0:48) followed by the loop again (0:08-0:48)."""
    import array
    import shutil
    import subprocess
    import music
    if not music.available() or not shutil.which("ffmpeg"):
        return   # needs GStreamer and ffmpeg (CI installs both); without them there is nothing to compare
    from gi.repository import GLib, Gst
    tracks = music.tracks(music.BUILTIN)
    assert len(tracks) == 9
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.raw"
        p = music.Player()
        p.bin.set_property("audio-sink", Gst.parse_bin_from_description(
            "audioconvert ! audioresample ! audio/x-raw,format=S16LE,channels=2,rate=44100 ! "
            f"filesink location={out} sync=false", True))
        loop = GLib.MainLoop()
        calls = []
        start_next = p._next
        def next_once():   # after the first track: stop instead of going on
            calls.append(1)
            if len(calls) > 1:
                p.stop()
                loop.quit()
            else:
                start_next()
        p._next = next_once
        p.play("", shuffle=False, volume=1.0, fade=False)
        GLib.timeout_add(60000, loop.quit)
        loop.run()
        got = array.array("h", out.read_bytes())
    ref = array.array("h", subprocess.run(["ffmpeg", "-v", "error", "-i", tracks[0], "-f", "s16le", "-ac", "2",
                                           "-ar", "44100", "-"], capture_output=True, check=True).stdout)
    second = 44100 * 2
    expected = ref[:48 * second] + ref[8 * second:48 * second]
    assert len(got) == len(expected)
    assert max(abs(a - b) for a, b in zip(got[::97], expected[::97])) < 8   # rounding only: no gap, no jump


def test_starfield_and_modem_build_up():
    page = pages.Page({"theme": "dark", "soft": False, "stars": True}, 1.0)
    page.set_text("\n".join(["x" * 60] * 20))
    a, b = page.render(), None
    page.time = 1.0
    b = page.render()
    assert bytes(a.get_data()) != bytes(b.get_data())                  # the stars move
    page.plain = True
    assert bytes(page.render().get_data()) == bytes(page.render().get_data())   # text only: no stars
    page.plain, page.cfg["stars"] = False, False
    page.set_text("abc\ndef")
    page.reveal = 5   # "abc", line break, "d" shown
    assert page._reveal_cell() == (1, 1) and page.total_chars() == 8


def test_sine_scroller_moves_its_letters():
    def letters(t):
        return list(overlays.scroller_letters(500, 300, t, "   HELLO SCENE   ", 30))
    now = letters(2.0)
    assert now and all(-30 <= x <= 500 and 150 < y < 300 for _ch, x, y, _c in now)   # in view, along the bottom
    assert [ch for ch, *_ in now] == list("HELLOSCENE")[:len(now)] and letters(2.5) != now


def test_long_nfo_draws_with_glow():
    """Over 32767 px a cairo image cannot be made: the glow is left out, the NFO is still drawn (review fix 1)."""
    for mode in ("halo", "soft"):
        page = pages.Page({**core.DEFAULTS, "glow_mode": mode, "ramp": False}, 0.8)
        page.set_text("\n".join(["████ text " * 8] * 2500))
        assert page.height > pages.MAX_IMAGE
        s = cairo.ImageSurface(cairo.FORMAT_RGB24, page.width, 300)
        page.paint(cairo.Context(s))   # raised "invalid value (typically too big)" before
        art = tuple(round(v * 255) for v in core.THEMES["light"][2])
        assert _pixel(s, round(page.padx) + 2, round(page.pady) + 2) == art, mode   # the blocks are there


def test_bad_ansi_values():
    """Colours above 255 and huge cursor jumps (review fixes 2 and 5)."""
    page = pages.Page(dict(core.DEFAULTS))
    pages.fill(page, b"\x1b[38;5;300mA\x1b[38;2;999;0;0mB")
    page.render()   # OverflowError before
    lines, _colors = decode.parse_ansi("A\x1b[5000000BX\x1b[9999999;1HY")
    assert len(lines) == decode.MAX_ROWS


def test_damaged_zip_is_an_oserror():
    """The window shows OSError as a message; other errors made opening fail silently (review fix 3)."""
    import zipfile
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "bad.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("group.nfo", b"x" * 5000)
        data = bytearray(path.read_bytes())
        i = data.find(b"group.nfo") + len("group.nfo")
        data[i + 5:i + 15] = b"\xff" * 10   # break the packed data
        path.write_bytes(data)
        try:
            decode.read(str(path))
            raise AssertionError("expected OSError")
        except OSError:
            pass


def test_block_layer_keeps_only_the_current_colours():
    """A new look replaces the cached block image instead of piling up (review fix 6)."""
    page = pages.Page({"theme": "dark", "soft": False}, 1.0)
    page.set_text("\n".join(["████"] * 20))
    for colors in (["#ff0000"] * 3, ["#00ff00"] * 3, ["#0000ff"] * 3, ["#ffffff"] * 3):
        page.cfg.update(ramp=True, ramp_colors=colors)
        page.render()
    assert sum(1 for k in page._fx if k == "layer" or (isinstance(k, tuple) and k[0] == "layer")) == 1


def test_a_theme_brings_its_colour_ramp():
    import ui_common
    t = ui_common
    assert list(t.THEME_RAMPS["dark"]) == core.DEFAULTS["ramp_colors"] and set(t.THEME_RAMPS) == set(core.THEMES)
    assert t.ramp_for_theme("amber", t.THEME_RAMPS["dark"]) == list(t.THEME_RAMPS["amber"])
    assert t.ramp_for_theme("light", t.RAMPS_DARK[1]) == list(t.THEME_RAMPS["light"])   # a random look's ramp too
    assert t.ramp_for_theme("amber", ["#123456", "#234567", "#345678"]) is None         # set by hand: stays
    assert t.ramp_for_theme("custom", t.THEME_RAMPS["dark"]) is None                      # Custom keeps what you have


def test_defaults_are_the_neon_style():
    """After a reset the Neon button lights up, and clicking it changes nothing."""
    import ui_common
    assert all(core.DEFAULTS[k] == v for k, v in ui_common.STYLES["neon"][1].items())


def test_geometric_shapes_are_art():
    """CP437 0xFE (■) and the other geometric shapes decorate NFOs: art colour, gone in text only and copies."""
    text = b"\xfe  Release Info  \xfe\n\xfe".decode("cp437")
    assert core.clean_text(text.split("\n"), dedent=False) == "Release Info"
    page = pages.Page({"theme": "dark", "soft": False, "copy_text_only": True})
    page.set_text(text)
    assert page.rows[0][0].strip() == "Release Info" and len(page.rows[0][2]) == 2   # ■ is drawn like a block
    assert not page.group   # but bullets alone are no logo: no ramp group, no wobble
    page.set_text("\u25b2 x \u2550")
    assert "\u25b2" in page.rows[0][1]   # the other shapes and the lines: drawn by the font in the art colour


def test_copying_a_selection_of_only_art_copies_that():
    """Selecting a few dots (art) and copying gave the whole NFO, as if nothing was selected."""
    page = pages.Page({"theme": "dark", "copy_text_only": True})
    page.set_text("Title: x\n  \u2219\u2219\u2219\u2219  \nmore text")
    page.sel = ((1, 2), (1, 4))
    assert page.selected_text() == "\u2219\u2219\u2219"
    assert core.is_art("\u2219") and core.is_art("\u00b7") and not core.is_art(".")


def test_text_only_drops_lone_signs():
    """ASCII used as art beside the blocks: gone in text only, real text and separator lines stay."""
    lines = ["█%                █%", "Shout out to all of those", "█%  █%", "------------------", "  +     +",
             "  o", "11 > Carmilla's Masque", "We miss you!"]
    assert core.clean_text(lines, dedent=False).split("\n") == [   # a dropped line leaves one blank, like art does
        "Shout out to all of those", "", "------------------", "", "11 > Carmilla's Masque", "We miss you!"]
    # underscores, no-break spaces and control codes drawn into the art are no text either
    lines = ["\xa0\xa0\xa0\u2593\u2588_\u2584\xa0\xa0\xa0\xa0", "___", "\x08", "Artist...: Somebody", "Rel_Date: 2026"]
    assert core.clean_text(lines, dedent=False).split("\n") == ["Artist...: Somebody", "Rel_Date: 2026"]
    # a logo in slashes and underscores goes, a rule stays
    logo = [r"\______  \  |  \_ ____/\_ ____/", r"|  |  _/  |      __)_ |  __)_", r"  \/        \/", "artist: x", "-----"]
    assert core.clean_text(logo, dedent=False).split("\n") == ["", "artist: x", "-----"][1:]
    page = pages.Page({"copy_text_only": True})
    page.set_text("\n".join(lines))
    page.sel = ((0, 0), (4, 20))
    assert [r for r, _a, _b in page.selection_rows(0, 5)] == [3, 4]   # marked is what gets copied


def test_every_language_translates_every_message():
    """All po files cover every message of the code, with the same {placeholders} and the same line ends."""
    used = set()
    for path in (ROOT / "src").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("_", "N_") and node.args \
                    and isinstance(node.args[0], ast.Constant):
                used.add(node.args[0].value)
    for path in sorted((ROOT / "po").glob("*.po")):
        catalog = i18n.load_po(path)
        missing = used - set(catalog)
        assert not missing, (path.name, missing)
        for msgid in used:
            same = lambda a, b: re.findall(r"\{\w+\}", a) == re.findall(r"\{\w+\}", b) and a[-1:].isspace() == b[-1:].isspace()
            assert same(msgid, catalog[msgid]), (path.name, msgid, catalog[msgid])
    assert len(list((ROOT / "po").glob("*.po"))) == 9
    pot = set(re.findall(r'^msgid (".+")$', (ROOT / "po" / "nfoglow.pot").read_text(), re.M))
    assert {ast.literal_eval(m) for m in pot} == used, "run tools/update_pot.py"


def test_the_dice_roll_every_setting_of_the_look():
    """A new effect that joins LOOK (undo, keep) must also be rolled, or the random look silently skips it."""
    import ast
    import ui_common
    tree = ast.parse((ROOT / "src" / "ui_app.py").read_text())
    roll = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "roll_look")
    rolled = {n.value for n in ast.walk(roll) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert set(ui_common.LOOK) <= rolled, set(ui_common.LOOK) - rolled


def test_every_setting_is_either_part_of_the_look_or_listed_as_not():
    """A new setting must be decided on: the dice and undo only know LOOK, so a look setting missing there is skipped."""
    import ui_common
    not_look = {"zoom", "encoding", "language", "copy_text_only", "custom", "recent", "remember_recent",
                "music", "music_dir", "music_shuffle", "volume", "music_fade", "music_info", "random_on_start",
                "sidebar", "maximized", "scroller_text", "update_check", "update_last"}
    unknown = set(core.DEFAULTS) - set(ui_common.LOOK) - not_look
    assert not unknown, f"part of the look (LOOK and roll_look) or behaviour (this list)? {unknown}"


def test_the_dos_font_is_bundled_and_has_the_vga_cell():
    assert pages.DOS_FONT_READY
    page = pages.Page({**CFG, "font": core.DOS_FONT}, 1.0)
    assert (page.cw, page.ch) == (8.0, 16)   # 8 x 16 pixels at 100 %, like the VGA text mode
    assert (ROOT / "data" / "fonts" / "LICENSE.txt").is_file() and "VileR" in (ROOT / "data" / "fonts" / "README.md").read_text()


def test_every_style_sets_every_effect():
    """A style must set each on/off effect, or switching from one style to another leaves effects of the first on."""
    import ui_common
    # the styles leave the smooth edges alone, like the theme and the font: pixels or not is a taste of its own
    effects = {k for k in ui_common.LOOK if isinstance(core.DEFAULTS[k], bool)} - {"smooth"}
    for name, (_label, settings) in ui_common.STYLES.items():
        assert effects <= set(settings), (name, effects - set(settings))
        assert not (settings.get("pulse") and settings.get("neon_flicker")), (name, "pulse and flicker beat the same glow")


def test_smooth_edges_round_a_staircase_and_leave_the_rest():
    """Smoothing anti-aliases the steps of the block art (partly covered pixels appear), keeps the art in place, and
    touches neither ANSI art nor the text-only view."""
    art = "\n".join(["▄█", "██▀", "█▀"])

    def render(cfg, plain=False):
        page = pages.Page({**CFG, "soft": False, "ramp": False, **cfg}, 1.0)
        page.set_text(art)
        page.plain = plain
        return page.render()
    colours = lambda s: {bytes(s.get_data())[i:i + 3] for i in range(0, len(bytes(s.get_data())), 4)}
    sharp = render({})
    for amount in ("low", "mid", "high"):
        smooth = render({"smooth": True, "smooth_amount": amount})
        assert bytes(smooth.get_data()) != bytes(sharp.get_data()), amount
        assert len(colours(smooth)) > len(colours(sharp)), amount   # in-between colours: anti-aliased edges
    assert bytes(render({"smooth": True}, plain=True).get_data()) == bytes(render({}, plain=True).get_data())


def test_the_text_only_view_shows_no_effect():
    """Text only: the theme's colours and the text, whatever effects are switched on."""
    import ui_common
    every = {k: True for k in ui_common.LOOK if isinstance(core.DEFAULTS[k], bool)}
    pages_ = []
    for cfg in (dict(CFG), {**CFG, **every, "glow_mode": "halo", "crt_mask": "dots"}):
        page = pages.Page(cfg, 1.0)
        page.plain = True
        page.set_text(core.clean_text(["██ Title: NfoGlow ██", "", "▓▓ Some text with a link www.example.org"]))
        page.time = 2.0
        pages_.append(bytes(page.render().get_data()))
    assert pages_[0] == pages_[1]


def test_look_code_round_trips_and_refuses_bad_codes():
    import base64
    import json
    import zlib
    import ui_common
    keys, choices = ui_common.LOOK_SHARED, ui_common.LOOK_CHOICES
    assert "font" in ui_common.LOOK and "font" not in keys
    cfg = {**core.DEFAULTS, "theme": "custom", "glow": 5, "opening": "rain", "ramp_colors": ["#010203", "#040506", "#070809"],
           "custom": {"bg": "#000000", "text": "#ffffff", "art": "#ff0000", "link": "#00ff00"}}
    code = core.look_code(cfg, keys)
    assert code.startswith("nfoglow:1:") and "\n" not in code and len(code) < 600
    got = core.read_look_code(f"  {code}\n", keys, choices)
    assert got == {**{k: cfg[k] for k in keys}, "custom": cfg["custom"], "dos_font": False}
    assert core.read_look_code(core.look_code({**cfg, "font": core.DOS_FONT}, keys), keys, choices)["dos_font"] is True
    assert core.read_look_code(core.look_code({**cfg, "font": "Fira Mono"}, keys), keys, choices)["dos_font"] is False
    assert "custom" not in core.read_look_code(core.look_code(core.DEFAULTS, keys), keys, choices)

    def make(data, prefix="nfoglow:1:"):
        return prefix + base64.urlsafe_b64encode(zlib.compress(json.dumps(data).encode())).decode()
    # what is not a code at all
    for bad in ("", "hello", "nfoglow:1:", "nfoglow:1:!!!", "nfoglow:2:" + code[10:], make([1]), make({}),
                "nfoglow:1:" + base64.urlsafe_b64encode(zlib.compress(b"\xff\xfe")).decode(), "nfoglow:1:" + "A" * 5000):
        assert core.read_look_code(bad, keys, choices) is None, bad
    assert core.read_look_code(make({"x": 1}), keys, choices) is None   # nothing known in it
    assert core.read_look_code("nfoglow:1:" + base64.urlsafe_b64encode(zlib.compress(b"[" * 1 + b" " * 30000 + b"]")).decode(),
                               keys, choices) is None   # a zip bomb stays out
    # a wrong value is left out, the rest is taken; settings outside the look are never taken
    got = core.read_look_code(make({"theme": "nope", "glow": 9, "opening": 3, "crt": True, "ramp_colors": ["red"] * 3,
                                    "volume": 100, "music_dir": "/etc", "stars_mode": "warp"}), keys, choices)
    assert got == {"crt": True, "stars_mode": "warp"}
    assert core.read_look_code(make({"dos_font": "yes", "crt": True}), keys, choices) == {"crt": True}
    # a custom theme needs all four colours, valid
    bad_custom = make({"theme": "custom", "custom": {"bg": "#000000", "text": "#ffffff", "art": "x", "link": "#00ff00"}})
    assert "custom" not in core.read_look_code(bad_custom, keys, choices)
    assert set(choices) <= set(keys) and all(core.DEFAULTS[k] in choices[k] for k in choices)


def test_installer_version_matches():
    assert f'VERSION="{core.__version__}"' in (ROOT / "install.sh").read_text()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)


def test_update_check():
    """Versions compare as numbers, a bad answer is refused, the weekly check is off by default and waits a week."""
    import io
    import json
    import time
    from contextlib import nullcontext
    from unittest import mock
    assert core.version_tuple("v1.10") > core.version_tuple("1.9") and core.version_tuple("1.2") == (1, 2)
    assert core.version_tuple("latest") is None and core.version_tuple("1.2-beta") is None

    def answer(tag, url="https://github.com/DigitGram/nfoglow/releases/tag/v9"):
        return nullcontext(io.BytesIO(json.dumps({"tag_name": tag, "html_url": url}).encode()))
    with mock.patch("urllib.request.urlopen", return_value=answer("v99.0")):
        assert core.newer_release()[0] == "99.0"
    with mock.patch("urllib.request.urlopen", return_value=answer("v" + core.__version__)):
        assert core.newer_release() is None   # the same version is not news
    for bad in (answer("nightly"), answer("v99", "https://evil.example/")):
        with mock.patch("urllib.request.urlopen", return_value=bad):
            try:
                core.newer_release()
            except ValueError:
                continue
            raise AssertionError("a strange answer was accepted")
    cfg = dict(core.DEFAULTS)
    assert not core.update_due(cfg)   # off by default
    cfg["update_check"] = True
    assert core.update_due(cfg)
    cfg["update_last"] = int(time.time())
    assert not core.update_due(cfg)
    assert core.update_due(cfg, time.time() + core.UPDATE_INTERVAL + 1)
    with mock.patch("os.path.exists", return_value=True):   # in a Flatpak the store updates
        assert not core.update_due(cfg, time.time() + 10 * core.UPDATE_INTERVAL)


def test_clean_text_keeps_letter_spaced_text():
    lines = ["  F o r e v e r   I m m o r t a l", "  o  o", "  + +", "  a b c"]
    assert core.clean_text(lines, dedent=False) == "F o r e v e r   I m m o r t a l"
