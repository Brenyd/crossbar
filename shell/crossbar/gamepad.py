"""The one place controllers are read.

Every gamepad is read here with evdev, translated through the user's mapping
(controls.py) into actions — up/down/left/right/ok/back/menu/home/prev/next/toggle —
and sent only to whatever is in front:

  - the XMB        -> pushed to the page over server-sent events
  - video player   -> mpv's control panel
  - web apps       -> typed as keys on a virtual keyboard (YouTube TV, Twitch, browser…)
  - a game / other -> nothing (it reads the controller itself)

The Quick Menu action (Guide/PS by default) works from anywhere.
"""
import collections
import glob
import os
import select
import threading
import time

from . import controls, player, system, util
from .events import HUB

REPEAT_DELAY, REPEAT_RATE = 0.38, 0.085

# What a web app gets for each action (Linux key names). YouTube's TV interface,
# Jellyfin/Plex TV layouts and normal pages all understand these.
WEB_KEYS = {
    "up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT",
    "ok": "KEY_ENTER", "back": "KEY_ESC", "menu": "KEY_TAB",
    "toggle": "KEY_PLAYPAUSE", "prev": "KEY_PREVIOUSSONG", "next": "KEY_NEXTSONG",
}


class Gamepads:
    def __init__(self, on_home):
        self.on_home = on_home
        self.devices = {}
        self.names = {}
        self.unreadable = {}     # path -> reason (permissions!)
        self.available = False
        self.error = ""
        self.log = collections.deque(maxlen=25)
        self._keymap, self._absmap = {}, {}
        self._held = {}          # action -> next repeat time (directions only)
        self._abs_dir = {}       # (path, code) -> -1/0/1
        self._capture = None     # {"event": Event, "token": str|None}
        self._focus_cache = (0, None)
        self._uinput = None
        self.uinput_error = ""
        self.reload()

    # ---- mapping ---------------------------------------------------------
    def reload(self):
        try:
            import evdev
        except ImportError:
            return
        E = evdev.ecodes.ecodes
        keymap, absmap = {}, {}
        for action, tokens in controls.load()["gamepad"].items():
            for t in tokens:
                if t.startswith("ABS_") and t[-1] in "+-":
                    code = E.get(t[:-1])
                    if code is not None:
                        absmap.setdefault((code, 1 if t[-1] == "+" else -1), []).append(action)
                else:
                    code = E.get(t)
                    if code is not None:
                        keymap.setdefault(code, []).append(action)
        self._keymap, self._absmap = keymap, absmap

    @staticmethod
    def _key_token(code):
        import evdev
        names = evdev.ecodes.BTN.get(code) or evdev.ecodes.KEY.get(code)
        if isinstance(names, (list, tuple)):
            preferred = [n for n in names if any(p in n for p in ("SOUTH", "EAST", "NORTH", "WEST", "DPAD", "MODE", "START", "SELECT", "THUMB", "_TL", "_TR"))]
            names = (preferred or list(names))[0]
        return names or f"BTN_{code}"

    # ---- routing ---------------------------------------------------------
    def _target(self):
        now = time.time()
        if now - self._focus_cache[0] < 0.25:
            return self._focus_cache[1]
        f = system.focused()
        if f is None:                       # no sway (dev mode): the XMB is the target
            t = "xmb"
        elif "xmb" in f["marks"] or system.is_xmb(f):
            t = "xmb"
        elif f["app"] == player.VIDEO_APP_ID:
            t = "video"
        elif system.is_web_app(f):
            t = "web"
        else:
            t = "app"
        self._focus_cache = (now, t)
        return t

    def _send(self, action, target, repeat=False):
        if target == "xmb":
            HUB.publish({"type": "input", "action": action, "repeat": repeat})
        elif target == "video":
            if not repeat or action in ("up", "down"):
                player.video_input(action)
        elif target == "web":
            self._web_key(action)

    def _press(self, action, token=""):
        if action == "home":
            self.log.appendleft({"t": time.time(), "token": token, "action": action, "to": "quick menu"})
            self.on_home()
            return
        target = self._target()
        self.log.appendleft({"t": time.time(), "token": token, "action": action, "to": target})
        self._send(action, target)
        if action in controls.DIRECTIONS and target in ("xmb", "video", "web"):
            self._held[action] = time.time() + REPEAT_DELAY

    def _release(self, action):
        self._held.pop(action, None)

    # ---- virtual keyboard for web apps -------------------------------------
    def _web_key(self, action):
        name = WEB_KEYS.get(action)
        if not name:
            return
        try:
            import evdev
            if self._uinput is None:
                keys = [evdev.ecodes.ecodes[k] for k in set(WEB_KEYS.values())]
                self._uinput = evdev.UInput({evdev.ecodes.EV_KEY: keys}, name="Crossbar Controller Keys")
                time.sleep(0.05)   # let the compositor notice the new keyboard
            code = evdev.ecodes.ecodes[name]
            self._uinput.write(evdev.ecodes.EV_KEY, code, 1)
            self._uinput.syn()
            self._uinput.write(evdev.ecodes.EV_KEY, code, 0)
            self._uinput.syn()
            self.uinput_error = ""
        except Exception as e:   # usually: no access to /dev/uinput
            self.uinput_error = str(e)
            self._uinput = None

    # ---- capture (for remapping in Settings) -------------------------------
    def capture(self, timeout=10):
        ev = threading.Event()
        self._capture = {"event": ev, "token": None}
        ev.wait(timeout)
        tok = self._capture["token"] if self._capture else None
        self._capture = None
        return tok

    def cancel_capture(self):
        if self._capture:
            self._capture["event"].set()

    def _captured(self, token):
        if self._capture and not self._capture["token"]:
            self._capture["token"] = token
            self._capture["event"].set()
            return True
        return False

    # ---- event handling --------------------------------------------------
    def _handle(self, d, ev):
        import evdev
        E = evdev.ecodes
        if ev.type == E.EV_KEY:
            if ev.value == 1 and self._capture:
                self._captured(self._key_token(ev.code))
                return
            actions = self._keymap.get(ev.code, [])
            if ev.value == 1 and not actions:
                self.log.appendleft({"t": time.time(), "token": self._key_token(ev.code), "action": None, "to": "unmapped"})
            for a in actions:
                if ev.value == 1:
                    self._press(a, self._key_token(ev.code))
                elif ev.value == 0:
                    self._release(a)
        elif ev.type == E.EV_ABS:
            info = d.absinfo(ev.code)
            span = info.max - info.min or 1
            name = E.ABS.get(ev.code, "")
            if name.startswith("ABS_HAT"):                    # d-pads: -1 / 0 / 1
                direction = (ev.value > 0) - (ev.value < 0)
            elif info.min >= 0 and name in ("ABS_Z", "ABS_RZ", "ABS_GAS", "ABS_BRAKE"):   # triggers: one-sided
                v = (ev.value - info.min) / span
                direction = 1 if v > 0.6 else 0
            else:
                v = (ev.value - (info.max + info.min) / 2) / (span / 2)
                direction = 0 if abs(v) < 0.6 else (1 if v > 0 else -1)
            key = (d.path, ev.code)
            prev = self._abs_dir.get(key, 0)
            if direction == prev:
                return
            self._abs_dir[key] = direction
            if prev:
                for a in self._absmap.get((ev.code, prev), []):
                    self._release(a)
            if direction:
                token = f"{name}{'+' if direction > 0 else '-'}"
                if self._capture:
                    self._captured(token)
                    return
                for a in self._absmap.get((ev.code, direction), []):
                    self._press(a, token)

    def _scan(self, evdev):
        # Look at every event node ourselves: evdev.list_devices() silently skips
        # ones we can't read, which hides permission problems.
        for path in sorted(glob.glob("/dev/input/event*")):
            if path in self.devices:
                continue
            try:
                d = evdev.InputDevice(path)
            except PermissionError:
                self.unreadable[path] = _device_name(path) or "permission denied"
                continue
            except OSError:
                continue
            self.unreadable.pop(path, None)
            try:
                keys = d.capabilities().get(evdev.ecodes.EV_KEY, [])
            except OSError:
                d.close()
                continue
            if evdev.ecodes.BTN_SOUTH in keys or evdev.ecodes.BTN_MODE in keys or evdev.ecodes.BTN_GAMEPAD in keys:
                if d.name.startswith("Crossbar "):      # our own virtual keyboard
                    d.close()
                    continue
                self.devices[path] = d
                self.names[path] = d.name
                print(f"gamepad: using {d.name} ({path})", flush=True)
            else:
                d.close()
        # forget unreadable nodes that disappeared
        for path in [p for p in self.unreadable if not os.path.exists(p)]:
            self.unreadable.pop(path, None)
        joy_blocked = {p: n for p, n in self.unreadable.items() if _is_joystick(p)}
        if joy_blocked and not self.devices:
            self.error = ("Controller found but not readable: " + ", ".join(sorted(set(joy_blocked.values()))) +
                          ". The Crossbar user needs access to /dev/input (see Controller Diagnostics).")
        else:
            self.error = ""

    def run(self):
        try:
            import evdev
        except ImportError:
            self.error = "python-evdev is not installed"
            print("python-evdev missing: controllers are read by the browser only", flush=True)
            return
        self.available = True
        last_scan = 0
        while True:
            try:
                if time.time() - last_scan > 3:
                    last_scan = time.time()
                    self._scan(evdev)
                if not self.devices:
                    time.sleep(1)
                    continue
                r, _, _ = select.select(list(self.devices.values()), [], [], 0.04)
                for d in r:
                    try:
                        for ev in d.read():
                            self._handle(d, ev)
                    except OSError:              # unplugged
                        self.devices.pop(d.path, None)
                        self.names.pop(d.path, None)
                        self._held.clear()
                now = time.time()
                for action, due in list(self._held.items()):
                    if now >= due:
                        self._held[action] = now + REPEAT_RATE
                        self._send(action, self._target(), repeat=True)
            except Exception as e:          # never let the controller thread die
                print(f"gamepad: {e!r}", flush=True)
                time.sleep(1)

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()

    def status(self):
        return {"available": self.available, "devices": list(self.names.values()),
                "unreadable": sorted(set(n for p, n in self.unreadable.items() if _is_joystick(p))),
                "error": self.error, "uinput_error": self.uinput_error}

    def recent(self):
        return list(self.log)


def _sysfs(path, leaf):
    try:
        with open(f"/sys/class/input/{os.path.basename(path)}/device/{leaf}") as f:
            return f.read().strip()
    except OSError:
        return ""


def _device_name(path):
    return _sysfs(path, "name")


def _is_joystick(path):
    """True if udev tagged this node as a joystick/gamepad (readable without opening it)."""
    try:
        major, minor = os.major(os.stat(path).st_rdev), os.minor(os.stat(path).st_rdev)
        with open(f"/run/udev/data/c{major}:{minor}") as f:
            return "E:ID_INPUT_JOYSTICK=1" in f.read()
    except OSError:
        return False


def mpv_should_read_gamepad(pads):
    """Fallback: if crossbard can't read any controller, let mpv try (SDL) itself."""
    return not pads.devices and bool(util.which("mpv"))
