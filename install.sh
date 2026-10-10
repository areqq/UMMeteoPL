#!/bin/sh
# UM Meteo.pl - instalacja / aktualizacja wtyczki na dekoderze z enigma2 (Python 3):
#   wget -qO- https://<serwer wtyczki>/install.sh | sh
# Wtyczka uruchamia ten sam skrypt z serwera przy automatycznej aktualizacji
# (update.py, z UMMETEO_DEST = swoim katalogiem). UMMETEO_URL podaje inne archiwum,
# np. https://github.com/areqq/UMMeteoPL/archive/refs/heads/master.tar.gz (bez sumy).
set -e

BASE="${UMMETEO_BASE:-https://<serwer wtyczki>}"
URL="${UMMETEO_URL:-$BASE/UMMeteoPL.tar.gz}"
DEST="${UMMETEO_DEST:-/usr/lib/enigma2/python/Plugins/Extensions/UMMeteoPL}"
TMP=$(mktemp -d /tmp/ummeteo-install.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "UMMeteoPL: $*" >&2; exit 1; }

[ -d "$(dirname "$DEST")" ] || fail "to nie wygląda na dekoder z enigma2"
command -v python3 >/dev/null 2>&1 || fail "wtyczka wymaga obrazu z Pythonem 3"

# BusyBox wget's own TLS fails against GitHub on some builds; python3 (used by the plugin anyway) is the fallback
download() {
    if command -v wget >/dev/null 2>&1 && wget -q -O "$2" "$1" 2>/dev/null; then return 0; fi
    if command -v curl >/dev/null 2>&1 && curl -fsSL -o "$2" "$1" 2>/dev/null; then return 0; fi
    python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$1" "$2"
}

echo "UMMeteoPL: pobieram $URL"
download "$URL" "$TMP/src.tar.gz" || fail "nie udało się pobrać archiwum"
if [ -z "${UMMETEO_URL:-}" ]; then
    download "$URL.sha256" "$TMP/src.sha256" || fail "nie udało się pobrać sumy kontrolnej"
    want=$(cut -d' ' -f1 <"$TMP/src.sha256")
    if command -v sha256sum >/dev/null 2>&1; then
        got=$(sha256sum "$TMP/src.tar.gz" | cut -d' ' -f1)
    else
        got=$(python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$TMP/src.tar.gz")
    fi
    [ "$want" = "$got" ] || fail "suma kontrolna archiwum się nie zgadza"
fi

tar -xzf "$TMP/src.tar.gz" -C "$TMP" || fail "uszkodzone archiwum"
SRC=
for d in "$TMP"/*/; do SRC=${d%/}; done
if [ ! -f "$SRC/plugin.py" ] || [ ! -f "$SRC/Meteo.py" ]; then
    fail "w archiwum nie ma wtyczki"
fi
rm -rf "$SRC/docs" "$SRC/tests" "$SRC/tools" "$SRC/scripts" "$SRC/.gitignore" "$SRC/install.sh"

# config.plugins.UMMeteoPL lives in /etc/enigma2/settings; only the legacy list is kept for migration
for f in meteo.ini meteo.ini.migrated; do
    if [ -f "$DEST/$f" ]; then
        cp -p "$DEST/$f" "$SRC/$f"
    fi
done

rm -rf "$DEST.new"
cp -r "$SRC" "$DEST.new"
rm -rf "$DEST"
mv "$DEST.new" "$DEST"

VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$DEST/version.py")
echo "UMMeteoPL: zainstalowano wersję ${VERSION:-?} w $DEST"
echo "UMMeteoPL: zrestartuj GUI (Menu > Czuwanie > Restart GUI), aby wczytać wtyczkę"
