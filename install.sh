#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
#
# NfoGlow installer: per user, no root needed.
#   From a checkout:  ./install.sh
#   One-liner:        curl -fsSL https://github.com/DigitGram/nfoglow/releases/latest/download/install.sh | bash
#   Without curl:     wget -qO- https://github.com/DigitGram/nfoglow/releases/latest/download/install.sh | bash
#   Uninstall:        ~/.local/share/nfoglow/install.sh --uninstall   (--purge also deletes your settings)
set -euo pipefail
[ "$(id -u)" -ne 0 ] || { echo "Run without sudo: the install is per user." >&2; exit 1; }

REPO="DigitGram/nfoglow"   # GitHub owner/name, used by the one-liner
VERSION="1.1.4"            # equals core.__version__ (a test checks); the download is this release's tag, never a branch that moves on
COMMIT=""                  # empty in the repository; the release workflow writes the tag's commit here, into the copy it attaches and that gets signed:
ARCHIVE_URL="https://github.com/$REPO/archive/${COMMIT:-refs/tags/v$VERSION}.tar.gz"   # a tag can be moved to other code, a commit names exactly one
PYTHON=/usr/bin/python3    # the system's Python: the GTK bindings are distro packages for it; a conda, pyenv or venv python3 first in PATH has none

APP_ID=io.github.digitgram.NfoGlow
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
CONFIG_DIR="$CONFIG_HOME/nfoglow"
APP_DIR="$DATA/nfoglow"
LAUNCHER="$HOME/.local/bin/nfoglow"
SRC=""   # the checkout this script lives in; stays empty when piped from curl or wget, wherever that runs
[ -f "${BASH_SOURCE[0]:-}" ] && SRC="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ---------------------------------------------------------------- output helpers
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  BLUE=$'\e[94m'; GREEN=$'\e[32m'; RED=$'\e[31m'; CYAN=$'\e[36m'; RESET=$'\e[0m'
else
  BLUE=""; GREEN=""; RED=""; CYAN=""; RESET=""
fi
TICK="[${GREEN}✓${RESET}]"; CROSS="[${RED}✗${RESET}]"; INFO="[${CYAN}i${RESET}]"

say() { printf '  %s %s\n' "$INFO" "$*"; }
tilde() { printf '%s' "${1/#$HOME/\~}"; }
closing() { printf '  %s Done. You can close this terminal window now.\n' "$TICK"; }

banner() {
  printf '%s\n' "$BLUE"
  cat <<'BANNER'
   ██▄▄  ██ ██▀▀▀▀ ▄▀▀▀▀▄ ▄▀▀▀▀▄ ██     ▄▀▀▀▀▄ ██  ██
   ██ ▀▄▄██ ██▀▀▀  ██  ██ ██ ▄▄▄ ██     ██  ██ ██▄▄██
   ▀▀   ▀▀▀ ▀▀      ▀▀▀▀   ▀▀▀▀  ▀▀▀▀▀▀  ▀▀▀▀  ▀▀  ▀▀
   ░▒▓██████████████████████████████████████████▓▒░

BANNER
  printf '%s  NFO & ANSI viewer  ·  GPL-3.0-or-later\n\n' "$RESET"
}

# step "message" command...  Runs the command quietly and prints [✓]/[✗]; on failure shows its output and exits.
step() {
  local message=$1 rc; shift
  set +e; ( set -e; "$@" ) >"$TMP/log" 2>&1; rc=$?; set -e
  if [ "$rc" -eq 0 ]; then
    printf '  %s %s\n' "$TICK" "$message"
  else
    printf '  %s %s\n' "$CROSS" "$message" >&2
    sed 's/^/      /' "$TMP/log" >&2
    exit 1
  fi
}

# Run an optional system tool if it exists; optional steps never abort the installer.
# shellcheck disable=SC2015
try() { command -v "$1" >/dev/null && "$@" || true; }

# ---------------------------------------------------------------- install steps
have_gtk() {
  "$PYTHON" -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
gi.require_foreign("cairo"); gi.require_version("PangoCairo", "1.0")
from gi.repository import Adw
raise SystemExit(Adw.get_minor_version() < 5)' 2>/dev/null
}

check_dependencies() {
  [ -x "$PYTHON" ] || { echo "$PYTHON is required."; exit 1; }
  have_gtk && return
  cat <<MSG
NfoGlow needs GTK 4 + libadwaita 1.5 or newer for Python (GNOME 46+). Install it, for example:
  Debian/Ubuntu: sudo apt install python3-gi python3-gi-cairo gir1.2-adw-1
  Fedora:        sudo dnf install python3-gobject libadwaita
  Arch:          sudo pacman -S python-gobject python-cairo libadwaita
MSG
  exit 1
}

download() {
  if command -v curl >/dev/null; then curl -fsSL "$ARCHIVE_URL" | tar -xz --strip-components=1 -C "$SRC"
  elif command -v wget >/dev/null; then wget -qO- "$ARCHIVE_URL" | tar -xz --strip-components=1 -C "$SRC"
  else echo "curl or wget is required to download NfoGlow."; exit 1
  fi
}

install_files() {
  mkdir -p "$APP_DIR/po" "$APP_DIR/music" "$APP_DIR/fonts" "$(dirname "$LAUNCHER")"
  rm -f "$APP_DIR"/*.py "$APP_DIR/po"/*.po "$APP_DIR/music"/* "$APP_DIR/fonts"/*   # an update must drop files that are no longer shipped
  cp "$SRC"/src/*.py "$SRC/install.sh" "$APP_DIR/"      # install.sh is kept for --uninstall
  cp "$SRC"/po/*.po "$APP_DIR/po/"
  [ -z "$COMMIT" ] || sed -i "s/^COMMIT=\"\"/COMMIT=\"$COMMIT\"/" "$APP_DIR/install.sh"   # the copy from the archive is not pinned: it must fetch the same commit
  sed -i "1s|^#!.*|#!$PYTHON|" "$APP_DIR/nfoglow.py"    # the installed program runs with the system's Python; the checkout (and the Flatpak) keep env python3
  cp "$SRC"/data/music/* "$APP_DIR/music/"               # the built-in chiptunes (CC BY 4.0, see their README)
  cp "$SRC"/data/fonts/* "$APP_DIR/fonts/"               # the DOS font (CC BY-SA 4.0, see its README); only NfoGlow uses it
  chmod +x "$APP_DIR/nfoglow.py" "$APP_DIR/install.sh"
  ln -sf "$APP_DIR/nfoglow.py" "$LAUNCHER"
}

esc() { printf '%s' "$1" | sed 's/[\\&|]/\\&/g'; }

install_desktop() {
  (cd "$SRC/data/icons/hicolor" && find . -type f) | while read -r icon; do
    mkdir -p "$DATA/icons/hicolor/$(dirname "$icon")"
    cp "$SRC/data/icons/hicolor/$icon" "$DATA/icons/hicolor/$icon"
  done
  mkdir -p "$DATA/applications" "$DATA/mime/packages"
  # The launcher points at the PNG by absolute path: the most reliable way to get the icon into the Shell.
  # Exec in quotes: a home folder with a space in its name; esc: a "|", "&" or "\" in it would change the sed command
  sed -e "s|@EXEC@|\"$(esc "$LAUNCHER")\"|" -e "s|@ICON@|$(esc "$DATA/icons/hicolor/256x256/apps/$APP_ID.png")|" \
      "$SRC/data/nfoglow.desktop.in" > "$DATA/applications/$APP_ID.desktop"
  cp "$SRC/data/$APP_ID.mime.xml" "$DATA/mime/packages/$APP_ID.xml"
}

refresh_desktop() {
  try update-mime-database "$DATA/mime"
  rm -f "$DATA/icons/hicolor/icon-theme.cache"   # a stale cache can hide new icons
  touch "$DATA/icons/hicolor" 2>/dev/null || true
  try update-desktop-database "$DATA/applications"
}

open_nfo_with_nfoglow() {   # only when no other program is chosen
  local mime current
  command -v xdg-mime >/dev/null || return 0
  for mime in text/x-nfo text/x-ansi application/x-srr; do
    current="$(xdg-mime query default "$mime" 2>/dev/null || true)"
    if [ -z "$current" ]; then xdg-mime default "$APP_ID.desktop" "$mime"; fi
  done
}

install_app() {
  banner
  if [ -z "$SRC" ] || [ ! -f "$SRC/src/nfoglow.py" ]; then
    SRC="$TMP/src"; mkdir "$SRC"
    step "Downloading NfoGlow" download
  fi
  step "Checking dependencies" check_dependencies
  step "Installing program files" install_files
  step "Installing icons, launcher and file types" install_desktop
  step "Opening .nfo, .diz, .ans and .srr files with NfoGlow" open_nfo_with_nfoglow
  step "Refreshing the desktop" refresh_desktop
  echo
  say "$("$LAUNCHER" --version) is installed."
  cat <<MSG

      Use       double-click an .nfo, .diz or .ans file, or open "NfoGlow" in the Activities overview
      Command   nfoglow FILE   ·   nfoglow --png OUT.png FILE   (render to an image)

MSG
  say "To uninstall later, run:"
  printf '        %s --uninstall    keeps your settings\n' "$(tilde "$APP_DIR/install.sh")"
  printf '        %s --purge        removes the settings too\n\n' "$(tilde "$APP_DIR/install.sh")"
  say "If the icon or launcher is missing, log out and in once."
  echo
  closing
}

# ---------------------------------------------------------------- uninstall steps
remove_files()    { rm -rf "$APP_DIR" "$LAUNCHER"; }
remove_settings() { rm -rf "$CONFIG_DIR"; }
remove_desktop() {
  rm -f "$DATA/applications/$APP_ID.desktop" "$DATA/mime/packages/$APP_ID.xml"
  find "$DATA/icons/hicolor" -name "$APP_ID*" -delete 2>/dev/null || true
  if [ -f "$CONFIG_HOME/mimeapps.list" ]; then   # the default-app entries `xdg-mime default` made
    sed -i --follow-symlinks "/^\(text\/x-nfo\|text\/x-ansi\|application\/x-srr\)=$APP_ID\.desktop;\?\$/d" "$CONFIG_HOME/mimeapps.list"
  fi
}

uninstall_app() {
  banner
  step "Removing program files" remove_files
  step "Removing launcher, icons and file types" remove_desktop
  [ "${1:-}" = purge ] && step "Removing settings" remove_settings
  step "Refreshing the desktop" refresh_desktop
  echo
  if [ "${1:-}" = purge ]; then say "NfoGlow was removed, including your settings."
  else say "NfoGlow was removed. Your settings in $(tilde "$CONFIG_DIR") were kept (--purge deletes them too)."; fi
  closing
}

case "${1:-}" in
  "")          install_app ;;
  --uninstall) uninstall_app ;;
  --purge)     uninstall_app purge ;;
  *)           echo "Usage: $0 [--uninstall | --purge]" >&2; exit 1 ;;
esac
