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
# Text size. MangoHud draws in the game's own pixels, so a size that reads on a 1080p screen is
# tiny on a 4K TV: "auto" follows the screen's height; the others are fixed multiples of it.
SIZES = ("auto", "small", "medium", "large", "huge")
SIZE_SCALE = {"small": 0.8, "auto": 1.0, "medium": 1.4, "large": 2.0, "huge": 2.8}
SIZE_NAMES = {"auto": "Automatic", "small": "Small", "medium": "Medium", "large": "Large", "huge": "Huge"}

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
            "corner": p.get("corner", "top-right"), "size": p.get("size", "auto"), "font_size": font_size()}


def screen_height():
    try:
        from . import display
        hs = [o["current"]["height"] for o in display.outputs() if o["current"].get("height")]
        return max(hs) if hs else 1080
    except Exception:
        return 1080


def font_size():
    """MangoHud's font size in pixels: 24 at 1080p, scaled to the screen, times the chosen size."""
    s = prefs().get("size", "auto")
    return max(14, round(24 * (screen_height() / 1080) * SIZE_SCALE.get(s, 1.0)))


def write_conf():
    p = prefs()
    mode, corner = p.get("fps", "off"), p.get("corner", "top-right")
    fs = font_size()
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    lines = ["# Written by Crossbar (Quick Menu › Performance). Changes here are overwritten.",
             "legacy_layout=false", f"position={corner}", f"font_size={fs}", f"font_size_text={fs}",
             "background_alpha=0.35", f"round_corners={max(6, fs // 3)}", f"offset_x={fs // 2}", f"offset_y={fs // 2}", "toggle_hud=Shift_R+F12", "reload_cfg=Shift_L+F4", *LINES.get(mode, LINES["off"])]
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


def set_size(size, reload_key=None):
    if size not in SIZES:
        raise ValueError(size)
    util.update_config(lambda c: c.setdefault("perf", {}).__setitem__("size", size))
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
