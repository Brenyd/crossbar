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

## 0.9
- [x] Crossbar cleans up after itself: a new session stops leftovers from the last one; the backend exits with sway
- [x] Quick Menu must confirm it's on screen, otherwise the controller is handed back (no more invisible menu)
- [x] Settings › System: Restart Crossbar / Exit Crossbar
- [x] Power in the Quick Menu is its own page with Cancel selected; power confirms default to No
- [x] App switcher in the Quick Menu: switch, close, force close
- [x] Game mode: the menu closes while a game runs to free memory; Quick Menu, music, Spotify, voice keep working
- [x] Display: screens that report no modes get common sizes (custom modes), rate shown as Auto instead of 0.00
- [x] IPTV: player user agent, tries the usual Xtream ports, clearer errors
- [x] Discord: explains the App Testers step when Discord refuses with invalid_scope

## 0.9.1
- [x] Music/Spotify play-pause shows "Now Playing · song" (Spotify's new non-JSON replies broke it)
- [x] Steam: start Steam first, wait through updates/sign-in, then send the game
- [x] IPTV on demand: all episode-list shapes, movie extension lookup, paging, stream reconnects
- [x] Update Crossbar restarts in place instead of exiting the session
- [x] install-cachyos.sh: install on CachyOS/Arch (PS5), boot straight into Crossbar, Switch to Desktop / Return to Crossbar

## 0.9.2
- [x] Per-app volume in the Quick Menu (and Settings › Sound › App Volume)
- [x] Button glyphs: Automatic / Xbox / PlayStation / Nintendo, everywhere incl. video playback and remapping

## 0.9.3
- [x] GOG: launch targets that are Windows shortcuts (.lnk) resolved; fixes itself for installed games
- [x] GOG/Epic: real error message when a game quits right away (log in ~/.cache/crossbar-games.log)
- [x] NAS: test the connection before saving, plain-language reasons, SMB1 fallback, any address format
- [x] Steam: leaves Big Picture after a game; never left showing behind the menu (no double input)
- [x] Session: one supervisor at a time, never a black screen (error screen + retry), logged restarts
- [x] PS5 hardware: temperatures, overlay HUD, fan target, fan mode/boost, front light
- [x] PlayStation glyphs drawn as centred shapes

## 0.10
- [x] Emulation: ROMs by system, emulator installs (Flathub/AppImage), BIOS checks, defaults, RetroAchievements
- [x] Trophies: RetroAchievements by console, Steam achievements
- [x] On-screen keyboard: QWERTY, in Crossbar and system-wide (input method + Quick Menu), closes on real keyboard/mouse
- [x] Discord rebuilt on its own web client: voice channels in Social without a developer app
- [x] XMB spacing: rows below a big highlighted tile, rows under the button hints

## 0.11
- [x] Quick Menu grouped into pages (Sound, Performance, Settings); long pages scroll instead of overflowing
- [x] Settings column grouped (Display & Sound, Network & Bluetooth, Games & Emulation, Theme & Time, System)
- [x] Trophies at the top of Game
- [x] Discord: voice channels hidden by default, chosen in Settings › Accounts › Discord
- [x] SteamGridDB artwork: change any game's or ROM's picture, fill in missing art
- [x] Frame rate overlay (MangoHud) from the Quick Menu
- [x] PS5: ps5_control built at install/update time (services left off)

## Next

- IPTV extras: EPG (now/next) for live channels, favourites, search.

## Later
- **Other desktop backends** — option to run Crossbar on KDE Plasma (KWin) and use KDE's settings backends
  (kscreen, bluedevil, plasma-nm), or on lighter compositors.
- Trophies/achievements view, friends list, screenshots/video capture.
