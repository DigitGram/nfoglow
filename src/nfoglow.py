#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
"""NfoGlow: a viewer for NFO and ANSI art.

  nfoglow [FILE...]                    open files in windows
  nfoglow --png OUT.png|OUT.pdf FILE   render FILE to an image or PDF (your theme and font)
  nfoglow --version
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))   # the launcher is a symlink


def main(argv):
    cmd = argv[1:2]
    if cmd in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if cmd == ["--version"]:
        import core
        print(f"NfoGlow {core.__version__}")
        return 0
    if cmd == ["--png"] and len(argv) == 4:
        import cairo
        import core
        import page as pages
        try:
            page, _label, _size = pages.load(argv[3], core.load_settings())
            page.export(argv[2])
        except (OSError, cairo.Error) as e:   # a missing file, a page too big for a PNG, a full disk
            print(f"nfoglow: {e}", file=sys.stderr)
            return 1
        return 0
    import ui_app
    return ui_app.App().run(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
