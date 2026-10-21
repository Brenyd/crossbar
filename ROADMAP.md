# Crossbar roadmap

Where Crossbar is going, what's broken right now, and what each version brought.
The details of every change are in [CHANGELOG.md](CHANGELOG.md).

✅ works · ⚠️ shipped, but not working right yet · 🔧 being worked on · 🧪 needs testing on real hardware

---

## Now: fix what's broken

These shipped but don't work properly yet. They come before any new features.

| | Area | What's wrong | Since |
|---|---|---|---|
| 🧪 | **VPN split tunnelling** | VPN apps lost DNS whenever Crossbar restarted (and OpenVPN never had it). Fixed in 1.2.3, with a DNS Through the VPN setting; needs confirming on the PS5 | 1.1 |
| 🧪 | **VPN port forwarding** | Only started on reconnect and gave up after one failure. 1.2.3 starts it straight away, retries, survives restarts, opens the firewall and adds Check Port Forwarding; needs confirming | 1.1 |
| 🧪 | **Torrents through the VPN** | The engine stayed bound to the previous connection's address. 1.2.3 rebinds on every connect; needs confirming | 1.1 |
| 🧪 | **Torrent search plugins** | No results (the DNS problem above). 1.2.3 fixes DNS, adds Sort, and says why when nothing is found; needs confirming | 1.1 |
| 🧪 | **Leak tests** | The torrent test relied on a third-party page; rebuilt in 1.2.3 to check the engine directly. DNS test explains systemd-resolved leaks; needs confirming | 1.1 |
| 🧪 | **Heavy games on the PS5** | Cyberpunk 2077 froze the console while loading, then left a black screen. 1.2.2 adds Memory Guard, the black-screen fix and quieter background work; it needs confirming on the PS5 | 1.2.2 |
| 🧪 | **Quick Menu and controller on every machine** | Overlay, controller hand-off and YouTube keys need reports from more hardware | 0.7 |

## Next

- **More memory for big games:** an optional compressed swap in RAM (zram) set up from Settings,
  undoable, so heavy games have room before Memory Guard has to step in.
- **More console skins:** new looks built on the looks system (see [docs/LOOKS.md](docs/LOOKS.md)),
  from the project or from anyone using the starter template.

---

## Version history

Newest first. Each version lists what it added; ⚠️ marks features that still need work (see *Now* above).

### 1.2 series: two interfaces, and staying out of the game's way

**1.2.9 Alpha**
- 🧪 **TV remotes:** Android TV / SofaBaton / Fire TV remotes, every button mapped and remappable
- 🧪 Media keys control whatever is playing; Channel ± and channel numbers in live TV

**1.2.8 Alpha**
- 🧪 Lutris installs run their commands (lutris-wrapper found, native and Flatpak)
- 🧪 Jackett starts (no more en-US culture crash)
- 🧪 Bluetooth controllers: no double connects, trusted so the PS button connects them, Pair Again

**1.2.7 Alpha**
- 🧪 **Jackett** in Torrents: install, add / configure any tracker from the controller, search through it
- 🧪 **Lutris installers** in Install Apps: community scripts, your own files and discs, every prompt on the TV

**1.2.6 Alpha**
- 🧪 Split tunneling: WireGuard's own packets no longer looped back into the tunnel (VPN apps timed out)
- 🧪 Torrents bound to the VPN (not run as a VPN app); search and leak tests sent from the VPN's address

**1.2.5 Alpha**
- 🧪 Split tunneling: MSS clamping for traffic sent into the VPN (connections hung)
- 🧪 PIA port forwarding tries the server's public address through the tunnel too; clearer check
- 🧪 Search plugins run one by one (community plugins with capitals in their names ran never), with each plugin's status
- ✅ Long highlighted text scrolls so it can be read

**1.2.4 Alpha**
- ✅ Cold boot starts straight in the chosen interface; only that interface is loaded
- ✅ Interface changes in Settings with a menu reload (no live switch, not in the Quick Menu)
- ✅ Smooth Now Playing time and bar in the cross-media bar too

**1.2.3 Alpha**
- 🧪 VPN apps' DNS kept working across Crossbar restarts, and for OpenVPN; **DNS Through the VPN** setting
- 🧪 Port forwarding: instant on/off, retries, survives restarts, same port kept, firewall opened, Check Port Forwarding
- 🧪 Torrents rebind to each new VPN address
- 🧪 Torrent IP leak test rebuilt (no third-party page); clearer DNS leak test
- ✅ **Torrent search sorting**: Seeds, Leechers, File Size, Upload Date, Name, Site; results show their age
- ✅ "Nothing found" explains whether it's DNS, the connection or the plugins

**1.2.2 Alpha**
- ✅ **Memory Guard:** closes a game that runs the console out of memory, instead of letting everything freeze
- ✅ Go to Home and Restart Crossbar bring the menu back after a game, even with its window still around
- ✅ Closing a Steam game ends every Proton process, not just the window
- ✅ The menu goes quiet behind games: animations pause, the backdrop stops, polling slows
- ✅ Lighter background work: cached status checks, a bounded DNS relay, split-rule retries that back off
- ✅ New README with screenshots of both interfaces, and the full reference in [docs/GUIDE.md](docs/GUIDE.md)

**1.2.1 Alpha**
- ✅ **Looks system:** each console skin is a folder (look.json, look.js, look.css), with a starter template and [docs/LOOKS.md](docs/LOOKS.md)
- ✅ The Dashboard's big tile is what you used last: the game, the video with its poster, the live channel with its logo, the song that's playing
- ✅ Now Playing centred along the top of the Dashboard, with smooth seconds
- ✅ **Trophies in the Quick Menu:** Steam, and RetroAchievements for emulated games
- ✅ **Friends & Party in the Quick Menu:** join voice channels, see who's online, call friends, mute, deafen, share the screen
- ✅ The in-game Quick Menu matches the look: a centred, 360-sized Guide with five tabs for the Dashboard
- ✅ Frame-rate and temperature overlays have separate corners and sizes (readable on a 4K TV)
- ✅ The system keyboard matches the Dashboard in other apps

**1.2 Alpha**
- ✅ **Dashboard (Xbox 360 style)** rebuilt from the ground up: pivots, a tile wall with a big tile, lists with a details pane, an Options flyout, panel dialogs
- ✅ **Interface switch** from Settings or the Quick Menu, applied live
- ✅ Settings › Theme reorganised: Interface first, then that look's own settings, then theme packs

### 1.1 series: torrents, VPN, network

**1.1.5 Alpha**
- ✅ **Update Branch:** install main or a test branch, and switch back and forth

**1.1.4 Alpha**
- ✅ First Xbox 360 interface (Blades / NXE / Metro eras), replaced by the 1.2 Dashboard
- ⚠️ VPN apps' DNS through a tunnel relay, IPv6 blocked for VPN apps, PIA port forwarding over the tunnel address

**1.1.3 Alpha**
- ⚠️ Split tunnelling on Arch (through `newgrp`); split rules follow the VPN when it reconnects
- ⚠️ Torrent search back to one item, with plugins switched on and off from Options
- ✅ Spotify: only ever one speaker (no more double audio)

**1.1.2 Alpha**
- ⚠️ Split tunnelling through a `crossbar-vpn` group; Check Split Tunneling and Check My Address show both addresses
- ⚠️ Torrent search through qBittorrent's own search runner

**1.1.1 Alpha**
- ✅ VPN connects to PIA (certificate check fixed)
- ⚠️ Split tunnelling as an on/off switch, with DNS through the VPN
- ✅ Leak tests: a torrent IP leak test and a DNS leak test
- ✅ Speed test download fixed

**1.1 Alpha**
- ✅ **Torrents:** a controller client on qBittorrent's engine; `.torrent` files and magnet links, transfers, settings
- ⚠️ Torrent search through qBittorrent search plugins (official and community)
- ✅ **VPN** from the controller: WireGuard and OpenVPN; sign-in for PIA, Mullvad and NordVPN; config import for the rest
- ⚠️ VPN port forwarding and split tunnelling
- ✅ Internet speed test
- ✅ Windows Components per game (winetricks / protontricks)

### 1.0 series: first alpha

**1.0.2 Alpha**
- ✅ **Launch Options** per game: environment variables, a launch command, the Proton / Wine version, common switches
- ✅ Frame-rate overlay in Steam games; icons per ROM system; tags for apps

**1.0.1 Alpha**
- ✅ Hide any game, app or ROM
- ✅ Flathub installs fixed; Discord calling and screen share with Discord's current client

**1.0 Alpha**
- ✅ Live download progress (Steam, GOG)
- ✅ **Eden** (Nintendo Switch) with keys and firmware
- ✅ Editable tags; Lutris games and Steam non-Steam games
- ✅ ProtonUp-Qt's tool catalogue in the Proton / Wine manager

### 0.x: building the console

**0.14:** Apps category (open apps, Flatpaks, AppImages) · Flathub browser and AppImage installer · your own folders · local artwork

**0.13:** Theme packs (colours, waves, background, font, icons, sounds) · PlayStation-style on-screen keyboard · faster start-up

**0.12 / 0.12.1:** Steam Big Picture in Game · download speed, time left and cancel · a controller-made web browser · Discord screen share and calling

**0.11 / 0.11.1:** Quick Menu pages (Sound, Performance, Settings) · grouped Settings · SteamGridDB artwork · frame-rate overlay (MangoHud) · Steam and Discord friends · Party

**0.10:** Emulation (ROMs, emulator installs, BIOS checks, RetroAchievements) · Trophies · on-screen keyboard, in Crossbar and system-wide · Discord voice on its own web client

**0.9 – 0.9.3:**
- Game mode (the menu closes during games)
- Restart and Exit Crossbar · an app switcher · per-app volume · button glyphs
- Install on CachyOS / Arch and the PS5 · PS5 temperatures, fan and front light
- More reliable Steam, GOG and NAS

**0.8:**
- The Proton / Wine picker (umu-launcher) and GE-Proton downloads · GOG and Epic Windows games
- A file browser · network drives (SMB / NFS) · IPTV (live TV, movies, series)

**0.7:** The Quick Menu as a true overlay · the controller service · Discord voice channels · Wi-Fi, Bluetooth, Date & Time · a built-in terminal · launch hand-off · support reports
