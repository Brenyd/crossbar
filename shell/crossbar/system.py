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
    """Bring the XMB to the front (two steps, so one failing can't block the other)."""
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
            return {"con_id": n["id"], "title": n.get("name") or "",
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


def windows():
    """Other apps currently open (games, Discord…), for 'Return to…' items."""
    raw = _swaymsg("-t", "get_tree", "-r")
    if not raw:
        return []
    out = []

    def walk(n):
        if n.get("pid") and "xmb" not in n.get("marks", []):
            app = n.get("app_id") or (n.get("window_properties") or {}).get("class") or ""
            out.append({"con_id": n["id"], "title": n.get("name") or app, "app": app})
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


def force_close(con_id, grace=4):
    """Ask a window to close; if it's still there after `grace` seconds, end its process."""
    import signal
    win = next((w for w in all_windows() if w["con_id"] == con_id), None)
    close_window(con_id)
    if not win:
        return

    def finish():
        time.sleep(grace)
        if any(w["con_id"] == con_id for w in all_windows()):
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.kill(win["pid"], sig)
                except ProcessLookupError:
                    return
                time.sleep(3)
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
                        "fullscreen": bool(n.get("fullscreen_mode"))})
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
def screen_size():
    """Current resolution of the main display (falls back to 1920x1080)."""
    raw = _swaymsg("-t", "get_outputs", "-r")
    try:
        for o in json.loads(raw or "[]"):
            if o.get("active") and o.get("current_mode"):
                scale = o.get("scale") or 1
                return int(o["current_mode"]["width"] / scale), int(o["current_mode"]["height"] / scale)
    except (ValueError, KeyError):
        pass
    return 1920, 1080


def open_web(url, profile, tv_ui=False, app=True):
    w, h = screen_size()
    args = ["chromium", "--ozone-platform-hint=auto", f"--user-data-dir={os.path.join(util.CONFIG_DIR, profile)}",
            "--no-first-run", "--autoplay-policy=no-user-gesture-required", "--noerrdialogs",
            "--disable-infobars", "--disable-session-crashed-bubble", "--hide-crash-restore-bubble",
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


def bluetooth_do(action, mac):
    word = {"connect": "Connection successful", "disconnect": "Successful disconnected", "remove": "Device has been removed"}[action]
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
    if on is None:
        return subprocess.run(["nmcli", "radio", "wifi"], capture_output=True, text=True).stdout.strip() == "enabled"
    subprocess.run(["nmcli", "radio", "wifi", "on" if on else "off"], capture_output=True)
    return on
