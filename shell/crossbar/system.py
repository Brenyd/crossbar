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


def focus_shell():
    """Bring the XMB to the front (what the PS/Home button does). Video pauses."""
    from . import player
    player.pause_video()
    _swaymsg("[all] fullscreen disable; [con_mark=xmb] focus")


def focused_app():
    raw = _swaymsg("-t", "get_tree", "-r")
    if not raw:
        return None
    stack = [json.loads(raw)]
    while stack:
        n = stack.pop()
        if n.get("focused"):
            return n.get("app_id") or (n.get("window_properties") or {}).get("class")
        stack += n.get("nodes", []) + n.get("floating_nodes", [])
    return None


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


def close_window(con_id):
    _swaymsg(f"[con_id={int(con_id)}] kill")


# ---- gamepad daemon ------------------------------------------------------
def start_gamepad_daemon():
    """Reads every gamepad directly (works whatever window is in front):
    - Guide/PS button: back to the XMB, from anything.
    - While the video player is in front: drive its control panel.
    The XMB itself reads gamepads through the browser, so it isn't handled here.
    """
    try:
        import evdev
    except ImportError:
        print("python-evdev missing: Home button disabled")
        return
    from . import player
    E = evdev.ecodes
    BUTTONS = {E.BTN_SOUTH: "ok", E.BTN_EAST: "back", E.BTN_NORTH: "menu", E.BTN_WEST: "menu",
               E.BTN_TL: "prev", E.BTN_TR: "next", E.BTN_START: "toggle", E.BTN_SELECT: "menu",
               E.BTN_DPAD_UP: "up", E.BTN_DPAD_DOWN: "down", E.BTN_DPAD_LEFT: "left", E.BTN_DPAD_RIGHT: "right"}
    stick = {}  # (path, axis) -> last direction, so a held stick fires once

    def send(action):
        if player.VIDEO.running() and focused_app() == player.VIDEO_APP_ID:
            player.video_input(action)

    def handle(d, ev):
        if ev.type == E.EV_KEY and ev.value == 1:
            if ev.code == E.BTN_MODE:
                focus_shell()
            elif ev.code in BUTTONS:
                send(BUTTONS[ev.code])
        elif ev.type == E.EV_ABS and ev.code in (E.ABS_HAT0X, E.ABS_HAT0Y):
            if ev.value:
                send({(E.ABS_HAT0X, -1): "left", (E.ABS_HAT0X, 1): "right",
                      (E.ABS_HAT0Y, -1): "up", (E.ABS_HAT0Y, 1): "down"}[(ev.code, 1 if ev.value > 0 else -1)])
        elif ev.type == E.EV_ABS and ev.code in (E.ABS_X, E.ABS_Y):
            info = d.absinfo(ev.code)
            mid = (info.max + info.min) / 2
            span = (info.max - info.min) / 2 or 1
            v = (ev.value - mid) / span
            direction = 0 if abs(v) < 0.6 else (1 if v > 0 else -1)
            key = (d.path, ev.code)
            if direction and stick.get(key) != direction:
                send({(E.ABS_X, -1): "left", (E.ABS_X, 1): "right", (E.ABS_Y, -1): "up", (E.ABS_Y, 1): "down"}[(ev.code, direction)])
            stick[key] = direction

    def loop():
        devices, last_scan = {}, 0
        while True:
            if time.time() - last_scan > 5:  # hot-plug
                last_scan = time.time()
                for path in evdev.list_devices():
                    if path in devices:
                        continue
                    try:
                        d = evdev.InputDevice(path)
                        keys = d.capabilities().get(E.EV_KEY, [])
                        if E.BTN_MODE in keys or E.BTN_SOUTH in keys:
                            devices[path] = d
                        else:
                            d.close()
                    except OSError:
                        pass
            if not devices:
                time.sleep(2)
                continue
            r, _, _ = select.select(list(devices.values()), [], [], 2)
            for d in r:
                try:
                    for ev in d.read():
                        handle(d, ev)
                except OSError:
                    devices.pop(d.path, None)

    threading.Thread(target=loop, daemon=True).start()


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
    }


def is_live():
    return os.path.isdir("/run/archiso")


def open_installer():
    if not is_live():
        raise RuntimeError("Already installed")
    util.spawn(["foot", "--title", "Install Crossbar", "sudo", "/usr/local/bin/crossbar-install"])


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
def open_web(url, profile, tv_ui=False, app=True):
    args = ["chromium", "--ozone-platform-hint=auto", f"--user-data-dir={os.path.join(util.CONFIG_DIR, profile)}",
            "--no-first-run", "--autoplay-policy=no-user-gesture-required"]
    if tv_ui:
        # YouTube serves its controller-friendly TV interface to console browsers.
        args.append("--user-agent=Mozilla/5.0 (PS4; Leanback Shell) Gecko/20100101 Firefox/65.0 "
                    "LeanbackShell/01.00.01.75 Sony PS4/ (PS4, , no, CH)")
    args += [f"--app={url}"] if app else ["--start-maximized", url]
    util.spawn(args)
