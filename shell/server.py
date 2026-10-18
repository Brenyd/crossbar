#!/usr/bin/env python3
"""crossbard — backend for the Crossbar XMB shell.

Serves the web UI and a small JSON API on 127.0.0.1. Standard library only
(plus optional python-evdev for the Home button).

    python3 server.py [--port 7777] [--demo]
"""
import argparse
import json
import mimetypes
import os
import sys
import threading
import time
import traceback
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
vendor = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
if os.path.isdir(vendor):
    sys.path.insert(0, vendor)

from crossbar import display, media, party, player, system, util  # noqa: E402
from crossbar.jobs import JobManager  # noqa: E402
from crossbar.providers.demo import Demo  # noqa: E402
from crossbar.providers.epic import Epic  # noqa: E402
from crossbar.providers.gog import GOG  # noqa: E402
from crossbar.providers.steam import Steam  # noqa: E402
from crossbar.spotify import SPOTIFY  # noqa: E402

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
REAL = {p.id: p for p in (Steam(), GOG(), Epic())}
DEMO = {pid: Demo(pid) for pid in REAL}
JOBS = JobManager()
FORCE_DEMO = False


def demo_on():
    return FORCE_DEMO or util.load_config().get("demo", True)


def providers():
    return DEMO if demo_on() else REAL


def provider(pid):
    p = providers().get(pid)
    if not p:
        raise KeyError(f"unknown store {pid}")
    return p


def safe(fn, default):
    try:
        return fn()
    except Exception as e:
        traceback.print_exc()
        return default(e) if callable(default) else default


def installed_games():
    cfg = util.load_config()
    played = cfg.get("last_played", {})
    with ThreadPoolExecutor(3) as ex:
        results = list(ex.map(lambda p: safe(p.installed, []), providers().values()))
    games = [g for r in results for g in r]
    for g in games:
        g["last_played"] = played.get(f"{g['provider']}:{g['id']}", 0)
    # most recently played first, like the original
    return sorted(games, key=lambda g: (-g["last_played"], g["title"].lower()))


def state():
    cfg = util.load_config()
    return {
        "demo": demo_on(),
        "user": cfg["user"],
        "theme": cfg["theme"],
        "sounds": cfg["sounds"],
        "providers": [{"id": p.id, "name": p.name, "login_fields": p.login_fields,
                       **safe(p.status, lambda e: {"linked": False, "account": "", "ready": False, "note": str(e)})}
                      for p in providers().values()],
        "party": {**cfg["party"], "services": party.services()},
        "jobs": JOBS.list(),
        "windows": system.windows(),
        "live": system.is_live(),
        "media": cfg["media"],
        "video": cfg["video"],
        "tv": cfg["tv"],
        "spotify": SPOTIFY.status(),
    }


# ---- routes ------------------------------------------------------------
def r_install(b):
    p = provider(b["provider"])
    return JOBS.start("install", b.get("title", b["id"]), lambda j: p.install(j, b["id"]), p.id, b["id"]).as_dict()


def r_uninstall(b):
    p = provider(b["provider"])
    return JOBS.start("uninstall", b.get("title", b["id"]), lambda j: p.uninstall(j, b["id"]), p.id, b["id"]).as_dict()


def r_launch(b):
    p = provider(b["provider"])
    p.launch(b["id"])
    util.update_config(lambda c: c["last_played"].__setitem__(f"{p.id}:{b['id']}", time.time()))
    return {"ok": True, "demo": demo_on()}


def r_login(pid, b):
    p = provider(pid)

    return JOBS.start("login", p.name, lambda job: p.login(job, b), p.id).as_dict()


def r_settings(b):
    allowed = {"demo", "user", "theme", "sounds"}

    def apply(c):
        for k, v in b.items():
            if k in allowed:
                c[k] = v
            elif k == "video" and isinstance(v, dict):
                c["video"].update({kk: vv for kk, vv in v.items() if kk in ("resume", "subtitles")})
    util.update_config(apply)
    return state()


def r_party(action, b):
    if action == "service":
        if b["service"] not in party.SERVICES:
            raise KeyError("unknown service")
        util.update_config(lambda c: c["party"].__setitem__("service", b["service"]))
    elif action == "start":
        sid = b.get("service") or util.load_config()["party"]["service"]
        return {"ok": True, "name": party.start(sid, b.get("url"))}
    elif action == "add":
        ch = {"name": b["name"].strip() or "Channel", "url": party.normalise_channel(b["url"])}
        util.update_config(lambda c: c["party"]["channels"].append(ch))
    elif action == "remove":
        util.update_config(lambda c: c["party"]["channels"].pop(int(b["index"])))
    return state()


def r_search(q):
    q = q.lower().strip()
    out = []
    for p in providers().values():
        if safe(lambda: p.status()["linked"], False):
            out += [g for g in safe(p.library, []) if q in g["title"].lower()]
    return sorted(out, key=lambda g: g["title"].lower())


GET = {
    "/api/state": lambda q: state(),
    "/api/installed": lambda q: installed_games(),
    "/api/jobs": lambda q: JOBS.list(),
    "/api/audio": lambda q: system.audio(),
    "/api/sysinfo": lambda q: system.sysinfo(),
    "/api/search": lambda q: r_search(q.get("q", "")),
    "/api/library": lambda q: provider(q.get("provider", "")).library(),
    "/api/media/list": lambda q: media.listdir(q["kind"], q.get("path") or None),
    "/api/media/scan": lambda q: media.scan(q["kind"]),
    "/api/fs": lambda q: media.browse_dirs(q.get("path") or None),
    "/api/music/state": lambda q: player.music_state(),
    "/api/video/state": lambda q: player.video_state(),
    "/api/display": lambda q: display.outputs(),
    "/api/audio/devices": lambda q: system.audio_devices(),
    "/api/network": lambda q: system.network_status(),
    "/api/wifi": lambda q: system.wifi_networks(),
    "/api/spotify/now": lambda q: SPOTIFY.now(),
    "/api/spotify/playlists": lambda q: SPOTIFY.playlists(),
    "/api/spotify/liked": lambda q: SPOTIFY.liked(),
    "/api/spotify/playlist": lambda q: SPOTIFY.playlist_items(q["id"]),
    "/api/spotify/search": lambda q: SPOTIFY.search(q.get("q", "")),
}


def r_music_play(b):
    pause_spotify()
    player.play_music(b["paths"], b.get("index", 0))
    return {"ok": True}


def pause_spotify():
    try:
        if SPOTIFY.status()["linked"]:
            SPOTIFY.control("pause")
    except Exception:
        pass


def r_spotify(action, b):
    if action == "config":
        util.update_config(lambda c: c["spotify"].__setitem__("client_id", b.get("client_id", "").strip()))
        return state()
    if action == "login":
        return JOBS.start("login", "Spotify", SPOTIFY.login, "spotify").as_dict()
    if action == "logout":
        SPOTIFY.logout()
        return state()
    if action == "play":
        player.pause_music()
        SPOTIFY.play(b.get("context_uri"), b.get("uris"), b.get("offset"), b.get("shuffle", False))
        return {"ok": True}
    if action == "transfer":
        player.pause_music()
        SPOTIFY.transfer()
        return {"ok": True}
    if action == "control":
        SPOTIFY.control(b["action"])
        return {"ok": True}
    raise KeyError(action)


def r_tv(action, b):
    if action == "open":
        svc = util.load_config()["tv"][int(b["index"])]
        player.pause_music()
        system.open_web(svc["url"], "tv", tv_ui=svc.get("tv_ui", False))
    elif action == "add":
        url = b["url"].strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        util.update_config(lambda c: c["tv"].append({"name": b.get("name", "").strip() or url, "url": url}))
    elif action == "remove":
        util.update_config(lambda c: c["tv"].pop(int(b["index"])))
    return state()


def route_post(path, b):
    parts = path.strip("/").split("/")[1:]  # drop "api"
    head = parts[0] if parts else ""
    if head == "install":
        return r_install(b)
    if head == "uninstall":
        return r_uninstall(b)
    if head == "launch":
        return r_launch(b)
    if head == "login":
        return r_login(parts[1], b)
    if head == "logout":
        provider(parts[1]).logout()
        return state()
    if head == "settings":
        return r_settings(b)
    if head == "party":
        return r_party(parts[1], b)
    if head == "audio":
        system.set_audio(b["target"], b.get("delta"), b.get("mute"))
        return system.audio()
    if head == "window":
        {"focus": system.focus_window, "close": system.close_window}[parts[1]](b["con_id"])
        return {"ok": True}
    if head == "home":
        system.focus_shell()
        return {"ok": True}
    if head == "media" and parts[1] == "folder":
        if b["kind"] not in media.KINDS or not media.allowed(b["path"]):
            raise KeyError("folder")
        util.update_config(lambda c: c["media"].__setitem__(b["kind"], b["path"]))
        return state()
    if head == "music":
        if parts[1] == "play":
            return r_music_play(b)
        player.music_control(b["action"], b.get("value"))
        return player.music_state()
    if head == "video" and parts[1] == "play":
        pause_spotify()
        player.play_video(b["paths"], b.get("index", 0))
        return {"ok": True}
    if head == "display":
        if parts[1] == "mode":
            display.set_mode(b["name"], b["width"], b["height"], b["refresh"], b.get("save", True))
        else:
            display.set_scale(b["name"], b["scale"], b.get("save", True))
        return display.outputs()
    if head == "audio-device":
        system.set_audio_device(b["id"])
        return system.audio_devices()
    if head == "wifi":
        return JOBS.start("wifi", b["ssid"], lambda j: system.wifi_connect(b["ssid"], b.get("password", ""))).as_dict()
    if head == "spotify":
        return r_spotify(parts[1], b)
    if head == "tv":
        return r_tv(parts[1], b)
    if head == "browser":
        system.open_web(b.get("url") or "https://duckduckgo.com", "browser", app=False)
        return {"ok": True}
    if head == "installer":
        system.open_installer()
        return {"ok": True}
    if head == "power":
        system.power(parts[1])
        return {"ok": True}
    raise KeyError(path)


class Handler(BaseHTTPRequestHandler):
    server_version = "crossbard/0.1"

    def log_message(self, fmt, *args):
        if os.environ.get("CROSSBAR_DEBUG"):
            super().log_message(fmt, *args)

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path, ctype, cache=False):
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _guard(self):
        # Only the local shell may talk to us (blocks DNS-rebinding style requests).
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def do_GET(self):
        if not self._guard():
            return self._send(403, {"error": "forbidden"})
        path, _, qs = self.path.partition("?")
        q = dict(p.split("=", 1) if "=" in p else (p, "") for p in qs.split("&") if p)
        q = {k: urllib.parse.unquote_plus(v) for k, v in q.items()}
        if path == "/spotify/callback":
            try:
                if "error" in q:
                    raise RuntimeError(q["error"])
                SPOTIFY.callback(q.get("code", ""), q.get("state", ""))
                msg = "Spotify is connected. You can close this window."
            except Exception as e:
                msg = f"Spotify sign-in failed: {e}"
            page = (f"<!doctype html><title>Spotify</title><body style='background:#000;color:#fff;font:28px sans-serif;"
                    f"display:grid;place-items:center;height:100vh;margin:0'>{msg}</body>")
            return self._send(200, page.encode(), "text/html; charset=utf-8")
        if path in ("/api/thumb", "/api/file"):
            p = q.get("path", "")
            if path == "/api/thumb":
                p = media.thumbnail(p, int(q.get("size", 480)))
                if not p:
                    return self._send(404, b"no thumbnail", "text/plain")
                return self._send_file(p, "image/jpeg", cache=True)
            ext = os.path.splitext(p)[1].lower()
            if not media.allowed(p) or ext not in media.PHOTO or not os.path.isfile(p):
                return self._send(404, b"not found", "text/plain")
            return self._send_file(p, mimetypes.guess_type(p)[0] or "application/octet-stream", cache=True)
        if path.startswith("/api/"):
            fn = GET.get(path)
            if not fn:
                return self._send(404, {"error": "not found"})
            try:
                return self._send(200, fn(q))
            except Exception as e:
                traceback.print_exc()
                return self._send(500, {"error": str(e)})
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        full = os.path.realpath(os.path.join(WEB, rel))
        if not full.startswith(os.path.realpath(WEB)) or not os.path.isfile(full):
            return self._send(404, b"not found", "text/plain")
        with open(full, "rb") as f:
            self._send(200, f.read(), mimetypes.guess_type(full)[0] or "application/octet-stream")

    def do_POST(self):
        if not self._guard() or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self._send(403, {"error": "forbidden"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            return self._send(200, route_post(self.path.split("?")[0], body))
        except KeyError as e:
            return self._send(404, {"error": f"not found: {e}"})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": str(e)})


def main():
    global FORCE_DEMO
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--demo", action="store_true", help="force the demo library")
    a = ap.parse_args()
    FORCE_DEMO = a.demo
    os.makedirs(util.GAMES_DIR, exist_ok=True)
    system.start_gamepad_daemon()
    threading.Thread(target=lambda: (display.apply_saved(), SPOTIFY.ensure_receiver()), daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"crossbard listening on http://127.0.0.1:{a.port} (demo={demo_on()})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
