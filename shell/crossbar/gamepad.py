"""The one place controllers are read.

Every gamepad is read here with evdev, translated through the user's mapping
(controls.py) into actions — up/down/left/right/ok/back/menu/home/prev/next/toggle —
and sent only to whatever is in front:

  - the XMB      -> pushed to the page over server-sent events
  - video player -> mpv's control panel
  - a game/app   -> nothing (it reads the controller itself)

The Quick Menu action (Guide/PS by default) works from anywhere.
"""
import select
import threading
import time

from . import controls, player, system
from .events import HUB

REPEAT_DELAY, REPEAT_RATE = 0.38, 0.085


class Gamepads:
    def __init__(self, on_home):
        self.on_home = on_home
        self.devices = {}
        self.names = {}
        self.available = False
        self._keymap, self._absmap = {}, {}
        self._held = {}          # action -> next repeat time (directions only)
        self._abs_dir = {}       # (path, code) -> -1/0/1
        self._capture = None     # {"event": Event, "token": str|None}
        self._focus_cache = (0, None)
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
        elif "xmb" in f["marks"]:
            t = "xmb"
        elif f["app"] == player.VIDEO_APP_ID:
            t = "video"
        else:
            t = "app"
        self._focus_cache = (now, t)
        return t

    def _press(self, action):
        if action == "home":
            self.on_home()
            return
        target = self._target()
        if target == "xmb":
            HUB.publish({"type": "input", "action": action})
        elif target == "video":
            player.video_input(action)
        if action in controls.DIRECTIONS and target in ("xmb", "video"):
            self._held[action] = time.time() + REPEAT_DELAY

    def _release(self, action):
        self._held.pop(action, None)

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
            for a in self._keymap.get(ev.code, []):
                if ev.value == 1:
                    self._press(a)
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
                if self._capture:
                    self._captured(f"{name}{'+' if direction > 0 else '-'}")
                    return
                for a in self._absmap.get((ev.code, direction), []):
                    self._press(a)

    def _scan(self, evdev):
        for path in evdev.list_devices():
            if path in self.devices:
                continue
            try:
                d = evdev.InputDevice(path)
                keys = d.capabilities().get(evdev.ecodes.EV_KEY, [])
                if evdev.ecodes.BTN_SOUTH in keys or evdev.ecodes.BTN_MODE in keys or evdev.ecodes.BTN_GAMEPAD in keys:
                    self.devices[path] = d
                    self.names[path] = d.name
                else:
                    d.close()
            except OSError:
                pass

    def run(self):
        try:
            import evdev
        except ImportError:
            print("python-evdev missing: controllers are read by the browser only")
            return
        self.available = True
        last_scan = 0
        while True:
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
                    t = self._target()
                    if t == "xmb":
                        HUB.publish({"type": "input", "action": action, "repeat": True})
                    elif t == "video" and action in ("up", "down"):
                        player.video_input(action)

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()

    def status(self):
        return {"available": self.available, "devices": list(self.names.values())}
