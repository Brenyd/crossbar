#!/usr/bin/env bash
# Boot the Crossbar ISO in QEMU with a persistent 64 GB games disk.
#   ./run-vm.sh [path/to.iso]
# Env: NOGL=1 (no virgl 3D), RAM=8G, CPUS=4, UEFI=1, PAD=vendor:product (pass a USB controller through)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ISO="${1:-$(ls -t "$HERE"/out/crossbar-*.iso 2>/dev/null | head -1)}"
[[ -f "$ISO" ]] || { echo "No ISO found. Build one with ./build-iso.sh first."; exit 1; }

DISK="$HERE/games.qcow2"
[[ -f "$DISK" ]] || qemu-img create -f qcow2 "$DISK" 64G

args=(
  -enable-kvm -cpu host -smp "${CPUS:-4}" -m "${RAM:-8G}" -machine q35
  -cdrom "$ISO" -boot d
  -drive if=none,id=games,file="$DISK",format=qcow2
  -device virtio-blk-pci,drive=games,serial=crossbar-games
  -nic user,model=virtio-net-pci
  -audiodev pa,id=snd -device intel-hda -device hda-duplex,audiodev=snd
  -device qemu-xhci -device usb-tablet -device usb-kbd
)
if [[ -n "${NOGL:-}" ]]; then
  args+=(-device virtio-vga -display gtk)
else
  args+=(-device virtio-vga-gl -display gtk,gl=on)
fi
if [[ -n "${UEFI:-}" ]]; then
  args+=(-drive if=pflash,format=raw,readonly=on,file=/usr/share/edk2/x64/OVMF_CODE.4m.fd)
fi
if [[ -n "${PAD:-}" ]]; then   # e.g. PAD=054c:0ce6 for a DualSense (see `lsusb`)
  args+=(-device "usb-host,vendorid=0x${PAD%%:*},productid=0x${PAD##*:}")
fi

exec qemu-system-x86_64 "${args[@]}"
