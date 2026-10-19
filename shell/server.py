#!/usr/bin/env python3
"""crossbard — backend for the Crossbar XMB shell.

Serves the web UI and a small JSON API on 127.0.0.1. Standard library only
(plus optional python-evdev for the Home button).

    python3 server.py [--port 7777] [--demo]
"""
import argparse
import inspect
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

from crossbar import apps, artwork, extgames, folders, themes, compat, friends, controls, emulation, files, perf, trophies, glyphs, iptv, ps5hw, nas, session, display, media, party, player, quick, system, terminal, util  # noqa: E402
from crossbar.events import HUB  # noqa: E402
from crossbar.gamepad import Gamepads, mpv_should_read_gamepad  # noqa: E402
from crossbar.jobs import JobManager  # noqa: E402
from crossbar.providers.demo import Demo  # noqa: E402
from crossbar.providers.epic import Epic  # noqa: E402
from crossbar.providers.gog import GOG  # noqa: E402
from crossbar.providers.steam import Steam  # noqa: E402
from crossbar.spotify import SPOTIFY  # noqa: E402
from crossbar.discordweb import DISCORD  # noqa: E402
from crossbar.browser import BROWSER  # noqa: E402

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
try:
    VERSION = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")).read().strip()
except OSError:
    VERSION = "dev"
REAL = {p.id: p for p in (Steam(), GOG(), Epic())}
DEMO = {pid: Demo(pid) for pid in REAL}
JOBS = JobManager()
PADS = Gamepads(on_home=quick.home_pressed)
glyphs.PAD_NAMES = lambda: PADS.status().get("devices") or []
quick.OVERLAY["hook"] = PADS.set_overlay


# ---- the browser: controller presses run in order on one worker (DevTools calls take a moment)
_browser_q = __import__("queue").Queue(maxsize=40)


def _browser_worker():
    while True:
        action, repeat = _browser_q.get()
        if action == "menu":                       # Y: the Browser page of the Quick Menu
            quick.open_overlay(page="browser")
            continue
        BROWSER.act(action, repeat)


def _browser_input(action, repeat):
    if repeat and _browser_q.qsize() > 3:
        return                                     # don't let held-stick moves pile up
    try:
        _browser_q.put_nowait((action, repeat))
    except Exception:
        pass


def _browser_keyboard():
    PADS.set_osk(True)
    HUB.publish({"type": "osk", "open": True})


PADS.browser_pid = lambda: BROWSER.proc.pid if BROWSER.running() else None
PADS.on_browser = _browser_input
BROWSER.on_keyboard = _browser_keyboard
threading.Thread(target=_browser_worker, daemon=True).start()
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
    games = artwork.apply([g for r in results for g in r])
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
        "theme_pack": themes.current_id(),
        "sounds": cfg["sounds"],
        "providers": [{"id": p.id, "name": p.name, "login_fields": p.login_fields,
                       **safe(p.status, lambda e: {"linked": False, "account": "", "ready": False, "note": str(e)})}
                      for p in providers().values()],
        "party": {**cfg["party"], "services": party.services()},
        "perf": perf.status(),
        "jobs": JOBS.list(),
        "windows": system.windows(),
        "live": system.is_live(),
        "media": cfg["media"],
        "video": cfg["video"],
        "tv": cfg["tv"],
        "spotify": SPOTIFY.status(),
        "term_token": terminal.TOKEN,
        "home": util.HOME,
        "iptv": iptv.status(),
        "clock24": cfg.get("clock24", False),
        "gamescope": cfg.get("gamescope", False),
        "steam_bigpicture": cfg.get("steam_bigpicture", True),
        "free_memory_in_games": cfg.get("free_memory_in_games", True),
        "glyphs": glyphs.current(),
        "desktop_available": session.desktop_available(),
        "ps5hw": ps5hw.available(),
        "boot_mode": session.boot_mode(),
        "gamescope_available": bool(util.which("gamescope")),
        "controls": controls.load(),
        "pads": PADS.status(),
    }


# ---- routes ------------------------------------------------------------
def discord_state():
    st = DISCORD.status()
    st["saved"] = util.load_config()["discord"].get("channels", [])
    return st


def r_discord(action, b):
    """Discord through its own web client (see crossbar/discordweb.py)."""
    if action == "open":            # show the Discord window (sign-in, chat, settings)
        DISCORD.start(show=True)
        DISCORD.show()
        return {"ok": True}
    if action == "start":
        DISCORD.start()
        return {"ok": True}
    if action == "join":
        return DISCORD.join(b["guild_id"], b["channel_id"])
    if action == "leave":
        return DISCORD.leave()
    if action == "mute":
        return DISCORD.toggle_mute()
    if action == "deaf":
        return DISCORD.toggle_deaf()
    if action == "save":
        ch = {"id": str(b["id"]), "name": b["name"], "guild": b.get("guild", ""), "guild_id": str(b.get("guild_id", ""))}
        util.update_config(lambda c: c["discord"].setdefault("channels", []).append(ch)
                           if all(x["id"] != ch["id"] for x in c["discord"].get("channels", [])) else None)
        return discord_state()
    if action == "remove":
        util.update_config(lambda c: c["discord"].__setitem__(
            "channels", [x for x in c["discord"].get("channels", []) if x["id"] != str(b["id"])]))
        return discord_state()
    if action == "call":
        return DISCORD.call(b["id"])
    if action == "share":
        return DISCORD.share_screen(bool(b.get("on", True)))
    if action == "signout":
        DISCORD.sign_out_local()
        return discord_state()
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


BROWSE_EXT = {".zip": ".zip", ".appimage": ".appimage", "image": (".png", ".jpg", ".jpeg", ".webp", ".gif")}


def r_apps(what, b):
    """Apps category / Store › Install Apps (crossbar/apps.py)."""
    if what == "launch":
        return r_app_launch(b["key"], b.get("name") or "App")
    if what == "category":
        r = apps.set_category(b["key"], b["category"])
        HUB.publish({"type": "apps"})
        return r
    if what == "uninstall":
        return JOBS.start("uninstall", b.get("name") or b["key"], lambda j: (apps.uninstall(j, b["key"]), HUB.publish({"type": "apps"})),
                          "app", b["key"]).as_dict()
    if what == "install-flatpak":
        def run(j):
            apps.install_flatpak(j, b["id"], b.get("category") or "apps")
            HUB.publish({"type": "apps"})
        return JOBS.start("install", b.get("name") or b["id"], run, "flatpak", b["id"]).as_dict()
    if what == "install-appimage":
        if not media.allowed(b["path"]):
            raise PermissionError("Pick a file in your home folder or on a drive")
        r = apps.install_appimage(b["path"], b.get("category") or "apps")
        HUB.publish({"type": "apps"})
        return r
    raise KeyError(what)


def r_app_launch(key, name):
    """Start an app with the "Starting…" screen; once its window shows, bring it forward.
    (Not a game: no game mode, and it stays out of Game › Return to….)"""
    argv, env = apps.argv(key)
    live = bool(os.environ.get("SWAYSOCK"))

    def run():
        before = {w["con_id"] for w in system.windows()}
        if live:
            HUB.publish({"type": "launching", "title": name, "sub": "Starting…"})
        try:
            util.spawn_checked(argv, env=env, what=name, wait=3, game=False)
        except Exception as e:
            HUB.publish({"type": "launch-timeout", "title": name, "error": str(e)})
            return
        if not live:
            return
        end = time.time() + 90
        while time.time() < end:
            time.sleep(0.5)
            new = [w for w in system.windows() if w["con_id"] not in before]
            if new:
                system.focus_window(new[-1]["con_id"])
                HUB.publish({"type": "launched", "title": name})
                return
        HUB.publish({"type": "launch-timeout", "title": name})
    threading.Thread(target=run, daemon=True).start()
    util.update_config(lambda c: c["last_played"].__setitem__(f"app:{key}", time.time()))
    return {"ok": True}


def r_browser(what, b):
    """Crossbar's browser (crossbar/browser.py) and its Quick Menu page."""
    if what == "open":
        BROWSER.start([b["url"]] if b.get("url") else None)
        return {"ok": True}
    if what == "size":
        return BROWSER.set_size(b.get("value", "auto"))
    if what == "bookmark":
        return {"bookmarks": BROWSER.add_bookmark(b.get("name"), b.get("url"))}
    if what == "unbookmark":
        return {"bookmarks": BROWSER.remove_bookmark(b["url"])}
    if not BROWSER.running():
        raise RuntimeError("The browser isn't open")
    if what == "navigate":
        return {"url": BROWSER.navigate(b.get("text", ""))}
    if what == "search":
        threading.Thread(target=BROWSER.search, daemon=True).start()
    elif what == "history":
        BROWSER.history(int(b.get("delta", -1)))
    elif what == "reload":
        BROWSER.reload()
    elif what == "tab":
        BROWSER.switch(b["id"])
    elif what == "new-tab":
        BROWSER.open_tab(b.get("url") or "http://127.0.0.1:7777/browser.html")
    elif what == "close-tab":
        BROWSER.close_tab(b.get("id"))
    elif what == "pointer":
        BROWSER.set_pointer(bool(b.get("on")))
    elif what == "close":
        BROWSER.close()
    else:
        raise KeyError(what)
    return BROWSER.info()


def r_bigpicture():
    """Game › Steam Big Picture: Steam's own console UI, full screen. The Quick Menu's Go to
    Home (or closing Big Picture) comes back; Steam is tucked away when the menu is in front."""
    from crossbar.providers import steam as steam_mod
    if demo_on():
        return {"demo": True}
    if not util.which("steam"):
        raise RuntimeError("Steam isn't installed")

    def run():
        try:
            HUB.publish({"type": "launching", "title": "Steam Big Picture", "sub": "Starting…"})
            if not steam_mod.steam_running():
                steam_mod.start_steam(True)
                steam_mod.wait_ready(True, lambda m: HUB.publish({"type": "launching", "title": "Steam Big Picture", "sub": m}))
            else:
                system.hold_launch(30)
                util.spawn(["steam", "steam://open/bigpicture"])
            for _ in range(40):                 # bring it in front once its window is there
                vis = [w for w in system.all_windows() if system.is_steam_client(w)]
                if vis:
                    system.bring_to_front(vis[-1]["con_id"])
                    break
                time.sleep(0.5)
            HUB.publish({"type": "launched", "title": "Steam Big Picture"})
        except Exception as e:
            HUB.publish({"type": "launch-timeout", "title": "Steam Big Picture", "error": str(e)})
    threading.Thread(target=run, daemon=True).start()
    return {"ok": True}


def r_install(b):
    p = provider(b["provider"])
    return JOBS.start("install", b.get("title", b["id"]), lambda j: p.install(j, b["id"]), p.id, b["id"]).as_dict()


def r_uninstall(b):
    p = provider(b["provider"])
    return JOBS.start("uninstall", b.get("title", b["id"]), lambda j: p.uninstall(j, b["id"]), p.id, b["id"]).as_dict()


def r_launch(b):
    p = {"emu": emulation.EMU, "lutris": extgames.LUTRIS, "shortcut": extgames.SHORTCUT}.get(b["provider"]) or provider(b["provider"])
    before = {w["con_id"] for w in system.windows()}
    title = b.get("title", "")
    live = (b["provider"] in ("emu", "lutris", "shortcut") or not demo_on()) and os.environ.get("SWAYSOCK")

    def progress(msg):
        if live:
            HUB.publish({"type": "launching", "title": title, "sub": msg})

    def is_game(w):
        app = (w.get("app") or "").lower()
        return w["con_id"] not in before and not system.is_background_window(w) and "discord" not in app \
            and not (w.get("title") or "").lower().startswith("steam")     # updater, sign-in, dialogs

    def run():
        if live:
            HUB.publish({"type": "launching", "title": title, "sub": "Starting…"})
            system.hold_launch(300)
        if b["provider"] in ("gog", "epic") and util.load_config().get("gamescope") and util.which("gamescope"):
            os.environ["CROSSBAR_WRAP"] = "gamescope"
        try:
            if "progress" in inspect.signature(p.launch).parameters:
                p.launch(b["id"], progress=progress)
            else:
                p.launch(b["id"])
        except Exception as e:
            system.release_launch()
            HUB.publish({"type": "launch-timeout", "title": title, "error": str(e)})
            return
        finally:
            os.environ.pop("CROSSBAR_WRAP", None)
        if not live:
            return
        system.hold_launch(300)
        # The game's window appears -> bring it forward and drop the splash.
        end = time.time() + 300       # first starts can compile shaders for a while
        while time.time() < end:
            time.sleep(0.5)
            new = [w for w in system.windows() if is_game(w)]
            if new:
                system.release_launch()
                system.focus_window(new[-1]["con_id"])
                HUB.publish({"type": "launched", "title": title})
                time.sleep(3)          # let the "launched" splash finish before the XMB closes
                session.enter_game_mode(title)
                return
        system.release_launch()
        HUB.publish({"type": "launch-timeout", "title": title})
    if b["provider"] in ("steam", "shortcut") or live:
        threading.Thread(target=run, daemon=True).start()
    else:
        run()
    util.update_config(lambda c: c["last_played"].__setitem__(f"{p.id}:{b['id']}", time.time()))
    return {"ok": True, "demo": demo_on()}


def r_login(pid, b):
    p = provider(pid)

    return JOBS.start("login", p.name, lambda job: p.login(job, b), p.id).as_dict()


def r_settings(b):
    allowed = {"demo", "user", "theme", "sounds", "clock24", "gamescope", "steam_bigpicture", "free_memory_in_games", "glyphs"}

    if "glyphs" in b and b["glyphs"] not in ("auto", *glyphs.STYLES):
        raise ValueError("glyphs must be auto, xbox, playstation or nintendo")

    def apply(c):
        for k, v in b.items():
            if k in allowed:
                c[k] = v
            elif k == "video" and isinstance(v, dict):
                c["video"].update({kk: vv for kk, vv in v.items() if kk in ("resume", "subtitles")})
    util.update_config(apply)
    if "glyphs" in b:
        player.write_glyphs()          # a playing video picks the new style up within seconds
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
    artwork.apply(out)
    return sorted(out, key=lambda g: g["title"].lower())


GET = {
    "/api/state": lambda q: state(),
    "/api/quick": lambda q: quick.info(),
    "/api/bluetooth": lambda q: system.bluetooth_status(),
    "/api/compat": lambda q: {**compat.summary(), "game": compat.tool_for(q["game"]) if q.get("game") else None},
    "/api/compat/ge": lambda q: compat.ge_releases(),
    "/api/compat/catalogue": lambda q: {"tools": compat.catalogue(), "app": compat.protonup_qt()},
    "/api/compat/tool": lambda q: compat.tool_releases(q["id"]) if q.get("id") in compat.CATALOGUE else [],
    "/api/files": lambda q: files.listdir(q.get("path") or None, q.get("hidden") == "1"),
    "/api/files/places": lambda q: files.places(),
    "/api/nas": lambda q: nas.drives(),
    "/api/iptv/status": lambda q: iptv.status(),
    "/api/iptv/categories": lambda q: iptv.categories(q["kind"], q.get("shown") == "1"),
    "/api/iptv/items": lambda q: iptv.items(q["kind"], q["cat"], q.get("all") == "1"),
    "/api/iptv/series": lambda q: iptv.series_info(q["id"]),
    "/api/time": lambda q: system.time_status(),
    "/api/timezones": lambda q: system.timezones(),
    "/api/wifi/radio": lambda q: {"on": system.wifi_radio()},
    "/api/discord/state": lambda q: discord_state(),
    "/api/discord/guilds": lambda q: DISCORD.guilds(),
    "/api/discord/friends": lambda q: DISCORD.friends(),
    "/api/discord/debug": lambda q: DISCORD.debug(),
    "/api/browser/info": lambda q: BROWSER.info(),
    "/api/theme": lambda q: themes.current(),
    "/api/themes": lambda q: themes.available(),
    "/api/browser/bookmarks": lambda q: {"bookmarks": BROWSER.bookmarks(), "size": __import__("crossbar.browser", fromlist=["size"]).size()},
    "/api/friends/steam": lambda q: friends.steam_friends(),
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
    "/api/library": lambda q: artwork.apply(provider(q.get("provider", "")).library()),
    "/api/art": lambda q: artwork.status(),
    "/api/art/search": lambda q: artwork.search(q.get("q", "")),
    "/api/art/grids": lambda q: artwork.grids(game_id=q.get("game_id"), steam_appid=q.get("steam_appid")),
    "/api/media/list": lambda q: media.listdir(q["kind"], q.get("path") or None),
    "/api/media/scan": lambda q: media.scan(q["kind"]),
    "/api/fs": lambda q: media.browse_dirs(q.get("path") or None, BROWSE_EXT.get(q.get("ext") or "")),
    "/api/apps": lambda q: apps.installed(),
    "/api/extgames": lambda q: extgames.games(),
    "/api/flathub/collection": lambda q: apps.flathub_collection(q.get("kind", "popular"), int(q.get("page") or 1)),
    "/api/flathub/categories": lambda q: apps.flathub_categories(),
    "/api/flathub/category": lambda q: apps.flathub_category(q["id"], int(q.get("page") or 1)),
    "/api/flathub/search": lambda q: apps.flathub_search(q.get("q", "")),
    "/api/flathub/app": lambda q: apps.flathub_app(q["id"]),
    "/api/xmb/folders": lambda q: folders.list_folders(),
    "/api/xmb/tags": lambda q: folders.tags(),
    "/api/music/state": lambda q: player.music_state(),
    "/api/video/state": lambda q: player.video_state(),
    "/api/display": lambda q: display.outputs(),
    "/api/ps5": lambda q: ps5hw.status(),
    "/api/emulation": lambda q: emulation.status(),
    "/api/trophies": lambda q: trophies.status(),
    "/api/trophies/ra": lambda q: {**trophies.ra_summary(), "consoles": trophies.ra_consoles()},
    "/api/trophies/ra/game": lambda q: trophies.ra_game(q["id"]),
    "/api/trophies/steam": lambda q: trophies.steam_games(),
    "/api/steam/friends": lambda q: trophies.steam_friends(),
    "/api/trophies/steam/game": lambda q: trophies.steam_game(q["id"]),
    "/api/emulation/emulators": lambda q: emulation.emulators(),
    "/api/emulation/systems": lambda q: emulation.systems_with_games(),
    "/api/emulation/all-systems": lambda q: [{"id": k, "name": s["name"], "exts": s["exts"]} for k, s in emulation.SYSTEMS.items()],
    "/api/emulation/games": lambda q: artwork.apply(emulation.games(q["system"]), lambda g, s=q["system"]: f"rom:{s}:{g['id']}"),
    "/api/emulation/bios": lambda q: emulation.bios_status(),
    "/api/emulation/choices": lambda q: emulation.choices(q["system"]),
    "/api/ps5/temps": lambda q: ps5hw.temps(),
    "/api/audio/apps": lambda q: system.app_streams(),
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
        return {"ok": True, "now": SPOTIFY.control(b["action"])}
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
    if head == "apps":
        return r_apps(parts[1] if len(parts) > 1 else "", b)
    if head == "xmb" and len(parts) > 2 and parts[1] == "folders":
        what = parts[2]
        if what == "create":
            return folders.create(b["cat"], b.get("name"))
        if what == "rename":
            return folders.rename(b["id"], b.get("name"))
        if what == "delete":
            return folders.delete(b["id"])
        if what == "move":
            return folders.move(b["key"], b["cat"], b.get("folder"))
        if what == "tag":
            return folders.set_tag(b["key"], b.get("text"))
        raise KeyError(what)
    if head == "theme":
        what = parts[1] if len(parts) > 1 else ""
        if what == "set":
            t = themes.set_theme(b["id"])
        elif what == "install":
            t = themes.install(b["path"])
        elif what == "remove":
            r = themes.remove(b["id"])
            HUB.publish({"type": "theme"})
            return r
        else:
            raise KeyError(what)
        HUB.publish({"type": "theme"})
        return t
    if head == "steam" and len(parts) > 1 and parts[1] == "bigpicture":
        return r_bigpicture()
    if head == "jobs" and len(parts) > 1 and parts[1] == "cancel":
        return JOBS.cancel(b["id"])
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
    if head == "audio" and len(parts) > 1 and parts[1] == "app":
        system.set_app_volume(b["ids"], b.get("delta"), b.get("mute"))
        return {"apps": system.app_streams()}
    if head == "audio":
        system.set_audio(b["target"], b.get("delta"), b.get("mute"))
        return system.audio()
    if head == "window":
        {"focus": system.bring_to_front, "close": system.close_window, "kill": system.kill_window}[parts[1]](b["con_id"])
        return {"ok": True}
    if head == "session":
        if parts[1] == "restart":
            session.restart()
        elif parts[1] == "exit":
            session.exit_session()
        elif parts[1] == "desktop":
            session.switch_to_desktop()
        elif parts[1] == "gaming":
            session.switch_session("gamescope")
        return {"ok": True}
    if head == "overlay":
        if parts[1] == "ack":
            quick.OVERLAY["acked"] = True
            return {"ok": True}
        if parts[1] == "switch":
            return {"ok": quick.overlay_switch(b.get("con_id"))}
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
    if head == "trophies" and len(parts) > 1 and parts[1] == "steam-setup":
        return trophies.steam_setup(b.get("key"), b.get("steamid", ""))
    if head == "art":
        what = parts[1] if len(parts) > 1 else ""
        if what == "set":
            return artwork.set_override(b["key"], b["url"])
        if what == "reset":
            return artwork.reset(b["key"])
        if what == "reset-all":
            return artwork.reset_all()
        if what == "settings":
            return artwork.set_settings(key=b.get("key"), auto=b.get("auto"))
        if what == "local":
            if not media.allowed(b["path"]):
                raise PermissionError("Pick a picture in your home folder or on a drive")
            return artwork.set_local(b["key"], b["path"])
        raise KeyError(path)
    if head == "emulation":
        what = parts[1] if len(parts) > 1 else ""
        if what == "install":
            emu = b["emu"]
            if emu not in emulation.EMULATORS:
                raise KeyError(emu)
            return JOBS.start("install", emulation.EMULATORS[emu]["name"], lambda j: emulation.install(j, emu), "emulation").as_dict()
        if what == "uninstall":
            emulation.uninstall(b["emu"])
            return {"ok": True}
        if what == "folders":
            return {"path": emulation.create_folders()}
        if what == "settings":
            kw = {}
            if b.get("aspect") in emulation.ASPECT:
                kw["aspect"] = b["aspect"]
            if "integer_scale" in b:
                kw["integer_scale"] = bool(b["integer_scale"])
            if "root" in b and b["root"]:
                kw["root"] = os.path.expanduser(str(b["root"]))
            if "ra_enabled" in b or "hardcore" in b or "web_key" in b:
                ra = dict(emulation.prefs().get("ra") or {})
                if "ra_enabled" in b:
                    ra["enabled"] = bool(b["ra_enabled"])
                if "hardcore" in b:
                    ra["hardcore"] = bool(b["hardcore"])
                if "web_key" in b:
                    ra["web_key"] = str(b["web_key"]).strip()
                kw["ra"] = ra
            if "ra_signout" in b:
                kw["ra"] = {}
            emulation.save_prefs(**kw)
            return {**emulation.status(), "applied": emulation.apply_defaults()}
        if what == "ra-login":
            return emulation.ra_login(b.get("user", "").strip(), b.get("password", ""), b.get("web_key", "").strip())
        if what == "configure":
            emulation.configure(b["emu"])
            return {"ok": True}
        if what == "choose":
            if b["system"] not in emulation.SYSTEMS:
                raise KeyError(b["system"])
            util.update_config(lambda c: c.setdefault("emulation", {}).setdefault("emulator", {}).__setitem__(b["system"], b["value"]))
            return {"ok": True}
        raise KeyError(what)
    if head == "perf":
        def reload_key():
            # only into a game (never the menu or another app): MangoHud's "reload config" keys
            if PADS._target(fresh=True) == "app":
                PADS.type_keys(special="f4", shift=True)
        if parts[1] == "fps":
            return perf.set_mode(b["mode"], reload_key)
        if parts[1] == "corner":
            ps5hw.set_hud(corner=b["corner"])          # the temperature overlay moves with it
            HUB.publish({"type": "ps5-hud"})
            return perf.set_corner(b["corner"], reload_key)
        raise KeyError(parts[1])
    if head == "osk":
        what = parts[1] if len(parts) > 1 else ""
        if what == "show":                 # the system keyboard (overlay) opened / closed
            on = bool(b.get("on"))
            if on and not quick.overlay_available():
                raise RuntimeError("The on-screen keyboard needs the Quick Menu overlay (gtk4-layer-shell)")
            if on and b.get("auto") and not PADS.pad_recent():
                return {"open": False}     # typing on a real keyboard: don't pop up
            f = system.focused() or {}
            if on and b.get("auto") and (system.is_xmb(f) or "xmb" in f.get("marks", [])):
                return {"open": False}     # the XMB has its own keyboard: two would type twice
            if on and b.get("auto") and (system.is_steam_client(f) or (f.get("app") or "").lower().startswith("steam_app")):
                return {"open": False}     # Steam has its own keyboard
            if on and (system.is_xmb(f) or "xmb" in f.get("marks", [])):
                # The menu is in front: its own keyboard types into its text box. The system one
                # would type keys into the menu itself (Enter / arrows picking things behind it).
                HUB.publish({"type": "osk-xmb"})
                return {"open": False, "xmb": True}
            PADS.set_osk(on)
            HUB.publish({"type": "osk", "open": on})
            return {"open": on}
        if what == "web":                  # the menu's own keyboard opened / closed (PlayStation-style buttons)
            PADS.osk_web = bool(b.get("open"))
            return {"open": PADS.osk_web}
        if what == "type":
            f = system.focused() or {}
            if system.is_xmb(f) or "xmb" in f.get("marks", []):
                return {"typed": 0}        # never press keys into the menu behind the keyboard
            if BROWSER.running() and f.get("pid") == BROWSER.proc.pid:
                return {"typed": BROWSER.type_text(b.get("text", ""), b.get("special"))}   # straight into the page
            return {"typed": PADS.type_keys(b.get("text", ""), b.get("special"))}
        raise KeyError(what)
    if head == "ps5":
        what = parts[1] if len(parts) > 1 else ""
        if what == "fan-target":
            ps5hw.set_fan_target(b["value"] if "value" in b else (ps5hw.fan_target() or 80) + int(b.get("delta", 0)))
        elif what == "led":
            ps5hw.set_led(b["name"])
        elif what == "fan-mode":
            ps5hw.set_fan_mode(b["mode"])
        elif what == "boost":
            ps5hw.set_boost(bool(b.get("on")))
        elif what == "hud":
            ps5hw.set_hud(b.get("on"), b.get("corner"))
            HUB.publish({"type": "ps5-hud"})
        else:
            raise KeyError(what)
        return ps5hw.status()
    if head == "display":
        if parts[1] == "mode":
            display.set_mode(b["name"], b["width"], b["height"], b.get("refresh") or 0, b.get("save", True), bool(b.get("custom")))
        else:
            display.set_scale(b["name"], b["scale"], b.get("save", True))
        return display.outputs()
    if head == "audio-device":
        system.set_audio_device(b["id"])
        return system.audio_devices()
    if head == "wifi":
        return JOBS.start("wifi", b["ssid"], lambda j: system.wifi_connect(b["ssid"], b.get("password", ""))).as_dict()
    if head == "iptv":
        act = parts[1]
        if act == "login":
            return JOBS.start("login", "IPTV", lambda j: iptv.login(j, b.get("server"), b.get("username"), b.get("password")), "iptv").as_dict()
        if act == "logout":
            iptv.logout()
        elif act == "refresh":
            iptv.refresh()
        elif act == "show":
            iptv.set_shown(b["kind"], b["cat"], bool(b.get("on")))
        elif act == "hide":
            iptv.set_channel_hidden(b["id"], bool(b.get("on")))
        elif act == "play":
            entries, idx = iptv.playlist(b["kind"], b.get("cat"), b.get("id"), b.get("series"))
            pause_spotify()
            player.play_video(None, idx, mpv_gamepad=mpv_should_read_gamepad(PADS), entries=entries, user_agent=iptv.USER_AGENT)
            return {"ok": True, "title": entries[idx][0]}
        return iptv.status()
    if head == "nas":
        if parts[1] == "add":
            return JOBS.start("login", b.get("name") or "Network drive", lambda j: nas.add(j, b), "nas").as_dict()
        if parts[1] == "remove":
            nas.remove(b["name"])
        elif parts[1] == "remount":
            nas.remount(b["name"])
        return nas.drives()
    if head == "files":
        act = parts[1]
        if act in ("copy", "move"):
            label = f"{'Moving' if act == 'move' else 'Copying'} {len(b['paths'])} item(s)"
            return JOBS.start("files", label, lambda j: files.paste(j, b["paths"], b["dest"], move=act == "move")).as_dict()
        if act == "trash":
            files.trash(b["paths"])
        elif act == "delete":
            files.delete_forever(b["paths"])
        elif act == "rename":
            return {"path": files.rename(b["path"], b["name"])}
        elif act == "mkdir":
            return {"path": files.mkdir(b["path"], b["name"])}
        elif act == "empty-trash":
            files.empty_trash()
        return {"ok": True}
    if head == "compat":
        if parts[1] == "default":
            compat.set_default(b["tool"])
        elif parts[1] == "game":
            compat.set_game(b["game"], b.get("tool"))
        elif parts[1] == "install":
            return JOBS.start("install", b["tag"], lambda j: compat.install_ge(j, b["tag"]), "proton", b["tag"]).as_dict()
        elif parts[1] == "remove":
            compat.remove_proton(b["tool"])
        elif parts[1] == "tool-install":
            if b["tool"] not in compat.CATALOGUE:
                raise KeyError(b["tool"])
            name = f'{compat.CATALOGUE[b["tool"]]["name"]} {b["tag"]}'
            return JOBS.start("install", name, lambda j: compat.install_tool(j, b["tool"], b["tag"]), "compat", f'{b["tool"]}:{b["tag"]}').as_dict()
        elif parts[1] == "tool-remove":
            compat.remove_tool(b["tool"], b["tag"])
        return compat.summary()
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
        return r_browser(parts[1] if len(parts) > 1 else "open", b)
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
        if path == "/api/apps/icon":
            p = apps.icon_file(q.get("key", ""))
            if not p:
                return self._send(404, b"no icon", "text/plain")
            return self._send_file(p, "image/svg+xml" if p.endswith(".svg") else "image/png", cache=True)
        if path.startswith("/art/"):              # artwork you picked from a file
            p = artwork.local_file(path[len("/art/"):])
            if not p:
                return self._send(404, b"not found", "text/plain")
            return self._send_file(p, mimetypes.guess_type(p)[0] or "image/png", cache=True)
        if path.startswith("/theme/"):            # a theme's pictures, fonts, sounds, css
            parts = urllib.parse.unquote(path[len("/theme/"):]).split("/", 1)
            hit = themes.file_path(parts[0], parts[1]) if len(parts) == 2 else None
            if not hit:
                return self._send(404, b"not found", "text/plain")
            return self._send_file(hit[0], hit[1], cache=True)
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
            except KeyError as e:
                return self._send(400, {"error": f"missing: {e.args[0] if e.args else e}"})
            except Exception as e:
                if not isinstance(e, (util.NetError, RuntimeError, PermissionError, ValueError)):
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
    session.watchdog()
    PADS.start()

    def keep_xmb_marked():
        while True:
            system.ensure_xmb_mark()
            time.sleep(5)
    threading.Thread(target=keep_xmb_marked, daemon=True).start()
    system.bind_home_keys(controls.load()["keyboard"]["home"])
    def background_start():
        display.apply_saved()
        ps5hw.apply_saved()
        SPOTIFY.ensure_receiver()
        if util.load_config()["discord"].get("signed_in"):
            try:
                DISCORD.start()                   # voice runs in Discord's window; keep it ready, hidden
            except Exception as e:
                print(f"discord: {e}", flush=True)
    threading.Thread(target=background_start, daemon=True).start()
    artwork.on_change = lambda: HUB.publish({"type": "art"})
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"crossbard listening on http://127.0.0.1:{a.port} (demo={demo_on()})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
