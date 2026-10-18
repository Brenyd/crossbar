#!/usr/bin/env python3
"""crossbar-inputd — owns the game controllers (runs as root).

Why root: reading /dev/input and creating a virtual keyboard (/dev/uinput)
depend on permissions that vary by setup. A tiny root service removes that
whole class of problems. It does nothing clever: it streams raw controller
events to crossbard (the user-side backend, which applies the button mapping
and decides where input goes) and carries out three requests:

  {"cmd": "grab", "on": true|false}   exclusive access (games/browsers stop seeing the pad)
  {"cmd": "key", "code": N}           tap a key on a virtual keyboard (drives web apps)
  {"cmd": "list"}                     re-send the device list

Socket: /run/crossbar/input.sock. Anyone can connect, but each connection is
checked (SO_PEERCRED) and only root or the user logged in at the screen (the
active logind session on seat0, whatever their username) is served.
Messages are JSON, one per line.
"""
import json
import os
import pwd
import select
import socket
import struct
import subprocess
import sys
import time

import evdev

SOCK_DIR = "/run/crossbar"
SOCK = os.path.join(SOCK_DIR, "input.sock")
USER = os.environ.get("CROSSBAR_USER", "")     # optional extra user to always allow
E = evdev.ecodes


def is_pad(d):
    try:
        keys = d.capabilities().get(E.EV_KEY, [])
    except OSError:
        return False
    return (E.BTN_SOUTH in keys or E.BTN_MODE in keys or E.BTN_GAMEPAD in keys) and not d.name.startswith("Crossbar ")


def is_virtual(d):
    """Steam Input's virtual controller (no physical path). Grabbed with the rest so a
    game can't see input while the Quick Menu is open, but never read: it mirrors the real pad."""
    try:
        return not d.phys and (d.info.vendor == 0x28DE or "Steam" in d.name or d.name == "Microsoft X-Box 360 pad")
    except AttributeError:
        return False


class Daemon:
    def __init__(self):
        self.devices = {}      # path -> InputDevice
        self.clients = []
        self.grabbed = False
        self.uinput = None
        os.makedirs(SOCK_DIR, exist_ok=True)
        try:
            os.unlink(SOCK)
        except OSError:
            pass
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(SOCK)
        os.chmod(SOCK, 0o666)          # access is decided per connection, see allowed()
        self.server.listen(4)
        self.server.setblocking(False)

    # ---- devices -------------------------------------------------------------
    def scan(self):
        for path in evdev.list_devices():
            if path in self.devices:
                continue
            try:
                d = evdev.InputDevice(path)
            except OSError:
                continue
            if not is_pad(d):
                d.close()
                continue
            self.devices[path] = d
            if self.grabbed:
                self._grab(d, True)
            self.broadcast(self.dev_msg(path, d, True))
            print(f"inputd: + {d.name} ({path})", flush=True)

    def dev_msg(self, path, d, added):
        msg = {"e": "dev", "path": path, "name": d.name, "added": added, "virtual": is_virtual(d)}
        if added:
            absinfo = {}
            for code, info in d.capabilities().get(E.EV_ABS, []):
                absinfo[str(code)] = [info.min, info.max]
            msg["abs"] = absinfo
        return msg

    def drop(self, path):
        d = self.devices.pop(path, None)
        if d:
            self.broadcast({"e": "dev", "path": path, "name": d.name, "added": False})
            print(f"inputd: - {d.name}", flush=True)
            try:
                d.close()
            except OSError:
                pass

    def _grab(self, d, on):
        try:
            d.grab() if on else d.ungrab()
        except OSError:
            pass

    def set_grab(self, on):
        if on == self.grabbed:
            return
        self.grabbed = on
        for d in self.devices.values():
            self._grab(d, on)

    # ---- virtual keyboard ------------------------------------------------
    def key(self, code):
        if self.uinput is None:
            keys = [E.KEY_UP, E.KEY_DOWN, E.KEY_LEFT, E.KEY_RIGHT, E.KEY_ENTER, E.KEY_ESC, E.KEY_TAB,
                    E.KEY_SPACE, E.KEY_BACKSPACE, E.KEY_PLAYPAUSE, E.KEY_NEXTSONG, E.KEY_PREVIOUSSONG, E.KEY_F]
            self.uinput = evdev.UInput({E.EV_KEY: keys}, name="Crossbar Controller Keys")
            time.sleep(0.15)       # let the compositor pick up the new keyboard
        self.uinput.write(E.EV_KEY, code, 1)
        self.uinput.syn()
        self.uinput.write(E.EV_KEY, code, 0)
        self.uinput.syn()

    # ---- who may connect ------------------------------------------------------
    @staticmethod
    def console_uids():
        """uid(s) of whoever is logged in at the screen right now (any username)."""
        uids = set()
        try:
            out = subprocess.run(["loginctl", "list-sessions", "--no-legend"], capture_output=True, text=True, timeout=5).stdout
            for line in out.splitlines():
                parts = line.split()
                if not parts:
                    continue
                props = subprocess.run(["loginctl", "show-session", parts[0], "-p", "User", "-p", "Seat", "-p", "Active",
                                        "-p", "Remote"], capture_output=True, text=True, timeout=5).stdout
                p = dict(x.split("=", 1) for x in props.splitlines() if "=" in x)
                if p.get("Seat") and p.get("Active") == "yes" and p.get("Remote") != "yes" and p.get("User", "").isdigit():
                    uids.add(int(p["User"]))
        except (OSError, subprocess.SubprocessError):
            pass
        if USER:
            try:
                uids.add(pwd.getpwnam(USER).pw_uid)
            except KeyError:
                pass
        return uids

    def allowed(self, c):
        try:
            pid, uid, gid = struct.unpack("3i", c.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
        except OSError:
            return False, None
        if uid == 0:
            return True, uid
        uids = self.console_uids()
        if not uids:                    # no logind info (unusual): fall back to regular users
            return uid >= 1000, uid
        return uid in uids, uid

    # ---- clients -----------------------------------------------------------
    def broadcast(self, msg):
        data = (json.dumps(msg) + "\n").encode()
        for c in list(self.clients):
            try:
                c.sendall(data)
            except OSError:
                self.close_client(c)

    def close_client(self, c):
        if c in self.clients:
            self.clients.remove(c)
        try:
            c.close()
        except OSError:
            pass
        if not self.clients:           # crossbard went away: never leave pads grabbed
            self.set_grab(False)

    def command(self, c, line):
        try:
            m = json.loads(line)
        except ValueError:
            return
        cmd = m.get("cmd")
        if cmd == "grab":
            self.set_grab(bool(m.get("on")))
        elif cmd == "key":
            try:
                self.key(int(m["code"]))
            except Exception as e:
                print(f"inputd: uinput: {e}", flush=True)
        elif cmd == "list":
            for path, d in self.devices.items():
                c.sendall((json.dumps(self.dev_msg(path, d, True)) + "\n").encode())

    def run(self):
        bufs = {}
        last_scan = 0
        print(f"inputd: listening on {SOCK} (console user(s): {sorted(self.console_uids())})", flush=True)
        while True:
            if time.time() - last_scan > 2:
                last_scan = time.time()
                self.scan()
            fds = [self.server] + self.clients + list(self.devices.values())
            r, _, _ = select.select(fds, [], [], 1)
            for x in r:
                if x is self.server:
                    c, _ = self.server.accept()
                    ok, uid = self.allowed(c)
                    if not ok:
                        print(f"inputd: refused uid {uid} (not the user at the screen)", flush=True)
                        try:
                            c.sendall((json.dumps({"e": "error", "msg": f"uid {uid} isn't the user logged in at the screen"}) + "\n").encode())
                            c.close()
                        except OSError:
                            pass
                        continue
                    self.clients.append(c)
                    bufs[c] = b""
                    for path, d in self.devices.items():
                        c.sendall((json.dumps(self.dev_msg(path, d, True)) + "\n").encode())
                elif isinstance(x, socket.socket):
                    try:
                        chunk = x.recv(4096)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        self.close_client(x)
                        bufs.pop(x, None)
                        continue
                    bufs[x] += chunk
                    while b"\n" in bufs[x]:
                        line, bufs[x] = bufs[x].split(b"\n", 1)
                        self.command(x, line)
                else:
                    try:
                        for ev in x.read():
                            if ev.type == E.EV_KEY:
                                self.broadcast({"e": "key", "path": x.path, "code": ev.code, "value": ev.value})
                            elif ev.type == E.EV_ABS:
                                self.broadcast({"e": "abs", "path": x.path, "code": ev.code, "value": ev.value})
                    except OSError:
                        self.drop(x.path)


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("crossbar-inputd should run as root", file=sys.stderr)
    Daemon().run()
