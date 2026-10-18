"""Frame-rate overlay (MangoHud) for games, toggled from the Quick Menu.

Games Crossbar starts get MANGOHUD=1, so MangoHud is loaded but hidden (`no_display`) unless
the overlay is on. Changing the mode rewrites MangoHud's config file and presses MangoHud's
"reload config" keys (Left Shift + F4) in the running game, so it changes immediately.
Steam games get it through Steam (Crossbar starts Steam with MANGOHUD=1); if Steam was already
running from elsewhere, it applies after Steam restarts. Vulkan games (incl. Proton/DXVK) only.
"""
import os

from . import util

CONF = os.path.expanduser("~/.config/MangoHud/MangoHud.conf")
MODES = ("off", "fps", "graph", "full")
CORNERS = ("top-right", "top-left", "bottom-left", "bottom-right")

LINES = {
    "off": ["no_display"],
    "fps": ["fps_only"],
    "graph": ["fps", "frametime", "frame_timing", "cpu_stats=0", "gpu_stats=0"],
    "full": ["fps", "frametime", "frame_timing", "cpu_stats", "cpu_temp", "gpu_stats", "gpu_temp", "ram"],
}


def available():
    return bool(util.which("mangohud")) or os.path.exists("/usr/share/vulkan/implicit_layer.d/MangoHud.x86_64.json")


def prefs():
    return util.load_config().get("perf") or {}


def status():
    p = prefs()
    return {"available": available(), "fps": p.get("fps", "off"), "last": p.get("last", "fps"),
            "corner": p.get("corner", "top-right")}


def write_conf():
    p = prefs()
    mode, corner = p.get("fps", "off"), p.get("corner", "top-right")
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    lines = ["# Written by Crossbar (Quick Menu › Performance). Changes here are overwritten.",
             "legacy_layout=false", f"position={corner}", "font_size=22", "background_alpha=0.35",
             "round_corners=8", "toggle_hud=Shift_R+F12", "reload_cfg=Shift_L+F4", *LINES.get(mode, LINES["off"])]
    with open(CONF, "w") as f:
        f.write("\n".join(lines) + "\n")


def set_mode(mode, reload_key=None):
    if mode not in MODES:
        raise ValueError(mode)
    util.update_config(lambda c: c.setdefault("perf", {}).update(fps=mode, **({"last": mode} if mode != "off" else {})))
    write_conf()
    if reload_key:
        reload_key()
    return status()


def set_corner(corner, reload_key=None):
    if corner not in CORNERS:
        raise ValueError(corner)
    util.update_config(lambda c: c.setdefault("perf", {}).__setitem__("corner", corner))
    write_conf()
    if reload_key:
        reload_key()
    return status()


def env():
    """Environment for games Crossbar starts: MangoHud loaded (hidden unless the overlay is on)."""
    if not available():
        return {}
    if not os.path.exists(CONF):
        write_conf()
    return {"MANGOHUD": "1"}
