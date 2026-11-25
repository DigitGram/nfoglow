# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""From bytes to text: CP437 or UTF-8 (and NFOs broken by a wrong encoding), ANSI art with its colours and cursor
moves, and the NFO inside a ZIP or a pyReScene .srr. No drawing here."""
import os
import re
import zipfile
import zlib

from core import VGA, is_art

NFO_SUFFIXES = (".nfo", ".diz", ".ans", ".asc")
BROWSE_SUFFIXES = (*NFO_SUFFIXES, ".srr")   # what the arrow keys step through in a folder
MAX_MEMBER = 4 * 1024 * 1024   # largest NFO read from a ZIP; guards against zip bombs
MAX_ROWS = 10000               # ANSI cursor moves stop here, so a bad file cannot make millions of lines
MAX_CELLS = 2_000_000          # ANSI lines end here: a SAUCE width of 65535 times 10000 rows would fill the memory


PORTAL_DOCS = f"/run/user/{os.getuid()}/doc/"


def real_path(path):
    """A file opened through the file manager or the file chooser of a Flatpak arrives as /run/user/N/doc/ID/NAME (the
    document portal), a folder that holds only that file: the arrow keys would find no other NFO. The portal keeps the
    real path of the file; it is used when the sandbox can read it (the Flatpak has the home folder read-only)."""
    if not path.startswith(PORTAL_DOCS):
        return path
    try:
        host = os.fsdecode(os.getxattr(path, "user.document-portal.host-path")).rstrip("\0")
        # the sandbox has its own /usr, /etc and /tmp: a file of the same name there is not the one that was opened
        same = os.path.isfile(host) and os.stat(host).st_size == os.stat(path).st_size
    except OSError:
        return path
    return host if same else path


def decode(data, enc="auto"):
    """bytes -> (text, encoding label, SAUCE width or None).
    Auto: UTF-8 when the bytes are valid UTF-8, else CP437 (the NFO standard)."""
    width = None
    if len(data) >= 128 and data[-128:].startswith(b"SAUCE00"):
        width = int.from_bytes(data[-128 + 96:-128 + 98], "little") or None   # TInfo1 = columns for ANSI
        data = data[:-128]
        cut = data.rfind(b"\x1a")   # EOF marker; only SAUCE comments follow it
        data = data[:cut] if cut >= 0 else data
    data = data.rstrip(b"\x1a")
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    if enc in ("auto", "utf-8"):
        try:
            text = data.decode("utf-8")
            if enc == "auto" and (fixed := _undo_double_encoding(text)):
                return fixed, "CP437 ← UTF-8", width
            return text, "UTF-8", width
        except UnicodeDecodeError:
            if enc == "utf-8":
                return data.decode("utf-8", "replace"), "UTF-8", width
    enc = "cp437" if enc == "auto" else enc
    return data.decode(enc, "replace"), {"cp437": "CP437", "cp850": "CP850", "latin-1": "Latin-1"}[enc], width


def _undo_double_encoding(text):
    """CP437 NFOs that an editor read as Latin-1/Windows-1252 and saved as UTF-8 show "ÛÛÛ" instead of "███".
    Returns the repaired text, or None when the text does not look like that."""
    if any(0x2500 <= ord(ch) <= 0x259F for ch in text):
        return None   # real block characters: proper UTF-8
    for enc in ("latin-1", "cp1252"):
        try:
            fixed = text.encode(enc).decode("cp437")
        except UnicodeError:
            continue
        # a few accented letters are not art, and neither is German text: ß Ä Ö Ü become ▀ ─ ╓ ▄ here, but alone,
        # while broken art always has runs of blocks or lines
        if sum(is_art(ch) for ch in fixed) >= 10 and re.search(r"[─-▟]{3}", fixed):
            return fixed
    return None


def is_ansi(text):
    return "\x1b[" in text


def _color256(n):
    if n < 16:
        return VGA[n]
    if n < 232:
        n -= 16
        return tuple((0, 95, 135, 175, 215, 255)[v] / 255 for v in (n // 36, n // 6 % 6, n % 6))
    return ((8 + (n - 232) * 10) / 255,) * 3


_TOKEN = re.compile(r"\x1b\[([0-9;?]*)([A-Za-z])|(.)", re.S)


def parse_ansi(text, width=None):
    """ANSI art -> (lines, colors); colors[r][c] = (fg, bg) as RGB tuples.
    Handles SGR colours (16, 256, true colour, bold = bright, blink = bright background like iCE colour)
    and cursor movement. shortcut: no scroll regions or line wrapping modes; ANSI art rarely uses them."""
    width = width or 80
    grid = {}
    r = c = 0
    fg, bg, bold, blink, inverse, saved = 7, 0, False, False, False, (0, 0)
    for m in _TOKEN.finditer(text):
        if m[3] is not None:
            ch = m[3]
            if ch == "\n":
                r, c = min(r + 1, MAX_ROWS - 1), 0
            elif ch == "\r":
                c = 0
            elif ch == "\t":
                c = min(width - 1, (c // 8 + 1) * 8)
            elif ch >= " ":
                if c >= width:
                    r, c = min(r + 1, MAX_ROWS - 1), 0
                f = VGA[fg + 8] if isinstance(fg, int) and bold and fg < 8 else (VGA[fg] if isinstance(fg, int) else fg)
                b = VGA[bg + 8] if isinstance(bg, int) and blink and bg < 8 else (VGA[bg] if isinstance(bg, int) else bg)
                grid[r, c] = (ch, *((b, f) if inverse else (f, b)))
                c += 1
            continue
        # [:9]: int() raises on more than 4300 digits
        args = [int(p[:9]) if p.isdigit() else 0 for p in m[1].replace("?", "").split(";")] if m[1] else []
        n = max(args[0], 1) if args else 1
        cmd = m[2]
        if cmd == "m":
            args = args or [0]
            i = 0
            while i < len(args):
                a = args[i]
                if a == 0:
                    fg, bg, bold, blink, inverse = 7, 0, False, False, False
                elif a == 1: bold = True
                elif a == 22: bold = False
                elif a in (5, 6): blink = True
                elif a == 25: blink = False
                elif a == 7: inverse = True
                elif a == 27: inverse = False
                elif 30 <= a <= 37: fg = a - 30
                elif a == 39: fg = 7
                elif 40 <= a <= 47: bg = a - 40
                elif a == 49: bg = 0
                elif 90 <= a <= 97: fg = a - 90 + 8
                elif 100 <= a <= 107: bg = a - 100 + 8
                elif a in (38, 48) and i + 1 < len(args):
                    if args[i + 1] == 5 and i + 2 < len(args):
                        col, i = _color256(args[i + 2]), i + 2
                    elif args[i + 1] == 2 and i + 4 < len(args):
                        col, i = tuple(v / 255 for v in args[i + 2:i + 5]), i + 4
                    else:
                        col = None
                    if col:
                        fg, bg = (col, bg) if a == 38 else (fg, col)
                i += 1
        elif cmd == "A": r = max(0, r - n)
        elif cmd == "B": r = min(r + n, MAX_ROWS - 1)
        elif cmd == "C": c = min(width - 1, c + n)
        elif cmd == "D": c = max(0, c - n)
        elif cmd in "Hf":
            r, c = (min(max(args[0] - 1, 0), MAX_ROWS - 1) if args else 0), (max(args[1] - 1, 0) if len(args) > 1 else 0)
        elif cmd == "s": saved = (r, c)
        elif cmd == "u": r, c = saved
    widths = {}
    for y, x in grid:
        widths[y] = max(widths.get(y, 0), x + 1)
    lines, colors = [], []
    default, left = (VGA[7], VGA[0]), MAX_CELLS
    for y in range(max(widths, default=-1) + 1):
        left -= widths.get(y, 0)
        if left < 0:   # 25 times a full 80-column ANSI: only a file made to blow up gets here
            break
        cells = [grid.get((y, x), (" ", *default)) for x in range(widths.get(y, 0))]
        lines.append("".join(t[0] for t in cells))
        colors.append([t[1:] for t in cells])
    return lines, colors


def _best(names):
    """The member to show: the first .nfo, else .diz/.ans/.asc; None when there is none."""
    found = [n for n in names if n.lower().endswith(NFO_SUFFIXES)]
    # by its ending, not os.path.splitext: a member named ".nfo" has no extension there
    return min(found, key=lambda n: (next(i for i, s in enumerate(NFO_SUFFIXES) if n.lower().endswith(s)), n.lower()),
               default=None)


def _read_file(path):
    """The bytes of a file, at most MAX_MEMBER: a video dropped by mistake or /dev/zero must not fill the memory."""
    with open(path, "rb") as f:
        data = f.read(MAX_MEMBER + 1)
    if len(data) > MAX_MEMBER:
        raise OSError("file too large")
    return data


def srr_files(data):
    """{name: bytes} of the files a pyReScene .srr stores (the NFO, SFV, ...).
    An SRR is a RAR without its contents: an SRR header block (type 0x69), then one "stored file" block (0x6A)
    per file, then the RAR headers, which hold no files. Each block starts with CRC (2), type (1), flags (2)
    and header size (2); a stored file adds its size (4), the name length (2) and the name."""
    if not data.startswith(b"iii"):
        raise OSError("not an SRR file")
    files, pos = {}, 0
    while pos + 7 <= len(data):
        kind, size = data[pos + 2], int.from_bytes(data[pos + 5:pos + 7], "little")
        if size < 7 or (kind != 0x69 and kind != 0x6A):
            break
        if kind == 0x6A:
            length = int.from_bytes(data[pos + 7:pos + 11], "little")
            name_len = int.from_bytes(data[pos + 11:pos + 13], "little")
            name = data[pos + 13:pos + 13 + name_len].decode("utf-8", "replace")
            files[name] = data[pos + size:pos + size + length]
            pos += length
        pos += size
    return files


def read(path):
    """(bytes, display name) of an NFO file, or of the NFO inside a ZIP or a pyReScene .srr
    (the first .nfo, else .diz/.ans/.asc). Raises OSError for unreadable files and archives without an NFO."""
    low = path.lower()
    if low.endswith((".zip", ".srr")):
        try:
            if low.endswith(".zip"):
                with zipfile.ZipFile(path) as z:
                    sizes = {i.filename: i.file_size for i in z.infolist() if i.file_size <= MAX_MEMBER}
                    name = _best(sizes)
                    data = z.read(name) if name else None
            else:
                files = srr_files(_read_file(path))
                name = _best(files)
                data = files.get(name)
        # RuntimeError: encrypted; NotImplementedError: a packing method Python lacks (Deflate64);
        # zlib.error, EOFError: damaged or cut-off data
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error) as e:
            raise OSError(str(e)) from e
        if name is None:
            raise OSError("no NFO inside")
        return data, f"{os.path.basename(path)} › {os.path.basename(name)}"
    return _read_file(path), os.path.basename(path)
