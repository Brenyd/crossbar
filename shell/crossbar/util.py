"""Shared helpers: config, paths, HTTP, VDF parsing, process launching."""
import json
import os
import re
import shutil
import subprocess
import threading
import urllib.parse
import urllib.request

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config")), "crossbar")
GAMES_DIR = os.environ.get("CROSSBAR_GAMES", os.path.join(HOME, "Games"))
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "demo": True,              # demo library until a real account is linked
    "user": "Player",
    "theme": "auto",           # "auto" = colour follows the month, like the original
    "sounds": True,
    "steam": {"api_key": "", "steamid": ""},
    "party": {"service": "discord", "channels": []},
    "last_played": {},
    "media": {"music": "~/Music", "video": "~/Videos", "photo": "~/Pictures"},
    "video": {"resume": True, "subtitles": "auto"},
    "display": {},             # {"OUTPUT-NAME": {"mode": "1920x1080@60.000Hz", "scale": 1.0}}
    "spotify": {"client_id": ""},
    "discord": {"channels": [], "signed_in": False},
    "tv": [
        {"name": "YouTube", "url": "https://www.youtube.com/tv", "tv_ui": True},
        {"name": "Twitch", "url": "https://www.twitch.tv"},
        {"name": "Plex", "url": "https://app.plex.tv"},
    ],
}

_lock = threading.RLock()


def _merge(base, extra):
    out = dict(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config():
    with _lock:
        try:
            with open(CONFIG_PATH) as f:
                return _merge(DEFAULT_CONFIG, json.load(f))
        except (OSError, ValueError):
            return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg):
    with _lock:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cfg, f, indent=2)
        os.chmod(tmp, 0o600)  # holds API keys
        os.replace(tmp, CONFIG_PATH)


def update_config(fn):
    with _lock:
        cfg = load_config()
        fn(cfg)
        save_config(cfg)
        return cfg


def http_json(url, headers=None, data=None, timeout=20):
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={"User-Agent": "Crossbar/0.1", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def download(url, dest, progress, headers=None, chunk=1 << 20):
    """Stream url to dest, calling progress(fraction)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Crossbar/0.1", **(headers or {})})
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with urllib.request.urlopen(req, timeout=60) as r, open(dest + ".part", "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            buf = r.read(chunk)
            if not buf:
                break
            f.write(buf)
            done += len(buf)
            if total:
                progress(done / total)
    os.replace(dest + ".part", dest)


def parse_vdf(text):
    """Minimal parser for Valve's text KeyValues format (.vdf / .acf)."""
    root, stack, key = {}, None, None
    stack = [root]
    for s, brace in re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text):
        if brace == "{":
            d = {}
            stack[-1][key or ""] = d
            stack.append(d)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
        elif key is None:
            key = s
        else:
            stack[-1][key] = s.replace("\\\\", "\\")
            key = None
    return root


def which(cmd):
    return shutil.which(cmd)


def spawn(argv, cwd=None, env=None):
    """Start a detached process (games, voice apps) that outlives requests.
    If CROSSBAR_WRAP=gamescope is set by the launcher, run it inside gamescope."""
    if os.environ.get("CROSSBAR_WRAP") == "gamescope" and shutil.which("gamescope"):
        argv = ["gamescope", "-f", "--", *argv]
    return subprocess.Popen(
        argv, cwd=cwd, env={**os.environ, **(env or {})},
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


GAME_LOG = os.path.join(os.path.expanduser("~/.cache"), "crossbar-games.log")


def spawn_checked(argv, cwd=None, env=None, what="The game", wait=5):
    """Start a game like spawn(), but keep its output in ~/.cache/crossbar-games.log and, if it
    quits with an error within a few seconds, raise that error instead of failing silently."""
    import time
    os.makedirs(os.path.dirname(GAME_LOG), exist_ok=True)
    log = open(GAME_LOG, "a")
    log.write(f"\n==== {time.strftime('%F %T')} {what}: {' '.join(argv)}\n")
    log.flush()
    start = log.tell()
    if os.environ.get("CROSSBAR_WRAP") == "gamescope" and shutil.which("gamescope"):
        argv = ["gamescope", "-f", "--", *argv]
    from . import perf
    env = {**perf.env(), **(env or {}), "CROSSBAR_GAME": "1"}   # frame-rate overlay; marks its windows as a game
    p = subprocess.Popen(argv, cwd=cwd, env={**os.environ, **env}, stdin=subprocess.DEVNULL,
                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    log.close()
    end = time.time() + wait
    while time.time() < end:
        if p.poll() is not None:
            break
        time.sleep(0.2)
    if p.returncode not in (None, 0):
        try:
            with open(GAME_LOG, errors="replace") as f:
                f.seek(start)
                tail = [ln.strip() for ln in f.read().splitlines() if ln.strip()][-3:]
        except OSError:
            tail = []
        msg = " / ".join(tail)[-220:] or f"it exited with code {p.returncode}"
        raise RuntimeError(f"{what} stopped right away: {msg}")
    return p


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "game"
