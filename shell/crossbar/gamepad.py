"""Controller handling: mapping, combos and routing.

Raw events come from crossbar-inputd (root service, /run/crossbar/input.sock)
or — if that isn't available — straight from /dev/input. Each press goes
through the user's mapping (controls.py) and is sent only to what's in front:

  - Quick Menu overlay -> the overlay
  - the XMB            -> the XMB page (server-sent events)
  - video player       -> mpv's control panel
  - web apps           -> keys on a virtual keyboard (YouTube TV, Twitch, browser…)
  - a game / other     -> nothing: the controller is released to the game

While Crossbar is the target it *grabs* the controller so nothing behind reacts.
The Quick Menu is a button combo (Select+Start by default) so Guide/PS stays
free for Steam's own overlay.

Combos: a button that's part of a combo fires its normal action on *release*
(if the combo didn't happen), so pressing Select+Start doesn't also trigger
Select's and Start's own actions.
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

from . import controls, player, session, system
from .events import HUB

REPEAT_DELAY, REPEAT_RATE = 0.38, 0.085
INPUTD_SOCK = "/run/crossbar/input.sock"

# Extra buttons in the browser (not mappable actions): right stick scrolls, triggers page,
# a stick click toggles the pointer.
BROWSER_RAW = {"ABS_RY+": "scroll_down", "ABS_RY-": "scroll_up", "ABS_RX+": "scroll_right", "ABS_RX-": "scroll_left",
               "ABS_Z+": "page_up", "ABS_RZ+": "page_down", "BTN_TL2": "page_up", "BTN_TR2": "page_down",
               "BTN_THUMBL": "pointer", "BTN_THUMBR": "pointer"}

WEB_KEYS = {
    "up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT",
    "ok": "KEY_ENTER", "back": "KEY_ESC", "menu": "KEY_TAB",
    "toggle": "KEY_PLAYPAUSE", "prev": "KEY_PREVIOUSSONG", "next": "KEY_NEXTSONG",
}


class Gamepads:
    def __init__(self, on_home):
        self.on_home = on_home
        self.mode = "starting"          # "inputd" | "direct" | "none"
        self.inputd_error = ""
        self.devices = {}               # path -> InputDevice (direct mode)
        self.names = {}                 # path -> name of real controllers
        self.virtual = {}               # path -> name of virtual pads (e.g. Steam's): grabbed, never read
        self.remotes = {}               # path -> name of TV remotes (held by crossbar-inputd)
        self._rkeymap = {}
        self._learn = None
        self.absinfo = {}
        self.unreadable = {}
        self.available = False
        self.error = ""
        self.log = collections.deque(maxlen=25)
        self.browser_pads = []          # what the XMB page's Gamepad API sees (for diagnostics)
        self.overlay_open = False
        self.grabbed = False
        self.xmb_focused = True
        self._keymap, self._absmap, self._combos, self._combo_keys = {}, {}, [], set()
        self._down = {}                 # key token -> press time
        self._consumed = set()
        self._held = {}
        self._abs_dir = {}
        self._capture = None
        self._focus_cache = (0, None)
        self._sock = None
        self._sock_lock = threading.Lock()
        self._uinput = None
        self.uinput_error = ""
        self.browser_pid = lambda: None       # set by the server: Crossbar's browser process
        self.on_browser = None                # set by the server: browser.act(action, repeat)
        self.on_media = None                  # set by the server: media key -> music / Spotify (True if handled)
        self.reload()

    # ---- mapping -----------------------------------------------------------
    def reload(self):
        try:
            import evdev
        except ImportError:
            return
        E = evdev.ecodes.ecodes
        keymap, absmap, combos = {}, {}, []
        for action, tokens in controls.load()["gamepad"].items():
            for t in tokens:
                if "&" in t:
                    parts = frozenset(x for x in t.split("&") if x in E)
                    if len(parts) >= 2:
                        combos.append((parts, action))
                elif t.startswith("ABS_") and t[-1] in "+-":
                    code = E.get(t[:-1])
                    if code is not None:
                        absmap.setdefault((code, 1 if t[-1] == "+" else -1), []).append(action)
                else:
                    code = E.get(t)
                    if code is not None:
                        keymap.setdefault(code, []).append(action)
        self._keymap, self._absmap, self._combos = keymap, absmap, combos
        rk = {}
        for action, tokens in controls.load()["remote"].items():
            for t in tokens:
                code = E.get(t)
                if code is not None:
                    rk.setdefault(code, []).append(action)
        self._rkeymap = rk
        self._combo_keys = {E[n] for parts, _ in combos for n in parts}

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
        if getattr(self, "osk_open", False):
            return "osk"                  # the system on-screen keyboard is up: it gets the pad
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
        elif f.get("pid") and f.get("pid") == self.browser_pid():
            t = "browser"                 # Crossbar's browser: driven over DevTools
        elif system.is_web_app(f):
            t = "web"
        elif not f.get("con_id"):
            t = "xmb"
        else:
            t = "app"
        self._focus_cache = (now, t)
        return t

    def update_grab(self):
        """Own the controller unless a game/app is in front; tell the XMB if it's in front."""
        target = self._target(fresh=True)
        xmb = target == "xmb"
        if xmb and not system.launching() and not self.overlay_open:
            # the menu is in front but a Steam window is still showing: Steam would get
            # the same presses (it reads controllers itself), so put it away
            vis = system.visible_steam()
            if vis:
                for w in vis:
                    system.hide_window(w["con_id"])
        if xmb != self.xmb_focused:
            self.xmb_focused = xmb
            HUB.publish({"type": "focus", "xmb": xmb})
        want = target != "app"
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
        if target in ("xmb", "overlay", "osk"):
            HUB.publish({"type": "input", "action": action, "to": target, "repeat": repeat})
        elif target == "video":
            if not repeat or action in ("up", "down"):
                player.video_input(action)
        elif target == "web":
            self._web_key(action)
        elif target == "browser" and self.on_browser:
            self.on_browser(action, repeat)

    def pad_recent(self):
        """True when the controller was used more recently than a real keyboard/mouse."""
        return getattr(self, "last_pad", 0) > getattr(self, "last_physical", 0)

    def keyboard_up(self):
        """An on-screen keyboard has the controller (the system one, or the menu's own)."""
        return getattr(self, "osk_open", False) or (getattr(self, "osk_web", False) and self._target() == "xmb")

    def _press(self, action, token=""):
        if token and action not in controls.DIRECTIONS and action != "home" and self.keyboard_up():
            from . import glyphs
            kb = glyphs.keyboard_action(token.split("+")[0], action, glyphs.xpad_layout(list(self.names.values())))
            if kb:
                action = kb
        if action == "home":
            self.log.appendleft({"t": time.time(), "token": token, "action": action, "to": "quick menu"})
            self.on_home()
            return
        target = self._target()
        self.last_pad = time.time()
        self.log.appendleft({"t": time.time(), "token": token, "action": action, "to": target})
        self._send(action, target)
        if action in controls.DIRECTIONS and target in ("xmb", "video", "web", "overlay", "osk", "browser"):
            self._held[action] = time.time() + REPEAT_DELAY

    def _raw(self, token, pressed):
        """Buttons/axes no action uses: the keyboard's L2/R2/L3, extras in the browser."""
        if pressed and self.keyboard_up():
            from . import glyphs
            kb = glyphs.keyboard_action(token, None, glyphs.xpad_layout(list(self.names.values())))
            if kb:
                self.last_pad = time.time()
                target = "osk" if getattr(self, "osk_open", False) else "xmb"
                self.log.appendleft({"t": time.time(), "token": token, "action": kb, "to": target})
                self._send(kb, target)
                return
        action = BROWSER_RAW.get(token)
        if not action:
            return
        if not pressed:
            self._held.pop(action, None)
            return
        if self._target() != "browser":
            return
        self.last_pad = time.time()
        self.log.appendleft({"t": time.time(), "token": token, "action": action, "to": "browser"})
        self._send(action, "browser")
        if action.startswith("scroll_"):
            self._held[action] = time.time() + 0.12

    def _release(self, action):
        self._held.pop(action, None)

    # ---- virtual keyboard for web apps --------------------------------------
    # ---- typing (on-screen keyboard) -------------------------------------------------
    US = {**{c: (c, False) for c in "abcdefghijklmnopqrstuvwxyz0123456789"},
          **{c.upper(): (c, True) for c in "abcdefghijklmnopqrstuvwxyz"},
          " ": ("SPACE", False), "\n": ("ENTER", False), "\t": ("TAB", False),
          "-": ("MINUS", False), "_": ("MINUS", True), "=": ("EQUAL", False), "+": ("EQUAL", True),
          "[": ("LEFTBRACE", False), "{": ("LEFTBRACE", True), "]": ("RIGHTBRACE", False), "}": ("RIGHTBRACE", True),
          ";": ("SEMICOLON", False), ":": ("SEMICOLON", True), "'": ("APOSTROPHE", False), '"': ("APOSTROPHE", True),
          "`": ("GRAVE", False), "~": ("GRAVE", True), "\\": ("BACKSLASH", False), "|": ("BACKSLASH", True),
          ",": ("COMMA", False), "<": ("COMMA", True), ".": ("DOT", False), ">": ("DOT", True),
          "/": ("SLASH", False), "?": ("SLASH", True),
          "!": ("1", True), "@": ("2", True), "#": ("3", True), "$": ("4", True), "%": ("5", True),
          "^": ("6", True), "&": ("7", True), "*": ("8", True), "(": ("9", True), ")": ("0", True)}
    SPECIAL = {"backspace": "BACKSPACE", "enter": "ENTER", "left": "LEFT", "right": "RIGHT", "up": "UP",
               "down": "DOWN", "tab": "TAB", "esc": "ESC", "home": "HOME", "end": "END", "delete": "DELETE",
               "f4": "F4", "f12": "F12"}

    def type_keys(self, text="", special=None, shift=False):
        """Type text (US layout) or one special key through the virtual keyboard."""
        import evdev
        ec = evdev.ecodes.ecodes
        seq = []
        if special:
            name = self.SPECIAL.get(special)
            if name:
                seq.append([ec["KEY_" + name], bool(shift)])
        for ch in text[:256]:
            k = self.US.get(ch)
            if k:
                seq.append([ec["KEY_" + k[0].upper()], k[1]])
        if not seq:
            return 0
        if self.mode == "inputd":
            self._cmd({"cmd": "keys", "seq": seq})
        else:
            if self._uinput is None or not getattr(self, "_uinput_full", False):
                keys = sorted({c for c, _ in seq} | {ec["KEY_LEFTSHIFT"]} | {ec["KEY_" + v] for v in self.SPECIAL.values()}
                              | {ec["KEY_" + v[0].upper()] for v in self.US.values()})
                self._uinput = evdev.UInput({evdev.ecodes.EV_KEY: keys}, name="Crossbar Controller Keys")
                self._uinput_full = True
                time.sleep(0.15)
            for code, shift in seq:
                if shift:
                    self._uinput.write(evdev.ecodes.EV_KEY, ec["KEY_LEFTSHIFT"], 1)
                self._uinput.write(evdev.ecodes.EV_KEY, code, 1)
                self._uinput.write(evdev.ecodes.EV_KEY, code, 0)
                if shift:
                    self._uinput.write(evdev.ecodes.EV_KEY, ec["KEY_LEFTSHIFT"], 0)
                self._uinput.syn()
        return len(seq)

    def _web_key(self, action):
        name = WEB_KEYS.get(action)
        if not name:
            return
        import evdev
        self._key_code(evdev.ecodes.ecodes[name])

    def _key_code(self, code):
        try:
            import evdev
            if self.mode == "inputd":
                self._cmd({"cmd": "key", "code": code})
                return
            if self._uinput is None:
                keys = sorted({evdev.ecodes.ecodes[k] for k in set(WEB_KEYS.values()) | set(self.MEDIA_KEYS.values())
                               | {"KEY_PAGEUP", "KEY_PAGEDOWN"}} | {code}
                              | {evdev.ecodes.ecodes[f"KEY_{d}"] for d in "0123456789"})
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
    def capture(self, timeout=10, combo=False, kind="gamepad"):
        ev = threading.Event()
        self._capture = {"event": ev, "token": None, "combo": combo and kind != "remote", "first": None, "kind": kind}
        ev.wait(timeout)
        tok = self._capture["token"] if self._capture else None
        self._capture = None
        return tok

    def cancel_capture(self):
        if self._capture:
            self._capture["event"].set()

    def _capture_key(self, token):
        c = self._capture
        if not c or c["token"]:
            return
        if not c["combo"]:
            c["token"] = token
            c["event"].set()
        elif c["first"] is None:
            c["first"] = token
        elif token != c["first"] and c["first"] in self._down_tokens():
            c["token"] = f"{c['first']}&{token}"
            c["event"].set()

    def _down_tokens(self):
        return {self._key_token(code) for code in self._down}

    # ---- raw events ------------------------------------------------------------
    def _on_key(self, code, value):
        if value == 1:
            self._down[code] = time.time()
        elif value == 0:
            self._down.pop(code, None)
        if self._capture and self._capture.get("kind") != "remote":
            if value == 1:
                self._capture_key(self._key_token(code))
            return
        token = self._key_token(code)
        if value == 1:
            fired = False
            for parts, action in self._combos:
                if token in parts and parts <= self._down_tokens():
                    import evdev
                    for n in parts:
                        self._consumed.add(evdev.ecodes.ecodes[n])
                    self._press(action, "+".join(sorted(parts)))
                    fired = True
            if fired or code in self._combo_keys:
                return                    # combo buttons act on release (below)
        elif value == 0 and code in self._combo_keys:
            if code in self._consumed:
                self._consumed.discard(code)
                return
            for a in self._keymap.get(code, []):
                self._press(a, token)
                self._release(a)
            return
        actions = self._keymap.get(code, [])
        if not actions and value in (0, 1) and (token in BROWSER_RAW or token in ("BTN_TL2", "BTN_TR2", "BTN_THUMBL")):
            return self._raw(token, value == 1)
        if value == 1 and not actions:
            self.log.appendleft({"t": time.time(), "token": token, "action": None, "to": "unmapped"})
        for a in actions:
            if value == 1:
                self._press(a, token)
            elif value == 0:
                self._release(a)

    # ---- TV remotes --------------------------------------------------------------
    VOLUME_STEP = 5

    @staticmethod
    def _remote_token(code):
        import evdev
        n = evdev.ecodes.KEY.get(code) or evdev.ecodes.BTN.get(code)
        if isinstance(n, (list, tuple)):
            n = next((x for x in n if x in controls.REMOTE_LABELS), None) \
                or next((x for x in n if "MIN_" not in x and "MAX" not in x), n[0])
        return n or f"KEY_{code}"

    def _on_remote_key(self, path, code, value):
        """A TV remote button: its own mapping (Settings › Controller, Remote & Keyboard › TV Remote).
        In a game or another app the remote still works: its keys are typed into that app."""
        token = self._remote_token(code)
        if value == 1 and self._learn is not None and not self._learn.get("name"):
            self._learn.update(name=self.remotes.get(path, ""), code=code)
            self._learn["event"].set()
            return
        if self._capture and self._capture.get("kind") == "remote":
            if value == 1:
                self._capture_key(token)
            return
        actions = self._rkeymap.get(code, [])
        if value == 0:
            for a in actions:
                self._release(a)
            return
        self.last_pad = time.time()
        if not actions:
            if value == 1:
                digit = token.rsplit("_", 1)[-1]
                if len(digit) == 1 and digit.isdigit() and self._target() == "video":
                    player.video_input(f"digit:{digit}")         # a channel number
                    self.log.appendleft({"t": time.time(), "token": token, "action": f"channel {digit}", "to": "video"})
                elif len(digit) == 1 and digit.isdigit() and self._target() not in ("overlay",):
                    import evdev
                    self._key_code(evdev.ecodes.ecodes["KEY_" + digit])
                    self.log.appendleft({"t": time.time(), "token": token, "action": f"type {digit}", "to": self._target()})
                else:
                    self.log.appendleft({"t": time.time(), "token": token, "action": None, "to": "unmapped (remote)"})
            return
        for a in actions:
            if a in ("volume_up", "volume_down", "mute"):
                if a == "mute" and value != 1:
                    continue
                threading.Thread(target=self._volume, args=(a,), daemon=True).start()
                continue
            target = self._target()
            if value == 2:                       # the remote's own key repeat: ours handles held directions
                if target == "video" and a in ("rewind", "fast_forward"):
                    player.video_input(a)
                elif target == "app" and a in controls.DIRECTIONS:
                    self._web_key(a)
                continue
            self.log.appendleft({"t": time.time(), "token": token, "action": a, "to": target})
            if a == "power":
                self.on_home()
            elif a in controls.MEDIA_ACTIONS:
                self._media(a, target)
            elif a in ("channel_up", "channel_down"):
                if target == "video":
                    player.video_input(a)        # live TV: the next / previous channel
                elif target in ("web", "app"):
                    self._key_code(self._ec("KEY_PAGEUP" if a == "channel_up" else "KEY_PAGEDOWN"))
                else:
                    self._press("next" if a == "channel_up" else "prev", token)
            elif a in ("last_channel", "subtitles", "audio_track"):
                if target == "video":
                    player.video_input(a)
            elif a == "live_tv":
                if target != "xmb":
                    system.show_shell()
                HUB.publish({"type": "open-cat", "cat": "tv", "folder": "live-tv"})
            elif target == "app" and a != "home":
                self._web_key(a)                 # a game / app in front: type the matching key into it
            else:
                self._press(a, token)

    MEDIA_KEYS = {"toggle": "KEY_PLAYPAUSE", "play": "KEY_PLAYCD", "pause": "KEY_PAUSECD", "stop": "KEY_STOPCD",
                  "rewind": "KEY_REWIND", "fast_forward": "KEY_FASTFORWARD", "prev": "KEY_PREVIOUSSONG",
                  "next": "KEY_NEXTSONG"}

    @staticmethod
    def _ec(name):
        import evdev
        return evdev.ecodes.ecodes[name]

    def _media(self, a, target):
        """Media keys reach whatever is playing: the video / live TV player, a web app or the
        browser (as real media keys), else music or Spotify behind the menu or a game."""
        if target == "video":
            player.video_input(a)
            return
        if target in ("web", "browser"):
            self._key_code(self._ec(self.MEDIA_KEYS[a]))
            return
        threading.Thread(target=self._media_behind, args=(a, target), daemon=True).start()

    def _media_behind(self, a, target):
        try:
            if self.on_media and self.on_media(a):
                return
        except Exception as e:
            self.log.appendleft({"t": time.time(), "token": a, "action": f"media failed: {e}", "to": "music"})
            return
        if player.VIDEO.running():               # a video left open behind the menu
            player.video_input(a)
        elif target == "app":
            self._key_code(self._ec(self.MEDIA_KEYS[a]))
        else:
            HUB.publish({"type": "notice", "icon": "music", "text": "Nothing is playing"})

    def _volume(self, a):
        try:
            if a == "mute":
                system.set_audio("output", mute=True)
            else:
                system.set_audio("output", delta=self.VOLUME_STEP if a == "volume_up" else -self.VOLUME_STEP)
            v = system.audio().get("output", {})
            if v:
                HUB.publish({"type": "notice", "icon": "sound",
                             "text": "Muted" if v.get("muted") else f"Volume {v.get('volume')}%"})
        except Exception as e:
            self.log.appendleft({"t": time.time(), "token": a, "action": f"volume failed: {e}", "to": "system"})

    def learn_remote(self, timeout=15):
        """Set Up a Remote: the next key pressed on any keyboard-like device names the remote."""
        self._learn = {"event": threading.Event(), "name": None}
        self._cmd({"cmd": "learn", "on": True, "timeout": timeout})
        self._learn["event"].wait(timeout)
        got, self._learn = self._learn, None
        self._cmd({"cmd": "learn", "on": False})
        return got.get("name") if got else None

    def cancel_learn(self):
        if self._learn:
            self._learn["event"].set()

    def push_remote_devices(self):
        self._cmd({"cmd": "remotes", "force": controls.load()["remote_devices"]})

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
            if not self._absmap.get((code, prev)):
                self._raw(f"{name}{'+' if prev > 0 else '-'}", False)
        if direction:
            token = f"{name}{'+' if direction > 0 else '-'}"
            if self._capture:
                if not self._capture["combo"]:
                    self._capture_key(token)
                return
            for a in self._absmap.get((code, direction), []):
                self._press(a, token)
            if not self._absmap.get((code, direction)):
                self._raw(token, True)

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
                target = self._target()
                if action.startswith("scroll_") and target != "browser":
                    self._held.pop(action, None)
                    continue
                self._send(action, target, repeat=True)

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
        s.settimeout(3)
        s.connect(INPUTD_SOCK)            # raises if the service isn't answering (stale socket)
        s.settimeout(None)
        self._sock, self.mode, self.available, self.error, self.inputd_error = s, "inputd", True, "", ""
        self.grabbed = None
        self.update_grab()
        self.push_remote_devices()
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
                        if m.get("e") == "error":
                            raise ConnectionError(m.get("msg", "refused"))
                        path = m.get("path")
                        if m["e"] in ("key", "abs") and path in self.virtual:
                            continue      # Steam's virtual pad mirrors the real one: ignore
                        if m["e"] == "key" and path in self.remotes:
                            self._on_remote_key(path, m["code"], m["value"])
                        elif m["e"] == "learned":
                            if self._learn is not None and not self._learn.get("name"):
                                self._learn.update(name=m.get("name"), code=m.get("code"))
                                self._learn["event"].set()
                        elif m["e"] == "key":
                            self._on_key(m["code"], m["value"])
                        elif m["e"] == "abs":
                            lo, hi = self.absinfo.get(path, {}).get(str(m["code"]), (-32768, 32767))
                            self._on_abs(path, m["code"], m["value"], lo, hi)
                        elif m["e"] == "physical":       # a real keyboard/mouse was used
                            self.last_physical = time.time()
                            HUB.publish({"type": "physical-input"})
                        elif m["e"] == "dev":
                            table = self.remotes if m.get("remote") else self.virtual if m.get("virtual") else self.names
                            if m["added"]:
                                table[path] = m["name"]
                                self.absinfo[path] = {k: tuple(v) for k, v in m.get("abs", {}).items()}
                            else:
                                table.pop(path, None)
                                self._held.clear()
                                self._down.clear()
                self._repeat_tick()
        finally:
            with self._sock_lock:
                self._sock = None
            self.names.clear()
            self.virtual.clear()
            self.remotes.clear()
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
            if (evdev.ecodes.BTN_SOUTH in keys or evdev.ecodes.BTN_MODE in keys) \
                    and not d.name.startswith("Crossbar ") and not is_virtual_pad(d):
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
                      ". The controller service (crossbar-inputd) isn't running.") if blocked and not self.devices else ""

    def _run_direct(self, evdev):
        if self.mode != "direct":
            self.mode = "direct"
            self.grabbed = None
            self.update_grab()
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
                self._down.clear()
        self._repeat_tick()

    def _close_direct(self):
        for d in self.devices.values():
            try:
                d.ungrab()
            except OSError:
                pass
            d.close()
        self.devices.clear()
        self.names.clear()

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
                    self._close_direct()
                    self._run_inputd()      # returns/raises when the service goes away
            except Exception as e:
                msg = repr(e)
                if isinstance(e, PermissionError):
                    msg = "the controller service refused this user (update crossbar-inputd)"
                if msg != self.inputd_error:      # log each new problem once, not every second
                    print(f"gamepad: controller service unavailable: {msg}; reading controllers directly", flush=True)
                self.inputd_error = msg
            # Fallback for a while, then try the service again.
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    self._run_direct(evdev)
                except Exception as e:
                    if repr(e) != getattr(self, "_last_direct_error", None):
                        print(f"gamepad: {e!r}", flush=True)
                        self._last_direct_error = repr(e)
                    time.sleep(1)

    def _watch_focus(self):
        """Re-decide grabbing (and tell the XMB) whenever the focused window changes."""
        while True:
            if not os.environ.get("SWAYSOCK"):
                return
            try:
                p = subprocess.Popen(["swaymsg", "-t", "subscribe", "-m", '["window"]'],
                                     stdout=subprocess.PIPE, text=True)
                steam_guard = 0
                for line in p.stdout:
                    if system.launching():
                        # a game is starting: Steam's updater / sign-in windows come and go
                        if any(k in line for k in ('"focus"', '"close"', '"new"', '"fullscreen_mode"')):
                            time.sleep(0.05)
                            self.update_grab()
                        continue
                    if ('"change": "focus"' in line or '"change":"focus"' in line) and time.time() < steam_guard:
                        # Steam brings Big Picture back after a game: send it away again
                        time.sleep(0.1)
                        f = system.focused()
                        if f and system.is_steam_client(f) and not self.overlay_open:
                            system.hide_steam()
                    if '"change": "close"' in line or '"change":"close"' in line:
                        steam_guard = time.time() + 12    # native games don't all say "steam_app"
                        # a game/video/app closed: go back to the menu, like a console
                        time.sleep(0.15)
                        if not self.overlay_open:
                            f = system.focused()
                            if f is not None and not ("xmb" in f["marks"] or system.is_xmb(f)) \
                                    and (not f.get("con_id") or system.is_background_window(f)):
                                system.after_game() if system.is_steam_client(f) else system.show_shell()
                        # game mode: the XMB is closed, so when the last game goes, bring it back
                        if session.game_mode() and not self.overlay_open and not any(
                                not system.is_background_window(w) and not system.is_xmb(w)
                                and "discord" not in (w.get("app") or "").lower() for w in system.windows()):
                            system.after_game()
                    if ('"change": "new"' in line or '"change":"new"' in line or '"change": "focus"' in line) \
                            and not session.game_mode():
                        f = system.focused()
                        app = ((f or {}).get("app") or "").lower()
                        if app.startswith("steam_app_") or app == "gamescope":
                            threading.Thread(target=session.enter_game_mode, args=(app, True), daemon=True).start()
                    if any(k in line for k in ('"focus"', '"close"', '"new"', '"fullscreen_mode"')):
                        time.sleep(0.05)
                        self.update_grab()
            except Exception as e:
                print(f"gamepad: focus watch: {e!r}", flush=True)
            time.sleep(2)

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()
        threading.Thread(target=self._watch_focus, daemon=True).start()

    def set_osk(self, on):
        self.osk_open = bool(on)
        self._held.clear()
        self.update_grab()

    def set_overlay(self, on):
        self.overlay_open = on
        self._held.clear()
        self.update_grab()

    def status(self):
        return {"available": self.available, "mode": self.mode, "devices": list(self.names.values()),
                "virtual": list(self.virtual.values()), "remotes": list(self.remotes.values()),
                "unreadable": sorted(set(n for p, n in self.unreadable.items() if _is_joystick(p))),
                "grabbed": bool(self.grabbed), "xmb_focused": self.xmb_focused, "error": self.error,
                "inputd_error": self.inputd_error, "uinput_error": self.uinput_error,
                "browser_pads": self.browser_pads}

    def recent(self):
        return list(self.log)


def is_virtual_pad(d):
    """Pads made by software (Steam Input's virtual controller): no physical path."""
    try:
        vendor = d.info.vendor
        phys = d.phys or ""
    except AttributeError:
        return False
    return not phys and (vendor == 0x28DE or "Steam" in d.name or d.name == "Microsoft X-Box 360 pad")


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
