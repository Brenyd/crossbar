"""Emulation, EmuDeck-style: one folder layout, emulators from Flathub, games per system.

Layout (the same as EmuDeck, so an existing EmuDeck folder just works):
    ~/Emulation/roms/<system>/   your games       ~/Emulation/bios/   BIOS / firmware files
    ~/Emulation/tools/           AppImages (DuckStation)
Emulators install as Flatpaks (per user, no root) and get access to that folder; RetroArch
cores are downloaded from the libretro buildbot. Defaults Crossbar can set for you: aspect
ratio, RetroAchievements sign-in (emulators that support it) and BIOS folders.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
import zipfile

from . import util

HOME = os.path.expanduser("~")
FLATHUB = "https://dl.flathub.org/repo/flathub.flatpakrepo"
CORE_URL = "https://buildbot.libretro.com/nightly/linux/x86_64/latest/{core}_libretro.so.zip"
DUCKSTATION_URL = "https://github.com/stenzek/duckstation/releases/download/latest/DuckStation-x64.AppImage"


def root():
    return os.path.expanduser(util.load_config().get("emulation", {}).get("root") or "~/Emulation")


def roms_dir():
    return os.path.join(root(), "roms")


def bios_dir():
    return os.path.join(root(), "bios")


# ---- emulators ------------------------------------------------------------------------------
# kind: flatpak | appimage. "run": argv after the launcher; {rom} is the game, {core} a RetroArch core.
EMULATORS = {
    "retroarch": {"name": "RetroArch", "kind": "flatpak", "id": "org.libretro.RetroArch",
                  "run": ["-f", "-L", "{core}", "{rom}"], "about": "Many classic systems through cores"},
    "dolphin": {"name": "Dolphin", "kind": "flatpak", "id": "org.DolphinEmu.dolphin-emu",
                "run": ["-b", "-e", "{rom}"], "about": "GameCube and Wii"},
    "pcsx2": {"name": "PCSX2", "kind": "flatpak", "id": "net.pcsx2.PCSX2",
              "run": ["-fullscreen", "-batch", "--", "{rom}"], "about": "PlayStation 2"},
    "rpcs3": {"name": "RPCS3", "kind": "flatpak", "id": "net.rpcs3.RPCS3",
              "run": ["--no-gui", "{rom}"], "about": "PlayStation 3"},
    "ppsspp": {"name": "PPSSPP", "kind": "flatpak", "id": "org.ppsspp.PPSSPP",
               "run": ["--fullscreen", "{rom}"], "about": "PSP"},
    "duckstation": {"name": "DuckStation", "kind": "appimage", "url": DUCKSTATION_URL, "file": "DuckStation-x64.AppImage",
                    "run": ["-fullscreen", "-batch", "{rom}"], "about": "PlayStation (standalone)"},
    "cemu": {"name": "Cemu", "kind": "flatpak", "id": "info.cemu.Cemu", "run": ["-f", "-g", "{rom}"], "about": "Wii U"},
    "azahar": {"name": "Azahar", "kind": "flatpak", "id": "org.azahar_emu.Azahar", "run": ["-f", "{rom}"], "about": "Nintendo 3DS"},
    "melonds": {"name": "melonDS", "kind": "flatpak", "id": "net.kuribo64.melonDS", "run": ["-f", "{rom}"], "about": "Nintendo DS"},
    "xemu": {"name": "xemu", "kind": "flatpak", "id": "app.xemu.xemu", "run": ["-full-screen", "-dvd_path", "{rom}"], "about": "Original Xbox"},
    "flycast": {"name": "Flycast", "kind": "flatpak", "id": "org.flycast.Flycast", "run": ["{rom}"], "about": "Dreamcast"},
    "scummvm": {"name": "ScummVM", "kind": "flatpak", "id": "org.scummvm.ScummVM",
                "run": ["--fullscreen", "--auto-detect", "--path={rom}"], "about": "Classic adventure games"},
}

# ---- systems (folder names as in EmuDeck / ES-DE) ---------------------------------------------
# emus: [(emulator, core or None)], first is the default. bios: [(file, required)]; "any" groups
# mean one of them is enough.
SYSTEMS = {
    "nes": {"name": "NES", "exts": "nes zip 7z", "emus": [("retroarch", "mesen"), ("retroarch", "nestopia")]},
    "snes": {"name": "Super Nintendo", "exts": "sfc smc zip 7z", "emus": [("retroarch", "snes9x")]},
    "n64": {"name": "Nintendo 64", "exts": "n64 z64 v64 zip 7z", "emus": [("retroarch", "mupen64plus_next")]},
    "gb": {"name": "Game Boy", "exts": "gb zip 7z", "emus": [("retroarch", "gambatte"), ("retroarch", "mgba")]},
    "gbc": {"name": "Game Boy Color", "exts": "gbc zip 7z", "emus": [("retroarch", "gambatte"), ("retroarch", "mgba")]},
    "gba": {"name": "Game Boy Advance", "exts": "gba zip 7z", "emus": [("retroarch", "mgba")],
            "bios": [("gba_bios.bin", False)]},
    "nds": {"name": "Nintendo DS", "exts": "nds zip", "emus": [("melonds", None), ("retroarch", "melondsds")],
            "bios": [("bios7.bin", False), ("bios9.bin", False), ("firmware.bin", False)]},
    "n3ds": {"name": "Nintendo 3DS", "exts": "3ds cci cxi 3dsx app", "emus": [("azahar", None)]},
    "gc": {"name": "GameCube", "exts": "iso gcm rvz gcz ciso", "emus": [("dolphin", None)]},
    "wii": {"name": "Wii", "exts": "iso wbfs rvz gcz", "emus": [("dolphin", None)]},
    "wiiu": {"name": "Wii U", "exts": "wua wud wux rpx", "emus": [("cemu", None)]},
    "mastersystem": {"name": "Master System", "exts": "sms zip 7z", "emus": [("retroarch", "genesis_plus_gx")]},
    "genesis": {"name": "Genesis / Mega Drive", "exts": "md gen smd bin zip 7z", "emus": [("retroarch", "genesis_plus_gx")]},
    "segacd": {"name": "Sega CD", "exts": "chd cue iso m3u", "emus": [("retroarch", "genesis_plus_gx")],
               "bios": [("bios_CD_U.bin", "any"), ("bios_CD_E.bin", "any"), ("bios_CD_J.bin", "any")]},
    "gamegear": {"name": "Game Gear", "exts": "gg zip 7z", "emus": [("retroarch", "genesis_plus_gx")]},
    "saturn": {"name": "Saturn", "exts": "chd cue m3u", "emus": [("retroarch", "mednafen_saturn")],
               "bios": [("sega_101.bin", "any"), ("mpr-17933.bin", "any")]},
    "dreamcast": {"name": "Dreamcast", "exts": "chd cdi gdi m3u", "emus": [("flycast", None), ("retroarch", "flycast")],
                  "bios": [("dc/dc_boot.bin", False), ("dc/dc_flash.bin", False)]},
    "psx": {"name": "PlayStation", "exts": "chd cue pbp m3u iso", "emus": [("retroarch", "swanstation"), ("duckstation", None),
                                                                           ("retroarch", "mednafen_psx_hw")],
            "bios": [("scph5501.bin", "any"), ("scph5500.bin", "any"), ("scph5502.bin", "any"), ("scph1001.bin", "any")]},
    "ps2": {"name": "PlayStation 2", "exts": "iso chd cso gz", "emus": [("pcsx2", None)], "bios": [("ps2:*", True)]},
    "ps3": {"name": "PlayStation 3", "exts": "dir", "emus": [("rpcs3", None)]},
    "psp": {"name": "PSP", "exts": "iso cso pbp chd", "emus": [("ppsspp", None)]},
    "xbox": {"name": "Xbox", "exts": "iso xiso", "emus": [("xemu", None)],
             "bios": [("mcpx_1.0.bin", True), ("Complex_4627.bin", True)]},
    "pcengine": {"name": "PC Engine / TurboGrafx", "exts": "pce cue chd zip", "emus": [("retroarch", "mednafen_pce_fast")],
                 "bios": [("syscard3.pce", False)]},
    "atari2600": {"name": "Atari 2600", "exts": "a26 bin zip", "emus": [("retroarch", "stella")]},
    "arcade": {"name": "Arcade", "exts": "zip 7z", "emus": [("retroarch", "fbneo"), ("retroarch", "mame2003_plus")],
               "bios": [("neogeo.zip", False)]},
    "scummvm": {"name": "ScummVM", "exts": "dir", "emus": [("scummvm", None)]},
}
SKIP = re.compile(r"\.(txt|nfo|jpg|png|xml|sav|srm|state\d*|dat|db)$", re.I)


# ---- what's installed --------------------------------------------------------------------------
def _flatpaks():
    if not util.which("flatpak"):
        return set()
    r = subprocess.run(["flatpak", "list", "--app", "--columns=application"], capture_output=True, text=True, timeout=30)
    return set(r.stdout.split())


def _appimage(e):
    return os.path.join(root(), "tools", e["file"])


def installed():
    fl = _flatpaks()
    out = {}
    for k, e in EMULATORS.items():
        out[k] = e["id"] in fl if e["kind"] == "flatpak" else os.access(_appimage(e), os.X_OK)
    return out


def emulators():
    inst = installed()
    uses = {}
    for sid, s in SYSTEMS.items():
        for emu, _ in s["emus"]:
            uses.setdefault(emu, []).append(s["name"])
    return [{"id": k, "name": e["name"], "about": e["about"], "installed": inst[k], "kind": e["kind"],
             "systems": uses.get(k, [])} for k, e in EMULATORS.items()]


# ---- installing ------------------------------------------------------------------------------------
def install(job, emu):
    e = EMULATORS[emu]
    os.makedirs(roms_dir(), exist_ok=True)
    if e["kind"] == "flatpak":
        if not util.which("flatpak"):
            raise RuntimeError("Flatpak isn't installed (sudo pacman -S flatpak)")
        job.set(0.05, "Adding Flathub…")
        subprocess.run(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB],
                       capture_output=True, text=True, timeout=120)
        job.set(0.15, f"Installing {e['name']} (this can take a few minutes)…")
        r = subprocess.run(["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", e["id"]],
                           capture_output=True, text=True, timeout=3600)
        if r.returncode:
            raise RuntimeError((r.stderr or r.stdout).strip()[-200:] or "flatpak install failed")
        # let it read your games and BIOS folder (Flatpaks are sandboxed)
        subprocess.run(["flatpak", "override", "--user", f"--filesystem={root()}", e["id"]], capture_output=True)
    else:
        os.makedirs(os.path.dirname(_appimage(e)), exist_ok=True)
        job.set(0.1, f"Downloading {e['name']}…")
        util.download(e["url"], _appimage(e), lambda f: job.set(0.1 + 0.8 * f, f"Downloading {e['name']} {int(f * 100)}%"))
        os.chmod(_appimage(e), 0o755)
    job.set(0.95, "Setting it up…")
    try:
        apply_defaults(emu)
    except Exception as ex:
        print(f"emulation: defaults for {emu}: {ex}", flush=True)


def uninstall(emu):
    e = EMULATORS[emu]
    if e["kind"] == "flatpak":
        r = subprocess.run(["flatpak", "uninstall", "--user", "-y", "--noninteractive", e["id"]],
                           capture_output=True, text=True, timeout=600)
        if r.returncode:
            raise RuntimeError((r.stderr or r.stdout).strip()[-200:])
    else:
        try:
            os.remove(_appimage(e))
        except OSError:
            pass


RA_CORES = os.path.join(HOME, ".var/app/org.libretro.RetroArch/config/retroarch/cores")


def core_path(core):
    return os.path.join(RA_CORES, f"{core}_libretro.so")


def ensure_core(core, job=None):
    path = core_path(core)
    if os.path.exists(path):
        return path
    os.makedirs(RA_CORES, exist_ok=True)
    if job:
        job.set(0.3, f"Downloading the {core} core…")
    tmp = path + ".zip"
    util.download(CORE_URL.format(core=core), tmp, lambda f: None)
    with zipfile.ZipFile(tmp) as z:
        z.extract(os.path.basename(path), RA_CORES)
    os.remove(tmp)
    return path


# ---- games -------------------------------------------------------------------------------------------
def _title(name):
    stem = re.sub(r"\.[^.]+$", "", name) if not os.path.isdir(name) else name
    clean = re.sub(r"\s*[\[(][^\])]*[\])]", "", stem).strip() or stem
    tags = ", ".join(t for t in re.findall(r"[\[(]([^\])]*)[\])]", stem) if not re.fullmatch(r"!|a\d*|b\d*|h\d*", t))
    return clean, tags


def games(system):
    s = SYSTEMS[system]
    folder = os.path.join(roms_dir(), system)
    if not os.path.isdir(folder):
        return []
    out = []
    if s["exts"] == "dir":                                  # PS3 / ScummVM: one folder per game
        for d in sorted(os.listdir(folder)):
            p = os.path.join(folder, d)
            if os.path.isdir(p) and not d.startswith("."):
                title, tags = _title(d)
                out.append({"id": d, "title": title, "tags": tags})
        return out
    exts = set(s["exts"].split())
    files = []
    for dirpath, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() not in ("media", "images", "videos", "manuals")]
        for n in names:
            if not n.startswith(".") and not SKIP.search(n) and n.rsplit(".", 1)[-1].lower() in exts:
                files.append(os.path.relpath(os.path.join(dirpath, n), folder))
    names_lower = {f.lower() for f in files}
    in_m3u = set()
    for f in files:                                        # discs listed in a playlist show once, as the playlist
        if f.lower().endswith(".m3u"):
            try:
                for line in open(os.path.join(folder, f), errors="replace"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        in_m3u.add(os.path.normpath(os.path.join(os.path.dirname(f), line)).lower())
            except OSError:
                pass
    for f in sorted(files, key=str.lower):
        low = f.lower()
        if low in in_m3u:
            continue
        if low.endswith(".bin") and (low[:-4] + ".cue") in names_lower:
            continue                                       # a .cue's data track
        title, tags = _title(os.path.basename(f))
        out.append({"id": f, "title": title, "tags": tags})
    return out


def systems_with_games():
    out = []
    for sid, s in SYSTEMS.items():
        n = len(games(sid))
        if n:
            out.append({"id": sid, "name": s["name"], "count": n})
    return out


def _emu_for(system, choice=None):
    s = SYSTEMS[system]
    pref = choice or util.load_config().get("emulation", {}).get("emulator", {}).get(system)
    opts = s["emus"]
    if pref:
        opts = sorted(opts, key=lambda o: f"{o[0]}:{o[1] or ''}" != pref)
    inst = installed()
    for emu, core in opts:
        if inst.get(emu):
            return emu, core
    names = " or ".join(EMULATORS[e]["name"] for e, _ in s["emus"])
    raise RuntimeError(f"Install {names} first (Game › Emulation › Emulators)")


def command(system, game_id, choice=None):
    folder = os.path.join(roms_dir(), system)
    rom = os.path.normpath(os.path.join(folder, game_id))
    if not rom.startswith(folder + os.sep) or not os.path.exists(rom):
        raise RuntimeError("That game file isn't there any more")
    emu, core = _emu_for(system, choice)
    e = EMULATORS[emu]
    if system == "ps3" and os.path.isdir(rom):              # RPCS3 boots the game's EBOOT.BIN
        g = glob.escape(rom)                                 # folder names often contain [IDs]
        boot = glob.glob(os.path.join(g, "PS3_GAME", "USRDIR", "EBOOT.BIN")) + glob.glob(os.path.join(g, "USRDIR", "EBOOT.BIN"))
        rom = boot[0] if boot else rom
    args = [a.replace("{rom}", rom).replace("{core}", ensure_core(core) if core else "") for a in e["run"]]
    if e["kind"] == "flatpak":
        # (~/.var/app/<id> - where RetroArch's cores live - has the same path inside the sandbox)
        argv = ["flatpak", "run", e["id"], *args]
    else:
        argv = [_appimage(e), *args]
    return argv, EMULATORS[emu]["name"]


class EmuProvider:
    """Lets the normal game launcher (Starting… screen, game mode, Quick Menu close) run ROMs."""
    id = "emu"

    def launch(self, game_id):
        system, rel = game_id.split("/", 1)
        argv, emu = command(system, rel)
        util.spawn_checked(argv, cwd=root(), what=f"{_title(os.path.basename(rel))[0]} ({emu})")


EMU = EmuProvider()


# ---- BIOS --------------------------------------------------------------------------------------------
def bios_status():
    b = bios_dir()
    out = []
    for sid, s in SYSTEMS.items():
        need = s.get("bios")
        if not need:
            continue
        items, any_group, any_ok = [], [], False
        for f, req in need:
            if f.startswith("ps2:"):
                found = [os.path.basename(p) for p in glob.glob(os.path.join(glob.escape(b), "*.bin")) + glob.glob(os.path.join(glob.escape(b), "ps2", "*.bin"))
                         if re.search(r"scph|ps2|bios", os.path.basename(p), re.I) and os.path.getsize(p) >= 4 * 1024 * 1024]
                items.append({"file": "PS2 BIOS (any scph*.bin, 4 MB)", "found": bool(found), "required": True,
                              "detail": ", ".join(found[:3])})
                continue
            ok = os.path.exists(os.path.join(b, f))
            if req == "any":
                any_group.append(f)
                any_ok = any_ok or ok
            items.append({"file": f, "found": ok, "required": req is True})
        status = "ok"
        if any(i["required"] and not i["found"] for i in items) or (any_group and not any_ok):
            status = "missing"
        elif any(not i["found"] for i in items if i["file"] not in any_group):
            status = "optional"
        out.append({"system": sid, "name": s["name"], "status": status, "files": items,
                    "one_of": any_group})
    return out


def create_folders():
    for sid in SYSTEMS:
        os.makedirs(os.path.join(roms_dir(), sid), exist_ok=True)
    os.makedirs(os.path.join(bios_dir(), "dc"), exist_ok=True)
    os.makedirs(os.path.join(root(), "saves"), exist_ok=True)
    return roms_dir()


# ---- settings written into the emulators' own config files ------------------------------------------------
CONF = {
    "retroarch": os.path.join(HOME, ".var/app/org.libretro.RetroArch/config/retroarch/retroarch.cfg"),
    "dolphin_gfx": os.path.join(HOME, ".var/app/org.DolphinEmu.dolphin-emu/config/dolphin-emu/GFX.ini"),
    "dolphin_ra": os.path.join(HOME, ".var/app/org.DolphinEmu.dolphin-emu/config/dolphin-emu/RetroAchievements.ini"),
    "pcsx2": os.path.join(HOME, ".var/app/net.pcsx2.PCSX2/config/PCSX2/inis/PCSX2.ini"),
    "duckstation": os.path.join(HOME, ".local/share/duckstation/settings.ini"),
    "ppsspp": os.path.join(HOME, ".var/app/org.ppsspp.PPSSPP/config/ppsspp/PSP/SYSTEM/ppsspp.ini"),
}


def set_cfg(path, values):
    """RetroArch-style `key = "value"` file: change/add lines, keep everything else."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = open(path, errors="replace").read().splitlines() if os.path.exists(path) else []
    left = dict(values)
    for i, ln in enumerate(lines):
        m = re.match(r"\s*([A-Za-z0-9_]+)\s*=", ln)
        if m and m.group(1) in left:
            lines[i] = f'{m.group(1)} = "{left.pop(m.group(1))}"'
    lines += [f'{k} = "{v}"' for k, v in left.items()]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def set_ini(path, section, values):
    """INI file: change/add keys in one [section], keep the rest (comments included)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = open(path, errors="replace").read().splitlines() if os.path.exists(path) else []
    left = dict(values)
    start = next((i for i, ln in enumerate(lines) if ln.strip() == f"[{section}]"), None)
    if start is None:
        lines += ["", f"[{section}]"] + [f"{k} = {v}" for k, v in left.items()]
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
        for i in range(start + 1, end):
            m = re.match(r"\s*([^=;#]+?)\s*=", lines[i])
            if m and m.group(1) in left:
                lines[i] = f"{m.group(1)} = {left.pop(m.group(1))}"
        lines[end:end] = [f"{k} = {v}" for k, v in left.items()]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def prefs():
    return util.load_config().get("emulation", {})


def save_prefs(**kw):
    util.update_config(lambda c: c.setdefault("emulation", {}).update(kw))


ASPECT = ("auto", "4:3", "16:9", "stretch")


def apply_defaults(only=None):
    """Write Crossbar's emulation choices into each installed emulator's settings."""
    p, inst = prefs(), installed()
    aspect = p.get("aspect", "auto")
    ra = p.get("ra") or {}
    bios = bios_dir()
    done = []
    if inst.get("retroarch") and only in (None, "retroarch"):
        v = {"system_directory": bios, "savefile_directory": os.path.join(root(), "saves", "retroarch"),
             "video_fullscreen": "true", "menu_driver": "ozone", "input_autodetect_enable": "true",
             "video_aspect_ratio_auto": "true" if aspect == "auto" else "false"}
        if aspect in ("4:3", "16:9"):
            v["aspect_ratio_index"] = "0" if aspect == "4:3" else "1"
        v["video_scale_integer"] = "true" if p.get("integer_scale") else "false"
        v["cheevos_enable"] = "true" if ra.get("enabled") and ra.get("user") else "false"
        v["cheevos_hardcore_mode_enable"] = "true" if ra.get("hardcore") else "false"
        if ra.get("user") and ra.get("token"):
            v["cheevos_username"], v["cheevos_token"] = ra["user"], ra["token"]
        set_cfg(CONF["retroarch"], v)
        done.append("RetroArch")
    if inst.get("dolphin") and only in (None, "dolphin"):
        set_ini(CONF["dolphin_gfx"], "Settings", {"AspectRatio": {"auto": 0, "16:9": 1, "4:3": 2, "stretch": 3}[aspect]})
        if ra.get("user") and ra.get("token"):
            set_ini(CONF["dolphin_ra"], "Achievements", {"Enabled": "True" if ra.get("enabled") else "False",
                                                         "Username": ra["user"], "ApiToken": ra["token"],
                                                         "HardcoreEnabled": "True" if ra.get("hardcore") else "False"})
        done.append("Dolphin")
    if inst.get("pcsx2") and only in (None, "pcsx2"):
        set_ini(CONF["pcsx2"], "EmuCore/GS", {"AspectRatio": {"auto": "Auto 4:3/3:2", "4:3": "4:3", "16:9": "16:9",
                                                              "stretch": "Stretch"}[aspect]})
        set_ini(CONF["pcsx2"], "Folders", {"Bios": os.path.join(bios)})
        if ra.get("user") and ra.get("token"):
            set_ini(CONF["pcsx2"], "Achievements", {"Enabled": str(bool(ra.get("enabled"))).lower(), "Username": ra["user"],
                                                    "Token": ra["token"], "ChallengeMode": str(bool(ra.get("hardcore"))).lower()})
        done.append("PCSX2")
    if inst.get("duckstation") and only in (None, "duckstation"):
        set_ini(CONF["duckstation"], "Display", {"AspectRatio": {"auto": "Auto (Game Native)", "4:3": "4:3", "16:9": "16:9",
                                                                 "stretch": "Stretch To Fill"}[aspect]})
        set_ini(CONF["duckstation"], "BIOS", {"SearchDirectory": bios})
        if ra.get("user") and ra.get("token"):
            set_ini(CONF["duckstation"], "Cheevos", {"Enabled": str(bool(ra.get("enabled"))).lower(), "Username": ra["user"],
                                                     "Token": ra["token"], "ChallengeMode": str(bool(ra.get("hardcore"))).lower()})
        done.append("DuckStation")
    if inst.get("ppsspp") and only in (None, "ppsspp"):
        set_ini(CONF["ppsspp"], "Achievements", {"AchievementsEnable": "True" if ra.get("enabled") and ra.get("user") else "False",
                                                 "AchievementsUserName": ra.get("user", ""),
                                                 "AchievementsChallengeMode": "True" if ra.get("hardcore") else "False"})
        done.append("PPSSPP")
    return done


# ---- RetroAchievements sign-in ------------------------------------------------------------------------
RA_LOGIN = "https://retroachievements.org/dorequest.php"


def ra_login(user, password, web_key=""):
    """Get a login token (what emulators store instead of your password). The password isn't kept."""
    body = urllib.parse.urlencode({"r": "login2", "u": user, "p": password}).encode()
    req = urllib.request.Request(RA_LOGIN, data=body, headers={"User-Agent": "Crossbar/0.9"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
    if not data.get("Success"):
        raise RuntimeError(data.get("Error") or "RetroAchievements refused the sign-in")
    ra = {"user": data.get("User", user), "token": data["Token"], "enabled": True,
          "hardcore": bool((prefs().get("ra") or {}).get("hardcore")), "web_key": web_key or (prefs().get("ra") or {}).get("web_key", "")}
    save_prefs(ra=ra)
    apply_defaults()
    return {"user": ra["user"]}


def status():
    p = prefs()
    ra = p.get("ra") or {}
    return {"root": root(), "roms": roms_dir(), "bios": bios_dir(), "aspect": p.get("aspect", "auto"),
            "integer_scale": bool(p.get("integer_scale")), "flatpak": bool(util.which("flatpak")),
            "ra": {"user": ra.get("user"), "enabled": bool(ra.get("enabled")), "hardcore": bool(ra.get("hardcore")),
                   "web_key": bool(ra.get("web_key"))},
            "emulator_choice": p.get("emulator", {})}


def choices(system):
    inst = installed()
    return [{"value": f"{e}:{c or ''}", "label": EMULATORS[e]["name"] + (f" ({c.replace('_', ' ')})" if c else ""),
             "installed": inst.get(e, False)} for e, c in SYSTEMS[system]["emus"]]


def configure(emu):
    """Open an emulator's own settings (controller mapping etc.) full screen."""
    e = EMULATORS[emu]
    if not installed().get(emu):
        raise RuntimeError(f"{e['name']} isn't installed")
    argv = ["flatpak", "run", e["id"]] if e["kind"] == "flatpak" else [_appimage(e)]
    util.spawn(argv, cwd=root())
