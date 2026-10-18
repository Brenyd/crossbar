"""Controller button glyphs (Xbox / PlayStation / Nintendo) for every hint Crossbar shows.

Hints are written with action tokens - "{ok} Select", "{prev}/{next} change channel" -
and rendered with the glyph of the button that is actually mapped to that action
(Settings › Controller & Keyboard can remap), in the chosen style.

Glyphs follow physical *position*: Linux reports the face buttons inconsistently
(the xpad driver used by Xbox pads and Steam's virtual pad reports X as BTN_NORTH
and Y as BTN_WEST, while PlayStation/Nintendo drivers use BTN_NORTH for the top
button), so each code is first turned into a position, then into that style's label.
"""
import re

from . import controls, util

STYLES = ("xbox", "playstation", "nintendo")
STYLE_NAMES = {"auto": "Automatic", "xbox": "Xbox", "playstation": "PlayStation", "nintendo": "Nintendo"}

FACE = {   # position -> label
    "xbox": {"south": "A", "east": "B", "west": "X", "north": "Y"},
    "playstation": {"south": "✕", "east": "○", "west": "□", "north": "△"},
    "nintendo": {"south": "B", "east": "A", "west": "Y", "north": "X"},
}
OTHER = {
    "xbox": {"BTN_TL": "LB", "BTN_TR": "RB", "BTN_TL2": "LT", "BTN_TR2": "RT", "BTN_START": "Menu",
             "BTN_SELECT": "View", "BTN_MODE": "Guide", "BTN_THUMBL": "LS", "BTN_THUMBR": "RS"},
    "playstation": {"BTN_TL": "L1", "BTN_TR": "R1", "BTN_TL2": "L2", "BTN_TR2": "R2", "BTN_START": "Options",
                    "BTN_SELECT": "Create", "BTN_MODE": "PS", "BTN_THUMBL": "L3", "BTN_THUMBR": "R3"},
    "nintendo": {"BTN_TL": "L", "BTN_TR": "R", "BTN_TL2": "ZL", "BTN_TR2": "ZR", "BTN_START": "+",
                 "BTN_SELECT": "−", "BTN_MODE": "Home", "BTN_THUMBL": "LS", "BTN_THUMBR": "RS"},
}
AXES = {"ABS_Z+": "BTN_TL2", "ABS_BRAKE+": "BTN_TL2", "ABS_RZ+": "BTN_TR2", "ABS_GAS+": "BTN_TR2"}
DPAD = {"up": "▲", "down": "▼", "left": "◀", "right": "▶"}

_PS = re.compile(r"sony|dualsense|dualshock|playstation|ps[345]\b|wireless controller", re.I)
_NIN = re.compile(r"nintendo|pro controller|joy-?con|switch", re.I)
_XBOX = re.compile(r"xbox|x-box|microsoft|steam|valve|8bitdo.*xinput", re.I)


def detect(names):
    """Style of the first recognisable connected controller (Xbox when unsure)."""
    for n in names or []:
        if _PS.search(n):
            return "playstation"
        if _NIN.search(n):
            return "nintendo"
        if _XBOX.search(n):
            return "xbox"
    return "xbox"


def xpad_layout(names):
    """True when the pad reports X/Y the xpad way (BTN_NORTH = left button)."""
    for n in names or []:
        if _PS.search(n) or _NIN.search(n):
            return False
        if _XBOX.search(n):
            return True
    return True     # no pad yet: Steam's virtual pad (the usual case) is xpad-style


def position(code, xpad):
    return {"BTN_SOUTH": "south", "BTN_EAST": "east",
            "BTN_NORTH": "west" if xpad else "north",
            "BTN_WEST": "north" if xpad else "west"}.get(code)


def label(code, style, xpad=True):
    code = AXES.get(code, code)
    if "&" in code:
        parts = [label(c, style, xpad) for c in code.split("&")]
        return (" & " if any(p in ("+", "−") for p in parts) else "+").join(parts)
    pos = position(code, xpad)
    if pos:
        return FACE[style][pos]
    if code in OTHER[style]:
        return OTHER[style][code]
    for d, g in (("UP", "up"), ("DOWN", "down"), ("LEFT", "left"), ("RIGHT", "right")):
        if code == f"BTN_DPAD_{d}":
            return DPAD[g]
    return controls.pad_label(code).split(" / ")[0]


PAD_NAMES = lambda: []      # set by the backend: names of the connected controllers


def current():
    try:
        return resolve(PAD_NAMES())
    except Exception:
        return resolve([])


def resolve(pad_names=None, cfg=None):
    """Everything the UIs need: {"style", "setting", "actions": {action: glyph}, "codes": {code: glyph}}."""
    cfg = cfg if cfg is not None else util.load_config()
    setting = cfg.get("glyphs", "auto")
    style = setting if setting in STYLES else detect(pad_names)
    xpad = xpad_layout(pad_names)
    mapping = controls.load().get("gamepad") or controls.DEFAULT_GAMEPAD
    actions = {}
    for action, codes in mapping.items():
        codes = [c for c in codes if not c.startswith(("ABS_X", "ABS_Y", "ABS_RX", "ABS_RY", "ABS_HAT"))] or codes
        pick = codes[0] if codes else None
        if action == "menu":     # the "options" button: prefer the top face button, like the △ on a PS3
            pick = next((c for c in codes if position(c, xpad) == "north"), pick)
        if pick:
            actions[action] = label(pick, style, xpad)
    codes = {c: label(c, style, xpad) for c in
             ("BTN_SOUTH", "BTN_EAST", "BTN_NORTH", "BTN_WEST", *OTHER[style].keys())}
    return {"style": style, "setting": setting, "actions": actions, "codes": codes}


TOKEN = re.compile(r"\{(ok|back|menu|home|prev|next|toggle|up|down|left|right)\}")


def render(text, g):
    """Replace {ok}/{back}/... with the glyphs from resolve()."""
    acts = (g or {}).get("actions") or {}
    return TOKEN.sub(lambda m: acts.get(m.group(1)) or DPAD.get(m.group(1)) or m.group(1), text or "")
