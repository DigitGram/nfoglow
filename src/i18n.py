# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""Minimal gettext-style translation: English source strings, one .po file per language.

Catalogs live in po/<lang>.po and are read directly, so there is no msgfmt/.mo build step.
To add a language: copy po/nfoglow.pot to po/<lang>.po and translate it (add a native name to
NATIVE_NAMES if you like). Missing translations fall back to English.
"""
import functools
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PO_DIR = next((d for d in (HERE / "po", HERE.parent / "po") if d.is_dir()), HERE / "po")  # installed / checkout
NATIVE_NAMES = {"en": "English", "de": "Deutsch", "es": "Español", "fr": "Français", "it": "Italiano",
                "ja": "日本語", "pl": "Polski", "pt_BR": "Português (Brasil)", "uk": "Українська", "zh_CN": "简体中文"}

_current = "en"


def N_(message):
    """Mark a string for extraction without translating it (translated later with translate())."""
    return message


def languages():
    """{code: native name} for English plus every po/<code>.po."""
    codes = ["en", *sorted(p.stem for p in PO_DIR.glob("*.po"))]
    return {code: NATIVE_NAMES.get(code, code) for code in codes}


def detect():
    """Language the way gettext picks it: the locale is the first non-empty of LC_ALL, LC_MESSAGES and LANG;
    LANGUAGE (a ":" list) goes before it, except for the locale C, C.UTF-8 or POSIX, which always means English.
    Unlike gettext it falls back to the locale when LANGUAGE names nothing we have."""
    available = languages()
    locale = next((os.environ[v] for v in ("LC_ALL", "LC_MESSAGES", "LANG") if os.environ.get(v)), "C")
    wanted = [locale] if locale.split(".")[0] in ("C", "POSIX") else [*os.environ.get("LANGUAGE", "").split(":"), locale]
    for value in wanted:
        name = value.split(".")[0].split("@")[0]  # "de_DE.UTF-8" -> "de_DE"
        if found := next((c for c in (name, name[:2], *(a for a in available if a.split("_")[0] == name[:2]))
                          if c in available), None):   # pt_PT gets pt_BR, zh_TW gets zh_CN: better than English
            return found
    return "en"


def set_language(code):
    """Select a language code, or "auto" to follow the system."""
    global _current
    _current = detect() if code == "auto" else code


def load_po(path):
    """Parse a .po file into {msgid: msgstr}.

    shortcut: no msgctxt and no plural forms (no message needs them yet); fuzzy and untranslated entries are
    skipped.
    """
    messages = {}
    for block in re.split(r"\n\s*\n", Path(path).read_text(encoding="utf-8")):
        fields, key, fuzzy = {}, None, False
        for line in map(str.strip, block.splitlines()):
            if line.startswith("#,"):
                fuzzy = fuzzy or "fuzzy" in line
            elif m := re.match(r"(msgid|msgstr) (\".*\")$", line):
                key = m[1]
                fields[key] = json.loads(m[2])  # PO string escapes are JSON-compatible
            elif line.startswith('"') and key:
                fields[key] += json.loads(line)
        if fuzzy or "msgid" not in fields:
            continue
        if fields.get("msgstr"):
            messages[fields["msgid"]] = fields["msgstr"]
    return messages


@functools.lru_cache(maxsize=None)
def _catalog(lang):
    path = PO_DIR / f"{lang}.po"
    return load_po(path) if path.is_file() else {}


def translate(message, lang):
    return _catalog(lang).get(message, message)


def _(message):
    return translate(message, _current)

