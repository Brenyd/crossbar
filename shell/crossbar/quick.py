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


def home_pressed():
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
        system.close_window(app["con_id"])
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
    return {
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
