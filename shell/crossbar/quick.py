"""Quick Menu: the Guide/PS button (or Home key) from anywhere.

Takes a screenshot of whatever is in front (so the menu can sit over a dimmed
copy of the game or movie), pauses video, brings the XMB forward and asks it to
open the Quick Menu. From there: resume, close the app, control music/Spotify,
volume, output device and more.
"""
import os
import subprocess
import time

from . import player, system, util
from .events import HUB
from .spotify import SPOTIFY

SHOT = os.path.join(player.RUNTIME, "crossbar-overlay.jpg")
STATE = {"app": None, "pending": 0}
_sp_cache = [0, None]


def _screenshot():
    if not util.which("grim"):
        return False
    try:
        os.unlink(SHOT)
    except OSError:
        pass
    r = subprocess.run(["grim", "-s", "0.5", "-t", "jpeg", "-q", "70", SHOT], capture_output=True, timeout=5)
    return r.returncode == 0 and os.path.exists(SHOT)


OVERLAY = {"open": False, "hook": None}


def overlay_available():
    """True when the always-on-top overlay window (crossbar-overlay) is running."""
    return HUB.listeners("overlay-host") > 0


def _app_from(f):
    if not f or not f.get("con_id") or "xmb" in f["marks"] or system.is_xmb(f):
        return None
    video = f["app"] == player.VIDEO_APP_ID
    return {"con_id": f["con_id"], "title": f["title"] or f["app"] or "App", "app": f["app"],
            "video": video, "was_playing": video and not player.VIDEO.get("pause", True)}


def open_overlay():
    STATE["app"] = _app_from(system.focused())
    if STATE["app"] and STATE["app"]["video"]:
        player.pause_video()
    OVERLAY["open"] = True
    if OVERLAY["hook"]:
        OVERLAY["hook"](True)
    HUB.publish({"type": "overlay", "visible": True})


def close_overlay(resume=True):
    if not OVERLAY["open"]:
        return
    OVERLAY["open"] = False
    if OVERLAY["hook"]:
        OVERLAY["hook"](False)
    HUB.publish({"type": "overlay", "visible": False})
    app = _app()
    if resume and app and app["video"] and app["was_playing"]:
        player.VIDEO.cmd("set_property", "pause", False)


def overlay_go_home():
    close_overlay(resume=False)
    system.show_shell()


def overlay_close_app():
    closed = close()
    close_overlay(resume=False)
    system.hide_steam()                       # Steam's Big Picture shouldn't pop up after
    return closed


def overlay_open_settings(folder):
    close_overlay(resume=False)
    system.show_shell()
    HUB.publish({"type": "open-settings", "folder": folder})


def home_pressed():
    # Preferred: a real overlay drawn above whatever is running.
    if overlay_available():
        if OVERLAY["open"]:
            close_overlay(resume=True)
        else:
            open_overlay()
        return
    # Fallback (no overlay window): switch to the XMB and open its Quick Menu.
    f = system.focused()
    if f is None or "xmb" in f["marks"] or not f["con_id"]:
        HUB.publish({"type": "quick", "toggle": True})
        return
    video = f["app"] == player.VIDEO_APP_ID
    STATE["app"] = {"con_id": f["con_id"], "title": f["title"] or f["app"] or "App", "app": f["app"],
                    "video": video, "was_playing": video and not player.VIDEO.get("pause", True)}
    shot = _screenshot()
    if video:
        player.pause_video()
    STATE["pending"] = time.time()
    system.show_shell()
    HUB.publish({"type": "quick", "open": True, "shot": shot, "t": time.time()})


def take_pending():
    """The XMB asks this when it gets focus, in case the event stream missed the request."""
    pending = time.time() - STATE["pending"] < 4
    STATE["pending"] = 0
    return pending


def _app():
    app = STATE["app"]
    if not app:
        return None
    if not any(w["con_id"] == app["con_id"] for w in system.windows()):
        STATE["app"] = None         # it was closed meanwhile
        return None
    return app


def resume():
    app = _app()
    if not app:
        return False
    system.focus_window(app["con_id"])
    if app["video"] and app["was_playing"]:
        player.VIDEO.cmd("set_property", "pause", False)
    return True


def close():
    app = _app()
    if not app:
        return False
    if app["video"]:
        player.VIDEO.stop()
    else:
        system.force_close(app["con_id"])     # polite close, then end it if it hangs
    STATE["app"] = None
    return True


def info():
    sp = None
    if time.time() - _sp_cache[0] > 2:
        try:
            _sp_cache[1] = SPOTIFY.now() if SPOTIFY.status()["linked"] else None
        except Exception:
            _sp_cache[1] = None
        _sp_cache[0] = time.time()
    sp = _sp_cache[1]
    devices = system.audio_devices()
    voice = None
    try:
        from .discord import DISCORD
        if DISCORD.sock:
            voice = {"channel": DISCORD.state["channel"], "mute": DISCORD.state["mute"], "deaf": DISCORD.state["deaf"]}
    except Exception:
        pass
    return {
        "voice": voice,
        "app": _app(),
        "music": player.music_state(),
        "spotify": sp,
        "audio": system.audio(),
        "output": next((d for d in devices["outputs"] if d["default"]), None),
        "outputs": devices["outputs"],
        "shot": os.path.exists(SHOT),
    }


def next_output():
    outs = system.audio_devices()["outputs"]
    if len(outs) < 2:
        return None
    i = next((k for k, d in enumerate(outs) if d["default"]), -1)
    nxt = outs[(i + 1) % len(outs)]
    system.set_audio_device(nxt["id"])
    return nxt["name"]
