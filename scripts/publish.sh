#!/bin/sh
# Publikuje wtyczkę na serwerze aktualizacji (FTP, katalog widoczny pod $UMMETEO_HTTP):
#
#   UMMeteoPL.tar.gz          git archive HEAD bez docs/tests/tools/scripts
#   UMMeteoPL.tar.gz.sha256   sprawdzana przez install.sh
#   install.sh                jednolinijkówka, uruchamiana też przez update.py co 8 h
#   index.html, screenshots/  strona z dokumentacją (docs/index.html)
#   version                   "<wersja>" + "install.sh <sha256>", wysyłany NA KOŃCU,
#                             żeby dekoder nie zobaczył wersji przed plikami
#
# Cel FTP z hasłem i adres publiczny POZA gitem (adresu nie ma być w gicie jawnie):
# $UMMETEO_FTP / $UMMETEO_HTTP albo scripts/publish.local (gitignored):
#   UMMETEO_FTP="ftp://<konto>:<hasło>@<host>:<port>/"
#   UMMETEO_HTTP="https://<host>/<katalog>"   # = unscramble(BASE_URL_ENC) z update.py
#
# Użycie: scripts/publish.sh [--force]   (--force: wyślij ponownie tę samą wersję)
set -eu
cd "$(dirname "$0")/.."

[ -z "${UMMETEO_FTP:-}" ] && [ -f scripts/publish.local ] && . scripts/publish.local
if [ -z "${UMMETEO_FTP:-}" ] || [ -z "${UMMETEO_HTTP:-}" ]; then
    echo "ustaw UMMETEO_FTP i UMMETEO_HTTP albo scripts/publish.local" >&2
    exit 1
fi
HTTP_BASE="${UMMETEO_HTTP%/}"
baked=$(python3 -c 'import base64, sys; k = b"UMMeteoPL"; print(bytes(c ^ k[i % len(k)] for i, c in enumerate(base64.b64decode(sys.argv[1]))).decode())' \
    "$(git show HEAD:update.py | sed -n 's/^BASE_URL_ENC = "\(.*\)"/\1/p')")
[ "$baked" = "$HTTP_BASE" ] || { echo "UMMETEO_HTTP różni się od adresu zaszyfrowanego w update.py" >&2; exit 1; }

[ -z "$(git status --porcelain)" ] || { echo "niezacommitowane zmiany - publikowany jest HEAD" >&2; exit 1; }
VERSION=$(git show HEAD:version.py | sed -n 's/^VERSION = "\(.*\)"/\1/p')
[ -n "$VERSION" ] || { echo "brak VERSION w version.py" >&2; exit 1; }

remote=$(curl -fsS --max-time 10 "$HTTP_BASE/version" 2>/dev/null | head -n1 || true)
if [ "$remote" = "$VERSION" ] && [ "${1:-}" != "--force" ]; then
    echo "na serwerze już jest $VERSION - podbij version.py albo użyj --force" >&2
    exit 1
fi

# Hasło idzie do curl przez plik netrc 0600, nigdy w argv (widoczne w `ps`).
host=$(printf '%s' "$UMMETEO_FTP" | sed -E 's#^[a-z]+://([^@]*@)?##; s#/.*##')
creds=$(printf '%s' "$UMMETEO_FTP" | sed -nE 's#^[a-z]+://([^@/]+)@.*#\1#p')
base=$(printf '%s' "${UMMETEO_FTP%/}" | sed -E 's#^([a-z]+://)[^@/]+@#\1#')
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
printf 'machine %s login %s password %s\n' "${host%%:*}" "${creds%%:*}" "${creds#*:}" > "$STAGE/netrc"
chmod 600 "$STAGE/netrc"
put() { curl -fsS --netrc-file "$STAGE/netrc" --ftp-create-dirs -T "$STAGE/out/$1" "$base/$1"; echo "-> $1" >&2; }

mkdir "$STAGE/out"
git archive --format=tar.gz --prefix=UMMeteoPL/ -o "$STAGE/out/UMMeteoPL.tar.gz" HEAD -- . \
    ':!docs' ':!tests' ':!tools' ':!scripts' ':!.gitignore' ':!install.sh'
(cd "$STAGE/out" && sha256sum UMMeteoPL.tar.gz > UMMeteoPL.tar.gz.sha256)
git show HEAD:install.sh > "$STAGE/out/install.sh"
printf '%s\ninstall.sh %s\n' "$VERSION" "$(sha256sum "$STAGE/out/install.sh" | cut -d' ' -f1)" > "$STAGE/out/version"

mkdir "$STAGE/out/screenshots"
git show HEAD:docs/index.html | sed "s#@BASE@#$HTTP_BASE#g" > "$STAGE/out/index.html"
shots=$(git ls-tree --name-only HEAD docs/screenshots/ | sed 's#^docs/##')
for f in $shots; do git show "HEAD:docs/$f" > "$STAGE/out/$f"; done

# shellcheck disable=SC2086  # $shots: plain file names, no spaces
for f in UMMeteoPL.tar.gz UMMeteoPL.tar.gz.sha256 install.sh index.html $shots version; do put "$f"; done

got=$(curl -fsS --max-time 20 "$HTTP_BASE/version?$(date +%s)" | head -n1 || true)
[ "$got" = "$VERSION" ] || { echo "!! $HTTP_BASE/version odpowiada '$got', oczekiwano '$VERSION'" >&2; exit 1; }
echo "opublikowano $VERSION: wget -qO- $HTTP_BASE/install.sh | sh" >&2
