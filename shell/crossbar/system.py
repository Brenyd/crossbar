"""Window management (sway), the Home-button daemon, audio and power."""
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
    """Bring the XMB to the front (what the PS/Home button does)."""
    _swaymsg("[all] fullscreen disable; [con_mark=xmb] focus")


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


# ---- Home button -------------------------------------------------------
def start_home_button_daemon():
    """Watch every gamepad for the Guide/PS button and pop the XMB to the front."""
    try:
        import evdev
    except ImportError:
        print("python-evdev missing: Home button disabled")
        return
    BTN = evdev.ecodes.BTN_MODE

    def loop():
        devices = {}
        last_scan = 0
        while True:
            if time.time() - last_scan > 5:  # hot-plug
                last_scan = time.time()
                for path in evdev.list_devices():
                    if path in devices:
                        continue
                    try:
                        d = evdev.InputDevice(path)
                        if BTN in d.capabilities().get(evdev.ecodes.EV_KEY, []):
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
                        if ev.type == evdev.ecodes.EV_KEY and ev.code == BTN and ev.value == 1:
                            focus_shell()
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
