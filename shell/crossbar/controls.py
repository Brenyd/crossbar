"""Button and key mapping shared by the XMB, the video player and the gamepad daemon.

Stored in ~/.config/crossbar/controls.json:
  {"gamepad": {action: [token, ...]}, "keyboard": {action: [key, ...]}}

Gamepad tokens are evdev names: "BTN_SOUTH" for buttons, "ABS_HAT0X-" / "ABS_Y+"
for a d-pad or stick direction. Keyboard keys use browser names ("ArrowUp",
"Enter", "Space", "a"…) and are translated for sway and mpv.
"""
import json
import os

from . import util

PATH = os.path.join(util.CONFIG_DIR, "controls.json")

ACTIONS = [
    ("up", "Up"), ("down", "Down"), ("left", "Left"), ("right", "Right"),
    ("ok", "Select / Enter"), ("back", "Back"), ("menu", "Options"),
    ("home", "Quick Menu"), ("prev", "Previous / Skip Back"), ("next", "Next / Skip"),
    ("toggle", "Play / Pause"),
]
DIRECTIONS = ("up", "down", "left", "right")

DEFAULT_GAMEPAD = {
    "up": ["BTN_DPAD_UP", "ABS_HAT0Y-", "ABS_Y-"],
    "down": ["BTN_DPAD_DOWN", "ABS_HAT0Y+", "ABS_Y+"],
    "left": ["BTN_DPAD_LEFT", "ABS_HAT0X-", "ABS_X-"],
    "right": ["BTN_DPAD_RIGHT", "ABS_HAT0X+", "ABS_X+"],
    "ok": ["BTN_SOUTH"],
    "back": ["BTN_EAST"],
    "menu": ["BTN_NORTH", "BTN_WEST", "BTN_SELECT"],
    "home": ["BTN_SELECT&BTN_START"],   # a combo: Guide/PS is left to Steam
    "prev": ["BTN_TL"],
    "next": ["BTN_TR"],
    "toggle": ["BTN_START"],
}
DEFAULT_KEYBOARD = {
    "up": ["ArrowUp"], "down": ["ArrowDown"], "left": ["ArrowLeft"], "right": ["ArrowRight"],
    "ok": ["Enter", "Space"], "back": ["Escape", "Backspace"], "menu": ["Tab", "t"],
    "home": ["Home"], "prev": ["PageUp"], "next": ["PageDown"], "toggle": ["p"],
}

# Friendly names. Linux reports Xbox X/Y as BTN_NORTH/BTN_WEST (the reverse of
# their physical positions), while PlayStation pads use BTN_NORTH for triangle.
PAD_LABELS = {
    "BTN_SOUTH": "A / ✕", "BTN_EAST": "B / ○", "BTN_NORTH": "△ / Xbox X", "BTN_WEST": "□ / Xbox Y",
    "BTN_TL": "L1 / LB", "BTN_TR": "R1 / RB", "BTN_TL2": "L2 / LT", "BTN_TR2": "R2 / RT",
    "BTN_START": "Start / Options", "BTN_SELECT": "Select / Share / View", "BTN_MODE": "Guide / PS",
    "BTN_THUMBL": "L3", "BTN_THUMBR": "R3",
    "BTN_DPAD_UP": "D-pad up", "BTN_DPAD_DOWN": "D-pad down", "BTN_DPAD_LEFT": "D-pad left", "BTN_DPAD_RIGHT": "D-pad right",
    "ABS_HAT0Y-": "D-pad up", "ABS_HAT0Y+": "D-pad down", "ABS_HAT0X-": "D-pad left", "ABS_HAT0X+": "D-pad right",
    "ABS_Y-": "Left stick up", "ABS_Y+": "Left stick down", "ABS_X-": "Left stick left", "ABS_X+": "Left stick right",
    "ABS_RY-": "Right stick up", "ABS_RY+": "Right stick down", "ABS_RX-": "Right stick left", "ABS_RX+": "Right stick right",
    "ABS_Z+": "L2 / LT", "ABS_RZ+": "R2 / RT", "ABS_BRAKE+": "L2 / LT", "ABS_GAS+": "R2 / RT",
}

XKB = {"ArrowUp": "Up", "ArrowDown": "Down", "ArrowLeft": "Left", "ArrowRight": "Right", "Enter": "Return",
       "Escape": "Escape", "Tab": "Tab", "Space": "space", "Backspace": "BackSpace", "Home": "Home", "End": "End",
       "PageUp": "Prior", "PageDown": "Next", "Insert": "Insert", "Delete": "Delete"}


def pad_label(token):
    if "&" in token:
        return " + ".join(pad_label(t).split(" / ")[0] for t in token.split("&"))
    if token in PAD_LABELS:
        return PAD_LABELS[token]
    return token.replace("BTN_", "Button ").replace("ABS_", "Axis ").replace("_", " ")


def key_to_xkb(key):
    if key in XKB:
        return XKB[key]
    if len(key) > 1 and key[0] == "F" and key[1:].isdigit():
        return key
    return key.lower() if len(key) == 1 else None


VERSION = 2


def load():
    try:
        with open(PATH) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if data.get("version", 1) < 2:
        # v1 used Guide/PS for the Quick Menu, which fights with Steam's overlay.
        g = data.get("gamepad") or {}
        if g.get("home") == ["BTN_MODE"]:
            g["home"] = list(DEFAULT_GAMEPAD["home"])
    out = {"gamepad": {}, "keyboard": {}, "version": VERSION}
    for kind, defaults in (("gamepad", DEFAULT_GAMEPAD), ("keyboard", DEFAULT_KEYBOARD)):
        saved = data.get(kind) if isinstance(data.get(kind), dict) else {}
        for action, _ in ACTIONS:
            v = saved.get(action)
            out[kind][action] = list(v) if isinstance(v, list) else list(defaults[action])
    return out


def save(c):
    c = {**c, "version": VERSION}
    os.makedirs(util.CONFIG_DIR, exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(c, f, indent=2)
    os.replace(tmp, PATH)


def set_binding(kind, action, tokens):
    if kind not in ("gamepad", "keyboard") or action not in dict(ACTIONS):
        raise KeyError(action)
    c = load()
    tokens = [t for t in dict.fromkeys(tokens) if t]
    if not tokens:
        raise ValueError("At least one button is needed")
    # A button does one thing: take it away from any other action first.
    # (Combos like Select+Start are separate tokens and don't steal Select or Start.)
    for a, toks in c[kind].items():
        if a != action:
            c[kind][a] = [t for t in toks if t not in tokens]
    c[kind][action] = tokens
    save(c)
    return c


def reset(kind=None, action=None):
    c = load()
    for k, defaults in (("gamepad", DEFAULT_GAMEPAD), ("keyboard", DEFAULT_KEYBOARD)):
        if kind in (None, k):
            for a in ([action] if action else defaults):
                c[k][a] = list(defaults[a])
    save(c)
    return c


def set_guide_home(on):
    """Guide/PS opens the Quick Menu too (off by default so Steam keeps it)."""
    c = load()
    home = [t for t in c["gamepad"]["home"] if t != "BTN_MODE"]
    if on:
        home.append("BTN_MODE")
        for a in c["gamepad"]:
            if a != "home":
                c["gamepad"][a] = [t for t in c["gamepad"][a] if t != "BTN_MODE"]
    if not home:
        home = list(DEFAULT_GAMEPAD["home"])
    c["gamepad"]["home"] = home
    save(c)
    return c


def swap_ok_back():
    c = load()
    g = c["gamepad"]
    g["ok"], g["back"] = g["back"], g["ok"]
    save(c)
    return c


def describe():
    c = load()
    return {**c, "actions": [{"id": a, "name": n} for a, n in ACTIONS],
            "guide_home": "BTN_MODE" in c["gamepad"]["home"],
            "labels": _labels(c)}


def _labels(c):
    """Button names in the chosen glyph style (Xbox / PlayStation / Nintendo)."""
    from . import glyphs
    toks = {t for toks in c["gamepad"].values() for t in toks}
    try:
        g = glyphs.current()
        xpad = glyphs.xpad_layout(glyphs.PAD_NAMES())
        out = {}
        for t in toks:
            if t.startswith(("ABS_X", "ABS_Y", "ABS_RX", "ABS_RY", "ABS_HAT", "BTN_DPAD")):
                out[t] = pad_label(t)
            else:
                out[t] = glyphs.label(t, g["style"], xpad)
        return out
    except Exception:
        return {t: pad_label(t) for t in toks}
