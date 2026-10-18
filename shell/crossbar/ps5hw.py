"""PS5 hardware on Linux: temperatures, the fan's thermal target, fan patterns and the front LED.

Uses the PS5 kernel drivers' interfaces (the same ones syrufex's PS5 Temperature Control
Panel uses, MIT): /sys/devices/platform/ps5-fan/target_temp, /sys/class/leds/ps5:<name>:indicator,
and the optional `ps5_control` tool for fixed fan patterns / boost. Writes go through the
polkit-authorised root helper (admin.py); reading needs no privileges.
"""
import glob
import json
import os
import subprocess

from . import util

FAN_TARGET = "/sys/devices/platform/ps5-fan/target_temp"
LED_GLOB = "/sys/class/leds/ps5:*:indicator"
ADMIN = "/usr/lib/crossbar/admin.py"
TARGET_RANGE = (40, 95)


def available():
    return os.path.exists(FAN_TARGET) or bool(glob.glob(LED_GLOB))


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def temps():
    """{"cpu": °C, "nvme": °C, "gpu": °C} from hwmon (no lm_sensors needed); missing ones are None."""
    out = {"cpu": None, "nvme": None, "gpu": None}
    for hw in glob.glob("/sys/class/hwmon/hwmon*"):
        name = _read(os.path.join(hw, "name")) or ""
        key = {"k10temp": "cpu", "zenpower": "cpu", "nvme": "nvme", "amdgpu": "gpu"}.get(name)
        if not key or out[key] is not None:
            continue
        # prefer the labelled sensor (Tctl for the CPU, Composite for NVMe, edge for the GPU)
        want = {"cpu": ("tctl", "tdie"), "nvme": ("composite",), "gpu": ("edge", "junction")}[key]
        best = None
        for inp in sorted(glob.glob(os.path.join(hw, "temp*_input"))):
            label = (_read(inp.replace("_input", "_label")) or "").lower()
            val = _read(inp)
            if val is None or not val.lstrip("-").isdigit():
                continue
            if best is None or label in want:
                best = round(int(val) / 1000)
                if label in want:
                    break
        out[key] = best
    return out


def fan_target():
    v = _read(FAN_TARGET)
    return int(v) if v and v.isdigit() else None


def leds():
    """Front LED presets the driver offers, and which one is on."""
    names, on = [], None
    for path in sorted(glob.glob(LED_GLOB)):
        name = os.path.basename(path)[len("ps5:"):-len(":indicator")]
        names.append(name)
        if (_read(os.path.join(path, "brightness")) or "0") != "0":
            on = name
    return names, on


def pretty(name):
    return "Off" if name == "off" else name.replace("zoneb_", "zone B ").replace("_", " ").capitalize()


def status():
    if not available():
        return {"available": False}
    names, on = leds()
    cfg = util.load_config().get("ps5") or {}
    return {"available": True, "temps": temps(), "fan_target": fan_target(), "target_range": list(TARGET_RANGE),
            "leds": names, "led": on, "ps5_control": bool(util.which("ps5_control")),
            "fan_mode": cfg.get("fan_mode", "auto"), "boost": cfg.get("boost", False),
            "hud": cfg.get("hud", False), "hud_corner": cfg.get("hud_corner", "top-right")}


def _admin(action, req):
    r = subprocess.run(["pkexec", ADMIN, action], input=json.dumps(req), capture_output=True, text=True, timeout=30)
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        res = {"ok": False, "error": (r.stderr or r.stdout).strip()[-200:] or "The system helper failed"}
    if not res.get("ok"):
        raise RuntimeError(res.get("error"))
    return res


def _remember(**kw):
    util.update_config(lambda c: c.setdefault("ps5", {}).update(kw))


def set_fan_target(value):
    value = max(TARGET_RANGE[0], min(TARGET_RANGE[1], int(value)))
    _admin("ps5-fan-target", {"value": value})
    _remember(fan_target=value)
    return value


def set_led(name):
    _admin("ps5-led", {"name": name})
    _remember(led=name)


def set_fan_mode(mode):
    if mode not in ("auto", "on", "off", "max"):
        raise ValueError(mode)
    if mode != "auto":
        _admin("ps5-control", {"args": ["--fan", mode]})
    else:   # back to the driver's own control: re-apply the thermal target
        t = (util.load_config().get("ps5") or {}).get("fan_target") or fan_target()
        if t:
            _admin("ps5-fan-target", {"value": int(t)})
    _remember(fan_mode=mode)


def set_boost(on):
    _admin("ps5-control", {"args": ["--boost", "on" if on else "off"]})
    _remember(boost=bool(on))


def set_hud(on=None, corner=None):
    kw = {}
    if on is not None:
        kw["hud"] = bool(on)
    if corner in ("top-left", "top-right", "bottom-left", "bottom-right"):
        kw["hud_corner"] = corner
    _remember(**kw)


def apply_saved():
    """At session start: the fan target and LED reset with each boot; put the user's back."""
    if not available():
        return
    cfg = util.load_config().get("ps5") or {}
    try:
        if cfg.get("fan_target") and cfg.get("fan_mode", "auto") == "auto":
            _admin("ps5-fan-target", {"value": int(cfg["fan_target"])})
        if cfg.get("led"):
            _admin("ps5-led", {"name": cfg["led"]})
    except Exception as e:
        print(f"ps5: couldn't restore settings: {e}", flush=True)
