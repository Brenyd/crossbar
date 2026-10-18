#!/usr/bin/env bash
# Try the shell on your current desktop without building an ISO.
#   ./dev-run.sh          demo library
#   ./dev-run.sh --real   your real Steam/GOG/Epic (needs steam / legendary installed)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLAG="--demo"; [[ "${1:-}" == "--real" ]] && FLAG=""
python3 "$HERE/shell/server.py" $FLAG &
PID=$!
trap 'kill $PID' EXIT
until curl -s -o /dev/null http://127.0.0.1:7777/api/jobs; do sleep 0.2; done
BROWSER=$(command -v chromium || command -v google-chrome-stable || command -v google-chrome || true)
if [[ -n "$BROWSER" ]]; then
  "$BROWSER" --app=http://127.0.0.1:7777 --user-data-dir=/tmp/crossbar-dev --start-fullscreen
else
  xdg-open http://127.0.0.1:7777; wait $PID
fi
