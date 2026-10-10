#!/bin/sh
# UM Meteo.pl - instalacja / aktualizacja wtyczki na dekoderze z enigma2 (Python 3):
#   wget -qO- https://raw.githubusercontent.com/areqq/UMMeteoPL/master/install.sh | sh
# Wtyczka uruchamia ten skrypt z serwera wtyczki w tle co 8 h, gdy jest tam inna
# wersja (update.py, z UMMETEO_DEST = swoim katalogiem). UMMETEO_URL podaje inne
# archiwum, np. https://github.com/areqq/UMMeteoPL/archive/refs/heads/master.tar.gz (bez sumy).
set -e

fail() { echo "UMMeteoPL: $*" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || fail "wtyczka wymaga obrazu z Pythonem 3"

# adres serwera wtyczki: XOR z "UMMeteoPL" + base64, jak BASE_URL_ENC w update.py
BASE_ENC="PTk5FQdfQH82NC4jAFoKATViJSFiMDkoCiQpOh0B"
BASE="${UMMETEO_BASE:-$(python3 -c 'import base64, sys; k = b"UMMeteoPL"; print(bytes(c ^ k[i % len(k)] for i, c in enumerate(base64.b64decode(sys.argv[1]))).decode())' "$BASE_ENC")}"
URL="${UMMETEO_URL:-$BASE/UMMeteoPL.tar.gz}"
DEST="${UMMETEO_DEST:-/usr/lib/enigma2/python/Plugins/Extensions/UMMeteoPL}"
TMP=$(mktemp -d /tmp/ummeteo-install.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

[ -d "$(dirname "$DEST")" ] || fail "to nie wygląda na dekoder z enigma2"

# BusyBox wget's own TLS fails against GitHub on some builds; python3 (used by the plugin anyway) is the fallback
download() {
    if command -v wget >/dev/null 2>&1 && wget -q -O "$2" "$1" 2>/dev/null; then return 0; fi
    if command -v curl >/dev/null 2>&1 && curl -fsSL -o "$2" "$1" 2>/dev/null; then return 0; fi
    python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$1" "$2"
}

want=
if [ -z "${UMMETEO_URL:-}" ]; then
    download "$URL.sha256" "$TMP/src.sha256" || fail "nie udało się pobrać sumy kontrolnej"
    want=$(cut -d' ' -f1 <"$TMP/src.sha256" | tr -cd '0-9a-f')
    [ ${#want} -eq 64 ] || fail "nieprawidłowa suma kontrolna"
    # Cloudflare przed serwerem trzyma .tar.gz do 4 h (max-age=14400), a .sha256 nie;
    # ?sha=<suma> to osobny klucz cache dla każdego wydania (file:// nie zna zapytań)
    case "$URL" in http*) URL="$URL?sha=$want" ;; esac
fi

echo "UMMeteoPL: pobieram $URL"
download "$URL" "$TMP/src.tar.gz" || fail "nie udało się pobrać archiwum"
if [ -n "$want" ]; then
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
