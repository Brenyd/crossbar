#!/usr/bin/env python3
"""crossbard — backend for the Crossbar XMB shell.

Serves the web UI and a small JSON API on 127.0.0.1. Standard library only
(plus optional python-evdev for the Home button).

    python3 server.py [--port 7777] [--demo]
"""
import argparse
import json
import mimetypes
import queue
import os
import subprocess
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

from crossbar import controls, display, media, party, player, quick, system, terminal, util  # noqa: E402
from crossbar.events import HUB  # noqa: E402
from crossbar.gamepad import Gamepads, mpv_should_read_gamepad  # noqa: E402
from crossbar.jobs import JobManager  # noqa: E402
from crossbar.providers.demo import Demo  # noqa: E402
from crossbar.providers.epic import Epic  # noqa: E402
from crossbar.providers.gog import GOG  # noqa: E402
from crossbar.providers.steam import Steam  # noqa: E402
from crossbar.spotify import SPOTIFY  # noqa: E402
from crossbar.discord import DISCORD, launch as launch_discord  # noqa: E402

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
try:
    VERSION = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")).read().strip()
except OSError:
    VERSION = "dev"
REAL = {p.id: p for p in (Steam(), GOG(), Epic())}
DEMO = {pid: Demo(pid) for pid in REAL}
JOBS = JobManager()
PADS = Gamepads(on_home=quick.home_pressed)
quick.OVERLAY["hook"] = PADS.set_overlay
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
        "term_token": terminal.TOKEN,
        "clock24": cfg.get("clock24", False),
        "gamescope": cfg.get("gamescope", False),
        "gamescope_available": bool(util.which("gamescope")),
        "controls": controls.load(),
        "pads": PADS.status(),
    }


# ---- routes ------------------------------------------------------------
def discord_state():
    st = DISCORD.status()
    saved = util.load_config()["discord"].get("channels", [])
    out = []
    for c in saved:
        item = dict(c)
        if st.get("connected"):
            try:
                item["members"] = DISCORD.channel(c["id"])["members"]
            except Exception:
                item["members"] = None
        out.append(item)
    st["saved"] = out
    return st


def r_discord(action, b):
    if action == "config":
        util.update_config(lambda c: c["discord"].update(client_id=b.get("client_id", "").strip(),
                                                          client_secret=b.get("client_secret", "").strip()))
        return discord_state()
    if action == "link":
        return JOBS.start("login", "Discord", DISCORD.link, "discord").as_dict()
    if action == "unlink":
        DISCORD.unlink()
        return discord_state()
    if action == "join":
        try:
            return {"channel": DISCORD.join(b["channel_id"], force=bool(b.get("force")))}
        except RuntimeError as e:
            if str(e) == "ALREADY_IN_VOICE":
                return {"already": True}
            raise
    if action == "leave":
        DISCORD.leave()
        return {"ok": True}
    if action == "mute":
        return DISCORD.set_voice(mute=not DISCORD.state["mute"])
    if action == "deaf":
        return DISCORD.set_voice(deaf=not DISCORD.state["deaf"])
    if action == "save":
        ch = {"id": str(b["id"]), "name": b["name"], "guild": b.get("guild", ""), "guild_id": b.get("guild_id", "")}
        util.update_config(lambda c: c["discord"]["channels"].append(ch)
                           if all(x["id"] != ch["id"] for x in c["discord"]["channels"]) else None)
        return discord_state()
    if action == "remove":
        util.update_config(lambda c: c["discord"].__setitem__(
            "channels", [x for x in c["discord"]["channels"] if x["id"] != str(b["id"])]))
        return discord_state()
    if action == "open":
        launch_discord(minimized=False)
        return {"ok": True}
    raise KeyError(action)


def diagnostics():
    """What crossbard sees — for Settings › Controller Diagnostics and crossbar-doctor."""
    import grp
    f = system.focused()
    groups = sorted({grp.getgrgid(g).gr_name for g in os.getgroups() if _safe_gr(g)})
    return {
        "pads": PADS.status(),
        "recent_input": PADS.recent(),
        "sway": f is not None,
        "focused": f,
        "xmb_window": bool(system.ensure_xmb_mark()),
        "user_groups": groups,
        "uinput": os.access("/dev/uinput", os.W_OK),
        "grim": bool(util.which("grim")),
        "mpv": bool(util.which("mpv")),
        "event_stream_listeners": HUB.listeners(),
        "version": VERSION,
        "overlay_window": quick.overlay_available(),
        "inputd": os.path.exists("/run/crossbar/input.sock"),
    }


def _safe_gr(g):
    import grp
    try:
        grp.getgrgid(g)
        return True
    except KeyError:
        return False


def r_install(b):
    p = provider(b["provider"])
    return JOBS.start("install", b.get("title", b["id"]), lambda j: p.install(j, b["id"]), p.id, b["id"]).as_dict()


def r_uninstall(b):
    p = provider(b["provider"])
    return JOBS.start("uninstall", b.get("title", b["id"]), lambda j: p.uninstall(j, b["id"]), p.id, b["id"]).as_dict()


def r_launch(b):
    p = provider(b["provider"])
    before = {w["con_id"] for w in system.windows()}
    if b["provider"] in ("gog", "epic") and util.load_config().get("gamescope") and util.which("gamescope"):
        os.environ["CROSSBAR_WRAP"] = "gamescope"
    try:
        p.launch(b["id"])
    finally:
        os.environ.pop("CROSSBAR_WRAP", None)
    if not demo_on() and os.environ.get("SWAYSOCK"):
        title = b.get("title", "")
        HUB.publish({"type": "launching", "title": title})

        def watch():
            # The game's window appears -> sway focuses it; tell the XMB to drop the splash.
            for _ in range(180):
                time.sleep(0.5)
                new = [w for w in system.windows() if w["con_id"] not in before and not system.is_background_window(w)]
                if new:
                    system.focus_window(new[-1]["con_id"])
                    HUB.publish({"type": "launched", "title": title})
                    return
            HUB.publish({"type": "launch-timeout", "title": title})
        threading.Thread(target=watch, daemon=True).start()
    util.update_config(lambda c: c["last_played"].__setitem__(f"{p.id}:{b['id']}", time.time()))
    return {"ok": True, "demo": demo_on()}


def r_login(pid, b):
    p = provider(pid)

    return JOBS.start("login", p.name, lambda job: p.login(job, b), p.id).as_dict()


def r_settings(b):
    allowed = {"demo", "user", "theme", "sounds", "clock24", "gamescope"}

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
    "/api/quick": lambda q: quick.info(),
    "/api/bluetooth": lambda q: system.bluetooth_status(),
    "/api/time": lambda q: system.time_status(),
    "/api/timezones": lambda q: system.timezones(),
    "/api/wifi/radio": lambda q: {"on": system.wifi_radio()},
    "/api/discord/state": lambda q: discord_state(),
    "/api/discord/guilds": lambda q: DISCORD.guilds(),
    "/api/discord/channels": lambda q: DISCORD.voice_channels(q["guild_id"]),
    "/api/quick/pending": lambda q: {"open": quick.take_pending()},
    "/api/quick/overlay-state": lambda q: {"open": quick.OVERLAY["open"]},
    "/api/diagnostics": lambda q: diagnostics(),
    "/api/controls": lambda q: {**controls.describe(), "pads": PADS.status()},
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
    if action == "restart":
        SPOTIFY.restart_speaker()
        return {"ok": True}
    if action == "control":
        SPOTIFY.control(b["action"])
        return {"ok": True}
    raise KeyError(action)


def r_tv(action, b):
    if action == "open":
        svc = util.load_config()["tv"][int(b["index"])]
        player.pause_music()
        system.open_web(svc["url"], "tv-" + util.slug(svc["name"]), tv_ui=svc.get("tv_ui", False))
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
    if head == "overlay":
        if parts[1] == "close":
            quick.close_overlay(resume=b.get("resume", True))
        elif parts[1] == "home":
            quick.overlay_go_home()
        elif parts[1] == "close-app":
            return {"ok": quick.overlay_close_app()}
        elif parts[1] == "settings":
            quick.overlay_open_settings(b.get("folder", ""))
        return {"ok": True}
    if head == "quick":
        if parts[1] == "resume":
            return {"ok": quick.resume()}
        if parts[1] == "close":
            return {"ok": quick.close()}
        if parts[1] == "output":
            return {"name": quick.next_output()}
        raise KeyError(path)
    if head == "controls":
        if len(parts) > 1 and parts[1] == "capture":
            return {"token": PADS.capture(float(b.get("timeout", 10)), bool(b.get("combo")))}
        if len(parts) > 1 and parts[1] == "browser-pads":
            PADS.browser_pads = [str(x)[:120] for x in b.get("pads", [])][:8]
            return {"ok": True}
        if len(parts) > 1 and parts[1] == "guide":
            controls.set_guide_home(bool(b.get("on")))
            PADS.reload()
            return {**controls.describe(), "pads": PADS.status()}
        if len(parts) > 1 and parts[1] == "cancel":
            PADS.cancel_capture()
            return {"ok": True}
        if b.get("swap"):
            controls.swap_ok_back()
        elif "reset" in b:
            controls.reset(None if b["reset"] == "all" else b["reset"], b.get("action"))
        else:
            controls.set_binding(b["kind"], b["action"], b["tokens"])
        PADS.reload()
        system.bind_home_keys(controls.load()["keyboard"]["home"])
        return {**controls.describe(), "pads": PADS.status()}
    if head == "debug" and os.environ.get("CROSSBAR_DEBUG"):
        PADS._press(b["action"], "DEBUG")   # simulate a controller press (routed like a real one)
        return {"ok": True}
    if head == "home":
        quick.home_pressed()
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
        player.play_video(b["paths"], b.get("index", 0), mpv_gamepad=mpv_should_read_gamepad(PADS))
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
    if head == "bluetooth":
        if parts[1] == "power":
            system.bluetooth_power(bool(b.get("on")))
            return system.bluetooth_status()
        if parts[1] == "scan":
            return JOBS.start("scan", "Bluetooth", lambda j: system.bluetooth_scan(10)).as_dict()
        if parts[1] == "pair":
            return JOBS.start("pair", b.get("name") or b["mac"], lambda j: system.bluetooth_pair(b["mac"])).as_dict()
        system.bluetooth_do(parts[1], b["mac"])       # connect / disconnect / remove
        return system.bluetooth_status()
    if head == "time":
        if parts[1] == "zone":
            system.set_timezone(b["zone"])
        elif parts[1] == "ntp":
            system.set_ntp(bool(b.get("on")))
        return system.time_status()
    if head == "wifi-extra":
        if parts[1] == "disconnect":
            system.wifi_disconnect()
        elif parts[1] == "forget":
            system.wifi_forget(b["ssid"])
        elif parts[1] == "radio":
            system.wifi_radio(bool(b.get("on")))
        return system.network_status()
    if head == "term":
        terminal.check(b.get("token"))
        if parts[1] == "open":
            s_ = terminal.open_session(b.get("cmd"), b.get("cols", 120), b.get("rows", 34))
            return {"id": s_.id}
        if parts[1] == "input":
            terminal.get(b["id"]).write(b["data"])
            return {"ok": True}
        if parts[1] == "resize":
            terminal.get(b["id"]).resize(b["cols"], b["rows"])
            return {"ok": True}
        if parts[1] == "replay":
            import base64 as _b64
            return {"data": _b64.b64encode(bytes(terminal.get(b["id"]).buffer)).decode()}
        if parts[1] == "close":
            terminal.close(b["id"])
            return {"ok": True}
        raise KeyError(path)
    if head == "show-terminal":           # Ctrl+Alt+T from anywhere (sway binding)
        system.show_shell()
        HUB.publish({"type": "open-terminal", "cmd": b.get("cmd")})
        return {"ok": True}
    if head == "discord":
        return r_discord(parts[1], b)
    if head == "spotify":
        return r_spotify(parts[1], b)
    if head == "tv":
        return r_tv(parts[1], b)
    if head == "browser":
        system.open_web(b.get("url") or "https://duckduckgo.com", "browser", app=False)
        return {"ok": True}
    if head == "report":
        if not util.which("crossbar-doctor"):
            raise RuntimeError("crossbar-doctor isn't installed (it comes with the Crossbar ISO)")
        r = subprocess.run(["crossbar-doctor", "--share"], capture_output=True, text=True, timeout=90)
        url = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        if not url.startswith("https://"):
            raise RuntimeError("Couldn't upload the report — is the internet connected?")
        return {"url": url}
    if head == "update":
        # a fresh private folder each time (a leftover root-owned /tmp/crossbar-main broke updates)
        return {"cmd": 'd=$(mktemp -d) && cd "$d" && '
                       "curl -fL https://github.com/Brenyd/crossbar/archive/refs/heads/main.tar.gz | tar xz && "
                       "cd crossbar-main && sudo ./update-system.sh"}
    if head == "installer":
        return system.open_installer()
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

    def _events(self, role=""):
        """Server-sent events stream for the XMB page (controller input, quick menu)."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        q = HUB.subscribe(role)
        try:
            while True:
                try:
                    ev = q.get(timeout=15)
                    self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            HUB.unsubscribe(q)

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
        if path == "/api/events":
            return self._events(q.get("role", ""))
        if path == "/api/overlay.jpg":
            if not os.path.exists(quick.SHOT):
                return self._send(404, b"none", "text/plain")
            return self._send_file(quick.SHOT, "image/jpeg")
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
    PADS.start()

    def keep_xmb_marked():
        while True:
            system.ensure_xmb_mark()
            time.sleep(5)
    threading.Thread(target=keep_xmb_marked, daemon=True).start()
    system.bind_home_keys(controls.load()["keyboard"]["home"])
    def background_start():
        display.apply_saved()
        SPOTIFY.ensure_receiver()
        if DISCORD.linked() and not DISCORD.running():
            try:
                launch_discord(minimized=True)     # voice runs in Discord; keep it ready, hidden
            except Exception as e:
                print(f"discord: {e}", flush=True)
    threading.Thread(target=background_start, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"crossbard listening on http://127.0.0.1:{a.port} (demo={demo_on()})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
