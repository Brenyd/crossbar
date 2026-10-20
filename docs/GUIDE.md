# Crossbar guide

Everything Crossbar does, section by section. The [README](../README.md) is the overview;
[INSTALL.md](INSTALL.md) covers installing; [CHANGELOG.md](../CHANGELOG.md) what changed.

**Contents:** [Controls](#controls) · [PS5 hardware](#ps5-hardware-linux-on-a-ps5) ·
[Interfaces](#interfaces) · [Button glyphs](#button-glyphs) · [Quick Menu](#quick-menu) ·
[Music, Video, Photo](#music-video-photo) · [Spotify](#spotify) ·
[Social](#social-friends-and-discord-voice) · [Emulation](#emulation) · [Trophies](#trophies) ·
[Keyboard](#on-screen-keyboard) · [Browser](#internet-browser) · [Downloads](#downloads) ·
[Apps](#apps) · [Torrents](#torrents) · [VPN](#vpn-and-speed-test) · [Folders](#folders) ·
[Artwork](#artwork-steamgriddb) · [Games](#games) · [Files, drives, IPTV](#files-network-drives-iptv) ·
[Settings](#settings) · [Stores](#how-the-stores-connect) · [Party chat](#party-chat)

## Controls

| Action | Keyboard | Gamepad |
|---|---|---|
| Move | Arrow keys | D-pad / left stick |
| Enter | Enter | A / ✕ |
| Back | Esc | B / ○ |
| Options | Tab | Y / △ |
| Quick Menu (from anywhere, over any app) | Home, or Super+Esc | **Select + Start** together |
| Steam's own overlay (in Steam games) | Shift+Tab | Guide / Steam / PS button |
| Built-in terminal | Ctrl+Alt+T | |
| Play/Pause, previous, next track (in the XMB) | P, Page Up, Page Down | Start, L1, R1 |

**Web apps** (YouTube, Twitch, Plex, the browser) open full screen at your display's
resolution, and the controller works in them too: Crossbar types arrow keys, Enter (A),
Esc (B), Tab (Y) and media keys on a virtual keyboard. YouTube opens in its TV interface,
which is built for exactly this.

Every button and key above can be changed in **Settings › Controller & Keyboard**: pick an
action, press the new button (or key), done. There's also *Swap Select and Back* and
*Reset All to Defaults*. Controllers are read by Crossbar itself and input only goes to
whatever is on screen — the menu, the video player, or nothing (games read the pad directly).

### How controllers work

A small root service, `crossbar-inputd`, reads every controller (so permissions can't get in
the way) and streams it to Crossbar, which applies your mapping and sends each press to
what's in front. While the menu, a video, a web app or the Quick Menu is in front, Crossbar
*holds* the controller so nothing behind reacts too. When a game is in front it lets go, and
the game reads the controller itself. Guide/PS always reaches the Quick Menu.

### If something isn't working

**Settings › System › Share Support Report** uploads a diagnostic report and shows a
short link — paste that link when asking for help.

### If the controller works in the menu but not in videos, web apps or the Quick Menu

Check `systemctl status crossbar-inputd` (it should be *active*). Without it Crossbar falls
back to reading the controller directly, which needs permissions.
**Settings › Controller & Keyboard › Controller Diagnostics** shows what Crossbar sees and
the last buttons it received. For a full report press Ctrl+Alt+T and run `crossbar-doctor`.
The ISO ships a udev rule (`/etc/udev/rules.d/70-crossbar-input.rules`) that gives the
console user access to controllers and `/dev/uinput`. On an existing install, copy that rule
in and reboot. In a VM, pass the controller through as a USB device.

## PS5 hardware (Linux on a PS5)

When the PS5 fan and LED kernel drivers are present, **Settings › PS5 Hardware** shows up:

- **Temperatures** — CPU, GPU and NVMe, read straight from the sensors.
- **Temperature Overlay** — a small box with the temperatures in a corner of your choice, on top of
  everything including games (it never takes input).
- **Fan Target Temperature** — 40–95 °C: the fan speeds up to keep the chip below it (lower = cooler,
  louder). Remembered and re-applied at every start.
- **Fan Mode / Boost** — fixed patterns (On / Off / Max) through `ps5_control`. On a PS5, installing or
  updating Crossbar downloads [ps5-linux/ps5-linux-tools](https://github.com/ps5-linux/ps5-linux-tools)
  and builds `ps5_control` into /usr/local/sbin (`./ps5-tools.sh` does just that step; `--update`
  rebuilds it). Its `ps5fan` / `ps5boost` services are installed but left off. It isn't shipped
  inside Crossbar because that project has no license yet. Nothing else is touched: not the kernel,
  drivers or boot setup.
- **Front Light** — every colour and animation the LED driver offers.

The Quick Menu has the temperatures (A shows/hides the overlay) and the fan target (◀ ▶).
Thanks to [syrufex/PS5-Temperature-Control-Panel-Linux](https://github.com/syrufex/PS5-Temperature-Control-Panel-Linux)
(MIT), whose app showed which driver interfaces to use; Crossbar's version is its own code and UI.

## Interfaces

**Settings › Theme & Time › Theme › Interface** (or **Interface** in the Quick Menu) swaps the whole
front end live: the **cross-media bar (PS3 style)** or the **Dashboard (Xbox 360 style)**. See the
[README](../README.md#two-interfaces) for what each looks like, [THEMES.md](THEMES.md) to restyle
one, and [LOOKS.md](LOOKS.md) to build a new console skin.

## Button glyphs

**Settings › Controller & Keyboard › Button Glyphs**: Automatic (matches the connected controller),
Xbox (A B X Y), PlayStation (✕ ○ □ △) or Nintendo (B A Y X). Every hint uses them — the menu, the
Quick Menu, the video player's panel and the remapping screen — and they follow your button mapping,
so a remapped action shows the button you actually press. Glyphs follow the button's *position*
(the bottom button is ✕ / A / B), so on a Nintendo pad confirm is **B**; turn on
**Swap Select and Back** if you'd rather confirm with A like on a Switch.

## Quick Menu

Press **Select + Start** (or **Home**) during a game, video or app. The Quick Menu opens **on top
of** whatever is running — a native window on the Wayland overlay layer, like the Steam or Discord
overlay — and takes the controller and keyboard while it's open, so the game underneath doesn't
react. Guide/PS is left to Steam by default (Settings › Controller & Keyboard can give it to
Crossbar instead). It follows your Interface:

| Cross-media bar | Dashboard |
|---|---|
| ![Quick Menu](quick-menu.png) | ![Guide](guide.png) |
| a list down the left, pages slide in | the Guide: centred, five tabs (**LB / RB**): games & apps, media, home, social, settings |

What's in it (in both):

- **Resume** / **Close** the game or video (closing returns you straight to the menu; a Steam game
  is ended completely, every Proton process, not just its window)
- **Go to Home** — the menu, leaving the game open
- **Trophies ▸** — the running game's trophies: Steam achievements, or RetroAchievements for an
  emulated game (matched to what you're playing), plus **All Trophies**
- **Friends & Party ▸** — your Discord voice channels (the ones shown in Social) to join or leave;
  who's online on Discord and Steam (A calls a Discord friend); while in voice, **Mute**,
  **Deafen**, **Share Screen** and **Leave**
- **Now Playing** — your music or Spotify: ◀ ▶ skip, A play/pause
- **Sound ▸** — **Sound Output**, **Microphone** mute, and **App Volume** for every app playing
  sound right now (◀ ▶ level, A mutes)
- **Performance ▸** — **Frame Rate Overlay** (Off / FPS only / FPS + frame time graph / Full with
  CPU, GPU and temperatures), its **position** and **size** (Auto scales to the screen, up to Huge
  for a 4K TV across the room), and on a PS5 the **Temperature Overlay** (its own position and
  size, so the two never cover each other) and **Fan Target**
- **Switch App** — every open app and game, plus Crossbar; Y gives **Switch To / Close / Force Close**
- **Keyboard**, **Interface** (swap looks right there), **Settings ▸** and **Power…** (opens with
  Cancel selected, so a stray A can't turn the console off)

| Trophies | Friends & Party |
|---|---|
| ![Trophies](guide-trophies.png) | ![Social](guide-social.png) |

B goes back a page, or on the first page resumes what you were doing.

The **frame rate overlay** is [MangoHud](https://github.com/flightlessmango/MangoHud): games Crossbar
starts load it hidden, so turning it on works mid-game. It works in Vulkan games, including Windows
games through Proton. Steam games get it when Crossbar starts Steam (if Steam was already open,
restart Steam once).

If the Quick Menu ever fails to appear, Crossbar notices within a second and a half, gives the
controller back and opens the menu inside Crossbar instead.

### Game mode and Memory Guard

**Free Memory While Gaming:** when a game starts, the menu window — a full browser and the biggest
part of Crossbar — closes. The backend, Quick Menu, controller service, music, Spotify and Discord
voice keep running. **Go to Home** (or quitting the game) brings it back in a couple of seconds, and
it stays open after that even if the game's window is still around. Before the game's window
appears (shader compiling, loading) the menu stays up but goes quiet: no animations, no backdrop,
polling every 10–16 s.

**Memory Guard** (on by default): if a game runs the console out of memory, Crossbar first closes the
menu window, and if memory still runs out, closes the game and tells you — instead of Linux
thrashing for minutes with stuttering sound and a frozen picture. Sway, sound, SSH and Crossbar's
own pieces are never picked. Both are in **Settings › Games & Emulation › Game Settings**.

![Memory Guard](memory-guard.png)

### Video and photos

**While a video plays** (panel hidden): A pause · ◀/▶ seek −10 s/+30 s · ▲/▼ volume ·
L1/R1 previous/next · Y show panel · B jump to Stop. With the panel open, ◀/▶ pick a
button (previous, rewind, play/pause, forward, next, subtitles, audio track, stop), A presses
it, B hides it. Videos resume where you stopped (toggle in Settings › Media).

**Photo viewer:** ◀/▶ browse · A slideshow · Y hide captions · B back.

## Music, Video, Photo

Pick your library folders in **Settings › Media** (defaults `~/Music`, `~/Videos`,
`~/Pictures`; any drive under `/run/media` or `/mnt` works). Browse by folder, or use
**All Songs / All Videos**.

- **Music** plays through a hidden mpv and keeps going while you browse or play games.
  *Now Playing* sits at the top of Music; A pauses, Y gives next/previous/shuffle/repeat/stop.
  Tags and album art come from the files (or a `cover.jpg` in the folder).
- **Video** opens mpv full screen with Crossbar's own control panel. Home pauses it and
  returns to the XMB; *Return to…* at the top of Video picks it back up.
- **Photo** shows thumbnails, a full-screen viewer and slideshows.
- **TV & Video Services** opens web apps in their own window: YouTube (its TV interface,
  made for controllers), Twitch, Plex, plus anything you add (Jellyfin, etc.).

## Spotify

Crossbar becomes a **Spotify Connect speaker named "Crossbar"** (via librespot), and the
Music › Spotify folder browses your Liked Songs and playlists, searches, and plays them on
it, with a Now Playing item and controls like local music. You can also start music on your
phone and move it to Crossbar with **Play on Crossbar**.

Spotify's rules (since February 2026) mean a one-time setup:

1. You need **Spotify Premium** (Connect playback and developer apps both require it).
2. On any device, open [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard), **Create app**.
   Redirect URI: `http://127.0.0.1:7777/spotify/callback`. Tick **Web API**. Save.
3. On Crossbar: **Music › Spotify › Set Up Spotify**, paste the **Client ID**, sign in once in
   the window that opens (and allow access). Press Home if the window doesn't close itself.

After that it just works, every boot. If playing from Crossbar fails, use **Settings › Account
Settings › Restart Spotify Speaker**; the speaker's log is `~/.cache/crossbar/librespot.log`. Developer-mode apps allow up to 5 accounts; playlists
you don't own can be played but their track list can't be shown (a Spotify restriction).

## Social: friends and Discord voice

![Social](social.png)

- **Friends › Steam** — who's online and what they're playing (needs the same free Steam Web API key
  as Trophies, and your Steam Friends List set to Public).
- **Friends › Discord** — friends online now; **A calls them** on Discord (voice runs in Crossbar's
  hidden Discord window, so you can keep playing).
- **Party** — the Discord voice channels you chose: A joins (or leaves).
- While you're in a call or channel it sits at the top of Social with Mute / Deafen, and the Quick
  Menu shows it too (A mutes, ◀ leaves). No developer app or setup.

How it works: Crossbar runs Discord's own web client (discord.com/app) in a window it keeps hidden,
and drives it the way you would, by clicking the voice channel, Disconnect, Mute and Deafen,
through Chromium's private DevTools pipe (only Crossbar's backend can use it; no open port).
Things are found by their accessibility labels, not screen positions, so Discord's redesigns
rarely break it; if one does, an action reports "couldn't find" and **Open Discord** still works.

1. **Social › Sign In to Discord**: Discord shows a QR code; scan it with the Discord app on your phone.
2. **Settings › Accounts › Discord › Voice Channels in Social** (or Social › Party › Choose Voice
   Channels) › a server: every voice channel is hidden until you turn it on (A shows / hides it),
   so Party only lists the ones you use.
3. **Open Discord** shows the full client (text chat, friends) with controller keys and the
   on-screen keyboard; the Quick Menu brings you back.

**Calling a friend** (Social › Friends › Discord › A) uses Discord's own "start call" for your DM with
them, the same thing its call button does, so it rings them; a DM is created first if you've never
messaged them.

**Share Screen** (Social, or the Quick Menu while you're in a call) goes live with what's on the TV.
The screen is picked for you (there's no picker to click on a TV); it uses the wlroots screen-capture
portal, which Crossbar sets up for its own session only (Plasma and gaming mode keep theirs).

Automating your own Discord client is a grey area in Discord's terms; Crossbar only does what you
ask for (join, leave, mute) and never reads or sends messages on its own.

## Emulation

**Game › Emulation** has **ROMs** (a folder per system, shown once it has games; A plays) and
**Emulators** (install / uninstall, from Flathub; DuckStation and Eden as their official AppImages). Games
launch like any other: the "Starting…" screen, the memory-saving game mode, and the Quick Menu's
Close to quit. Folder layout is EmuDeck's, so an existing EmuDeck folder works as-is:

```
~/Emulation/roms/<system>/   nes snes n64 gb gbc gba nds n3ds gc wii wiiu mastersystem genesis segacd
                             gamegear saturn dreamcast psx ps2 ps3 psp switch xbox pcengine atari2600 arcade scummvm
~/Emulation/bios/            BIOS / firmware files
~/Emulation/bios/switch/     keys/prod.keys (+ title.keys) and firmware/*.nca for Switch games
```

ROMs show a tag with their system ([SNES], [PS2], [SWITCH]…) like store games do; **Y › Edit Tag…**
changes or hides it.

**Nintendo Switch** runs on [Eden](https://git.eden-emu.dev/eden-emu/eden): Emulators › Eden installs
the newest stable AppImage (the Steam Deck build on Zen 2 machines like the PS5). Put your
`prod.keys` / `title.keys` in `bios/switch/keys` and firmware `.nca` files in `bios/switch/firmware`;
Crossbar copies them into Eden before each game. BIOS Files shows whether they're there.

**Settings › Games & Emulation › Emulation**: the folder, **BIOS Files** (checked per system, with what's missing),
**Emulator Settings & Controls** (opens each emulator to map buttons; pads are detected
automatically), **Default Emulator per System**, **Aspect Ratio**, **Pixel-Perfect Scaling** and
**RetroAchievements** (sign in once; emulators get a login token, not your password). Crossbar writes
these into RetroArch, Dolphin, PCSX2, DuckStation and PPSSPP's own settings.

## Trophies

**Game › Trophies**: **RetroAchievements** by console (your points and rank, each game's progress,
every badge) once you add your Web API key (retroachievements.org › Settings › Keys), and **Steam**
achievements per game with a free Steam Web API key (steamcommunity.com/dev/apikey; your profile's
Game details must be public). GOG and Epic aren't listed: they don't share achievements with other apps.

While you play, **Quick Menu › Trophies** shows the running game's list (Steam, or RetroAchievements
for the game your emulator is running), even when the emulator shows its own pop-ups.

## On-screen keyboard

Text fields open a QWERTY keyboard when you're using a controller. The buttons work like a
PlayStation's keyboard (by button position, whatever controller you use):

| ✕ | ○ | □ | △ | L1 / R1 | L2 | L3 | R2 or Options |
|---|---|---|---|---|---|---|---|
| type | close | backspace | space | move the cursor | shift (twice: caps) | symbols | done |

Touch a real keyboard or mouse and it closes.
In other apps it opens by itself in apps that support Wayland's text-input (GTK, Qt, and Crossbar's
own web windows like Discord and TV apps), typing any character; anywhere else use **Quick Menu ›
Keyboard**. It stays away from Steam, which has its own.

## Internet browser

**TV & Video › Internet Browser** is Chromium, full screen, driven by Crossbar so the controller
works on any site:

| Button | In the browser |
|---|---|
| D-pad / left stick | jump between links, buttons and fields (a big blue highlight shows where you are) |
| A | open it · on a text box, the on-screen keyboard, which types straight into the page |
| B | back |
| L1 / R1 | previous / next tab |
| Right stick · L2 / R2 | scroll · page up / down |
| L3 | pointer mode, for sites that need a cursor (A clicks) |
| Start | search or type an address |
| Y | the browser menu: address, back/forward, reload, tabs, bookmark this page, pointer, size, close |

Everything is drawn big enough to read from the couch: 125% at 1080p and 250% at 4K by default.
Change it with Y › Size (◀ ▶) or **Settings › Media › Browser**; the browser reopens with your tabs.
The start page has your bookmarks (add with Y › Bookmark This Page, remove in Settings › Media › Browser).
TV services (YouTube TV, Jellyfin, your own) still open as full-screen apps.

## Downloads

Downloads show their speed and time left (from Steam's, legendary's and GOG's own numbers). To stop one,
highlight it and press **A** (or **Y › Cancel Download**): it stops and what was downloaded is deleted.
- **GOG**, **Epic** and emulators: stopped and cleaned up by Crossbar (an Epic *update* is only stopped;
  the installed game is never deleted).
- **Steam**: new installs only; Steam itself removes the partial game (it may ask you to confirm).

## Apps

**Apps** shows what's open right now first (A switches to it, Y › Close / Force Close), then your
Flatpaks and AppImages (A opens; Y › Show In… moves an app to another category, Change Artwork…,
Uninstall). Emulators installed from Game › Emulation stay there.

**Store › Install Apps** (also at the bottom of Apps):
- **Flatpak (Flathub)** — Search, Popular, Trending, New Apps, Recently Updated and Categories, with
  each app's description and screenshots. Installs are for your user (no password), with progress
  and Cancel. You pick the category it shows up in (Apps, Game, TV & Video Services, Video, Music,
  Photo or Social).
- **AppImage** — browse to an `.AppImage` (Downloads, a USB stick, a network drive). It's moved to
  `~/Applications`, made runnable, and its name and icon are read from inside it. Pick a category
  the same way.

## Torrents

**Apps › Torrents** is a torrent client made for the controller and the TV, running qBittorrent's
engine (qbittorrent-nox) in the background, reachable only from this machine.
- **Search**: press to search; **Options** (Y / △) on it turns each installed plugin on or off for
  searches. Categories other than Everything only use the plugins that have them.
- Search goes through your **search plugins**: Search Plugins › Get Official Plugins, or
  **Get Community Plugins** (the list on the [qBittorrent wiki](https://github.com/qbittorrent/search-plugins/wiki/Unofficial-search-plugins),
  public and private sites). Plugins for private sites ask for your account when they're installed
  (Y › Sign In… later); it's written into the plugin's own settings. Community plugins are code
  written by other people: only install ones you trust.
- **Downloading / Finished & Seeding / All**: live progress, speed and time left. A or Y on one:
  pause, files (skip or prioritise), download in order (watch while it downloads), force start,
  speed limit, recheck, remove (with or without the files).
- **Add a Torrent**: a magnet link or a `.torrent` file (Downloads, USB stick…).
- **Settings**: download folder; **Network & VPN** (only use the VPN — no VPN, no torrent traffic —,
  a network interface, the VPN's forwarded port as the listening port, UPnP); speed limits and slow
  mode; queue; seeding limits; connections, encryption, DHT / PeX / LSD, anonymous mode; adding
  paused; notifications; keep seeding in the background.

## VPN and speed test

**Settings › Network & Bluetooth › Network › VPN** connects with WireGuard or OpenVPN itself
(through NetworkManager) — no VPN company's app.
- **Private Internet Access**: sign in with your username and password; every region with its
  latency; WireGuard or OpenVPN; **port forwarding** (kept alive every 15 minutes, and handed to
  the torrent client). Follows PIA's own [manual-connections](https://github.com/pia-foss/manual-connections) scripts.
- **Mullvad** (account number) and **NordVPN** (access token): sign in, pick a city or country.
- **Proton VPN, Surfshark, Windscribe, IVPN, AirVPN, ExpressVPN, your own server**: import the
  WireGuard `.conf` / OpenVPN `.ovpn` files from your account page (a folder or `.zip` of them gives
  you several locations). Proton's port forwarding (NAT-PMP) works too.
- **Split Tunneling** (on by default): nothing uses the VPN except the apps and sites you add —
  Torrents, Steam and its games, other games, Discord, the browser, AppImages — and their DNS goes
  through the VPN too. Turn it off and everything uses the VPN. Apps that use the VPN are started
  (through util-linux's `newgrp`) in a `crossbar-vpn` group which the firewall routes through the VPN (created once, with your
  password); Crossbar's own checks use your normal line. **Check Split Tunneling** shows whether
  it's working.
- **Leak Tests**: a torrent IP leak test (your torrent engine announces a made-up torrent to
  [WhatIsMyIP.net's tracker checker](https://www.whatismyip.net/tools/torrent-ip-checker/); Crossbar shows the address it saw
  next to yours without the VPN) and a DNS leak test ([bash.ws](https://bash.ws/dnsleak)).
- **Connect at Startup**, **Check My Address** (what VPN apps and everything else are seen as). Passwords, tokens and keys stay in a file only you
  can read.

**Internet Speed Test** (same menu) measures download, upload, latency and jitter against
Cloudflare's nearest server — through the VPN when it's on.

## Folders

Make your own folders in any category (Game, Apps, Music…): highlight anything, **Y › Move to
Folder… › Into a New Folder…**. Y on a folder renames or deletes it (what's inside goes back to the
list); Y on something inside takes it out again.

## Artwork (SteamGridDB)

Highlight any game or app — Steam, GOG, Epic, a ROM, a Flatpak or AppImage — press **Y** and choose
**Change Artwork…** to pick from [SteamGridDB](https://www.steamgriddb.com)'s community artwork,
search under a different name, use **Local File…** (any picture on the console, a USB stick or a
network drive; no API key needed), or go back to the original. Needs a free API key (steamgriddb.com › sign in › Preferences › API),
added in **Settings › Games & Emulation › Artwork**. With the key, games that have no picture (most
ROMs, some GOG / Epic games) get one automatically in the background (turn off with **Fill In
Missing Artwork**). Your picks are kept in Crossbar's settings; **Reset All Artwork** undoes them.

## Games

Sign in to **Steam, GOG and Epic** in **Settings › Accounts**; your libraries then show
in **Store**, and installed games in **Game**.

- If Steam isn't running yet — or is updating itself — Crossbar starts it first, shows Steam's
  update progress on the "Starting…" screen, and only sends the game once Steam is fully up
  (a game sent while Steam updates is otherwise lost).
- **Steam** games launch through **Big Picture** (Steam's console mode) by default, so Steam Input
  and Steam's overlay work like on a Steam Deck. When the game ends — or you close it from the
  Quick Menu — Steam is tucked away and you're back in Crossbar. (Toggle in Game Settings.)
- **If a game won't start**, the error comes from the game itself (for example a missing file or a
  Wine/Proton message) instead of just "didn't open a window"; full output is in `~/.cache/crossbar-games.log`.
- **GOG** Windows games install from GOG's own installers (unpacked with innoextract) and run with
  Proton through **umu-launcher**; native Linux builds are used when GOG has one.
- **Epic** games run through the same Proton setup (legendary + umu).
- **Settings › Games & Emulation › Game Settings › Windows Games**: choose the default tool (UMU-Proton, newest
  GE-Proton, a GE-Proton version you download there, Steam's Proton, or Wine). Per game:
  Y › *Compatibility Tool…*. Each game gets its own prefix in `~/Games/prefixes`.
- Closing a game from the Quick Menu asks it to quit, and ends it if it hangs.
- **Lutris**: games you've added in Lutris (the Flathub version or your distro's) show up in Game and
  start through Lutris, so its runners and Wine settings apply.
- **Non-Steam games** you've added to Steam show up too (with their Steam grid art) and start through
  Steam, so Proton settings you gave them there apply.
- Both can move to another category with **Y › Show In…**. Every game has a tag next to its name
  ([STEAM], [GOG], [LUTRIS], [NON-STEAM]…): **Y › Edit Tag…** renames or hides it.
- **Y › Launch Options…** on Windows games (Steam, Lutris, GOG, Epic): environment variables, a launch
  command (`gamemoderun %command% -dx11`), the Proton / Wine version and common switches (MangoHud,
  GameMode, Proton log…). Steam's go into Steam's own settings, Lutris' into Lutris'.
- **Y › Hide** takes any game, app or ROM off the XMB; Settings › Games & Emulation › Game Settings ›
  Hidden Games & Apps brings it back.
- **Compatibility Tools** (Settings › Games & Emulation › Game Settings › Windows Games): the
  tools [ProtonUp-Qt](https://github.com/DavidoTek/ProtonUp-Qt) installs — GE-Proton, Proton-CachyOS,
  Luxtorpeda and Boxtron for Steam; Wine-GE, Kron4ek Wine, Lutris-Wine, DXVK and vkd3d-proton for
  Lutris — with progress, cancel and remove. ProtonUp-Qt itself is one press away there too.

Launching shows a *Starting…* screen until the game's window appears, then hands over. Steam runs
in the background with its library window tucked away, and **Steam's overlay works normally**
inside Steam games. GOG and Epic games can optionally run in gamescope (Settings › Games & Emulation › Game Settings).
When a game closes you're back in the menu.

## Files, network drives, IPTV

- **Users › File Browser** — your home folder, USB drives and network drives: open media,
  copy / cut / paste, rename, new folder, move to Trash (restorable) or delete permanently.
- **Settings › Network Settings › Network Drives** — add an SMB (Windows/Samba, most NAS boxes) or
  NFS share: server, share, username, password (or paste the whole address, like `\\nas\Media` or
  `//192.168.0.50/Media`). The connection is tested first and nothing is saved if it fails; you get the
  reason (NAS unreachable, wrong share name with the list of shares it has, wrong password, or an
  old NAS that only speaks SMB1, which is then used automatically). It's written to `/etc/fstab` as an on-demand mount
  under `/mnt/nas/<name>` (with `nofail`, so an offline NAS never blocks boot); the password lives in
  a root-only file in `/etc/crossbar/nas/`, never in fstab. Use a drive as your Music/Video/Photo
  folder from its options.
- **IPTV (Xtream Codes)** — **Settings › Media › IPTV**: sign in with the server, username
  and password from your provider, then choose which **Live TV**, **Movie** and **TV Show**
  categories appear (and hide channels you don't want). Live TV shows under TV & Video Services
  (L1/R1 change channel while watching); Movies and TV Shows under Video.
  Big Movie / TV Show categories are shown 60 titles at a time (**More…** at the end).
  If sign-in times out, use the exact address your provider gave **including the port**
  (e.g. `http://example.com:8080`); without one, Crossbar tries the usual Xtream ports (8080,
  25461, 8000, 80). Requests identify as VLC, since many providers block unknown players.

## Settings

The Settings column groups related sections: **Display & Sound**, **Network & Bluetooth**,
**Controller & Keyboard**, **Games & Emulation** (Game Settings, Artwork, Emulation), **Media**,
**Accounts**, **Theme & Time** and **System** (with PS5 Hardware on a PS5).

| Section | What's in it |
|---|---|
| Display | Resolution, refresh rate, scale per screen; new modes auto-revert after 15 s unless you choose Keep. Screens that report no modes get common sizes as custom modes, rate shown as Auto |
| Sound | Output device, input (mic) device, volumes, menu sounds |
| Network | Status, Wi-Fi on/off, scan, connect, disconnect, forget; VPN; speed test; network drives (SMB/NFS) |
| Bluetooth | On/off, find devices, pair controllers and headsets, connect, forget |
| Controller & Keyboard | Remap every button and key, button combos, Guide/PS option, swap Select/Back, diagnostics |
| Game Settings | Windows games (Proton/Wine picker, GE-Proton downloads), Big Picture launching, gamescope, free memory while gaming, Memory Guard, frame rate overlay, demo library |
| Artwork | SteamGridDB API key, fill in missing artwork, reset all |
| Theme | Interface (cross-media bar or Dashboard), then that look's settings — Dashboard: background and accent colour; cross-media bar: wave colour — plus theme packs (stock and your own, install from a folder or .zip) — see [Interfaces](#interfaces) and [THEMES.md](THEMES.md) |
| Media | Music / Video / Photo folders, IPTV, resume videos, subtitles default |
| Date & Time | Time zone, automatic time, 12/24-hour clock |
| Accounts | Steam, GOG, Epic sign-in; Spotify; Discord (sign in, which voice channels show in Social); user name |
| System | Terminal, **Restart Crossbar** (restarts every Crossbar piece — useful while testing), **Exit Crossbar**, update, share support report, system information, install to disk |

Everything is set inside Crossbar — no separate settings apps. Under the hood these are the same
system services KDE Plasma's settings use (NetworkManager, BlueZ, PipeWire, systemd), driven
directly.

## How the stores connect

Starts in **demo mode** with sample games so everything is clickable. Turn it off in
Settings › Demo Library, then sign in from Store.

| Store | Sign-in | Downloads | Launch |
|---|---|---|---|
| Steam | SteamID64 + Web API key lists your library; the Steam client signs in on first install | Steam client (`steam://install`), progress read from its appmanifest files | `steam://rungameid` |
| GOG | Official GOG sign-in page in a web view (same OAuth flow Minigalaxy/Heroic use) | Native Linux installers via GOG's API | `start.sh` |
| Epic | Epic sign-in page in a web view → `legendary auth` | `legendary install`, live progress | `legendary launch` (Wine) |

Everything lives under `~/Games`, which in the VM is the 64 GB `games.qcow2` disk. Steam,
legendary and Crossbar settings are kept there too, so they survive reboots of the live ISO.

## Party chat

Pick a voice service (Discord app or web, Mumble, TeamSpeak, Element), hit **Start Party**, and
press Home to come back to the XMB while voice keeps running. **Quick Join** stores channel
links (paste a `discord.com/channels/…` link and it opens in the Discord app).
