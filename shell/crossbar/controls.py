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
# a TV remote has a few buttons a controller doesn't
REMOTE_ACTIONS = ACTIONS + [("volume_up", "Volume Up"), ("volume_down", "Volume Down"), ("mute", "Mute"),
                            ("power", "Power (opens the Quick Menu)")]

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

# Android TV remotes (and most Bluetooth / IR / HDMI-CEC remotes) send these Linux keys.
DEFAULT_REMOTE = {
    "up": ["KEY_UP"], "down": ["KEY_DOWN"], "left": ["KEY_LEFT"], "right": ["KEY_RIGHT"],
    "ok": ["KEY_SELECT", "KEY_OK", "KEY_ENTER", "KEY_KPENTER"],
    "back": ["KEY_BACK", "KEY_ESC", "KEY_EXIT", "KEY_BACKSPACE", "KEY_STOP", "KEY_STOPCD"],
    "menu": ["KEY_MENU", "KEY_COMPOSE", "KEY_CONTEXT_MENU", "KEY_OPTION", "KEY_INFO", "KEY_EPG", "KEY_PROGRAM", "KEY_SETUP"],
    "home": ["KEY_HOMEPAGE", "KEY_HOME"],
    "prev": ["KEY_PREVIOUSSONG", "KEY_REWIND", "KEY_CHANNELDOWN", "KEY_PAGEUP"],
    "next": ["KEY_NEXTSONG", "KEY_FASTFORWARD", "KEY_CHANNELUP", "KEY_PAGEDOWN"],
    "toggle": ["KEY_PLAYPAUSE", "KEY_PLAY", "KEY_PAUSE", "KEY_PLAYCD", "KEY_PAUSECD", "KEY_MEDIA"],
    "volume_up": ["KEY_VOLUMEUP"], "volume_down": ["KEY_VOLUMEDOWN"], "mute": ["KEY_MUTE"],
    "power": ["KEY_POWER", "KEY_SLEEP", "KEY_POWER2"],
}
REMOTE_LABELS = {
    "KEY_UP": "Up", "KEY_DOWN": "Down", "KEY_LEFT": "Left", "KEY_RIGHT": "Right", "KEY_SELECT": "OK", "KEY_OK": "OK",
    "KEY_ENTER": "Enter", "KEY_KPENTER": "Enter", "KEY_BACK": "Back", "KEY_ESC": "Esc", "KEY_EXIT": "Exit",
    "KEY_BACKSPACE": "Backspace", "KEY_STOP": "Stop", "KEY_STOPCD": "Stop", "KEY_MENU": "Menu", "KEY_COMPOSE": "Menu",
    "KEY_CONTEXT_MENU": "Menu", "KEY_OPTION": "Options", "KEY_INFO": "Info", "KEY_EPG": "Guide", "KEY_PROGRAM": "Guide",
    "KEY_SETUP": "Settings", "KEY_HOMEPAGE": "Home", "KEY_HOME": "Home", "KEY_PREVIOUSSONG": "Previous",
    "KEY_REWIND": "Rewind", "KEY_CHANNELDOWN": "Channel −", "KEY_PAGEUP": "Page Up", "KEY_NEXTSONG": "Next",
    "KEY_FASTFORWARD": "Fast Forward", "KEY_CHANNELUP": "Channel +", "KEY_PAGEDOWN": "Page Down",
    "KEY_PLAYPAUSE": "Play/Pause", "KEY_PLAY": "Play", "KEY_PAUSE": "Pause", "KEY_PLAYCD": "Play", "KEY_PAUSECD": "Pause",
    "KEY_MEDIA": "Media", "KEY_VOLUMEUP": "Volume +", "KEY_VOLUMEDOWN": "Volume −", "KEY_MUTE": "Mute",
    "KEY_POWER": "Power", "KEY_SLEEP": "Sleep", "KEY_POWER2": "Power", "KEY_SEARCH": "Search",
    "KEY_VOICECOMMAND": "Voice / Mic", "KEY_RED": "Red", "KEY_GREEN": "Green", "KEY_YELLOW": "Yellow", "KEY_BLUE": "Blue",
    "KEY_TV": "TV", "KEY_SUBTITLE": "Subtitles", "KEY_AUDIO": "Audio", "KEY_LAST": "Last", "KEY_TEXT": "Teletext",
}


def remote_label(token):
    if token in REMOTE_LABELS:
        return REMOTE_LABELS[token]
    return token.replace("KEY_", "").replace("_", " ").title()


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
    out = {"gamepad": {}, "keyboard": {}, "remote": {}, "version": VERSION,
           "remote_devices": {str(k): bool(v) for k, v in (data.get("remote_devices") or {}).items()}
           if isinstance(data.get("remote_devices"), dict) else {}}
    for kind, defaults in (("gamepad", DEFAULT_GAMEPAD), ("keyboard", DEFAULT_KEYBOARD), ("remote", DEFAULT_REMOTE)):
        saved = data.get(kind) if isinstance(data.get(kind), dict) else {}
        for action, _ in (REMOTE_ACTIONS if kind == "remote" else ACTIONS):
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
    if kind not in ("gamepad", "keyboard", "remote") or action not in dict(REMOTE_ACTIONS if kind == "remote" else ACTIONS):
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
    for k, defaults in (("gamepad", DEFAULT_GAMEPAD), ("keyboard", DEFAULT_KEYBOARD), ("remote", DEFAULT_REMOTE)):
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


def set_remote_device(name, on):
    """Mark a device as a TV remote (True), as not one (False), or back to automatic (None)."""
    c = load()
    if on is None:
        c["remote_devices"].pop(name, None)
    else:
        c["remote_devices"][name] = bool(on)
    save(c)
    return c


def describe():
    c = load()
    return {**c, "actions": [{"id": a, "name": n} for a, n in ACTIONS],
            "remote_actions": [{"id": a, "name": n} for a, n in REMOTE_ACTIONS],
            "remote_labels": {t: remote_label(t) for toks in c["remote"].values() for t in toks},
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
