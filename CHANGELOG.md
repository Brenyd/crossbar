# Changelog

## 1.2.1 Alpha (testing branch)
- **Dashboard now playing**: the seconds tick smoothly (they jumped as each player report came
  in late and rounded; Spotify's position is no longer rounded down either), on the top bar, the
  tile and its details alike; the song that's playing — with its album art — is the big tile in
  Music
- **Looks are modular now (console skins)**: each look is a folder — look.json (name, settings,
  colours, Quick Menu style), look.js (its drawing code) and look.css — in shell/web/looks/ or
  ~/.local/share/crossbar/looks/, picked up automatically. Settings › Theme builds each look's
  settings from its look.json; a starter look to copy is in looks/_template, and docs/LOOKS.md
  explains the whole contract. The XMB and the Dashboard are both looks now
- **Dashboard**: the big tile in each section is what you used last there — the game you
  played, the video you watched (with its picture), the setting you opened — and it's where
  you start. Tiles no longer overlap it when selected. What's playing (music or Spotify) shows
  centred along the top with its progress
- **Video › Continue watching**: the last video you played, first in Video (both looks)
- **The in-game Quick Menu matches the look**: with the Dashboard it's a Guide — your profile
  and the time, five tabs (Games & Apps, Media, Home, Social, Settings) walked with LB / RB,
  rows lit in your accent colour. The Dashboard's own Guide uses the same five tabs
- **Trophies in the Quick Menu** (both looks): the running game's trophies (Steam
  achievements: unlocked count and the list), and All Trophies, which opens Game › Trophies
- **Interface** switch in the in-game Quick Menu too
- **Performance overlays**: the frame-rate and temperature overlays have their own positions
  (they no longer move together and cover each other — temperatures default to top left), and
  each has a **size**: Automatic follows the screen (so it's readable on a 4K TV), or Small /
  Medium / Large / Huge

## 1.2 Alpha (testing branch)
- **Dashboard (Xbox 360 style), rebuilt from the ground up** as its own front end rather than the
  XMB re-arranged: lowercase pivots across the top (LB / RB, or ◀ ▶ past the last tile), a
  sideways wall of tiles led by a big hero tile, flat colour and a lifted, outlined selection;
  folders of pictures open as tile walls and every other folder as a list with a solid highlight
  bar and a details pane (long descriptions wrap there instead of running off the screen); your
  profile and the time in the corner; coloured A / B / Y hints; Options (Y) as a flyout from the
  right; dialogs as panels with stacked buttons; toasts rising from the bottom; a matching
  on-screen keyboard. Replaces the earlier Blades / NXE / Metro versions
- **The Quick Menu has a matching Guide** in the Dashboard: your profile, tabs (Home, Sound,
  Performance — LB / RB) and the same rows and commands. A new **Interface** row swaps between
  the two looks from anywhere (◀ ▶ or A), in either look
- **Settings › Theme makes sense now**: Interface first, then that look's own settings —
  Dashboard: **Background** (Light, Dark, Green, or your theme pack's picture) and **Accent
  Colour** (green, blue, orange, pink, purple, red, silver); cross-media bar: Wave Colour — then
  **Theme Packs** (in their own folder), Install a Theme…, Make Your Own
- Underneath, both looks are one menu: the same items, actions, folders, Options, dialogs and
  controller mapping. The shell seam in xmb.js now lets a look draw the Quick Menu, stack dialog
  buttons, use LB / RB and refresh a details pane (documented above `Shell`)
- Fixed: a dialog after one with text fields could show its buttons dimmed

## 1.1.5 Alpha
- **Update Branch** (Settings › System): pick which GitHub branch Update Crossbar installs — main
  (stable) or a test branch such as testing/xbox-360-interface — and switch back the same way.
  Picking one offers to install it right away; About shows the branch you're on

## 1.1.4 Alpha
- **Xbox 360 interface**: Settings › Theme & Time › Theme › **Interface** switches the menu between
  the cross-media bar and an Xbox 360 dashboard, and **Dashboard Era** picks which 360: Blades
  (2005, slanted coloured blades with the list in the open one), the New Xbox Experience (2008,
  channels down the left and a row of big tiles — ▲ ▼ changes channel, ◀ ▶ walks the tiles) or
  Metro (2011, a three-row grid of flat tiles that pages between categories). It changes the
  moment you pick it, with no restart, and you keep your place in the menu. Your games, apps,
  folders, Options menu, dialogs, Quick Menu, keyboard and controller mapping are all unchanged,
  and theme packs recolour the dashboards too (new `--x360-*` CSS variables in docs/THEMES.md)
- **VPN apps' DNS**: their lookups went to the system's local resolver (127.0.0.53), which the
  firewall tried to send out of the tunnel; the kernel refuses that, so lookups hung (test app
  timed out, "Couldn't reach bash.ws", torrent search found nothing). Those lookups now go to a
  small relay in Crossbar that asks the VPN's DNS server through the tunnel
- **No IPv6 leaks for VPN apps**: the VPN carries IPv4, so VPN apps' IPv6 is refused (they fall back
  to IPv4 through the VPN) instead of going out your own line
- **PIA port forwarding** (WireGuard): asked the server's public address, which refuses it
  ("Connection refused"); now asks its address inside the tunnel, as PIA's own scripts do
- **Check Split Tunneling** tests the connection without DNS and DNS on its own, so it says which
  one is broken
- **Torrent search** errors no longer show Python's harmless shutdown warnings

## 1.1.3 Alpha
- **Split tunneling on Arch**: VPN apps were started with `sg`, which Arch doesn't ship ("No such
  file or directory: 'sg'" in the DNS leak test, Check Split Tunneling and torrent search). They now
  go through util-linux's `newgrp`, which every Arch system has
- **Split rules follow the VPN**: if the VPN comes up without Crossbar (at boot, or NetworkManager
  reconnects it) the routing rules are put back within half a minute; Check Split Tunneling puts
  them back on the spot and shows the VPN connection, its address and whether the rules are there
- **Torrent search**: Search is one item again: press it to search; Y / △ (Options) lists your
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

