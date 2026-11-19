#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""Writes po/nfoglow.pot from every _("...") and N_("...") in src/. Run after changing UI texts."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def messages():
    found = {}
    for path in sorted((ROOT / "src").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("_", "N_") and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.setdefault(node.args[0].value, f"src/{path.name}")
    return found


if __name__ == "__main__":
    out = ['msgid ""', 'msgstr ""', '"Project-Id-Version: NfoGlow\\n"', '"Content-Type: text/plain; charset=UTF-8\\n"', ""]
    for msg, where in messages().items():
        out += [f"#: {where}", f"msgid {json.dumps(msg, ensure_ascii=False)}", 'msgstr ""', ""]
    (ROOT / "po" / "nfoglow.pot").write_text("\n".join(out))
    print(len(messages()), "messages")
