"""The Crossbar session: restart/exit, game mode, and not outliving sway.

Game mode: while a game runs, the XMB window (a full browser, the biggest
piece of Crossbar) is closed to give the game the memory. The backend, the
Quick Menu overlay and the controller service keep running, so the Quick Menu,
music, Spotify, Discord voice and volume all still work. Going Home (or the
game ending) brings the XMB back in a couple of seconds.
"""
import os
import subprocess
import threading
import time

from . import util

RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
FLAG = os.path.join(RUNTIME, "crossbar-gamemode")
_lock = threading.Lock()


def _pkill(pattern):
    subprocess.run(["pkill", "-u", str(os.getuid()), "-f", pattern], capture_output=True)


# ---- game mode ----------------------------------------------------------------
def game_mode():
    return os.path.exists(FLAG)


def enter_game_mode(reason=""):
    from . import quick
    if not util.load_config().get("free_memory_in_games", True):
        return False
    if not quick.overlay_available():
        return False                      # without the overlay there'd be no way back
    with _lock:
        if game_mode():
            return True
        open(FLAG, "w").write(reason)
        _pkill("crossbar/shell-browser")  # crossbar-shell won't restart it while the flag exists
    print(f"session: game mode on ({reason})", flush=True)
    return True


def leave_game_mode(wait=10):
    """Bring the XMB back. Returns once its window exists (or after `wait` seconds)."""
    from . import system
    with _lock:
        if not game_mode():
            return
        os.remove(FLAG)
    print("session: game mode off", flush=True)
    end = time.time() + wait
    while time.time() < end:
        if system.ensure_xmb_mark():
            return
        time.sleep(0.25)


# ---- restart / exit ------------------------------------------------------------
def restart():
    """Stop every Crossbar piece; crossbar-shell starts them again within seconds."""
    try:
        os.remove(FLAG)
    except OSError:
        pass
    me = os.getpid()
    subprocess.Popen(["sh", "-c", f"sleep 0.4; pkill -u {os.getuid()} -f /usr/lib/crossbar/overlay.py; "
                                  f"pkill -u {os.getuid()} -f crossbar/shell-browser; kill {me}"],
                     start_new_session=True)


def exit_session():
    from . import system
    system._swaymsg("exit")


# ---- don't outlive the screen ----------------------------------------------------
def watchdog():
    """If the sway session that started us is gone, exit (a new session starts a new backend)."""
    sock = os.environ.get("SWAYSOCK")
    if not sock:
        return

    def loop():
        misses = 0
        while True:
            time.sleep(5)
            misses = misses + 1 if not os.path.exists(sock) else 0
            if misses >= 2:
                print("session: sway is gone, stopping", flush=True)
                os._exit(0)
    threading.Thread(target=loop, daemon=True).start()
