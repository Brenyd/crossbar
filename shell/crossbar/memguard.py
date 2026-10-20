"""Memory guard: a game that runs the console out of memory mustn't freeze everything.

When memory runs out, Linux first spends minutes thrashing (sound stutters, the picture and
the controller stop answering) before its own out-of-memory killer acts, and then it may pick
the wrong process. The guard watches free memory and memory pressure twice a second and acts
early, in two steps:

  low       a game is starting or running -> close the menu window (game mode), the biggest
            piece of Crossbar, so the game gets that memory
  critical  still running out -> end the process using the most memory (almost always the
            game) and say so, instead of letting the whole console lock up

Crossbar's own pieces, sway, sound (PipeWire) and the login are never picked. Settings ›
System › Memory Guard turns it off (config "memory_guard").
"""
import os
import signal
import threading
import time

from . import util

PROTECT = {"sway", "swaybg", "Xwayland", "pipewire", "pipewire-pulse", "wireplumber", "systemd", "dbus-daemon",
           "dbus-broker", "dbus-broker-lau", "crossbar-shell", "bash", "sh", "sshd", "sudo", "login", "agetty",
           "python3", "python", "rtkit-daemon", "seatd", "polkitd", "xdg-desktop-por", "gamescope", "steam",
           "steamwebhelper", "librespot", "mpv", "tmux", "ssh-agent", "gpg-agent", "at-spi-bus-laun", "at-spi2-registr"}

STATE = {"level": "ok", "avail_pct": 100.0, "psi": 0.0, "killed": [], "on": True}
_hooks = {"notice": None}


def meminfo():
    out = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, _, v = line.partition(":")
            out[k] = int(v.split()[0])          # kB
    return out


def psi_full():
    """How much of the last 10 s every task was stalled waiting for memory (%)."""
    try:
        with open("/proc/pressure/memory") as f:
            for line in f:
                if line.startswith("full"):
                    return float(line.split("avg10=")[1].split()[0])
    except (OSError, IndexError, ValueError):
        pass
    return 0.0


def classify(mi, psi):
    """'ok', 'low' or 'critical' from /proc/meminfo numbers (kB) and memory pressure."""
    total = mi.get("MemTotal", 1)
    avail = mi.get("MemAvailable", total)
    swap_t, swap_f = mi.get("SwapTotal", 0), mi.get("SwapFree", 0)
    pct = 100.0 * avail / total
    swap_low = swap_t == 0 or swap_f < swap_t * 0.15
    if (pct < 4 or avail < 300 * 1024) and swap_low:
        return "critical", pct
    if psi > 40 and pct < 10:
        return "critical", pct                  # thrashing: everything waits on memory
    if pct < 12 and swap_low or psi > 15:
        return "low", pct
    return "ok", pct


def biggest():
    """(pid, name, rss kB) of our user's process using the most memory that isn't protected."""
    me, uid, best = os.getpid(), os.getuid(), None
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) == me:
            continue
        try:
            st = os.stat(f"/proc/{d}")
            if st.st_uid != uid:
                continue
            with open(f"/proc/{d}/comm") as f:
                name = f.read().strip()
            if name in PROTECT:
                continue
            with open(f"/proc/{d}/statm") as f:
                rss = int(f.read().split()[1]) * (os.sysconf("SC_PAGE_SIZE") // 1024)
        except (OSError, ValueError, IndexError):
            continue
        if not best or rss > best[2]:
            best = (int(d), name, rss)
    return best


def _game_running():
    from . import system
    if system.launching():
        return True
    return any((w.get("app") or "").lower().startswith("steam_app_") or (w.get("app") or "").lower() == "gamescope"
               for w in system.windows())


def _notice(text):
    print(f"memguard: {text}", flush=True)
    if _hooks["notice"]:
        try:
            _hooks["notice"](text)
        except Exception:
            pass


def step(mi=None, psi=None, now=None, act=True):
    """One check; returns the level. Split out so it can be tested."""
    now = now or time.time()
    mi = mi or meminfo()
    psi = psi_full() if psi is None else psi
    level, pct = classify(mi, psi)
    prev = STATE["level"]
    STATE.update(level=level, avail_pct=round(pct, 1), psi=psi)
    if not act:
        return level
    if level in ("low", "critical") and prev == "ok":
        try:
            from . import session
            if _game_running():
                session.enter_game_mode("memory")
        except Exception as e:
            print(f"memguard: game mode: {e!r}", flush=True)
    if level == "critical":
        STATE["crit"] = STATE.get("crit", 0) + 1
        # two checks in a row (a second), and not right after the last one (memory takes a moment to come back)
        if STATE["crit"] >= 2 and now - STATE.get("last_kill", 0) > 8:
            b = biggest()
            if b and b[2] > 400 * 1024:
                try:
                    os.kill(b[0], signal.SIGKILL)
                    STATE["last_kill"] = now
                    STATE["killed"] = (STATE["killed"] + [{"pid": b[0], "name": b[1], "mb": b[2] // 1024, "at": now}])[-10:]
                    _notice(f"{b[1]} ran out of memory ({b[2] // 1024} MB) — closed it so the console wouldn't freeze")
                except OSError:
                    pass
            STATE["crit"] = 0
    else:
        STATE["crit"] = 0
    return level


def run():
    while True:
        try:
            on = util.load_config().get("memory_guard", True) if STATE.get("cfg_at", 0) < time.time() - 10 else STATE["on"]
            if STATE.get("cfg_at", 0) < time.time() - 10:
                STATE.update(on=on, cfg_at=time.time())
            lvl = step(act=STATE["on"])
        except Exception as e:
            print(f"memguard: {e!r}", flush=True)
            lvl = "ok"
        time.sleep(0.5 if lvl != "ok" or STATE["avail_pct"] < 25 else 1.5)


def start(notice=None):
    _hooks["notice"] = notice
    if os.path.exists("/proc/meminfo"):
        threading.Thread(target=run, daemon=True, name="memguard").start()


def status():
    return {k: STATE[k] for k in ("level", "avail_pct", "psi", "killed", "on")}
