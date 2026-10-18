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

if [[ -n "${CROSSBAR_SKIP_PACKAGES:-}" ]]; then
  echo "(packages handled by the installer)"
else
step "Installing packages (only what's missing)"
if ! grep -q '^\[multilib\]' /etc/pacman.conf; then
  printf '\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n' >>/etc/pacman.conf
fi
mapfile -t PKGS < <(grep -vE '^\s*(#|$)' "$HERE/iso/packages.extra")
MISSING=()
if ! id player >/dev/null 2>&1; then
  # not the Crossbar ISO: leave the system's graphics drivers alone
  mapfile -t PKGS < <(printf '%s\n' "${PKGS[@]}" | grep -vE '^(spice-vdagent|mesa|lib32-mesa|vulkan-.*|lib32-vulkan-.*)$')
fi
for p in "${PKGS[@]}"; do pacman -T "$p" >/dev/null 2>&1 || MISSING+=("$p"); done
if ((${#MISSING[@]})); then
  source "$HERE/packages-safe.sh"     # never lets pacman pull in or swap a kernel
  safe_install "${MISSING[@]}"
  ((${#FAILED[@]})) && echo "couldn't install: ${FAILED[*]} (Crossbar works without them)"
else
  echo "all packages present"
fi
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
install -Dm644 "$HERE/iso/airootfs/usr/share/polkit-1/actions/org.crossbar.admin.policy" /usr/share/polkit-1/actions/org.crossbar.admin.policy
install -Dm644 "$HERE/iso/airootfs/usr/share/wayland-sessions/crossbar.desktop" /usr/share/wayland-sessions/crossbar.desktop
install -Dm644 "$HERE/iso/airootfs/usr/share/applications/crossbar-return.desktop" /usr/share/applications/crossbar-return.desktop
chmod 755 /usr/lib/crossbar/admin.py /usr/lib/crossbar/inputd.py /usr/lib/crossbar/overlay.py
modprobe uinput || true
udevadm control --reload
udevadm trigger --subsystem-match=input --subsystem-match=misc --action=change
systemctl daemon-reload
systemctl enable crossbar-inputd.service bluetooth.service >/dev/null 2>&1 || true
# the boot setup is only for the Crossbar ISO's "player" user
if id player >/dev/null 2>&1; then systemctl enable crossbar-setup.service >/dev/null 2>&1 || true
else systemctl disable crossbar-setup.service >/dev/null 2>&1 || true; fi
systemctl start bluetooth.service >/dev/null 2>&1 || true
systemctl restart crossbar-inputd.service
sleep 1
systemctl is-active --quiet crossbar-inputd && echo "crossbar-inputd: running" || { echo "crossbar-inputd FAILED:"; journalctl -u crossbar-inputd -n 15 --no-pager; }

if [[ -n "${CROSSBAR_NO_RESTART:-}" ]]; then exit 0; fi
step "Restarting Crossbar"
UID_U=$(id -u "$U")
SOCK=""
for s_ in /run/user/"$UID_U"/sway-ipc.*.sock; do   # the live one (a crashed sway can leave old sockets)
  [[ -S "$s_" ]] && sudo -u "$U" SWAYSOCK="$s_" swaymsg -t get_version >/dev/null 2>&1 && SOCK="$s_" && break
done
if [[ -n "$SOCK" ]]; then
  # Restart Crossbar's pieces *inside* the running session (sway keeps running, so there's
  # no drop to the TTY). This terminal belongs to the backend being restarted, so the restart
  # runs detached and starts a couple of seconds after this script finishes.
  sudo -u "$U" SWAYSOCK="$SOCK" XDG_RUNTIME_DIR="/run/user/$UID_U" setsid -f bash -c '
    exec >>"'"$UHOME"'/.cache/crossbar-shell.log" 2>&1
    echo "$(date "+%F %T") update: restarting Crossbar"
    sleep 2
    swaymsg reload >/dev/null 2>&1                                   # new keybindings / rules
    # the new supervisor takes over: stops the old one and its pieces, then starts everything
    swaymsg exec /usr/local/bin/crossbar-shell
    sleep 10                     # the old backend is still answering for a few seconds
    for i in $(seq 60); do curl -s -m 2 -o /dev/null http://127.0.0.1:7777/api/jobs && break; sleep 1; done
    echo "$(date "+%F %T") update: backend $(curl -s -m 2 -o /dev/null -w "%{http_code}" http://127.0.0.1:7777/api/jobs)"
    sleep 15
    HOME="'"$UHOME"'" /usr/local/bin/crossbar-doctor >"'"$UHOME"'/crossbar-report.txt" 2>&1
  ' </dev/null >/dev/null 2>&1
  echo
  echo "Done. Crossbar restarts in a few seconds (the screen goes dark briefly)."
  echo "A report will be saved to $UHOME/crossbar-report.txt"
else
  echo "Not in a Crossbar session right now; it starts with the new version next time."
fi
