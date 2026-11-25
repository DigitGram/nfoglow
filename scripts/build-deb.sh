#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 DigitGram
#
# Builds nfoglow_<version>_all.deb from this checkout (only dpkg-deb needed, no debhelper):
#   scripts/build-deb.sh [OUTDIR]     default OUTDIR: the current folder
# The package installs for the whole system: sudo apt install ./nfoglow_<version>_all.deb
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
OUT="$(mkdir -p "${1:-.}" && cd "${1:-.}" && pwd)"
VERSION="$(sed -n 's/^VERSION="\([^"]*\)".*/\1/p' "$ROOT/install.sh")"
[ -n "$VERSION" ] || { echo "no VERSION in install.sh" >&2; exit 1; }
APP_ID=io.github.digitgram.NfoGlow
EPOCH="${SOURCE_DATE_EPOCH:-$(git -C "$ROOT" log -1 --format=%ct 2>/dev/null || date +%s)}"

PKG="$(mktemp -d)"
trap 'rm -rf "$PKG"' EXIT
D="$PKG/nfoglow_${VERSION}_all"
mkdir -p "$D/DEBIAN" "$D/usr/bin" "$D/usr/share/applications" "$D/usr/share/metainfo" \
         "$D/usr/share/mime/packages" "$D/usr/share/doc/nfoglow"

# program files: the same layout as install.sh, below /usr/share/nfoglow
S="$D/usr/share/nfoglow"
install -Dm644 -t "$S" "$ROOT"/src/*.py
install -Dm644 -t "$S/po" "$ROOT"/po/*.po
install -Dm644 -t "$S/music" "$ROOT"/data/music/*
install -Dm644 -t "$S/fonts" "$ROOT"/data/fonts/*
sed -i '1s|^#!.*|#!/usr/bin/python3|' "$S/nfoglow.py"
chmod 755 "$S/nfoglow.py"
ln -s ../share/nfoglow/nfoglow.py "$D/usr/bin/nfoglow"

# desktop file, icons, file types, appstream
sed -e 's|@EXEC@|nfoglow|' -e "s|@ICON@|$APP_ID|" "$ROOT/data/nfoglow.desktop.in" > "$D/usr/share/applications/$APP_ID.desktop"
chmod 644 "$D/usr/share/applications/$APP_ID.desktop"
install -Dm644 "$ROOT/data/$APP_ID.mime.xml" "$D/usr/share/mime/packages/$APP_ID.xml"
install -Dm644 -t "$D/usr/share/metainfo" "$ROOT/data/$APP_ID.metainfo.xml"
(cd "$ROOT/data/icons" && find hicolor -type f -exec install -Dm644 {} "$D/usr/share/icons/{}" \;)

# copyright (Debian wants it) and the licences of the bundled music and font
cat > "$D/usr/share/doc/nfoglow/copyright" <<'COPYRIGHT'
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: NfoGlow
Source: https://github.com/DigitGram/nfoglow

Files: *
Copyright: 2026 DigitGram
License: GPL-3+

Files: usr/share/nfoglow/music/*
Copyright: Stennish
License: CC-BY-4.0
Comment: Shortened and converted to Ogg Vorbis, see usr/share/doc/nfoglow/music-README.md.

Files: usr/share/nfoglow/fonts/*
Copyright: 2016-2020 VileR
License: CC-BY-SA-4.0
Comment: PxPlus IBM VGA 8x16 from The Ultimate Oldschool PC Font Pack, unchanged. Licence text: fonts/LICENSE.txt.

License: GPL-3+
 On Debian systems, the full text of the GNU General Public License version 3
 is in /usr/share/common-licenses/GPL-3.

License: CC-BY-4.0
 https://creativecommons.org/licenses/by/4.0/legalcode

License: CC-BY-SA-4.0
 https://creativecommons.org/licenses/by-sa/4.0/legalcode
COPYRIGHT
install -Dm644 "$ROOT/data/music/README.md" "$D/usr/share/doc/nfoglow/music-README.md"
printf 'nfoglow (%s) unstable; urgency=medium\n\n  * Release %s, see https://github.com/DigitGram/nfoglow/releases\n\n -- DigitGram <120712067+DigitGram@users.noreply.github.com>  %s\n' \
  "$VERSION" "$VERSION" "$(LC_ALL=C date -u -d "@$EPOCH" '+%a, %d %b %Y %H:%M:%S +0000')" | gzip -9n > "$D/usr/share/doc/nfoglow/changelog.gz"
chmod 644 "$D/usr/share/doc/nfoglow/changelog.gz"

# DEBIAN/control
SIZE="$(du -s --apparent-size --block-size=1024 --exclude=DEBIAN "$D" | cut -f1)"
cat > "$D/DEBIAN/control" <<CONTROL
Package: nfoglow
Version: $VERSION
Section: graphics
Priority: optional
Architecture: all
Installed-Size: $SIZE
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.5), gir1.2-pango-1.0, shared-mime-info
Recommends: gir1.2-gstreamer-1.0, gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad
Maintainer: DigitGram <120712067+DigitGram@users.noreply.github.com>
Homepage: https://github.com/DigitGram/nfoglow
Description: NFO and ANSI art viewer with exact pixels, glow and chiptunes
 NfoGlow shows .nfo, .diz and .ans files the way the scene meant it: block
 graphics as exact pixels without seams, optional glow, CRT and demoscene
 effects, CP437 and other encodings, SAUCE, files inside ZIP and .srr, and
 export to PNG or PDF. Music (chiptunes or your own tracker files) is
 optional and needs GStreamer.
CONTROL

# refresh the desktop caches and compile the bytecode (a user cannot write next to the program)
cat > "$D/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
if [ "$1" = configure ]; then
  /usr/bin/python3 -m compileall -q /usr/share/nfoglow >/dev/null 2>&1 || true
  command -v update-mime-database >/dev/null && update-mime-database /usr/share/mime >/dev/null 2>&1 || true
  command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
  command -v gtk4-update-icon-cache >/dev/null && gtk4-update-icon-cache -q -t -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
  command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
exit 0
POSTINST
# the bytecode is not dpkg's file: it must go before dpkg removes the folders, or /usr/share/nfoglow stays behind
cat > "$D/DEBIAN/prerm" <<'PRERM'
#!/bin/sh
set -e
case "$1" in
  remove|upgrade|deconfigure) rm -rf /usr/share/nfoglow/__pycache__ ;;
esac
exit 0
PRERM
cat > "$D/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
case "$1" in
  remove|purge)
    command -v update-mime-database >/dev/null && update-mime-database /usr/share/mime >/dev/null 2>&1 || true
    command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
    command -v gtk4-update-icon-cache >/dev/null && gtk4-update-icon-cache -q -t -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
    command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
    ;;
esac
exit 0
POSTRM
chmod 755 "$D/DEBIAN/postinst" "$D/DEBIAN/prerm" "$D/DEBIAN/postrm"

# same bytes for the same commit: fixed mtimes and modes, owner root
find "$D" -type d -exec chmod 755 {} +
find "$D" -type f ! -perm -u+x -exec chmod 644 {} +
chmod 755 "$D/DEBIAN/postinst" "$D/DEBIAN/prerm" "$D/DEBIAN/postrm"
find "$D" -exec touch -h -d "@$EPOCH" {} +
SOURCE_DATE_EPOCH="$EPOCH" dpkg-deb --root-owner-group -Zxz --build "$D" "$OUT/nfoglow_${VERSION}_all.deb" >/dev/null
echo "$OUT/nfoglow_${VERSION}_all.deb"
