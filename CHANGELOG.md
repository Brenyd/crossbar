# Changelog

## 1.3 Alpha (testing branch)
- **Blades**, a third interface (Settings › Theme › Interface), in the style of the Xbox 360's first
  dashboard (2005): every category is a glossy coloured blade; the open one fills the screen and the
  others stand in stacks on either side with their names running up their edges. Left / right or
  LB / RB flips blades like pages; each has a list down the left and a showcase on the right (the
  highlighted thing's picture with a reflection, its name and description); folders open on the same
  blade, and left goes back. Your card and what's playing sit in the corner
- **Its Guide is a blade too**: the Quick Menu slides in from the left as a coloured blade with your
  card, in the menu and over games (the native overlay has a new "blade" style for looks)
- Options slide in as a small blade; dialogs are dark glass with a band in the blade's colour;
  notifications are glass capsules; the button hints are the coloured round buttons
- Settings: Background (Light, Dark, theme picture), Blade Colours (Classic — a colour per blade —
  or all Silver / Green / Blue / Black) and Guide Colour
- No console maker's logo or brand marks are drawn

## 1.2.9 Alpha
- **TV remotes** (Settings › Controller, Remote & Keyboard › TV Remote): an Android TV remote — or a
  SofaBaton set up as one, a Fire TV / Google TV remote, an IR receiver, HDMI-CEC — now works fully,
  not only its arrows. Found automatically, or by pressing a button in **Set Up a Remote…**; every
  button can be remapped, and **Test the Remote** shows what arrived
- **Media keys control whatever is playing**: music, Spotify, a video, live TV, YouTube and other web
  apps, even behind a game. Play, Pause and Stop do exactly that; Rewind / Fast Forward skip songs in
  music and seek in videos (hold to keep going)
- **Live TV with a remote**: Channel ± changes channel, number keys type a channel number, Record
  goes back to the last channel, Red / Green switch subtitles / audio track, Blue or Guide opens Live TV
- Volume ± and Mute change the console's volume; Home opens the Quick Menu; Power opens the Quick
  Menu instead of shutting down. In games and other apps the remote types the matching keys. The
  controller service holds the remote while Crossbar runs (so keys never act twice) and lets it go
  when Crossbar stops
- The video player: Previous goes to the previous channel in live TV (not back to 0:00)
- **PS5: Return to Crossbar from the desktop went to gaming mode.** The hook that catches it after
  Plasma closes was only added when the PS5 switcher script matched one exact line, and updates
  never re-applied it. It's now placed wherever that script hands over to gaming mode, every update
  refreshes it, and Return to Crossbar ends the desktop session itself if the hook is ever missing
- **Return to Crossbar icon on the Plasma desktop**, added by the installer and by Update (once: delete
  it and it stays deleted; Uninstall removes it)

## 1.2.8 Alpha (testing branch)
- **Lutris installs stopped with "Couldn't find lutris-wrapper script"**: Lutris looks for its wrapper
  next to the program that started it, which was Crossbar's helper (and, in the Flatpak, Lutris lives
  under /app). The helper now finds Lutris's real folder first, so install commands run
- **Jackett stopped right away (CultureNotFoundException, en-US)**: Crossbar started it in .NET's
  ICU-free mode, which Jackett can't run in. It now uses the system's ICU, and if there is none,
  lets .NET accept named cultures. When Jackett does fail to start, the reason is in the message
- **Bluetooth controllers that wouldn't connect** (br-connection-busy / br-connection-create-socket):
  pressing Connect twice no longer starts two connections; paired devices are trusted, so a
  controller connects itself when its PS button is pressed; a connect that fails says what to do;
  new **Pair Again** in Options forgets the device, finds it in pairing mode and pairs it fresh

## 1.2.7 Alpha
- **Jackett in Torrents** (Torrents › Jackett): install the official Jackett build from its GitHub,
  then add any tracker it supports — public, semi-private, private with your account — and fill in
  each tracker's own settings form with the controller (text, password, choices, categories, options,
  captcha picture). Add & Test shows Jackett's exact answer. Jackett then searches alongside your
  plugins (each tracker's results and errors shown), and its downloads go through Jackett so private
  sites' sign-ins work. Settings: FlareSolverr, admin password, start with Crossbar, update, stop
- **Lutris installers in Install Apps**: search lutris.net, pick a game's installer, see what it
  downloads and what you provide (your own setup files, disc images), choose them and the install
  folder, Install. Lutris's own installer engine runs the script; its questions (Wine download, a
  language / edition menu, a disc, a file) come up on the screen; progress in Downloads; the game
  lands in Game. Local .yml scripts too. Install Lutris installs the Arch package (refusing if
  pacman would touch graphics drivers or the kernel), or use the Flatpak

## 1.2.6 Alpha (testing branch)
- **VPN apps time out — the cause**: WireGuard encrypts a packet in place, so the encrypted copy can
  still look like it came from the VPN app that sent it. The split-tunneling rule marked it too and
  sent it back into the tunnel: a loop, so VPN apps (the test app, the DNS leak test, the torrent
  engine in the VPN group) connected nowhere, while traffic from the VPN's own address worked.
  WireGuard's packets now carry their own mark and, with the VPN server's address, are left alone
- **Torrents "Only Use the VPN"**: the engine is bound to the VPN's interface and address only,
  not also run as a VPN app — traffic from the VPN's address goes straight through the tunnel (the
  path that works), and with the VPN down there's no torrent traffic. An engine still running the
  old way is restarted once
- **Search plugins and the leak tests** (Crossbar's own helpers) send their connections from the
  VPN's address too
- **Firewalled** in Torrents explains itself: peers can't connect in without the VPN's forwarded
  port; downloads still work (A on the line for more)

## 1.2.5 Alpha (testing branch)
- **VPN apps' connections no longer hang** (split tunneling): traffic sent into the VPN by the split
  rules had already been sized for your normal connection, and the VPN's packets are smaller, so
  connections opened and then stalled (the test app "timed out", torrents waited for peers). TCP is
  now clamped to the tunnel's size on the way in (MSS clamping)
- **PIA port forwarding**: asked PIA only at the server's address inside the tunnel, which some
  servers refuse. It now also tries the server's public address through the tunnel (what other PIA
  scripts use) and remembers whichever answers, with its requests tied to the VPN interface like
  `curl --interface`. Check Port Forwarding shows the location (fresh from PIA: does it forward?)
  and each address tried
- **Torrent search plugins run one by one**: each enabled plugin runs on its own (a few at a time)
  instead of all in one qBittorrent search process — which lower-cased plugin names, so community
  plugins whose file names have capitals never ran. A plugin whose class is named differently from
  its file runs too; one that hangs is stopped after a minute without holding up the rest; and
  every plugin's result shows on the first row (how many it found, or ✕), with each one's error
  (a site blocking it is called out) on A
- **Long text scrolls**: the highlighted line in Options panels, lists and the Quick Menu scrolls
  slowly across when it doesn't fit, so the whole thing can be read

## 1.2.4 Alpha (testing branch)
- **Starts in your interface from a cold boot**: the menu page now comes from the backend with the
  chosen look built in, so the very first frame is the Dashboard (or the cross-media bar) — it no
  longer started in the cross-media bar and waited on the backend to switch, and a slow or missed
  answer at boot can't leave you in the wrong one
- **Only the chosen interface is loaded**: the other look's code, styles and backdrop aren't loaded
  at all (the cross-media bar's waves don't run under the Dashboard)
- **Interface is a setting now, not a live switch**: Settings › Theme › Interface saves your choice
  and reloads the menu into it (a few seconds, back to Theme). The Interface row is gone from both
  Quick Menus; the in-game Quick Menu keeps the style of the interface that's running
- **Now Playing ticks smoothly in the cross-media bar too**: the time and progress bar move every
  second instead of jumping with each report from the player or Spotify (the Dashboard had this
  already)

## 1.2.3 Alpha (testing branch)
- **VPN apps' DNS survives restarts**: with split tunneling on, VPN apps' lookups go to a relay
  inside Crossbar, and the firewall kept sending them there after Crossbar restarted (an update,
  Restart Crossbar, Memory Guard) while nothing was listening. So nothing that used the VPN could
  look up a name: torrent trackers and DHT, search plugins, the leak tests. The relay now starts
  first thing, the VPN's DNS server is saved, and OpenVPN connections (which never had one in split
  mode) use one too (Cloudflare's, through the tunnel, when the provider doesn't say)
- **DNS Through the VPN** (Split Tunneling): Automatic sends every lookup to the VPN's DNS when
  systemd-resolved does the lookups (it asks for every app itself, so per-app DNS can't work there),
  or choose For Everything / For VPN Apps Only. The VPN's DNS server is always reached through the tunnel
- **Port forwarding**: switching it on works straight away (it needed a reconnect, and did nothing
  if you said no); it retries when PIA doesn't answer (it gave up for good after the first failure);
  it carries on after Crossbar restarts; PIA's signature is kept so the port stays the same; a
  location without port forwarding says so; the port is opened in ufw / firewalld on the VPN only;
  Torrents picks the port up when it starts later; Y › Check Port Forwarding shows each step
- **Torrents through the VPN**: each VPN connection has a new address; the engine is now bound to
  the new one (and asks its trackers again) on every connect and restart, instead of staying on
  the old one
- **Torrent IP leak test rebuilt**: no more third-party tracker page. It checks a connection made the
  way the engine makes them and the address the BitTorrent network reports to the engine, and with
  the VPN off and "Only Use the VPN" on, confirms there's no torrent traffic
- **DNS leak test**: compares with your own address checked fresh, shows the VPN's DNS server, and
  explains a systemd-resolved leak with the setting that fixes it
- **Torrent search**: **Sort** by Seeds, Leechers, File Size, Upload Date, Name or Site (kept for the
  next search); results show their age; "Nothing found" now says why — DNS, the connection, or
  the plugins — after testing the plugins' sites the way the search reaches them
- Split tunneling: everything leaving through the VPN gets the VPN's address (sites sent through it
  included), and reverse-path checks are relaxed whether or not the app group exists

## 1.2.2 Alpha
- **Memory Guard** (Settings › System, on by default): when a game runs the console out of
  memory, Crossbar first closes the menu window to give it room, and if memory still runs out,
  closes the game and says so, instead of the whole console freezing for minutes (sound
  stuttering, no picture, no controller)
- **Black screen after a game fixed**: with a game window still around (a hung one, or Big
  Picture coming back), Go to Home and Restart Crossbar would bring the menu back and then close
  it straight away again for "game mode". Going Home now keeps the menu, Restart brings it to the
  front, and if the piece that runs the menu window was killed it's started again
- **Close a Steam game** ends all of it (Proton runs a game as many processes), not just its window
- **The menu goes quiet behind games**: while a game is loading or in front, animations
  pause, the backdrop stops drawing, the controller is read by the backend only, and status
  polling drops from several times a second to every 10–16 s
- The Dashboard's backdrop no longer moves (a blurred layer moving repainted the whole 4K screen
  every frame)
- Cheaper status checks: the screen size and the list of looks are cached
- VPN: the DNS relay uses a fixed set of workers (not a thread per question) and can't spin on
  a broken socket; when split-tunnel rules can't be applied, retries back off to 10 minutes
  instead of starting a privileged helper every 30 s

## 1.2.1 Alpha
- **Friends & Party in the Quick Menu** (both looks, in-game too): your Discord voice channels
  (the ones shown in Social) to join or leave, who's online on Discord and Steam (A calls a Discord
  friend), and, while in voice, mute, deafen, share screen and leave. In the Guide it's the
  Social tab
- **Big tiles for IPTV**: the last film or episode you watched is Video's big tile with its
  poster, and the last live channel is TV's, with the channel logo (Watch again)
- **The system keyboard matches the Dashboard** in other apps too (it drew in the theme pack's
  colours)
- The in-game Guide is centred vertically as well
- **Quick Menu › Trophies for emulated games**: RetroAchievements trophies of the game you're
  playing (unlocked count, points, the list) — the game RetroAchievements sees you playing,
  matched against its title
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

## 1.2 Alpha
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

