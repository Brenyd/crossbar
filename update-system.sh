#!/usr/bin/env bash
# Update a running Crossbar system (live ISO or installed) to this version WITHOUT
# rebuilding the ISO: installs new packages, copies Crossbar, installs the system
# services and device rules, then restarts the Crossbar session.
#
#   From Crossbar: Settings › System Settings › Update Crossbar
#   Or in a terminal (Ctrl+Alt+T):
#     curl -L https://github.com/Brenyd/crossbar/archive/refs/heads/main.tar.gz | tar xz
#     cd crossbar-main && ./update-system.sh
#
# On the live ISO the update lasts until reboot (the live system runs from RAM).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ $EUID -eq 0 ]] || exec sudo "$0" "$@"
# The user Crossbar runs as: whoever ran this through sudo, else whoever is at the screen.
U="${SUDO_USER:-}"
if [[ -z "$U" || "$U" == root ]]; then
  U=$(loginctl list-sessions --no-legend 2>/dev/null | awk '$4 ~ /seat/ {print $3; exit}')
fi
[[ -n "$U" && "$U" != root ]] || U=player
UHOME=$(getent passwd "$U" | cut -d: -f6)
echo "Updating Crossbar for user: $U ($UHOME)"

step() { printf '\n\e[1m:: %s\e[0m\n' "$*"; }

step "Installing packages (only what's missing)"
if ! grep -q '^\[multilib\]' /etc/pacman.conf; then
  printf '\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n' >>/etc/pacman.conf
fi
mapfile -t PKGS < <(grep -vE '^\s*(#|$)' "$HERE/iso/packages.extra")
MISSING=()
for p in "${PKGS[@]}"; do pacman -Qq "$p" >/dev/null 2>&1 || MISSING+=("$p"); done
if ((${#MISSING[@]})); then
  echo "installing: ${MISSING[*]}"
  pacman -Sy --needed --noconfirm "${MISSING[@]}"
else
  echo "all packages present"
fi

step "Fetching bundled web libraries (terminal)"
"$HERE/fetch-vendor.sh" || echo "warning: terminal falls back to plain text"

step "Copying Crossbar to /usr/lib/crossbar"
rm -rf /usr/lib/crossbar.new
cp -r "$HERE/shell" /usr/lib/crossbar.new
[[ -d /usr/lib/crossbar/vendor ]] && cp -r /usr/lib/crossbar/vendor /usr/lib/crossbar.new/   # keep legendary
find /usr/lib/crossbar.new -name __pycache__ -prune -exec rm -rf {} +
rm -rf /usr/lib/crossbar.old
[[ -d /usr/lib/crossbar ]] && mv /usr/lib/crossbar /usr/lib/crossbar.old
mv /usr/lib/crossbar.new /usr/lib/crossbar
rm -rf /usr/lib/crossbar.old

step "Installing scripts, session config, services and device rules"
install -m755 "$HERE"/iso/airootfs/usr/local/bin/* /usr/local/bin/
install -Dm644 "$HERE/iso/airootfs/etc/crossbar/sway.conf" /etc/crossbar/sway.conf
install -Dm644 "$HERE/iso/airootfs/etc/udev/rules.d/70-crossbar-input.rules" /etc/udev/rules.d/70-crossbar-input.rules
install -Dm644 "$HERE/iso/airootfs/etc/modules-load.d/crossbar-uinput.conf" /etc/modules-load.d/crossbar-uinput.conf
install -Dm644 "$HERE/iso/airootfs/etc/systemd/system/crossbar-inputd.service" /etc/systemd/system/crossbar-inputd.service
install -Dm644 "$HERE/iso/airootfs/etc/systemd/system/crossbar-setup.service" /etc/systemd/system/crossbar-setup.service
install -Dm644 "$HERE/iso/airootfs/etc/polkit-1/rules.d/50-crossbar.rules" /etc/polkit-1/rules.d/50-crossbar.rules
modprobe uinput || true
udevadm control --reload
udevadm trigger --subsystem-match=input --subsystem-match=misc --action=change
systemctl daemon-reload
systemctl enable crossbar-inputd.service crossbar-setup.service bluetooth.service >/dev/null 2>&1 || true
systemctl start bluetooth.service >/dev/null 2>&1 || true
systemctl restart crossbar-inputd.service
sleep 1
systemctl is-active --quiet crossbar-inputd && echo "crossbar-inputd: running" || { echo "crossbar-inputd FAILED:"; journalctl -u crossbar-inputd -n 15 --no-pager; }

step "Restarting the Crossbar session"
SOCK=$(ls /run/user/"$(id -u $U)"/sway-ipc.*.sock 2>/dev/null | head -1 || true)
if [[ -n "$SOCK" ]]; then
  # stop the old backend so the new one starts with the session
  pkill -u "$U" -f "/usr/lib/crossbar/server.py" || true
  pkill -u "$U" -f "/usr/lib/crossbar/overlay.py" || true
  sudo -u "$U" SWAYSOCK="$SOCK" swaymsg exit >/dev/null 2>&1 || true
  echo "Crossbar will come back in a few seconds."
  ( sleep 15; sudo -u "$U" HOME="$UHOME" /usr/local/bin/crossbar-doctor >"$UHOME/crossbar-report.txt" 2>&1 ) &
  echo "A report will be saved to $UHOME/crossbar-report.txt (run: cat ~/crossbar-report.txt)"
else
  echo "Not in a Crossbar session right now; log in on tty1 to start it."
fi
