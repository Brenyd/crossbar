#!/usr/bin/env bash
# Install Crossbar on an existing CachyOS / Arch install (for example CachyOS on a PS5)
# and make it what the machine boots into.
#
#   git clone https://github.com/Brenyd/crossbar.git && cd crossbar && ./install-cachyos.sh
#
# What it does:
#   1. installs yay if it's missing, then the packages Crossbar needs (repos first, AUR via yay)
#   2. installs Crossbar itself (same as update-system.sh: /usr/lib/crossbar, services, rules)
#   3. makes tty1 autologin (or a login manager, if you use one) start Crossbar instead of your
#      usual session; your autologin and startup scripts are kept, Plasma stays installed
#      Graphics drivers, kernel, bootloader and NetworkManager are not touched.
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
  for f in "$UHOME/.bash_profile" "$UHOME/.profile" "$UHOME/.zprofile"; do
    [[ -f "$f" ]] && sed -i '/^# >>> crossbar (install-cachyos.sh) >>>$/,/^# <<< crossbar <<<$/d' "$f"
  done
  rm -f "$UHOME/.config/fish/conf.d/00-crossbar.fish" "$UHOME/.config/crossbar/boot-session"
  echo "Crossbar no longer starts at boot; your previous login setup is back."
  echo "(Crossbar is still installed: pick the \"Crossbar\" session on the login screen to use it.)"
  exit 0
fi

command -v pacman >/dev/null || { echo "This needs an Arch-based system (pacman)."; exit 1; }
echo "Installing Crossbar for $U ($UHOME); login manager: $DM"

# ---- 1. packages ----------------------------------------------------------------------------
step "Installing yay (AUR helper)"
if command -v yay >/dev/null; then
  echo "yay already installed"
elif pacman -S --needed --noconfirm yay 2>/dev/null; then
  echo "yay installed from the repos"            # CachyOS ships it in its own repo
else
  # Plain Arch: build the prebuilt yay-bin from the AUR (no Go toolchain needed).
  pacman -S --needed --noconfirm base-devel git
  B=$(sudo -u "$U" mktemp -d)
  sudo -u "$U" git clone --depth 1 https://aur.archlinux.org/yay-bin.git "$B/yay-bin"
  ( cd "$B/yay-bin" && sudo -u "$U" makepkg --noconfirm )     # build as you (makepkg refuses root)
  pacman -U --noconfirm "$B"/yay-bin/yay-bin-*.pkg.tar.zst
  rm -rf "$B"
fi
command -v yay >/dev/null || warn "yay couldn't be installed; AUR-only packages will be skipped"

step "Installing packages"
if ! grep -q '^\[multilib\]' /etc/pacman.conf; then
  printf '\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n' >>/etc/pacman.conf
  NEED_SYNC=1
fi
# Installing from an out-of-date package database is a "partial upgrade" (breaks things on Arch),
# so the system must be up to date first; this only refreshes the database if multilib was just added.
if [[ -n "${NEED_SYNC:-}" ]]; then pacman -Sy --noconfirm >/dev/null; fi
# The ISO's list minus things only a VM or the live ISO needs (software rendering, VM agent).
# Graphics drivers are never touched: your system already has a working display stack
# (on a PS5 that can be custom builds), and installing the stock ones could replace them.
SKIP='^(spice-vdagent|mesa|lib32-mesa|vulkan-.*|lib32-vulkan-.*)$'
mapfile -t PKGS < <(grep -vE '^\s*(#|$)' "$HERE/iso/packages.extra" | sed 's/\s.*//' | grep -vE "$SKIP")
MISSING=()
# pacman -T also counts packages "provided" by something else (e.g. a -git build) as present
for p in "${PKGS[@]}"; do pacman -T "$p" >/dev/null 2>&1 || MISSING+=("$p"); done
source "$HERE/packages-safe.sh"
if ((${#MISSING[@]})); then
  safe_install "${MISSING[@]}"
else
  FAILED=(); KERNEL_SKIPPED=()
  echo "all packages present"
fi
if ((${#FAILED[@]})); then
  AUR=$(command -v yay || command -v paru || true)
  if [[ -n "$AUR" ]]; then
    echo "not in the repos, trying the AUR with $(basename "$AUR"): ${FAILED[*]}"
    # AUR helpers must run as the user, never root
    # (it may ask for your password once more, for the final pacman step)
    sudo -u "$U" "$AUR" -S --needed --noconfirm --sudoloop "${FAILED[@]}" || true
  fi
  STILL=()
  for p in "${FAILED[@]}"; do pacman -T "$p" >/dev/null 2>&1 || STILL+=("$p"); done
  ((${#STILL[@]})) && warn "couldn't install: ${STILL[*]} — Crossbar works without them, but some features won't"
fi
((${#KERNEL_SKIPPED[@]})) && warn "not installed because they'd need a different kernel: ${KERNEL_SKIPPED[*]} (your kernel was left alone)"

# ---- 2. Crossbar itself -----------------------------------------------------------------------
step "Installing Crossbar"
for g in wheel input video audio render; do
  getent group "$g" >/dev/null && usermod -aG "$g" "$U"
done
CROSSBAR_SKIP_PACKAGES=1 CROSSBAR_NO_RESTART=1 SUDO_USER="$U" "$HERE/update-system.sh"
mkdir -p "$UHOME/Games" && chown "$U:" "$UHOME/Games"

# ---- 3. boot straight into Crossbar ---------------------------------------------------------------
HOOK_BEGIN="# >>> crossbar (install-cachyos.sh) >>>"
HOOK_END="# <<< crossbar <<<"
SHELL_NAME=$(basename "$(getent passwd "$U" | cut -d: -f7)")

add_hook() {   # put the hook at the TOP of a login file, so it runs before your own autostart
  local f="$1" body="$2"
  sudo -u "$U" touch "$f"
  remove_hook "$f"
  { printf '%s\n%s\n%s\n' "$HOOK_BEGIN" "$body" "$HOOK_END"; cat "$f"; } >"$f.crossbar-tmp"
  cat "$f.crossbar-tmp" >"$f" && rm -f "$f.crossbar-tmp"
  echo "  added a 4-line block at the top of $f"
}
remove_hook() {
  [[ -f "$1" ]] && sed -i "/^$HOOK_BEGIN\$/,/^$HOOK_END\$/d" "$1" || true
}

if ((AUTOLOGIN)); then
  step "Making Crossbar the session this machine boots into"
  if [[ "$DM" == sddm || "$DM" == plasmalogin ]] && systemctl is-enabled --quiet display-manager.service 2>/dev/null; then
    # A zzz-crossbar.conf drop-in sorts after the distro's own autologin files
    # (CachyOS handheld writes zz-steamos-autologin.conf), so it wins without editing them.
    echo '{"session":"crossbar","uid":'"$UID_U"'}' | python3 /usr/lib/crossbar/admin.py boot-session
    echo "$DM will log $U straight into Crossbar (no login screen)."
  else
    # TTY autologin (no login manager). Your getty autologin and your own startup script stay
    # exactly as they are; a small block at the top of your login file starts Crossbar on tty1
    # when ~/.config/crossbar/boot-session says "crossbar", and otherwise does nothing, so your
    # own setup (gaming mode / Plasma) runs as before.
    if systemctl cat getty@tty1.service 2>/dev/null | grep -q -- '--autologin'; then
      echo "TTY autologin found on tty1: keeping it."
    else
      warn "No TTY autologin on tty1 found. Crossbar will start when $U logs in on tty1."
    fi
    sudo -u "$U" mkdir -p "$UHOME/.config/crossbar"
    echo crossbar | sudo -u "$U" tee "$UHOME/.config/crossbar/boot-session" >/dev/null
    SH_HOOK='if [ -z "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ] && [ "$(tty)" = /dev/tty1 ] && [ "$(cat "$HOME/.config/crossbar/boot-session" 2>/dev/null)" = crossbar ]; then
  exec /usr/local/bin/crossbar-session
fi'
    case "$SHELL_NAME" in
      fish)
        F="$UHOME/.config/fish/conf.d/00-crossbar.fish"     # conf.d runs before config.fish; 00 runs first
        sudo -u "$U" mkdir -p "$(dirname "$F")"
        cat >"$F" <<'EOF'
# Added by Crossbar's install-cachyos.sh: start Crossbar on tty1 when it's the chosen session.
# Remove with ./install-cachyos.sh --uninstall (or delete this file).
if status is-login; and test -z "$WAYLAND_DISPLAY$DISPLAY"; and test (tty) = /dev/tty1
    if string match -q crossbar -- (cat ~/.config/crossbar/boot-session 2>/dev/null)
        exec /usr/local/bin/crossbar-session
    end
end
EOF
        chown "$U:" "$F"; echo "  added $F"
        ;;
      zsh) add_hook "$UHOME/.zprofile" "$SH_HOOK" ;;
      *)   F="$UHOME/.bash_profile"; [[ -f "$F" ]] || F="$UHOME/.profile"; add_hook "$F" "$SH_HOOK" ;;
    esac
    # Where your current autostart lives (if it's in a system-wide file it runs before the hook).
    FOUND=$(grep -lsE 'gamescope|startplasma|steamos-session|start-hyprland|sway' /etc/profile /etc/profile.d/* \
            /etc/fish/config.fish /etc/fish/conf.d/* /etc/zsh/zprofile 2>/dev/null || true)
    # ...or started by systemd instead of a login shell (getty override running it directly,
    # or a service), which the hook can't come before either.
    GETTY=$(systemctl cat getty@tty1.service 2>/dev/null | grep -E '^ExecStart=.*(gamescope|steam|startplasma)' || true)
    UNITS=$(grep -lsE 'gamescope|steamos-session' /etc/systemd/system/*.service \
            "$UHOME"/.config/systemd/user/*.service 2>/dev/null || true)
    [[ -n "$GETTY" ]] && FOUND="$FOUND getty@tty1 (its ExecStart starts the session directly)"
    [[ -n "$UNITS" ]] && FOUND="$FOUND $UNITS"
    if [[ -n "$FOUND" ]]; then
      warn "Your session autostart seems to be in a system-wide file that runs before Crossbar's hook:"
      warn "  $FOUND"
      warn "If you still boot into your old session, make that script skip when"
      warn "~/.config/crossbar/boot-session contains 'crossbar' (or tell Crossbar's author)."
    fi
  fi
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
