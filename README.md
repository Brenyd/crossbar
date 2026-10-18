# Crossbar — prototype 0.1

An Arch-based live distro that boots straight into a console-style cross-media-bar shell:
flowing month-coloured waves, categories across, items down, folders, a △-style options
panel, and gamepad control. One Game list merges Steam, GOG and Epic; a Store category
downloads from all three; a Party category starts your voice app of choice.

![Game category](docs/game.png)

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
| Back to the XMB from a game or Discord | Super+Esc | Guide / PS button |
| Terminal (debugging) | Ctrl+Alt+T | |

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
shell/crossbar/system.py      sway window control, Guide-button daemon, audio, power
shell/crossbar/party.py       voice services + channels
shell/crossbar/login_helper.py  web-view window for GOG/Epic sign-in
shell/web/                    the XMB (HTML/CSS/JS, canvas waves)
iso/                          archiso overlay: packages, autologin, sway session, boot setup
```

Boot path: autologin `player` on tty1 → sway (tabbed, so one app is visible at a time) →
`crossbar-shell` starts the backend and a kiosk Chromium window → the XMB.

## Known gaps (next steps)

- GOG Windows-only games and Epic games run through plain Wine; Proton/umu integration is next.
- Steam owned-games listing needs a Web API key; a QR/password login through the client would be smoother.
- No on-screen keyboard yet — text fields need a physical keyboard.
- The installer erases the whole disk (no dual-boot), and NVIDIA drivers aren't included yet.
- Party is a launcher, not an in-game overlay (Discord's API doesn't allow a third-party voice UI).
