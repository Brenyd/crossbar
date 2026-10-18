# Crossbar — prototype 0.5

An Arch-based live distro that boots straight into a console-style cross-media-bar shell:
flowing month-coloured waves, categories across, items down, folders, a △-style options
panel, and gamepad control.

Categories, in the original order: **Users · Settings · Photo · Music · Video ·
TV & Video Services · Game · Network · Store · Party**. One Game list merges Steam, GOG and
Epic; Store downloads from all three; Music plays your files and Spotify; Video plays
anything mpv can, with a controller-friendly control panel.

![Game category](docs/game.png)

![Music category](docs/music.png)

## Run it

**Full install guide (virt-manager and bare metal): [docs/INSTALL.md](docs/INSTALL.md)**

**Quickest — on your current desktop, no ISO (demo library):**

```bash
git clone https://github.com/Brenyd/crossbar.git && cd crossbar
./dev-run.sh            # opens the shell in a Chromium app window
./dev-run.sh --real     # use your real accounts (needs steam / legendary installed)
```

**Build the ISO** (on Arch or CachyOS; needs ~15 GB free and downloads ~3 GB):

```bash
./build-iso.sh          # -> out/crossbar-YYYY.MM.DD-x86_64.iso
./build-in-docker.sh    # same, from any distro with Docker or Podman
```

**Boot it in a VM:**

```bash
./run-vm.sh                     # QEMU/KVM, virgl 3D, 8 GB RAM, 64 GB games disk
NOGL=1 ./run-vm.sh              # if the window is black (no virgl on your host)
PAD=054c:0ce6 ./run-vm.sh       # pass a USB controller through (ids from `lsusb`)
```

To install permanently, open **Settings › Install to Disk** from the live system
(UEFI only, erases the chosen disk). See [docs/INSTALL.md](docs/INSTALL.md).

## Controls

| Action | Keyboard | Gamepad |
|---|---|---|
| Move | Arrow keys | D-pad / left stick |
| Enter | Enter | A / ✕ |
| Back | Esc | B / ○ |
| Options | Tab | Y / △ |
| Quick Menu (from anywhere) | Home, or Super+Esc | Guide / PS button |
| Play/Pause, previous, next track (in the XMB) | P, Page Up, Page Down | Start, L1, R1 |
| Terminal (debugging) | Ctrl+Alt+T | |

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

### If the controller works in the menu but not in videos, web apps or the Quick Menu

Check `systemctl status crossbar-inputd` (it should be *active*). Without it Crossbar falls
back to reading the controller directly, which needs permissions.
**Settings › Controller & Keyboard › Controller Diagnostics** shows what Crossbar sees and
the last buttons it received. For a full report press Ctrl+Alt+T and run `crossbar-doctor`.
The ISO ships a udev rule (`/etc/udev/rules.d/70-crossbar-input.rules`) that gives the
console user access to controllers and `/dev/uinput`. On an existing install, copy that rule
in and reboot. In a VM, pass the controller through as a USB device.

## Quick Menu

Press **Guide/PS** (or **Home**) during a game, video or app. The Quick Menu slides in
**on top of** whatever is running (a real overlay on the Wayland overlay layer, so it works
over fullscreen games and video), with:

- **Resume** / **Close** the game or video (closing returns you straight to the XMB)
- **Go to Home** — the XMB, leaving the game open
- **Now Playing** — your music or Spotify: ◀ ▶ skip, A play/pause
- **Volume** (◀ ▶, A mutes), **Sound Output** switch, **Microphone** mute
- **Controller & Keyboard**, **Network**, **Power**

B resumes what you were doing.
**While a video plays** (panel hidden): A pause · ◀/▶ seek −10 s/+30 s · ▲/▼ volume ·
L1/R1 previous/next · Y show panel · B jump to Stop. With the panel open, ◀/▶ pick a
button (previous, rewind, play/pause, forward, next, subtitles, audio track, stop), A presses
it, B hides it. Videos resume where you stopped (toggle in Settings › Media Settings).

**Photo viewer:** ◀/▶ browse · A slideshow · Y hide captions · B back.

## Music, Video, Photo

Pick your library folders in **Settings › Media Settings** (defaults `~/Music`, `~/Videos`,
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

## Settings

| Section | What's in it |
|---|---|
| Display | Resolution, refresh rate, scale per screen; new modes auto-revert after 15 s unless you choose Keep |
| Sound | Output device, input (mic) device, volumes, menu sounds |
| Controller & Keyboard | Remap every button and key, swap Select/Back, connected controllers |
| Theme | Background colour, or automatic by month |
| Media | Music / Video / Photo folders, resume videos, subtitles default |
| Network | Connection status, Wi-Fi scan and connect |
| Accounts | User name, Spotify |
| System | Demo library, system information, install to disk |

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

## Layout

```
shell/server.py               backend: JSON API + serves the UI (stdlib only)
shell/crossbar/providers/     steam.py, gog.py, epic.py, demo.py
shell/crossbar/system.py      sway windows, audio devices, Wi-Fi, power
shell/crossbar/gamepad.py     reads every controller, applies the mapping, routes to what's in front
shell/crossbar/controls.py    button/key mapping (~/.config/crossbar/controls.json)
shell/crossbar/quick.py       Quick Menu: open over the app in front, resume / close it
shell/inputd.py               crossbar-inputd: root controller service (grab, virtual keyboard)
shell/overlay.py              crossbar-overlay: GTK4 layer-shell window hosting web/overlay.html
shell/crossbar/media.py       library folders, tags, thumbnails, folder picker
shell/crossbar/player.py      mpv music (hidden) and video (full screen) over IPC
shell/crossbar/spotify.py     librespot Connect speaker + Spotify Web API
shell/crossbar/display.py     resolution / refresh / scale via sway
shell/crossbar/party.py       voice services + channels
shell/mpv/crossbar-osc.lua    the controller-friendly video control panel
shell/crossbar/login_helper.py  web-view window for GOG/Epic sign-in
shell/web/                    the XMB: xmb.js (core), media.js (Photo/Music/Video/TV/Network), quick.js, settings.js
iso/                          archiso overlay: packages, autologin, sway session, boot setup
```

Boot path: autologin `player` on tty1 → sway (tabbed, so one app is visible at a time) →
`crossbar-shell` starts the backend and a kiosk Chromium window → the XMB.

## Known gaps (next steps)

- GOG Windows-only games and Epic games run through plain Wine; Proton/umu integration is next.
- Steam owned-games listing needs a Web API key; a QR/password login through the client would be smoother.
- No on-screen keyboard yet — text fields (Wi-Fi password, Spotify Client ID, search) need a physical keyboard.
- Netflix/Disney+/Spotify's web player need Widevine DRM, which Arch's Chromium doesn't ship.
- In the YouTube TV interface the controller works only if the site picks it up; arrow keys always work.
- The installer erases the whole disk (no dual-boot), and NVIDIA drivers aren't included yet.
- Party is a launcher, not an in-game overlay (Discord's API doesn't allow a third-party voice UI).
