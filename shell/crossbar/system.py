"""Window management (sway), the gamepad daemon, audio, network and power."""
import json
import os
import re
import select
import subprocess
import threading
import time

from . import util


# ---- sway --------------------------------------------------------------
def _swaymsg(*args):
    if not os.environ.get("SWAYSOCK") or not util.which("swaymsg"):
        return None
    r = subprocess.run(["swaymsg", *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


XMB_TITLE = "Crossbar"


def is_xmb(f):
    return bool(f) and f.get("title") == XMB_TITLE and "chrom" in (f.get("app") or "").lower()


def is_web_app(f):
    """Chromium windows other than the XMB: TV services, the browser, sign-in pages."""
    return bool(f) and "chrom" in (f.get("app") or "").lower() and not is_xmb(f) and "xmb" not in f.get("marks", [])


def is_steam_client(w):
    """Steam's own windows (library, Big Picture, friends) — not a game."""
    app, title = (w.get("app") or "").lower(), w.get("title") or ""
    return app == "steam" and not app.startswith("steam_app")


_LAUNCH = {"until": 0}


def hold_launch(seconds=300):
    """A game is starting (Steam may be updating, windows come and go): don't treat
    windows closing as "the game ended" until it's up."""
    _LAUNCH["until"] = time.time() + seconds


def release_launch():
    _LAUNCH["until"] = 0


def launching():
    return time.time() < _LAUNCH["until"]


def is_background_window(w):
    """Windows you wouldn't want left in front after a game closes: Steam's client.
    (Discord is NOT one: when you open it, it should stay in front.)"""
    return is_steam_client(w)


def ensure_xmb_mark():
    """Mark the XMB window so we can always focus it, even if sway's title rule missed it."""
    raw = _swaymsg("-t", "get_tree", "-r")
    if not raw:
        return None
    stack, found = [json.loads(raw)], None
    while stack:
        n = stack.pop()
        if n.get("pid") and (n.get("name") == XMB_TITLE or "xmb" in n.get("marks", [])):
            found = n
            if "xmb" not in n.get("marks", []):
                _swaymsg(f"[con_id={n['id']}] mark --add xmb")
            break
        stack += n.get("nodes", []) + n.get("floating_nodes", [])
    return found


def show_shell():
    """Bring the XMB to the front (two steps, so one failing can't block the other).
    If it was closed for game mode, it's started again first."""
    from . import session
    session.leave_game_mode()
    _swaymsg("[all] fullscreen disable")
    xmb = ensure_xmb_mark()
    if xmb:
        _swaymsg(f"[con_id={xmb['id']}] focus")
    else:
        _swaymsg("[con_mark=xmb] focus")


def focus_shell():
    """Back to the XMB from anything; video pauses."""
    from . import player
    player.pause_video()
    show_shell()


def focused():
    """The window in front: {"con_id","app","title","marks"}; None without sway."""
    raw = _swaymsg("-t", "get_tree", "-r")
    if not raw:
        return None
    stack = [json.loads(raw)]
    while stack:
        n = stack.pop()
        if n.get("focused") and n.get("type") in ("con", "floating_con"):
            return {"con_id": n["id"], "title": n.get("name") or "", "pid": n.get("pid"),
                    "app": n.get("app_id") or (n.get("window_properties") or {}).get("class") or "",
                    "marks": n.get("marks", [])}
        stack += n.get("nodes", []) + n.get("floating_nodes", [])
    return {"con_id": None, "title": "", "app": "", "marks": []}


_bound_home = []


def bind_home_keys(keys):
    """Make the keyboard Quick Menu key(s) work over every app, via sway."""
    from . import controls
    global _bound_home
    for k in _bound_home:
        _swaymsg(f"unbindsym {k}")
    _bound_home = []
    for key in keys:
        x = controls.key_to_xkb(key)
        if x and _swaymsg(f"bindsym --no-repeat {x} exec /usr/local/bin/crossbar-home") is not None:
            _bound_home.append(x)


# Emulators and game runners recognised by their window's app id (in case the marker is lost)
GAME_APPS = ("org.libretro.retroarch", "retroarch", "org.dolphinemu.dolphin-emu", "dolphin-emu", "net.pcsx2.pcsx2", "pcsx2",
             "net.rpcs3.rpcs3", "rpcs3", "org.ppsspp.ppsspp", "ppsspp", "info.cemu.cemu", "cemu", "org.azahar_emu.azahar",
             "azahar", "net.kuribo64.melonds", "melonds", "app.xemu.xemu", "xemu", "org.flycast.flycast", "flycast",
             "org.scummvm.scummvm", "scummvm", "duckstation", "org.duckstation.duckstation", "gamescope")


def _proc_env(pid):
    try:
        with open(f"/proc/{int(pid)}/environ", "rb") as f:
            return dict(x.split(b"=", 1) for x in f.read().split(b"\0") if b"=" in x)
    except (OSError, ValueError):
        return {}


def is_game_window(w, pid=None):
    """A game or emulator (shown under Game › Return to…), not an app like Discord or a browser."""
    app = (w.get("app") or "").lower()
    if app.startswith("steam_app") or any(app == g or app.startswith(g + ".") for g in GAME_APPS):
        return True
    if "chrom" in app or is_steam_client(w) or app in ("crossbar-player", "mpv", "foot", "alacritty", "konsole"):
        return False
    env = _proc_env(pid) if pid else {}
    if env.get(b"CROSSBAR_GAME") == b"1":
        return True                                  # started by Crossbar as a game (Wine/Proton included)
    gid = env.get(b"SteamGameId") or env.get(b"SteamAppId") or b"0"
    return gid not in (b"", b"0")                    # a game Steam started


def windows():
    """Other apps currently open (games, Discord…), for 'Return to…' items. game: a game or emulator."""
    raw = _swaymsg("-t", "get_tree", "-r")
    if not raw:
        return []
    out = []

    def walk(n):
        if n.get("pid") and "xmb" not in n.get("marks", []):
            app = n.get("app_id") or (n.get("window_properties") or {}).get("class") or ""
            w = {"con_id": n["id"], "title": n.get("name") or app, "app": app}
            w["game"] = is_game_window(w, n.get("pid"))
            out.append(w)
        for c in n.get("nodes", []) + n.get("floating_nodes", []):
            walk(c)

    walk(json.loads(raw))
    return out


def focus_window(con_id):
    _swaymsg(f"[con_id={int(con_id)}] focus")


def current_workspace():
    raw = _swaymsg("-t", "get_workspaces", "-r")
    try:
        return next((w["name"] for w in json.loads(raw or "[]") if w.get("focused")), "1")
    except ValueError:
        return "1"


def bring_to_front(con_id):
    """Show a window as a normal full-size tab, even if it was hidden in the scratchpad."""
    ws = current_workspace()
    _swaymsg(f'[con_id={int(con_id)}] move container to workspace "{ws}"')
    _swaymsg(f"[con_id={int(con_id)}] floating disable")
    _swaymsg(f"[con_id={int(con_id)}] focus")


def hide_steam():
    """Tuck Steam's client / Big Picture windows away and go back to the menu."""
    for w in all_windows():
        if is_steam_client(w):
            hide_window(w["con_id"])
    show_shell()


_AFTER = {"until": 0}


def visible_steam():
    return [w for w in all_windows() if is_steam_client(w) and w.get("visible")]


def after_game():
    """A game ended: take Steam out of Big Picture (it reads the controller itself, so a
    Big Picture left running behind the menu reacts to every press too) and keep Steam's
    windows tucked away for a few seconds while it settles."""
    running = time.time() < _AFTER["until"]
    _AFTER["until"] = time.time() + 15
    hide_steam()
    if running:
        return

    def run():
        if any("big picture" in (w.get("title") or "").lower() for w in all_windows() if is_steam_client(w)) \
                and util.which("steam"):
            subprocess.Popen(["steam", "steam://close/bigpicture"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        while time.time() < _AFTER["until"]:
            time.sleep(1)
            if launching():                     # a new game is starting: leave Steam alone
                return
            vis = visible_steam()
            for w in vis:
                hide_window(w["con_id"])
            f = focused()
            if vis or not f or not f.get("con_id") or is_steam_client(f):
                show_shell()
    threading.Thread(target=run, daemon=True).start()


def kill_window(con_id):
    """Force close: end the window's process right away."""
    import signal
    win = next((w for w in all_windows() if w["con_id"] == int(con_id)), None)
    if win and win.get("pid"):
        try:
            os.kill(win["pid"], signal.SIGKILL)
        except ProcessLookupError:
            pass


def force_close(con_id, grace=4):
    """Ask a window to close; if it's still there after `grace` seconds, end its process."""
    import signal
    win = next((w for w in all_windows() if w["con_id"] == con_id), None)
    close_window(con_id)
    if not win:
        return

    m = re.match(r"steam_app_(\d+)$", win.get("app") or "")

    def finish():
        time.sleep(grace)
        if any(w["con_id"] == con_id for w in all_windows()):
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.kill(win["pid"], sig)
                except ProcessLookupError:
                    break
                time.sleep(3)
        if m:
            # a Steam (Proton) game is many processes: end the rest through Steam's launcher
            # ("reaper"), or the game keeps its memory with no window
            subprocess.run(["pkill", "-TERM", "-u", str(os.getuid()), "-f", f"reaper SteamLaunch AppId={m.group(1)}( |$)"],
                           capture_output=True)
    threading.Thread(target=finish, daemon=True).start()


def hide_window(con_id):
    """Tuck a window away (sway scratchpad) without closing it."""
    _swaymsg(f"[con_id={int(con_id)}] move scratchpad")


def all_windows():
    """Every app window, including hidden (scratchpad) ones."""
    raw = _swaymsg("-t", "get_tree", "-r")
    if not raw:
        return []
    out, stack = [], [json.loads(raw)]
    while stack:
        n = stack.pop()
        if n.get("pid") and n.get("type") in ("con", "floating_con"):
            out.append({"con_id": n["id"], "pid": n["pid"], "title": n.get("name") or "",
                        "app": n.get("app_id") or (n.get("window_properties") or {}).get("class") or "",
                        "fullscreen": bool(n.get("fullscreen_mode")), "visible": bool(n.get("visible"))})
        stack += n.get("nodes", []) + n.get("floating_nodes", [])
    return out


def close_window(con_id):
    _swaymsg(f"[con_id={int(con_id)}] kill")


# ---- audio (PipeWire via wpctl) ---------------------------------------
def audio():
    out = {}
    for key, node in (("output", "@DEFAULT_AUDIO_SINK@"), ("mic", "@DEFAULT_AUDIO_SOURCE@")):
        vol, muted, name = None, False, ""
        if util.which("wpctl"):
            r = subprocess.run(["wpctl", "get-volume", node], capture_output=True, text=True)
            m = re.search(r"([\d.]+)", r.stdout)
            if m:
                vol, muted = round(float(m.group(1)) * 100), "MUTED" in r.stdout
            r = subprocess.run(["wpctl", "inspect", node], capture_output=True, text=True)
            m = re.search(r'node\.description = "([^"]+)"', r.stdout)
            name = m.group(1) if m else ""
        out[key] = {"volume": vol, "muted": muted, "name": name}
    return out


def set_audio(target, delta=None, mute=None):
    node = "@DEFAULT_AUDIO_SINK@" if target == "output" else "@DEFAULT_AUDIO_SOURCE@"
    if not util.which("wpctl"):
        raise RuntimeError("Audio control needs PipeWire (wpctl)")
    if delta:
        subprocess.run(["wpctl", "set-volume", "-l", "1.0", node, f"{abs(delta)}%{'+' if delta > 0 else '-'}"])
    if mute is not None:
        subprocess.run(["wpctl", "set-mute", node, "toggle"])


def power(action):
    subprocess.Popen(["systemctl", {"poweroff": "poweroff", "reboot": "reboot"}[action]])


def sysinfo():
    def read(p):
        try:
            return open(p).read().strip()
        except OSError:
            return ""
    os_name = re.search(r'PRETTY_NAME="([^"]+)"', read("/etc/os-release"))
    mem = re.search(r"MemTotal:\s+(\d+)", read("/proc/meminfo"))
    cpu = re.search(r"model name\s*:\s*(.+)", read("/proc/cpuinfo"))
    return {
        "os": os_name.group(1) if os_name else "Linux",
        "kernel": os.uname().release,
        "cpu": cpu.group(1) if cpu else os.uname().machine,
        "memory": f"{int(mem.group(1)) // 1024} MB" if mem else "?",
        "games_dir": util.GAMES_DIR,
        "version": open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION")).read().strip()
        if os.path.exists(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION")) else "dev",
    }


def is_live():
    return os.path.isdir("/run/archiso")


def open_installer():
    if not is_live():
        raise RuntimeError("Already installed")
    return {"cmd": "sudo /usr/local/bin/crossbar-install"}


# ---- audio devices (PipeWire) ---------------------------------------------
def audio_devices():
    """Output and input devices with the current defaults marked."""
    if not util.which("pw-dump"):
        return {"outputs": [], "inputs": []}
    try:
        data = json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=5).stdout or "[]")
    except (ValueError, subprocess.TimeoutExpired):
        return {"outputs": [], "inputs": []}
    defaults = {}
    for o in data:
        if o.get("type") == "PipeWire:Interface:Metadata" and (o.get("props") or {}).get("metadata.name") == "default":
            for e in o.get("metadata") or []:
                v = e.get("value")
                if isinstance(v, str):
                    try:
                        v = json.loads(v)
                    except ValueError:
                        v = {}
                if e.get("key") in ("default.audio.sink", "default.audio.source"):
                    defaults[e["key"]] = (v or {}).get("name")
    out = {"outputs": [], "inputs": []}
    for o in data:
        if o.get("type") != "PipeWire:Interface:Node":
            continue
        props = (o.get("info") or {}).get("props") or {}
        cls = props.get("media.class")
        if cls not in ("Audio/Sink", "Audio/Source"):
            continue
        key, bucket = ("default.audio.sink", "outputs") if cls == "Audio/Sink" else ("default.audio.source", "inputs")
        out[bucket].append({"id": o["id"], "name": props.get("node.description") or props.get("node.nick") or props.get("node.name"),
                            "default": props.get("node.name") == defaults.get(key)})
    return out


# ---- per-app volume (PipeWire playback streams) ------------------------------
def _cmdline(pid):
    try:
        return open(f"/proc/{int(pid)}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace")
    except (OSError, ValueError, TypeError):
        return ""


def _stream_app(props):
    """A friendly name for whoever owns a playback stream, and a key to group its streams."""
    from . import player
    pid = props.get("application.process.id")
    binary = (props.get("application.process.binary") or "").lower()
    name = props.get("application.name") or binary or "App"
    cmd = _cmdline(pid)
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        pid = None
    for proc, label in ((getattr(player, "MUSIC", None), "Music"), (getattr(player, "VIDEO", None), "Video")):
        p = getattr(proc, "proc", None)
        if pid and p is not None and getattr(p, "pid", None) == pid:
            return label, f"crossbar-{label.lower()}"
    if "librespot" in binary or "librespot" in name.lower():
        return "Spotify", "spotify"
    if "crossbar/shell-browser" in cmd:
        return "Crossbar Menu Sounds", "crossbar-menu"
    m = re.search(r"--app=https?://(?:www\.)?([^/\s]+)", cmd)
    if m:                       # web apps (YouTube, Twitch…) opened from TV & Video Services
        host = m.group(1)
        known = {"youtube.com": "YouTube", "tv.youtube.com": "YouTube", "twitch.tv": "Twitch", "netflix.com": "Netflix"}
        return known.get(host, host.split(".")[-2].capitalize() if "." in host else host), f"web-{host}"
    if binary.startswith("steam") or "steam_app" in cmd or "proton" in cmd or "wine" in binary:
        label = props.get("application.name") or "Game"
        if label.lower() in ("steam", "wine", "wine64-preloader", "proton"):
            label = "Game"
        return label, f"app-{pid or label}"
    pretty = {"chromium": "Browser", "firefox": "Firefox", "discord": "Discord", "vesktop": "Discord", "mumble": "Mumble"}
    return pretty.get(binary, name[:1].upper() + name[1:]), f"bin-{binary or name}"


def app_streams(dump=None):
    """Apps currently playing sound: [{"key","name","sub","ids","volume","muted"}]."""
    if dump is None:
        if not util.which("pw-dump"):
            return []
        try:
            dump = json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=5).stdout or "[]")
        except (ValueError, subprocess.TimeoutExpired):
            return []
    apps = {}
    for o in dump:
        if o.get("type") != "PipeWire:Interface:Node":
            continue
        info = o.get("info") or {}
        props = info.get("props") or {}
        if props.get("media.class") != "Stream/Output/Audio":
            continue
        name, key = _stream_app(props)
        vol, muted = None, False
        for prm in ((info.get("params") or {}).get("Props") or []):
            if "channelVolumes" in prm:
                cv = prm["channelVolumes"] or [1.0]
                vol = round((max(cv) ** (1 / 3)) * 100)     # wpctl / pavucontrol show the cubic scale
                muted = bool(prm.get("mute"))
        a = apps.setdefault(key, {"key": key, "name": name, "ids": [], "volume": vol, "muted": muted, "media": []})
        a["ids"].append(o["id"])
        if vol is not None and (a["volume"] is None or vol > a["volume"]):
            a["volume"] = vol
        a["muted"] = a["muted"] and muted if a["media"] else muted
        if props.get("media.name"):
            a["media"].append(props["media.name"])
    out = []
    for a in apps.values():
        media = [m for m in a.pop("media") if m.lower() not in ("playback", "audio stream", "audiostream")]
        a["sub"] = media[0] if media else ""
        if a["volume"] is None:
            a["volume"] = 100
        out.append(a)
    order = {"crossbar-music": 0, "spotify": 1, "crossbar-video": 2}
    return sorted(out, key=lambda a: (order.get(a["key"], 5), a["key"] == "crossbar-menu", a["name"].lower()))


def set_app_volume(ids, delta=None, mute=None):
    if not util.which("wpctl"):
        raise RuntimeError("Audio control needs PipeWire (wpctl)")
    for i in ids:
        i = str(int(i))
        if delta:
            subprocess.run(["wpctl", "set-volume", "-l", "1.0", i, f"{abs(int(delta))}%{'+' if delta > 0 else '-'}"],
                           capture_output=True)
        if mute is not None:
            subprocess.run(["wpctl", "set-mute", i, "1" if mute else "0"], capture_output=True)


def set_audio_device(node_id):
    if not util.which("wpctl"):
        raise RuntimeError("Audio control needs PipeWire (wpctl)")
    subprocess.run(["wpctl", "set-default", str(int(node_id))], check=True)


# ---- network (NetworkManager) ---------------------------------------------
def _nm_split(line):
    return [p.replace("\\:", ":") for p in re.split(r"(?<!\\):", line)]


def network_status():
    if not util.which("nmcli"):
        return {"available": False, "devices": []}
    r = subprocess.run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"],
                       capture_output=True, text=True)
    devs = []
    for line in r.stdout.splitlines():
        dev, typ, state, conn = (_nm_split(line) + ["", "", "", ""])[:4]
        if typ in ("ethernet", "wifi"):
            ip = subprocess.run(["nmcli", "-g", "IP4.ADDRESS", "device", "show", dev],
                                capture_output=True, text=True).stdout.split("\n")[0].split("/")[0]
            devs.append({"device": dev, "type": typ, "state": state, "connection": conn, "ip": ip})
    online = subprocess.run(["nmcli", "networking", "connectivity"], capture_output=True, text=True).stdout.strip()
    return {"available": True, "devices": devs, "connectivity": online}


def wifi_networks():
    if not util.which("nmcli"):
        raise RuntimeError("Wi-Fi needs NetworkManager")
    r = subprocess.run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes"],
                       capture_output=True, text=True, timeout=30)
    seen, nets = set(), []
    for line in r.stdout.splitlines():
        inuse, ssid, signal, sec = (_nm_split(line) + ["", "", "", ""])[:4]
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        nets.append({"ssid": ssid, "signal": int(signal or 0), "secure": sec not in ("", "--"), "connected": inuse == "*"})
    return sorted(nets, key=lambda n: (not n["connected"], -n["signal"]))


def wifi_connect(ssid, password=""):
    args = ["nmcli", "device", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    r = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else "Couldn't connect")


# ---- apps in their own window (TV services, browser) ------------------------
def screen_size(physical=False):
    """Current resolution of the main display (falls back to 1920x1080).
    physical: real pixels, not divided by sway's scale."""
    raw = _swaymsg("-t", "get_outputs", "-r")
    try:
        for o in json.loads(raw or "[]"):
            if o.get("active") and o.get("current_mode"):
                scale = 1 if physical else (o.get("scale") or 1)
                return int(o["current_mode"]["width"] / scale), int(o["current_mode"]["height"] / scale)
    except (ValueError, KeyError):
        pass
    return 1920, 1080


def open_web(url, profile, tv_ui=False, app=True):
    w, h = screen_size()
    args = ["chromium", "--ozone-platform-hint=auto", f"--user-data-dir={os.path.join(util.CONFIG_DIR, profile)}",
            "--no-first-run", "--autoplay-policy=no-user-gesture-required", "--noerrdialogs",
            "--disable-infobars", "--disable-session-crashed-bubble", "--hide-crash-restore-bubble",
            "--enable-wayland-ime", "--wayland-text-input-version=3",   # text fields open the on-screen keyboard
            f"--window-size={w},{h}", "--window-position=0,0"]
    if tv_ui:
        # YouTube serves its controller-friendly TV interface to console browsers.
        args.append("--user-agent=Mozilla/5.0 (PS4; Leanback Shell) Gecko/20100101 Firefox/65.0 "
                    "LeanbackShell/01.00.01.75 Sony PS4/ (PS4, , no, CH)")
    # TV services run full screen with no browser UI, like a console app;
    # Guide/PS (or Home) opens the Quick Menu to leave or close them.
    args += ["--kiosk", url] if app else ["--start-maximized", url]
    util.spawn(args)


# ---- Bluetooth (BlueZ via bluetoothctl) -------------------------------------
_BT_ICON = {"input-gaming": "game", "audio-headset": "sound", "audio-headphones": "sound", "audio-card": "sound",
            "input-keyboard": "browser", "input-mouse": "browser", "phone": "voice"}


def _btctl(*args, timeout=15):
    if not util.which("bluetoothctl"):
        raise RuntimeError("Bluetooth needs bluez-utils")
    r = subprocess.run(["bluetoothctl", *args], capture_output=True, text=True, timeout=timeout)
    return r.stdout


def _bt_devices(flt=None):
    out = _btctl("devices", *([flt] if flt else []))
    devs = {}
    for line in out.splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3 and parts[0] == "Device":
            devs[parts[1]] = parts[2]
    return devs


def bluetooth_status():
    if not util.which("bluetoothctl"):
        return {"available": False, "powered": False, "devices": []}
    show = _btctl("show")
    if "No default controller" in show or not show.strip():
        return {"available": False, "powered": False, "devices": [], "note": "No Bluetooth adapter found"}
    powered = "Powered: yes" in show
    allk = _bt_devices()
    paired = _bt_devices("Paired")
    connected = _bt_devices("Connected")
    devices = []
    for mac, name in allk.items():
        info = _btctl("info", mac, timeout=5)
        m = re.search(r"Icon: (\S+)", info)
        devices.append({"mac": mac, "name": name, "paired": mac in paired, "connected": mac in connected,
                        "kind": _BT_ICON.get(m.group(1) if m else "", "settings")})
    devices.sort(key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))
    return {"available": True, "powered": powered, "devices": devices}


def bluetooth_power(on):
    _btctl("power", "on" if on else "off")


def bluetooth_scan(seconds=10):
    _btctl("--timeout", str(seconds), "scan", "on", timeout=seconds + 5)


def bluetooth_pair(mac):
    """Pair (no PIN, like controllers and headsets), trust, connect — one bluetoothctl session."""
    p = subprocess.Popen(["bluetoothctl"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1)
    out = []

    def say(cmd, until, timeout):
        p.stdin.write(cmd + "\n")
        p.stdin.flush()
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([p.stdout], [], [], 0.5)
            if r:
                line = p.stdout.readline()
                out.append(line)
                for word in until:
                    if word in line:
                        return word
        return None

    try:
        say("agent NoInputNoOutput", ["Agent registered", "already registered"], 5)
        say("default-agent", ["Default agent request successful"], 5)
        res = say(f"pair {mac}", ["Pairing successful", "AlreadyExists", "Failed to pair", "not available"], 30)
        if res in ("Failed to pair", "not available", None):
            raise RuntimeError("Pairing failed — put the device in pairing mode and try again")
        say(f"trust {mac}", ["trust succeeded"], 5)
        res = say(f"connect {mac}", ["Connection successful", "Failed to connect"], 20)
        if res != "Connection successful":
            raise RuntimeError("Paired, but couldn't connect")
    finally:
        try:
            p.stdin.write("quit\n")
            p.stdin.flush()
        except OSError:
            pass
        p.wait(timeout=5)


_bt_busy = {}
_bt_lock = threading.Lock()


def _bt_connected(mac):
    return "Connected: yes" in _btctl("info", mac, timeout=5)


def _bt_connect(mac):
    """Connect a paired device. Controllers (DualSense, DualShock, Xbox) mostly connect themselves
    when their PS / Guide button is pressed: trusting them is what lets that work, and a host-side
    connect to a controller that's asleep fails with br-connection-create-socket."""
    with _bt_lock:
        if _bt_busy.get(mac, 0) > time.time():
            raise RuntimeError("Already connecting — give it a few seconds")
        _bt_busy[mac] = time.time() + 30
    try:
        info = _btctl("info", mac, timeout=5)
        pad = "Icon: input-gaming" in info
        if "Trusted: no" in info:
            _btctl("trust", mac, timeout=5)
        for attempt in range(2):
            out = _btctl("connect", mac, timeout=25)
            if "Connection successful" in out or _bt_connected(mac):
                return
            if "InProgress" in out or "busy" in out:          # BlueZ is already connecting: wait for it
                for _ in range(20):
                    time.sleep(0.5)
                    if _bt_connected(mac):
                        return
            time.sleep(1.5)
            if _bt_connected(mac):                            # the device connected itself meanwhile
                return
        if pad:
            raise RuntimeError("The controller didn't answer. Press its PS (or Guide) button to connect it. "
                               "If the light just blinks and goes out, it's paired with another system: "
                               "choose Pair Again in Options")
        raise RuntimeError("The device didn't answer: switch it on and bring it closer, or choose Pair Again in Options")
    finally:
        _bt_busy.pop(mac, None)


def bluetooth_repair(mac):
    """Forget the device, find it again in pairing mode, and pair it fresh (a stale link key is the
    usual reason a paired controller stops connecting)."""
    _btctl("remove", mac, timeout=10)
    for _ in range(3):
        bluetooth_scan(8)
        if mac in _bt_devices():
            return bluetooth_pair(mac)
    raise RuntimeError("Didn't find it: hold Create + PS (Share + PS on a DualShock 4) until the light flashes fast, then try again")


def bluetooth_do(action, mac):
    if action == "connect":
        return _bt_connect(mac)
    word = {"disconnect": "Successful disconnected", "remove": "Device has been removed"}[action]
    out = _btctl(action, mac, timeout=25)
    if word.split()[0] not in out:
        raise RuntimeError(out.strip().splitlines()[-1] if out.strip() else f"{action} failed")


# ---- date & time (systemd timedated) -------------------------------------------
def time_status():
    out = subprocess.run(["timedatectl", "show"], capture_output=True, text=True).stdout if util.which("timedatectl") else ""
    vals = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    return {"timezone": vals.get("Timezone", time.tzname[0]), "ntp": vals.get("NTP") == "yes",
            "synced": vals.get("NTPSynchronized") == "yes", "available": bool(out)}


def timezones():
    out = subprocess.run(["timedatectl", "list-timezones"], capture_output=True, text=True).stdout
    return [z for z in out.split() if z]


def set_timezone(tz):
    if tz not in timezones():
        raise ValueError("unknown time zone")
    r = subprocess.run(["timedatectl", "set-timezone", tz], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "couldn't set the time zone")


def set_ntp(on):
    r = subprocess.run(["timedatectl", "set-ntp", "true" if on else "false"], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "couldn't change automatic time")


# ---- Wi-Fi extras -----------------------------------------------------------------
def wifi_disconnect():
    devs = [d for d in network_status().get("devices", []) if d["type"] == "wifi" and d["connection"]]
    for d in devs:
        subprocess.run(["nmcli", "device", "disconnect", d["device"]], capture_output=True)


def wifi_forget(ssid):
    subprocess.run(["nmcli", "connection", "delete", "id", ssid], capture_output=True)


def wifi_radio(on=None):
    if not util.which("nmcli"):
        if on is None:
            return False
        raise RuntimeError("Wi-Fi needs NetworkManager")
    if on is None:
        return subprocess.run(["nmcli", "radio", "wifi"], capture_output=True, text=True).stdout.strip() == "enabled"
    subprocess.run(["nmcli", "radio", "wifi", "on" if on else "off"], capture_output=True)
    return on
