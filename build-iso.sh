#!/usr/bin/env bash
# Build the Crossbar live ISO with archiso. Run on Arch / CachyOS (or use build-in-docker.sh).
#   ./build-iso.sh            -> out/crossbar-YYYY.MM.DD-x86_64.iso
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${OUT:-$HERE/out}"
WORK="${WORK:-/var/tmp/crossbar-build}"

if [[ $EUID -ne 0 ]]; then exec sudo -E OUT="$OUT" WORK="$WORK" "$0" "$@"; fi

pacman -Q archiso python-pip >/dev/null 2>&1 || pacman -S --needed --noconfirm archiso python-pip

PROFILE="$WORK/profile"
rm -rf "$WORK"
mkdir -p "$WORK"

echo ":: Starting from archiso's releng profile"
cp -r /usr/share/archiso/configs/releng "$PROFILE"
rm -f "$PROFILE/airootfs/etc/systemd/system/getty@tty1.service.d/autologin.conf"   # releng autologins root

echo ":: Overlaying Crossbar files"
cp -rT "$HERE/iso/airootfs" "$PROFILE/airootfs"
mkdir -p "$PROFILE/airootfs/usr/lib/crossbar"
cp -r "$HERE/shell/." "$PROFILE/airootfs/usr/lib/crossbar/"
find "$PROFILE/airootfs/usr/lib/crossbar" -name __pycache__ -prune -exec rm -rf {} +
mkdir -p "$PROFILE/airootfs/etc/systemd/system/multi-user.target.wants"
ln -sf /etc/systemd/system/crossbar-setup.service \
  "$PROFILE/airootfs/etc/systemd/system/multi-user.target.wants/crossbar-setup.service"

echo ":: Vendoring legendary (Epic Games CLI, not in the official repos)"
pip install --quiet --no-deps --no-compile --target "$PROFILE/airootfs/usr/lib/crossbar/vendor" legendary-gl
cat >"$PROFILE/airootfs/usr/local/bin/legendary" <<'EOF'
#!/bin/sh
PYTHONPATH=/usr/lib/crossbar/vendor exec python3 -c 'import sys; from legendary.cli import main; sys.exit(main())' "$@"
EOF

echo ":: Packages (+ multilib for Steam)"
cat "$HERE/iso/packages.extra" >>"$PROFILE/packages.x86_64"
install -Dm644 "$HERE/iso/packages.extra" "$PROFILE/airootfs/usr/share/crossbar/packages.txt"   # for crossbar-install
sed -i '/^#\[multilib\]/{s/^#//;n;s/^#//}' "$PROFILE/pacman.conf"
grep -q '^\[multilib\]' "$PROFILE/pacman.conf" || printf '\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n' >>"$PROFILE/pacman.conf"
cp "$PROFILE/pacman.conf" "$PROFILE/airootfs/etc/pacman.conf"   # installed system keeps multilib

echo ":: Branding and permissions"
sed -i -e 's/^iso_name=.*/iso_name="crossbar"/' \
       -e 's/ARCH_/CROSSBAR_/' \
       -e 's/^iso_publisher=.*/iso_publisher="Crossbar"/' \
       -e 's/^iso_application=.*/iso_application="Crossbar Live"/' "$PROFILE/profiledef.sh"
sed -i '/^file_permissions=(/a\
  ["/etc/gshadow"]="0:0:400"\
  ["/etc/sudoers.d/player"]="0:0:440"\
  ["/home/player"]="1000:1000:750"\
  ["/home/player/.bash_profile"]="1000:1000:644"\
  ["/usr/local/bin/crossbar-session"]="0:0:755"\
  ["/usr/local/bin/crossbar-shell"]="0:0:755"\
  ["/usr/local/bin/crossbar-setup"]="0:0:755"\
  ["/usr/local/bin/crossbar-install"]="0:0:755"\
  ["/usr/local/bin/legendary"]="0:0:755"' "$PROFILE/profiledef.sh"

# Bigger RAM overlay (Steam's first-run bootstrap is ~1 GB) and a quiet boot.
find "$PROFILE"/{efiboot,syslinux,grub} -type f \( -name '*.conf' -o -name '*.cfg' \) 2>/dev/null \
  | xargs sed -i 's/archisobasedir=%INSTALL_DIR%/& cow_spacesize=4G quiet loglevel=3/'

echo ":: Building (this downloads ~3 GB of packages)"
mkarchiso -v -w "$WORK/build" -o "$OUT" "$PROFILE"
chown -R "${SUDO_UID:-0}:${SUDO_GID:-0}" "$OUT"
ls -lh "$OUT"/*.iso
