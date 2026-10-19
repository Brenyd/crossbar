# Changelog

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

