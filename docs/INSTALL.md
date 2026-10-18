# Installing Crossbar

Crossbar ships as a live ISO. You can run it live (nothing is installed) or use the
built-in installer to put it on a disk permanently.

- [1. Build the ISO](#1-build-the-iso)
- [2. Virtual machine with virt-manager](#2-virtual-machine-with-virt-manager)
- [3. Bare metal](#3-bare-metal)
- [Troubleshooting](#troubleshooting)

> Prototype software. The installer **erases the whole disk you choose** and does not
> support dual-boot. Use a spare disk or a VM.

## 1. Build the ISO

There are no prebuilt ISOs yet (they're ~3 GB, over GitHub's release-asset limit).

On Arch, CachyOS, EndeavourOS or Manjaro:

```bash
git clone https://github.com/Brenyd/crossbar.git
cd crossbar
./build-iso.sh
```

On any other distro with Docker or Podman:

```bash
./build-in-docker.sh
```

You need about 15 GB free and a decent connection (it downloads ~3 GB of packages).
The result is `out/crossbar-YYYY.MM.DD-x86_64.iso`.

## 2. Virtual machine with virt-manager

### Host setup (once)

```bash
# Arch / CachyOS
sudo pacman -S --needed virt-manager qemu-full libvirt edk2-ovmf dnsmasq
sudo systemctl enable --now libvirtd
sudo usermod -aG libvirt "$USER"     # log out and back in afterwards
```

On Fedora: `sudo dnf install @virtualization`. On Ubuntu/Debian:
`sudo apt install virt-manager qemu-system-x86 ovmf libvirt-daemon-system`.

### Create the VM

1. **File › New Virtual Machine › Local install media**, browse to the ISO.
   If asked for the OS, type **Arch Linux**.
2. **Memory:** 8192 MB (6144 minimum). **CPUs:** 4 or more.
3. **Storage:** create a disk of **64 GB** or more.
4. Name it `crossbar` and tick **Customize configuration before install**, then **Finish**.
5. In the configuration window:
   - **Overview › Firmware:** pick **UEFI** (the plain `OVMF_CODE` entry, *not* `secboot`). Required for installing.
   - **Video:** model **Virtio**, tick **3D acceleration**.
   - **Display Spice:** Listen type **None**, tick **OpenGL**, pick your GPU.
     (If 3D fails on your host, untick both; the shell still runs with software rendering, just slower.)
   - **Sound:** model **ich9** (or HDA).
   - **Controller (optional):** **Add Hardware › USB Host Device**, choose your gamepad.
6. **Begin Installation.** Crossbar boots straight into the XMB.

### Option A — keep it live, with a persistent games disk

Give the disk the serial number Crossbar looks for, and it will format it on first
boot (only if it's blank) and keep games, Steam and settings there across reboots:

- Before step 6 (or with the VM off): select **VirtIO Disk 1 › Advanced options › Serial number**, enter `crossbar-games`, **Apply**.

Without this, the live system keeps downloads in RAM and loses them on shutdown.

### Option B — install to the virtual disk

1. In the XMB go to **Settings › Install to Disk** (or press **Ctrl+Alt+T** and run `sudo crossbar-install`).
2. Choose `/dev/vda`, type it again to confirm, set a password and time zone.
3. When it finishes, shut down, then in the VM's settings remove the ISO from **SATA CDROM 1**
   (or move **VirtIO Disk 1** to the top of **Boot Options**). Start the VM.

If you set the `crossbar-games` serial for Option A first, that's fine — the installer erases the disk anyway.

### Without virt-manager

`./run-vm.sh` starts the ISO straight in QEMU with a 64 GB games disk already attached.

## 3. Bare metal

### What you need

- x86_64 PC with **UEFI** firmware, 8 GB+ RAM, 64 GB+ disk you can erase.
- **AMD or Intel graphics** work out of the box. NVIDIA isn't included yet: after installing,
  run `sudo pacman -S nvidia-open-dkms lib32-nvidia-utils linux-headers` (Turing / GTX 16-series or newer) and reboot.
- Internet. **Ethernet is easiest**; Wi-Fi works but needs one command (below).
- A USB stick of 8 GB+ (it will be erased).

### Write the USB stick

Linux:

```bash
lsblk                                   # find the stick, e.g. /dev/sdb — double-check it!
sudo dd if=out/crossbar-*.iso of=/dev/sdX bs=4M status=progress oflag=sync
```

Windows: **Rufus** (choose **DD image mode** when asked) or **balenaEtcher**.
**Ventoy** also works: copy the ISO onto the Ventoy drive.

### Boot it

1. In your firmware settings (Del/F2 at power-on) **disable Secure Boot**.
2. Plug the stick in and open the boot menu (usually **F12**, **F11**, **F8** or **Esc**), pick the USB entry (the UEFI one).
3. Crossbar starts in the XMB as a live system.

To keep games between live sessions on a real machine, label an existing ext4 partition
`CROSSBAR_GAMES` (`sudo e2label /dev/sdXN CROSSBAR_GAMES`) and Crossbar mounts it at `~/Games`.
It never formats real disks on its own.

### Install

1. Wi-Fi only: press **Ctrl+Alt+T** and run:
   ```bash
   iwctl
   # then inside iwctl:
   station wlan0 scan
   station wlan0 get-networks
   station wlan0 connect "Your Network"
   exit
   ```
2. **Settings › Install to Disk** (or `sudo crossbar-install` in the terminal).
3. Pick the disk, type its name again to confirm, set a password and time zone.
4. When it says *Done*, reboot and remove the USB stick.

The installed system autologins to the XMB, uses NetworkManager for networking
(`nmtui` in the terminal for Wi-Fi), and updates like any Arch system: `sudo pacman -Syu`.

What the installer creates: a 1 GiB EFI partition and an ext4 root filling the rest,
systemd-boot, user `player` with your password, and the same packages as the ISO.

## Troubleshooting

| Problem | Fix |
|---|---|
| Black screen in virt-manager | Turn off 3D acceleration and OpenGL (Video + Display Spice). |
| "This installer needs a UEFI boot" | Set Firmware to UEFI (VM) or disable Legacy/CSM boot (bare metal). |
| USB stick won't boot | Disable Secure Boot; use the UEFI entry in the boot menu; re-write with DD mode. |
| Controller not detected in the VM | Add it as a USB Host Device; Bluetooth pads should be paired on the host and passed through as USB, or use a cable. |
| Need a terminal | Ctrl+Alt+T. Logs: `~/.cache/crossbard.log`, `~/.cache/sway.log`. |
| Stuck in an app | Super+Esc (or the Guide/PS button) returns to the XMB; Ctrl+Alt+Q closes the focused app. |
