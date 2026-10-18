#!/usr/bin/env bash
# Install Crossbar on an existing CachyOS / Arch install (for example CachyOS on a PS5)
# and make it what the machine boots into.
#
#   git clone https://github.com/Brenyd/crossbar.git && cd crossbar && ./install-cachyos.sh
#
# What it does:
#   1. installs the packages Crossbar needs (pacman, then paru/yay for anything not in the repos)
#   2. installs Crossbar itself (same as update-system.sh: /usr/lib/crossbar, services, rules)
#   3. adds a "Crossbar" login session and sets the login manager to log you straight into it
#      (no login screen; Plasma stays installed but doesn't run)
#   4. adds "Return to Crossbar" to the Plasma app menu; Crossbar gets Settings › System ›
#      Switch to Desktop
#
# Nothing is erased: your kernel, bootloader, desktop and Steam gaming-mode setup are left
# installed. Undo with:  ./install-cachyos.sh --uninstall   (restores your previous login setup)
#
# Options:
#   --no-autologin   install, but don't change what boots (pick "Crossbar" on the login screen)
#   --uninstall      stop booting into Crossbar (files stay; run update-system.sh to update)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTOLOGIN=1
case "${1:-}" in
  --no-autologin) AUTOLOGIN=0 ;;
  --uninstall) UNINSTALL=1 ;;
  "") ;;
  *) echo "usage: $0 [--no-autologin | --uninstall]"; exit 2 ;;
esac

[[ $EUID -eq 0 ]] || exec sudo "$0" "$@"
U="${SUDO_USER:-}"
if [[ -z "$U" || "$U" == root ]]; then
  echo "Run this as your normal user (it uses sudo itself), not as root."; exit 1
fi
UHOME=$(getent passwd "$U" | cut -d: -f6)
UID_U=$(id -u "$U")
step() { printf '\n\e[1;36m:: %s\e[0m\n' "$*"; }
warn() { printf '\e[1;33m!! %s\e[0m\n' "$*"; }

DM=$(basename "$(readlink -f /etc/systemd/system/display-manager.service 2>/dev/null || echo none)" .service)
case "$DM" in sddm*) DM=sddm ;; plasmalogin*) DM=plasmalogin ;; esac

# ---- uninstall ------------------------------------------------------------------------------
if [[ -n "${UNINSTALL:-}" ]]; then
  rm -f "/etc/sddm.conf.d/zzz-crossbar.conf" "/etc/plasmalogin.conf.d/zzz-crossbar.conf"
  if [[ -f /etc/greetd/config.toml.crossbar-backup ]]; then
    mv /etc/greetd/config.toml.crossbar-backup /etc/greetd/config.toml
  fi
  echo "Crossbar no longer starts at boot; your previous login setup is back."
  echo "(Crossbar is still installed: pick the \"Crossbar\" session on the login screen to use it.)"
  exit 0
fi

command -v pacman >/dev/null || { echo "This needs an Arch-based system (pacman)."; exit 1; }
echo "Installing Crossbar for $U ($UHOME); login manager: $DM"

# ---- 1. packages ----------------------------------------------------------------------------
step "Installing packages"
if ! grep -q '^\[multilib\]' /etc/pacman.conf; then
  printf '\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n' >>/etc/pacman.conf
  NEED_SYNC=1
fi
# Installing from an out-of-date package database is a "partial upgrade" (breaks things on Arch),
# so the system must be up to date first; this only refreshes the database if multilib was just added.
if [[ -n "${NEED_SYNC:-}" ]]; then pacman -Sy --noconfirm >/dev/null; fi
# The ISO's list minus things only a VM or the live ISO needs (software rendering, VM agent).
SKIP='^(spice-vdagent|vulkan-swrast|lib32-vulkan-swrast)$'
mapfile -t PKGS < <(grep -vE '^\s*(#|$)' "$HERE/iso/packages.extra" | sed 's/\s.*//' | grep -vE "$SKIP")
MISSING=()
for p in "${PKGS[@]}"; do pacman -Qq "$p" >/dev/null 2>&1 || MISSING+=("$p"); done
FAILED=()
if ((${#MISSING[@]})); then
  echo "installing: ${MISSING[*]}"
  if ! pacman -S --needed --noconfirm "${MISSING[@]}"; then
    # one unknown name fails the whole batch: retry one by one and collect what's not in the repos
    for p in "${MISSING[@]}"; do
      pacman -Qq "$p" >/dev/null 2>&1 && continue
      pacman -S --needed --noconfirm "$p" >/dev/null 2>&1 || FAILED+=("$p")
    done
  fi
else
  echo "all packages present"
fi
if ((${#FAILED[@]})); then
  AUR=$(command -v paru || command -v yay || true)
  if [[ -n "$AUR" ]]; then
    echo "not in the repos, trying the AUR with $(basename "$AUR"): ${FAILED[*]}"
    # AUR helpers must run as the user, never root
    sudo -u "$U" "$AUR" -S --needed --noconfirm "${FAILED[@]}" || true
  fi
  STILL=()
  for p in "${FAILED[@]}"; do pacman -Qq "$p" >/dev/null 2>&1 || STILL+=("$p"); done
  ((${#STILL[@]})) && warn "couldn't install: ${STILL[*]} — Crossbar works without them, but some features won't"
fi

# ---- 2. Crossbar itself -----------------------------------------------------------------------
step "Installing Crossbar"
for g in wheel input video audio render; do
  getent group "$g" >/dev/null && usermod -aG "$g" "$U"
done
CROSSBAR_SKIP_PACKAGES=1 CROSSBAR_NO_RESTART=1 SUDO_USER="$U" "$HERE/update-system.sh"
mkdir -p "$UHOME/Games" && chown "$U:" "$UHOME/Games"

# ---- 3. boot straight into Crossbar ---------------------------------------------------------------
if ((AUTOLOGIN)); then
  step "Making Crossbar the session this machine boots into"
  case "$DM" in
    sddm|plasmalogin)
      # A zzz-crossbar.conf drop-in sorts after the distro's own autologin files
      # (CachyOS handheld writes zz-steamos-autologin.conf), so it wins without editing them.
      echo '{"session":"crossbar","uid":'"$UID_U"'}' | python3 /usr/lib/crossbar/admin.py boot-session
      echo "$DM will log $U straight into Crossbar (no login screen)."
      ;;
    none|getty*)
      # No login manager: use greetd to start Crossbar on boot, with a login prompt as fallback.
      pacman -S --needed --noconfirm greetd
      [[ -f /etc/greetd/config.toml && ! -f /etc/greetd/config.toml.crossbar-backup ]] && \
        cp /etc/greetd/config.toml /etc/greetd/config.toml.crossbar-backup
      cat >/etc/greetd/config.toml <<EOF
[terminal]
vt = 1

[default_session]
command = "agreety --cmd /usr/local/bin/crossbar-session"

[initial_session]
command = "/usr/local/bin/crossbar-session"
user = "$U"
EOF
      systemctl enable greetd.service
      echo "greetd will start Crossbar for $U at boot."
      ;;
    *)
      warn "Login manager '$DM' isn't set up automatically. Choose the \"Crossbar\" session on its"
      warn "login screen and turn on automatic login for $U in its settings."
      ;;
  esac
fi

# ---- 4. hide the boot text (optional, only when it's safe to do) -------------------------------------
# The PS5 boots through its own loader, so the kernel command line isn't touched here.
# A quiet console during the hand-off to the login manager:
mkdir -p /etc/sysctl.d
echo "kernel.printk = 3 3 3 3" >/etc/sysctl.d/20-crossbar-quiet.conf

step "Done"
cat <<EOF
Crossbar is installed. Reboot to start it:   sudo reboot

  • Plasma desktop: Settings › System › Switch to Desktop (in Crossbar)
  • Back to Crossbar from the desktop: app menu › "Return to Crossbar"
  • Update later: Settings › System › Update Crossbar
  • Stop booting into Crossbar: ./install-cachyos.sh --uninstall
EOF
