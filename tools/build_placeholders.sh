#!/bin/sh
# Rebuild loading.png and error.png (the frames shown while the forecast loads or fails)
# with the plugin's own renderer, at the FullHD scale. Run from the plugin directory
# after `zig build` in zig/ (the native binary).
set -e
cd "$(dirname "$0")/.."
BIN=${BIN:-zig/zig-out/bin/ummeteo}
"$BIN" --placeholder loading --scale 1.5 --level 9 --out loading.png
"$BIN" --placeholder error --scale 1.5 --level 9 --out error.png
ls -la loading.png error.png
