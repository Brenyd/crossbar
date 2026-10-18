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


# Offered when the screen doesn't list its own modes (some drivers, VMs, adapters).
COMMON = [(3840, 2160), (2560, 1440), (2560, 1080), (1920, 1200), (1920, 1080), (1680, 1050),
          (1600, 900), (1440, 900), (1366, 768), (1280, 800), (1280, 720)]


def _mode_str(m):
    """sway mode string; without a known refresh rate let sway pick it."""
    r = int(m.get("refresh") or 0)
    return f"{m['width']}x{m['height']}" + (f"@{r / 1000:.3f}Hz" if r > 0 else "")


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
        listed = bool(modes)
        if not listed:   # nothing reported: offer common sizes as custom modes (sway picks the rate)
            top = (cur.get("width") or 0) * (cur.get("height") or 0)
            for w, h in COMMON:
                if (w, h) != (cur.get("width"), cur.get("height")) and (not top or w * h <= max(top, 1920 * 1080)):
                    modes.append({"width": w, "height": h, "refresh": 0, "custom": True})
            if cur.get("width"):
                modes.append({"width": cur["width"], "height": cur["height"], "refresh": cur.get("refresh") or 0, "custom": True})
        modes.sort(key=lambda m: (-m["width"] * m["height"], -m["refresh"]))
        out.append({"name": o["name"], "label": " ".join(x for x in (o.get("make"), o.get("model")) if x and x != "Unknown") or o["name"],
                    "current": {"width": cur.get("width", 0), "height": cur.get("height", 0), "refresh": cur.get("refresh") or 0},
                    "modes": modes, "listed": listed, "scale": o.get("scale", 1.0)})
    return out


def set_mode(name, width, height, refresh=0, save=True, custom=False):
    m = {"width": int(width), "height": int(height), "refresh": int(refresh or 0)}
    mode = _mode_str(m)
    args = ["output", name, "mode"] + (["--custom"] if custom else []) + [mode]
    try:
        _swaymsg(*args)
    except RuntimeError as first:
        if custom:
            raise RuntimeError(f"The screen refused {m['width']} × {m['height']}: {first}")
        try:    # the exact rate may not be accepted: try a custom mode at that size
            args = ["output", name, "mode", "--custom", mode]
            _swaymsg(*args)
        except RuntimeError:
            raise RuntimeError(f"The screen refused {m['width']} × {m['height']}: {first}")
    if save:
        saved = " ".join(args[3:])
        util.update_config(lambda c: c["display"].setdefault(name, {}).__setitem__("mode", saved))


def set_scale(name, scale, save=True):
    _swaymsg("output", name, "scale", str(float(scale)))
    if save:
        util.update_config(lambda c: c["display"].setdefault(name, {}).__setitem__("scale", float(scale)))


def apply_saved():
    """Re-apply the user's display choices when the session starts."""
    for name, s in util.load_config().get("display", {}).items():
        try:
            if s.get("mode"):
                _swaymsg("output", name, "mode", *s["mode"].split())
            if s.get("scale"):
                _swaymsg("output", name, "scale", str(s["scale"]))
        except RuntimeError as e:
            print(f"display: couldn't restore {name}: {e}")
