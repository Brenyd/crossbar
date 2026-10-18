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

## 0.8
- [x] Proton / Wine picker (umu-launcher), GE-Proton download manager, per-game tool
- [x] GOG Windows games (innoextract + goggame .info launch tasks); Epic through umu too
- [x] File browser (copy / cut / paste / rename / Trash / delete)
- [x] Network drives: SMB / NFS via a polkit-authorised root helper, fstab automount, root-only credentials
- [x] IPTV (Xtream Codes): Live TV, Movies, TV Shows; choose categories, hide channels
- [x] Steam games via Big Picture, Steam hidden again afterwards; store accounts in Settings
- [x] Discord linking: Discord window brought forward, progress shown, crashes reported

## Next
- **On-screen keyboard** — controller typing for every text field in Crossbar; for other apps a Wayland
  virtual-keyboard (wvkbd); Steam's own keyboard keeps working inside Steam.

- IPTV extras: EPG (now/next) for live channels, favourites, search.

## Later
- **Other desktop backends** — option to run Crossbar on KDE Plasma (KWin) and use KDE's settings backends
  (kscreen, bluedevil, plasma-nm), or on lighter compositors.
- Trophies/achievements view, friends list, screenshots/video capture.
