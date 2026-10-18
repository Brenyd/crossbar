"""Controller handling: mapping and routing.

Raw events come from crossbar-inputd (root service, /run/crossbar/input.sock),
or — if that isn't running — straight from /dev/input. Each press is translated
through the user's mapping (controls.py) into an action and sent only to what's
in front:

  - Quick Menu overlay -> the overlay page
  - the XMB            -> the XMB page (server-sent events)
  - video player       -> mpv's control panel
  - web apps           -> keys on a virtual keyboard (YouTube TV, Twitch, browser…)
  - a game / other     -> nothing: the controller is released to the game

While Crossbar is the target it *grabs* the controller, so a browser or game in
the background can't also react to the same press. Guide/PS (the "home" action)
always opens the Quick Menu.
"""
import collections
import glob
import json
import os
import select
import socket
import subprocess
import threading
import time

from . import controls, player, system
from .events import HUB

REPEAT_DELAY, REPEAT_RATE = 0.38, 0.085
INPUTD_SOCK = "/run/crossbar/input.sock"

WEB_KEYS = {
    "up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT",
    "ok": "KEY_ENTER", "back": "KEY_ESC", "menu": "KEY_TAB",
    "toggle": "KEY_PLAYPAUSE", "prev": "KEY_PREVIOUSSONG", "next": "KEY_NEXTSONG",
}


class Gamepads:
    def __init__(self, on_home):
        self.on_home = on_home
        self.mode = "starting"          # "inputd" | "direct" | "none"
        self.devices = {}               # path -> InputDevice (direct mode)
        self.names = {}                 # path -> name
        self.absinfo = {}               # path -> {code: (min, max)}
        self.unreadable = {}
        self.available = False
        self.error = ""
        self.log = collections.deque(maxlen=25)
        self.overlay_open = False
        self.grabbed = False
        self._keymap, self._absmap = {}, {}
        self._held = {}
        self._abs_dir = {}
        self._capture = None
        self._focus_cache = (0, None)
        self._sock = None
        self._sock_lock = threading.Lock()
        self._uinput = None
        self.uinput_error = ""
        self.reload()

    # ---- mapping -----------------------------------------------------------
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

    # ---- where input goes ----------------------------------------------------
    def _target(self, fresh=False):
        if self.overlay_open:
            return "overlay"
        now = time.time()
        if not fresh and now - self._focus_cache[0] < 0.25:
            return self._focus_cache[1]
        f = system.focused()
        if f is None:
            t = "xmb"                     # no sway (dev mode)
        elif "xmb" in f["marks"] or system.is_xmb(f):
            t = "xmb"
        elif f["app"] == player.VIDEO_APP_ID:
            t = "video"
        elif system.is_web_app(f):
            t = "web"
        elif not f.get("con_id"):
            t = "xmb"                     # nothing focused: treat as the menu
        else:
            t = "app"
        self._focus_cache = (now, t)
        return t

    def update_grab(self):
        """Own the controller unless a game/app is in front."""
        want = self._target(fresh=True) != "app"
        if want != self.grabbed:
            self.grabbed = want
            if self.mode == "inputd":
                self._cmd({"cmd": "grab", "on": want})
            elif self.mode == "direct":
                for d in self.devices.values():
                    try:
                        d.grab() if want else d.ungrab()
                    except OSError:
                        pass

    def _send(self, action, target, repeat=False):
        if target in ("xmb", "overlay"):
            HUB.publish({"type": "input", "action": action, "to": target, "repeat": repeat})
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
        if action in controls.DIRECTIONS and target in ("xmb", "video", "web", "overlay"):
            self._held[action] = time.time() + REPEAT_DELAY

    def _release(self, action):
        self._held.pop(action, None)

    # ---- virtual keyboard for web apps --------------------------------------
    def _web_key(self, action):
        name = WEB_KEYS.get(action)
        if not name:
            return
        try:
            import evdev
            code = evdev.ecodes.ecodes[name]
            if self.mode == "inputd":
                self._cmd({"cmd": "key", "code": code})
                return
            if self._uinput is None:
                keys = [evdev.ecodes.ecodes[k] for k in set(WEB_KEYS.values())]
                self._uinput = evdev.UInput({evdev.ecodes.EV_KEY: keys}, name="Crossbar Controller Keys")
                time.sleep(0.15)
            for v in (1, 0):
                self._uinput.write(evdev.ecodes.EV_KEY, code, v)
                self._uinput.syn()
            self.uinput_error = ""
        except Exception as e:
            self.uinput_error = str(e)
            self._uinput = None

    # ---- capture (Settings › remap) ------------------------------------------
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

    # ---- raw events (from either source) -------------------------------------
    def _on_key(self, code, value):
        if value == 1 and self._capture:
            self._captured(self._key_token(code))
            return
        actions = self._keymap.get(code, [])
        if value == 1 and not actions:
            self.log.appendleft({"t": time.time(), "token": self._key_token(code), "action": None, "to": "unmapped"})
        for a in actions:
            if value == 1:
                self._press(a, self._key_token(code))
            elif value == 0:
                self._release(a)

    def _on_abs(self, path, code, value, lo, hi):
        import evdev
        E = evdev.ecodes
        span = hi - lo or 1
        name = E.ABS.get(code, "")
        if name.startswith("ABS_HAT"):
            direction = (value > 0) - (value < 0)
        elif lo >= 0 and name in ("ABS_Z", "ABS_RZ", "ABS_GAS", "ABS_BRAKE"):
            direction = 1 if (value - lo) / span > 0.6 else 0
        else:
            v = (value - (hi + lo) / 2) / (span / 2)
            direction = 0 if abs(v) < 0.6 else (1 if v > 0 else -1)
        key = (path, code)
        prev = self._abs_dir.get(key, 0)
        if direction == prev:
            return
        self._abs_dir[key] = direction
        if prev:
            for a in self._absmap.get((code, prev), []):
                self._release(a)
        if direction:
            token = f"{name}{'+' if direction > 0 else '-'}"
            if self._capture:
                self._captured(token)
                return
            for a in self._absmap.get((code, direction), []):
                self._press(a, token)

    def _handle(self, d, ev):
        """Direct-mode adapter (also used by tests)."""
        import evdev
        if ev.type == evdev.ecodes.EV_KEY:
            self._on_key(ev.code, ev.value)
        elif ev.type == evdev.ecodes.EV_ABS:
            info = d.absinfo(ev.code)
            self._on_abs(d.path, ev.code, ev.value, info.min, info.max)

    def _repeat_tick(self):
        now = time.time()
        for action, due in list(self._held.items()):
            if now >= due:
                self._held[action] = now + REPEAT_RATE
                self._send(action, self._target(), repeat=True)

    # ---- source 1: crossbar-inputd -------------------------------------------
    def _cmd(self, msg):
        with self._sock_lock:
            if self._sock:
                try:
                    self._sock.sendall((json.dumps(msg) + "\n").encode())
                except OSError:
                    pass

    def _run_inputd(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(INPUTD_SOCK)
        self._sock, self.mode, self.available, self.error = s, "inputd", True, ""
        self.grabbed = False
        self.update_grab()
        print("gamepad: connected to crossbar-inputd", flush=True)
        buf = b""
        try:
            while True:
                r, _, _ = select.select([s], [], [], 0.04)
                if r:
                    chunk = s.recv(65536)
                    if not chunk:
                        raise ConnectionError("crossbar-inputd closed the connection")
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        m = json.loads(line)
                        if m["e"] == "key":
                            self._on_key(m["code"], m["value"])
                        elif m["e"] == "abs":
                            lo, hi = self.absinfo.get(m["path"], {}).get(str(m["code"]), (-32768, 32767))
                            self._on_abs(m["path"], m["code"], m["value"], lo, hi)
                        elif m["e"] == "dev":
                            if m["added"]:
                                self.names[m["path"]] = m["name"]
                                self.absinfo[m["path"]] = {k: tuple(v) for k, v in m.get("abs", {}).items()}
                            else:
                                self.names.pop(m["path"], None)
                                self._held.clear()
                self._repeat_tick()
        finally:
            with self._sock_lock:
                self._sock = None
            self.names.clear()
            s.close()

    # ---- source 2: read /dev/input directly (fallback) --------------------------
    def _scan(self, evdev):
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
            if (evdev.ecodes.BTN_SOUTH in keys or evdev.ecodes.BTN_MODE in keys or evdev.ecodes.BTN_GAMEPAD in keys) \
                    and not d.name.startswith("Crossbar "):
                self.devices[path] = d
                self.names[path] = d.name
                if self.grabbed:
                    try:
                        d.grab()
                    except OSError:
                        pass
                print(f"gamepad: using {d.name} ({path})", flush=True)
            else:
                d.close()
        for path in [p for p in self.unreadable if not os.path.exists(p)]:
            self.unreadable.pop(path, None)
        blocked = {p: n for p, n in self.unreadable.items() if _is_joystick(p)}
        self.error = ("Controller found but not readable: " + ", ".join(sorted(set(blocked.values()))) +
                      ". Is crossbar-inputd running? See Controller Diagnostics.") if blocked and not self.devices else ""

    def _run_direct(self, evdev):
        self.mode = "direct"
        self._scan(evdev)
        if not self.devices:
            time.sleep(1)
            return
        r, _, _ = select.select(list(self.devices.values()), [], [], 0.04)
        for d in r:
            try:
                for ev in d.read():
                    self._handle(d, ev)
            except OSError:
                self.devices.pop(d.path, None)
                self.names.pop(d.path, None)
                self._held.clear()
        self._repeat_tick()

    def run(self):
        try:
            import evdev
        except ImportError:
            self.mode, self.error = "none", "python-evdev is not installed"
            return
        self.available = True
        while True:
            try:
                if os.path.exists(INPUTD_SOCK):
                    self._run_inputd()          # returns only when the service goes away
                else:
                    deadline = time.time() + 3
                    while time.time() < deadline and not os.path.exists(INPUTD_SOCK):
                        self._run_direct(evdev)
            except Exception as e:
                print(f"gamepad: {e!r}", flush=True)
                time.sleep(1)

    def _watch_focus(self):
        """Re-decide grabbing whenever the focused window changes (sway events)."""
        while True:
            if not os.environ.get("SWAYSOCK"):
                return
            try:
                p = subprocess.Popen(["swaymsg", "-t", "subscribe", "-m", '["window"]'],
                                     stdout=subprocess.PIPE, text=True)
                for line in p.stdout:
                    if '"change": "focus"' in line or '"change":"focus"' in line or '"close"' in line or '"new"' in line:
                        time.sleep(0.05)
                        self.update_grab()
            except Exception as e:
                print(f"gamepad: focus watch: {e!r}", flush=True)
            time.sleep(2)

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()
        threading.Thread(target=self._watch_focus, daemon=True).start()

    def set_overlay(self, on):
        self.overlay_open = on
        self._held.clear()
        self.update_grab()

    def status(self):
        return {"available": self.available, "mode": self.mode, "devices": list(self.names.values()),
                "unreadable": sorted(set(n for p, n in self.unreadable.items() if _is_joystick(p))),
                "grabbed": self.grabbed, "error": self.error, "uinput_error": self.uinput_error}

    def recent(self):
        return list(self.log)


def _device_name(path):
    try:
        with open(f"/sys/class/input/{os.path.basename(path)}/device/name") as f:
            return f.read().strip()
    except OSError:
        return ""


def _is_joystick(path):
    try:
        st = os.stat(path)
        with open(f"/run/udev/data/c{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}") as f:
            return "E:ID_INPUT_JOYSTICK=1" in f.read()
    except OSError:
        return False


def mpv_should_read_gamepad(pads):
    return not pads.names
