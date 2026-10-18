#!/usr/bin/env bash
# Downloads the web libraries Crossbar bundles (xterm.js for the built-in terminal)
# into shell/web/vendor. Run by build-iso.sh and update-system.sh; safe to re-run.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
V="$HERE/shell/web/vendor/xterm"
mkdir -p "$V"
CDN=https://cdn.jsdelivr.net/npm
get() { [[ -s "$2" ]] || curl -fsSL --retry 3 "$1" -o "$2"; }
get "$CDN/@xterm/xterm@5.5.0/lib/xterm.js"            "$V/xterm.js"
get "$CDN/@xterm/xterm@5.5.0/css/xterm.css"           "$V/xterm.css"
get "$CDN/@xterm/addon-fit@0.10.0/lib/addon-fit.js"   "$V/addon-fit.js"
echo "vendor libraries ready in $V"
