"""mpv-based playback.

Music: one hidden mpv (no window) that keeps playing while you browse or game.
Video: a fullscreen mpv window with Crossbar's own controller-friendly control
panel (mpv/crossbar-osc.lua). Gamepad input reaches it through crossbard.
"""
import json
import os
import socket
import subprocess
import tempfile
import threading
import time

from . import util

RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
OSC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mpv", "crossbar-osc.lua")
WATCH_LATER = os.path.join(util.CONFIG_DIR, "watch_later")
VIDEO_APP_ID = "crossbar-player"


class Mpv:
    def __init__(self, name, args):
        self.sock = os.path.join(RUNTIME, f"crossbar-{name}.sock")
        self.args = args
        self.proc = None
        self._lock = threading.Lock()
        self._rid = 0

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, extra=()):
        if self.running():
            return
        if not util.which("mpv"):
            raise RuntimeError("mpv is not installed")
        try:
            os.unlink(self.sock)
        except OSError:
            pass
        self.proc = subprocess.Popen(["mpv", f"--input-ipc-server={self.sock}", *self.args, *extra],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(50):
            if os.path.exists(self.sock):
                return
            time.sleep(0.1)

    def cmd(self, *args):
        if not self.running():
            return None
        with self._lock:
            self._rid += 1
            rid = self._rid
            try:
                s = socket.socket(socket.AF_UNIX)
                s.settimeout(1.5)
                s.connect(self.sock)
                s.sendall(json.dumps({"command": list(args), "request_id": rid}).encode() + b"\n")
                buf = b""
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        return None
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        msg = json.loads(line)
                        if msg.get("request_id") == rid:
                            return msg.get("data") if msg.get("error") == "success" else None
            except (OSError, ValueError):
                return None
            finally:
                s.close()

    def get(self, prop, default=None):
        v = self.cmd("get_property", prop)
        return default if v is None else v

    def stop(self):
        if self.running():
            self.cmd("quit")
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


MUSIC = Mpv("music", ["--idle=yes", "--no-video", "--audio-display=no", "--no-terminal",
                      "--volume=80", "--gapless-audio=weak", "--replaygain=album"])
VIDEO = Mpv("video", [])
_music_meta = {"shuffle": False}


# ---- music ---------------------------------------------------------------
def play_music(paths, index=0):
    paths = [p for p in paths if os.path.isfile(p)]
    if not paths:
        raise RuntimeError("Nothing to play")
    MUSIC.start()
    m3u = os.path.join(RUNTIME, "crossbar-music.m3u")
    with open(m3u, "w") as f:
        f.write("\n".join(paths) + "\n")
    MUSIC.cmd("loadlist", m3u, "replace")
    MUSIC.cmd("set_property", "playlist-pos", int(index))
    MUSIC.cmd("set_property", "pause", False)
    _music_meta["shuffle"] = False


def music_state():
    if not MUSIC.running() or MUSIC.get("idle-active", True):
        return None
    meta = MUSIC.get("metadata", {}) or {}
    low = {k.lower(): v for k, v in meta.items()}
    path = MUSIC.get("path", "")
    return {
        "path": path,
        "title": low.get("title") or MUSIC.get("media-title") or os.path.basename(path),
        "artist": low.get("artist") or low.get("album_artist") or "",
        "album": low.get("album", ""),
        "position": MUSIC.get("time-pos", 0) or 0,
        "duration": MUSIC.get("duration", 0) or 0,
        "paused": bool(MUSIC.get("pause", False)),
        "index": MUSIC.get("playlist-pos", 0),
        "count": MUSIC.get("playlist-count", 0),
        "repeat": MUSIC.get("loop-playlist", "no") not in ("no", False),
        "shuffle": _music_meta["shuffle"],
        "volume": MUSIC.get("volume", 80),
    }


def music_control(action, value=None):
    if not MUSIC.running():
        return
    if action == "toggle":
        MUSIC.cmd("cycle", "pause")
    elif action == "pause":
        MUSIC.cmd("set_property", "pause", True)
    elif action == "next":
        MUSIC.cmd("playlist-next", "force")
    elif action == "prev":
        if (MUSIC.get("time-pos", 0) or 0) > 4:
            MUSIC.cmd("seek", 0, "absolute")
        else:
            MUSIC.cmd("playlist-prev", "force")
    elif action == "stop":
        MUSIC.cmd("stop")
    elif action == "seek":
        MUSIC.cmd("seek", float(value), "relative")
    elif action == "shuffle":
        if _music_meta["shuffle"]:
            MUSIC.cmd("playlist-unshuffle")
        else:
            MUSIC.cmd("playlist-shuffle")
        _music_meta["shuffle"] = not _music_meta["shuffle"]
    elif action == "repeat":
        cur = MUSIC.get("loop-playlist", "no")
        MUSIC.cmd("set_property", "loop-playlist", "no" if cur not in ("no", False) else "inf")
    elif action == "volume":
        MUSIC.cmd("add", "volume", float(value))


def pause_music():
    if MUSIC.running():
        MUSIC.cmd("set_property", "pause", True)


# ---- video ---------------------------------------------------------------
def play_video(paths, index=0, mpv_gamepad=False, entries=None, user_agent=None):
    """Play local files (paths) or streams (entries = [(title, url)], e.g. IPTV)."""
    if entries:
        lines = ["#EXTM3U"] + [ln for t, u in entries for ln in (f"#EXTINF:-1,{t.replace(chr(10), ' ')}", u)]
    else:
        lines = [p for p in paths if os.path.isfile(p)]
    if not lines:
        raise RuntimeError("Nothing to play")
    pause_music()
    cfg = util.load_config()["video"]
    m3u = os.path.join(RUNTIME, "crossbar-video.m3u")
    fd = os.open(m3u, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # stream URLs can contain a password
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    if VIDEO.running():
        VIDEO.cmd("set_property", "user-agent", user_agent or "")
        VIDEO.cmd("loadlist", m3u, "replace")
        VIDEO.cmd("set_property", "playlist-pos", int(index))
        VIDEO.cmd("set_property", "pause", False)
        return
    os.makedirs(WATCH_LATER, exist_ok=True)
    args = [
        "--fs", "--force-window=immediate", f"--wayland-app-id={VIDEO_APP_ID}", "--title=${media-title}",
        "--osc=no", "--osd-bar=no", "--osd-level=0", "--no-terminal", "--keep-open=no",
        f"--script={OSC}", f"--watch-later-dir={WATCH_LATER}",
        "--save-position-on-quit" if cfg.get("resume", True) else "--no-save-position-on-quit",
        "--sub-auto=fuzzy", f"--sid={'no' if cfg.get('subtitles') == 'off' else 'auto'}",
        "--hwdec=auto-safe", "--cursor-autohide=1000",
        f"--script-opts=crossbar-controls={os.path.join(util.CONFIG_DIR, 'controls.json')},"
        f"crossbar-gamepad={'yes' if mpv_gamepad else 'no'}",
        f"--input-gamepad={'yes' if mpv_gamepad else 'no'}",
        f"--playlist={m3u}", f"--playlist-start={int(index)}",
    ] + ([f"--user-agent={user_agent}", "--force-seekable=yes", "--cache=yes", "--demuxer-max-bytes=200MiB",
          "--network-timeout=30", "--stream-lavf-o=reconnect=1,reconnect_streamed=1,reconnect_delay_max=5"]
         if user_agent else [])
    VIDEO.start(args)
    threading.Thread(target=_focus_player, daemon=True).start()


def _focus_player():
    """Make sure the player window — not the XMB — gets the keyboard and controller."""
    from . import system
    for _ in range(40):
        time.sleep(0.15)
        f = system.focused()
        if f is None:
            return
        if f["app"] == VIDEO_APP_ID:
            return
        if any(w["app"] == VIDEO_APP_ID for w in system.windows()):
            system._swaymsg(f"[app_id={VIDEO_APP_ID}] focus")
            return


def video_state():
    if not VIDEO.running():
        return None
    return {"title": VIDEO.get("media-title", ""), "paused": bool(VIDEO.get("pause", False)),
            "position": VIDEO.get("time-pos", 0) or 0, "duration": VIDEO.get("duration", 0) or 0}


def video_input(action):
    """Forward a controller action to the on-screen control panel."""
    VIDEO.cmd("script-message", "crossbar-input", action)


def pause_video():
    if VIDEO.running():
        VIDEO.cmd("set_property", "pause", True)
