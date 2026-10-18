"""Terminal sessions for the built-in terminal (Settings › System Settings › Terminal).

A shell runs in a pseudo-terminal here; the XMB page shows it (xterm.js) and
sends keystrokes back. Output is streamed over server-sent events.
"""
import base64
import fcntl
import os
import pty
import secrets
import select
import signal
import struct
import termios
import threading
import time

from .events import HUB

TOKEN = secrets.token_urlsafe(24)     # only the XMB page (same origin) can read this from /api/state
SESSIONS = {}
_lock = threading.Lock()


class Session:
    def __init__(self, cmd=None, cols=120, rows=34):
        self.id = secrets.token_hex(6)
        self.buffer = bytearray()         # recent output, so a reopened view can catch up
        self.alive = True
        pid, fd = pty.fork()
        if pid == 0:                      # child: become the shell
            os.environ["TERM"] = "xterm-256color"
            os.environ.setdefault("LANG", "en_US.UTF-8")
            os.chdir(os.path.expanduser("~"))
            if cmd:
                os.execvp("bash", ["bash", "-lc", cmd + "; echo; echo '[finished — press Esc to close]'; exec bash -l"])
            os.execvp("bash", ["bash", "-l"])
        self.pid, self.fd = pid, fd
        self.resize(cols, rows)
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        while self.alive:
            try:
                r, _, _ = select.select([self.fd], [], [], 0.5)
                if not r:
                    continue
                data = os.read(self.fd, 65536)
            except OSError:
                data = b""
            if not data:
                break
            self.buffer += data
            del self.buffer[:-200_000]
            HUB.publish({"type": "term", "id": self.id, "data": base64.b64encode(data).decode()})
        self.alive = False
        HUB.publish({"type": "term-exit", "id": self.id})
        try:
            os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            pass

    def write(self, data):
        os.write(self.fd, data.encode())

    def resize(self, cols, rows):
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", int(rows), int(cols), 0, 0))
        except OSError:
            pass

    def close(self):
        self.alive = False
        for sig in (signal.SIGHUP, signal.SIGKILL):
            try:
                os.kill(self.pid, sig)
                time.sleep(0.1)
            except ProcessLookupError:
                break
        try:
            os.close(self.fd)
        except OSError:
            pass


def check(token):
    if not token or not secrets.compare_digest(str(token), TOKEN):
        raise PermissionError("terminal token")


def open_session(cmd=None, cols=120, rows=34):
    with _lock:
        s = Session(cmd, cols, rows)
        SESSIONS[s.id] = s
    return s


def get(sid):
    s = SESSIONS.get(sid)
    if not s:
        raise KeyError("terminal session")
    return s


def close(sid):
    s = SESSIONS.pop(sid, None)
    if s:
        s.close()
