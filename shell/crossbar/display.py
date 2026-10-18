"""Display modes (resolution, refresh rate, scale) through sway."""
import json
import os
import subprocess

from . import util


def _swaymsg(*args):
    if not os.environ.get("SWAYSOCK") or not util.which("swaymsg"):
        raise RuntimeError("Display settings need the Crossbar session (sway)")
    r = subprocess.run(["swaymsg", *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError((r.stdout + r.stderr).strip()[-200:] or "swaymsg failed")
    return r.stdout


def _mode_str(m):
    return f"{m['width']}x{m['height']}@{m['refresh'] / 1000:.3f}Hz"


def outputs():
    try:
        raw = json.loads(_swaymsg("-t", "get_outputs", "-r"))
    except RuntimeError:
        return []
    out = []
    for o in raw:
        if not o.get("active"):
            continue
        cur = o.get("current_mode") or {}
        modes, seen = [], set()
        for m in o.get("modes", []):
            key = (m["width"], m["height"], round(m["refresh"] / 1000, 2))
            if key not in seen:
                seen.add(key)
                modes.append({"width": m["width"], "height": m["height"], "refresh": m["refresh"]})
        modes.sort(key=lambda m: (-m["width"] * m["height"], -m["refresh"]))
        out.append({"name": o["name"], "label": " ".join(x for x in (o.get("make"), o.get("model")) if x and x != "Unknown") or o["name"],
                    "current": cur, "modes": modes, "scale": o.get("scale", 1.0)})
    return out


def set_mode(name, width, height, refresh, save=True):
    m = {"width": int(width), "height": int(height), "refresh": int(refresh)}
    _swaymsg("output", name, "mode", _mode_str(m))
    if save:
        util.update_config(lambda c: c["display"].setdefault(name, {}).__setitem__("mode", _mode_str(m)))


def set_scale(name, scale, save=True):
    _swaymsg("output", name, "scale", str(float(scale)))
    if save:
        util.update_config(lambda c: c["display"].setdefault(name, {}).__setitem__("scale", float(scale)))


def apply_saved():
    """Re-apply the user's display choices when the session starts."""
    for name, s in util.load_config().get("display", {}).items():
        try:
            if s.get("mode"):
                _swaymsg("output", name, "mode", s["mode"])
            if s.get("scale"):
                _swaymsg("output", name, "scale", str(s["scale"]))
        except RuntimeError as e:
            print(f"display: couldn't restore {name}: {e}")
