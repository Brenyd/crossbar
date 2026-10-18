# Crossbar roadmap

## Now (0.7) — make the basics solid
- [x] Quick Menu as a true overlay above every app (native GTK4 layer-shell window, no web engine)
- [x] Quick Menu on a button combo (Select + Start) so Guide/PS stays with Steam's overlay
- [x] Controller service reads every pad, grabs it while Crossbar/overlay is in front, releases it to games
- [x] Steam Input's virtual pad held during the overlay but never double-read
- [x] Controller mapping works even when only the browser can see the pad (remap fallback)
- [x] Discord voice channels in Social: join / leave / mute / deafen / who's in
- [x] Settings: Network (Wi-Fi on/off, forget), Bluetooth pairing, Date & Time, Game Settings
- [x] Built-in terminal (no separate window), updates and installer run in it
- [x] Game launch handoff: "Starting…" screen, Steam's client window hidden, back to the menu on exit
- [x] Shareable support report
- [ ] **Confirm on real hardware** — overlay, controller grab, YouTube keys (needs a report from a real machine)

## Next
- **Wine / Proton picker** — per-game compatibility tool (Proton-GE, Wine-GE, system Wine) via umu-launcher;
  download/manage versions from Settings › Game Settings.
- **GOG Windows games** — install Windows builds (gogdl / innoextract) and run them through the picked Proton.
- **File browser** — built into the XMB: browse drives, copy / paste / move / rename / delete, with controller.
- **NAS mounts** — Settings › Network › Network Drives: SMB/CIFS and NFS; server, share, user, password,
  mount point; writes a credentials file (0600) and an fstab entry with `x-systemd.automount` so a missing
  NAS never blocks boot.
- **On-screen keyboard** — controller typing for every text field in Crossbar; for other apps a Wayland
  virtual-keyboard (wvkbd); Steam's own keyboard keeps working inside Steam.

## Later
- **IPTV (Xtream Codes)** — log in once in Settings › Media › IPTV; Movies and TV Shows appear under Video,
  Live TV under TV & Video Services; choose which categories/channels show on the XMB; plays in mpv with the
  same controller panel; EPG for live channels.
- **Other desktop backends** — option to run Crossbar on KDE Plasma (KWin) and use KDE's settings backends
  (kscreen, bluedevil, plasma-nm), or on lighter compositors.
- Trophies/achievements view, friends list, screenshots/video capture.
