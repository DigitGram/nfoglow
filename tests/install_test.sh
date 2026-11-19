#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
# Installs this checkout into a throw-away home, starts it and removes it again: nothing of NfoGlow may stay.
# Usage: tests/install_test.sh   (not as root: install.sh refuses that)
set -euo pipefail
cd "$(dirname "$0")/.."
HOME="$(mktemp -d)"; export HOME
trap 'rm -rf "$HOME"' EXIT
unset XDG_DATA_HOME XDG_CONFIG_HOME   # so both lie in the throw-away home
mkdir "$HOME/.config" "$HOME/bin"     # .config: xdg-mime 1.2.1 cannot create it, and --purge must clean the entry it makes there
printf '#!/bin/sh\nexit 1\n' > "$HOME/bin/python3"; chmod +x "$HOME/bin/python3"
PATH="$HOME/bin:$PATH"                # a python3 without GTK first in PATH, as conda and pyenv put one: the install must not use it

./install.sh > /dev/null
[ "$("$HOME/.local/bin/nfoglow" --version)" = "NfoGlow $(sed -n 's/^VERSION="\([^"]*\)".*/\1/p' install.sh)" ]
[ "$(head -n 1 "$HOME/.local/share/nfoglow/nfoglow.py")" = "#!/usr/bin/python3" ]   # the installed program runs with the system's Python
[ -f "$HOME/.local/share/applications/io.github.digitgram.NfoGlow.desktop" ]
"$HOME/.local/share/nfoglow/install.sh" --purge > /dev/null
if find "$HOME" -iname '*nfoglow*' | grep . || grep -rli nfoglow "$HOME"; then
  echo "left behind after --purge (listed above)" >&2; exit 1
fi
echo "install test ok"
