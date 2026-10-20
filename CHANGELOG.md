# Changelog

## 1.1.3 Alpha
- **Split tunneling on Arch**: VPN apps were started with `sg`, which Arch doesn't ship ("No such
  file or directory: 'sg'" in the DNS leak test, Check Split Tunneling and torrent search). They now
  go through util-linux's `newgrp`, which every Arch system has
- **Split rules follow the VPN**: if the VPN comes up without Crossbar (at boot, or NetworkManager
  reconnects it) the routing rules are put back within half a minute; Check Split Tunneling puts
  them back on the spot and shows the VPN connection, its address and whether the rules are there
- **Torrent search**: Search is one item again. {ok} searches, Y / △ (Options) lists your
  plugins to turn on or off (✓ on, – off), all on / all off, and Get More Plugins
- **Dialogs**: the menu behind a dialog fades back, so its text no longer reads through
- **Spotify**: one speaker only. A speaker left over from before an update or restart is stopped
  instead of playing alongside a new one (the double audio). When Spotify loses the speaker while
  music keeps playing, the track stays in Music with Stop / Reconnect, and playing anything
  restarts the speaker first

## 1.1.2 Alpha
- **Split tunneling works from the console session**: apps that use the VPN were marked through a
  systemd user scope, which didn't take on the TTY session, so they still went out your own line
  (the DNS leak test said so). They're now started in a `crossbar-vpn` group that the firewall
  sends through the VPN (made once, with your password, the first time)
- **Clearer VPN answers**: with split tunneling on, Crossbar itself and Check My Address use your
  own line by design; Check My Address now shows both addresses (VPN apps / everything else), the
  torrent leak test says when Torrents simply isn't set to use the VPN, and **Check Split
  Tunneling** (VPN › Leak Tests) shows what a VPN app is seen as, the rules, and whether the
  firewall is marking its traffic
- **Torrent search**: runs qBittorrent's own search runner with your plugins (the Web API search
  kept coming back empty); plugin errors are shown; plugins without the category you pick are left
  out (pick Everything to use them all)
- **Search** is a folder: **New Search…**, **Search With** (turn each plugin on or off, all on / all
  off) and Search Plugins. Plugin lists mark the ones you've installed

## 1.1.1 Alpha
- **VPN connects**: PIA's servers were refused by Python 3.13's strict certificate check (their CA
  doesn't mark Basic Constraints critical); that one check is relaxed for PIA's own CA only
- **Split tunneling** is a switch, on by default: nothing uses the VPN except the apps and sites you
  add (Torrents, Steam, other games, Discord, the browser, AppImages). Their DNS goes through the VPN
  too. Off: everything uses the VPN
- **Leak tests** (VPN › Leak Tests, and in Torrents): a torrent IP leak test (the torrent engine
  announces a made-up torrent to WhatIsMyIP.net's tracker checker, and Crossbar shows which address
  it saw) and a DNS leak test (bash.ws)
- **Torrent search** results: Crossbar now keeps one session with the engine (qBittorrent keeps a
  search in the session that started it, so results came back "not found")
- **Speed test** download: asked Cloudflare for 100 MB at a time, which it refuses (read as 0 Mbps);
  now 25 MB, errors are reported, and latency / jitter ignore one-off stalls

## 1.1 Alpha
- **Torrents** (Apps › Torrents): a controller client on qBittorrent's engine — search through
  qBittorrent search plugins (official, and the community list from the qBittorrent wiki with a
  sign-in for private sites), transfers with files / order / limits, magnet links and .torrent
  files, binding to the VPN, and the common settings, console-sized
- **VPN** (Settings › Network): WireGuard and OpenVPN through NetworkManager; sign-in wizards for
  PIA (regions with latency, port forwarding), Mullvad and NordVPN; config import for Proton VPN,
  Surfshark, Windscribe, IVPN, AirVPN, ExpressVPN and any server; split tunneling for sites and apps;
  connect at startup
- **Internet speed test**: download, upload, latency and jitter
- **Windows Components** per game (Y › Windows & Proton): DLLs, fonts, runtimes and the Windows
  version through winetricks / protontricks, into that game's own prefix (Steam, GOG, Epic, Lutris)
- **Y menus** are grouped (Customize…, Windows & Proton…), Delete last
- Games and apps are in **alphabetical order**; app icons are centred like the other icons
- **Discord**: screen share no longer shows Chromium's "Choose what to share" window, and stopping
  it from the XMB / Quick Menu now tells Discord (no more endless loading for viewers)

## 1.0.2 Alpha
- **Launch Options** (Y › Launch Options… on Steam, Lutris, GOG, Epic and non-Steam games): environment
  variables, a launch command (`gamemoderun %command% -dx11`), the Proton / Wine version, and one-press
  common options (MangoHud, GameMode, Proton log, WineD3D, esync / fsync, NVAPI…). Steam's are saved
  in Steam's own settings (put in place the next time you start the game here, or Apply Now);
  Lutris' in the game's Lutris settings
- **Frame-rate overlay in Steam games**: Steam is now always started with the overlay's setting
  (installing, Big Picture and sign-in used to start it without), and a Steam started some other way
  is restarted once when you launch a game with the overlay on
- **ROM systems** each have their own icon; **apps** get [FLATPAK] / [APPIMG] tags, and the line
  under apps and games just says Play (in Game) or Start
- **Long text** (Flathub's About, messages) scrolls with up / down
- **Discord**: screen share watches the capture itself; if the browser refuses it in the
  background, Discord comes forward for a moment to start it, then your game comes back
- **Spotify**: playback starts straight on the speaker instead of transferring to it first, which
  librespot 0.8 rejects on an idle speaker ("transfer context had no uri")

## 1.0.1 Alpha
- **Hide** any game, app or ROM from the XMB (Y › Hide); bring it back in
  Settings › Games & Emulation › Game Settings › Hidden Games & Apps
- **Flathub**: opening an app's page failed ("'list' object has no attribute 'items'") since
  Flathub changed how it lists screenshots, so nothing could be installed — fixed
- **Discord**: calling a friend and Share Your Screen work with Discord's current client. Buttons
  that only name themselves in a hover tooltip are found by hovering them; DMs open through
  Discord's own functions, its DM list or a real click on the friend; sharing is detected (and
  stopped) through the captured screen itself
- **Spotify**: occasional Spotify server errors (500/502/503) are retried quietly; when playback
  keeps failing the speaker restarts once by itself, and the message explains what librespot reported.
  Restart Speaker is also on Y in Music › Spotify

## 1.0 Alpha
- **Downloads**: live progress for Steam (follows the data landing on disk, not Steam's slow counters),
  GOG shows progress from the start, rows update in place every second
- **Eden** (Nintendo Switch) in Emulation: newest stable AppImage (Steam Deck build on Zen 2 / PS5),
  Switch keys and firmware from bios/switch handed to Eden
- **Tags** on ROMs ([SNES], [PS2]…) instead of the console subtitle; every game's tag is editable (Y › Edit Tag…)
- **Lutris** games and Steam **non-Steam games** in the XMB (Game by default, Y › Show In… to move)
- **Compatibility Tools**: ProtonUp-Qt's catalogue (GE-Proton, Proton-CachyOS, Luxtorpeda, Boxtron,
  Wine-GE, Kron4ek, Lutris-Wine, DXVK, vkd3d-proton) in Settings, plus the ProtonUp-Qt app itself
- Fixes: plain-language network errors (GitHub rate limits, offline Flathub), Trash when empty,
  Wi-Fi without NetworkManager, missing-parameter errors; the wave background renders at 30 fps,
  Flatpak lists are cached

## 0.14

| | |
|---|---|
| ![Apps](docs/apps.png) | ![Flathub](docs/flathub.png) |
| **Apps** — what's open right now (switch to it or close it), plus your Flatpaks and AppImages | **Install Apps** — browse and search Flathub, or install an AppImage; you pick which category it shows up in |

Also: **your own folders** in any category (Y › Move to Folder…), and **Local File…** for artwork.

## 0.13

![Themes](docs/themes.png)

**Themes**: Classic, Midnight, Phosphor and Sunset to start with, and your own: colours, waves,
a background picture or video, font, icons, sounds, keyboard and Quick Menu colours, all from one
folder. See **[docs/THEMES.md](docs/THEMES.md)** to make one. Also: PlayStation-style keyboard
buttons, a faster start-up, Discord Share Screen from Crossbar, and calling friends.

## 0.12

| | |
|---|---|
| ![Browser](docs/browser.png) | ![Downloads](docs/downloads.png) |
| **A browser made for the controller** — D-pad jumps between links, A opens, the keyboard types straight into the page, sized for a TV | **Downloads you can stop** — speed and time left; Y › Cancel Download deletes what was downloaded. Plus **Steam Big Picture** in Game |

## 0.11

| | |
|---|---|
| ![Artwork picker](docs/artwork-picker.png) | ![Grouped settings](docs/settings-grouped.png) |
| **Change Artwork** — any game or ROM, from SteamGridDB's community art (Y › Change Artwork…) | **Tidier Settings** — related sections grouped: Display & Sound, Network & Bluetooth, Games & Emulation… |
| ![Discord channels](docs/discord-channels.png) | ![Quick Menu](docs/quick-menu-grouped.png) |
| **Pick your voice channels** — Social only shows the ones you turn on in Settings › Accounts › Discord | **Shorter Quick Menu** — Sound and Performance open their own page; long lists scroll |

Also: **Trophies** at the top of Game, a **frame rate overlay** for games (MangoHud), and on a PS5
**ps5_control** is set up for fan modes and boost.

### Earlier

| | |
|---|---|
| ![Live TV](docs/iptv-live-tv.png) | ![Movies](docs/iptv-movies.png) |
| **IPTV Live TV** — your provider's channels with logos; L1/R1 change channel while watching | **IPTV Movies** — posters shown whole, big categories a page at a time |
| ![TV Shows](docs/iptv-tv-shows.png) | ![IPTV categories](docs/iptv-settings.png) |
| **IPTV TV Shows** — seasons and episodes | **Choose what shows** — pick categories in Settings › Media › IPTV |
| ![Steam updating](docs/steam-starting.png) | ![Now Playing](docs/now-playing.png) |
| **Steam cold start** — Crossbar waits through Steam's own updates, then starts the game | **Now Playing** — play/pause and skip show the song, anywhere in the menu |
| ![System settings](docs/settings-system.png) | ![Game settings](docs/game-settings.png) |
| **Settings › System** — Restart Crossbar, and on a PS5 switch to gaming mode or the desktop | **Free Memory While Gaming** — the menu closes while you play; Quick Menu keeps working |

<sub>Screenshots use the demo library and a stand-in IPTV server with invented channels and titles.</sub>

