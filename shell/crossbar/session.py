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
        _pkill("^[^ ]*chrom[^ ]* .*crossbar/shell-browser")  # crossbar-shell won't restart it while the flag exists
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
    # [x] patterns so pkill can't match this helper's own command line
    subprocess.Popen(["sh", "-c", f"sleep 0.4; pkill -u {os.getuid()} -f '^python3 /usr/lib/crossbar/overlay[.]py'; "
                                  f"pkill -u {os.getuid()} -f '^[^ ]*chrom[^ ]* .*crossbar/shell-browser'; kill {me}"],
                     start_new_session=True)


# ---- Crossbar <-> Plasma desktop (installs made with install-cachyos.sh) --------------------
BOOT_FILE = os.path.expanduser("~/.config/crossbar/boot-session")


PS5_TOKEN = os.path.expanduser("~/.config/ps5-next-session")
PS5_SCRIPT = "/etc/profile.d/ps5-tty-session.sh"


def ps5_mode():
    """PS5 setup with Crossbar added to its session switcher (ps5-session.sh)."""
    try:
        return os.path.exists(PS5_TOKEN) and ">>> crossbar >>>" in open(PS5_SCRIPT).read()
    except OSError:
        return False


def boot_mode():
    """'ps5', 'tty' (tty1 autologin + login-file hook), 'dm' (login manager), or None."""
    if ps5_mode():
        return "ps5"
    if os.path.exists(BOOT_FILE):
        return "tty"
    return "dm" if desktop_available() else None


def desktop_available():
    """True when the login manager starts Crossbar and a Plasma session exists to switch to."""
    if os.path.exists(BOOT_FILE) or ps5_mode():
        return True
    ws = "/usr/share/wayland-sessions"
    if not os.path.exists(os.path.join(ws, "crossbar.desktop")):
        return False
    if not any(os.path.exists(os.path.join(ws, f)) for f in ("plasma.desktop", "plasmawayland.desktop")):
        return False
    target = os.path.basename(os.path.realpath("/etc/systemd/system/display-manager.service"))
    return target.startswith(("sddm", "plasmalogin"))


def switch_session(target):
    """PS5 setup: leave Crossbar for gaming mode ("gamescope") or Plasma ("desktop")."""
    if target not in ("gamescope", "desktop"):
        raise ValueError(target)
    with open(PS5_TOKEN, "w") as f:
        f.write(target + "\n")
    subprocess.Popen(["sh", "-c", "sleep 1; swaymsg exit"], start_new_session=True)


def switch_to_desktop():
    if ps5_mode():
        return switch_session("desktop")
    if os.path.exists(BOOT_FILE):
        # TTY setup: hand tty1 back to your own startup (gaming mode / Plasma) until you return
        with open(BOOT_FILE, "w") as f:
            f.write("system\n")
        subprocess.Popen(["sh", "-c", "sleep 1; swaymsg exit"], start_new_session=True)
        return
    import json
    r = subprocess.run(["pkexec", "/usr/lib/crossbar/admin.py", "boot-session"], input=json.dumps({"session": "desktop"}),
                       capture_output=True, text=True, timeout=60)
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        res = {"ok": False, "error": (r.stderr or r.stdout).strip()[-200:] or "The system helper failed"}
    if not res.get("ok"):
        raise RuntimeError(res.get("error"))
    # the login manager logs straight back in, into the desktop
    subprocess.Popen(["sh", "-c", "sleep 1; swaymsg exit"], start_new_session=True)


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
