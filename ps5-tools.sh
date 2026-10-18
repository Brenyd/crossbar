#!/usr/bin/env bash
# PS5 only: install ps5_control (fan patterns and boost) from github.com/ps5-linux/ps5-linux-tools.
#
# Crossbar can't ship ps5_control itself (that project has no license yet), so on a PS5 this
# downloads and builds it here, the same way its own install.sh would, with two differences:
#   * only ps5_control is built and installed (to /usr/local/sbin, where its services expect it);
#   * its ps5fan / ps5boost services are installed but NOT enabled or started. Turn them on in
#     Crossbar (Settings › System › PS5) or with: sudo systemctl enable --now ps5fan.service
# The kernel, drivers and boot setup are never touched. Does nothing on other machines.
#
#   ./ps5-tools.sh            install if missing (also run by update-system.sh)
#   ./ps5-tools.sh --update   rebuild from the latest source
#   ./ps5-tools.sh detect     exit 0 on PS5 hardware
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="https://github.com/ps5-linux/ps5-linux-tools"
BIN=/usr/local/sbin/ps5_control

is_ps5() {
  [[ -e /dev/icc || -d /sys/devices/platform/ps5-fan ]] && return 0
  uname -r | grep -qi ps5 && return 0
  pacman -Qq 2>/dev/null | grep -qx 'linux-ps5' && return 0
  grep -qi 'playstation 5\|sony interactive' /sys/class/dmi/id/{product_name,sys_vendor,board_vendor} 2>/dev/null
}

case "${1:-}" in
  detect) is_ps5 && exit 0 || exit 1 ;;
  --update) FORCE=1 ;;
  "") FORCE=0 ;;
  *) echo "usage: $0 [--update | detect]"; exit 2 ;;
esac
is_ps5 || { echo "not a PS5: nothing to do"; exit 0; }
[[ $EUID -eq 0 ]] || exec sudo "$0" "$@"

if [[ -x "$BIN" ]] && ((!FORCE)); then
  echo "ps5_control already installed ($BIN)"
  exit 0
fi

NEED=()
for p in gcc make git; do pacman -T "$p" >/dev/null 2>&1 || NEED+=("$p"); done
if ((${#NEED[@]})); then
  source "$HERE/packages-safe.sh"     # never lets pacman pull in or swap a kernel
  safe_install "${NEED[@]}"
fi
for c in gcc make git; do command -v "$c" >/dev/null || { echo "ps5_control: $c is missing, skipped"; exit 0; }; done

WORK=$(mktemp -d /tmp/ps5-linux-tools.XXXXXX)
trap 'rm -rf "$WORK"' EXIT
if ! git clone -q --depth 1 "$REPO" "$WORK/src"; then
  echo "ps5_control: couldn't download $REPO (offline?), skipped"
  exit 0
fi
chmod 755 "$WORK"
chown -R nobody: "$WORK/src"          # built as an unprivileged user, installed as root
if ! runuser -u nobody -- make -C "$WORK/src" ps5_control >/dev/null 2>"$WORK/err"; then
  echo "ps5_control: build failed:"; tail -5 "$WORK/err"; exit 0
fi
install -Dm755 "$WORK/src/ps5_control" "$BIN"
for u in ps5fan ps5boost; do
  # installed so they're there to turn on; enabling is left to you
  [[ -f "$WORK/src/systemd/$u.service" && ! -f /etc/systemd/system/$u.service ]] && \
    install -Dm644 "$WORK/src/systemd/$u.service" "/etc/systemd/system/$u.service"
done
systemctl daemon-reload 2>/dev/null || true
echo "ps5_control installed ($(git -c safe.directory="*" -C "$WORK/src" rev-parse --short HEAD)); fan/boost services left off"
