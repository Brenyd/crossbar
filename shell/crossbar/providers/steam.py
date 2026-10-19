"""Steam: owned games via the Steam Web API, installs/launches via the Steam client.

The Steam client does the actual downloading (steam://install/<appid>); we watch
its appmanifest files to show progress on the XMB.
"""
import glob
import os
import time

from .. import util
from .base import Provider, game

ART = "https://cdn.cloudflare.steamstatic.com/steam/apps/{}/header.jpg"
OWNED = ("https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
         "?key={key}&steamid={sid}&include_appinfo=1&include_played_free_games=1&format=json")
# Runtimes/tools Steam installs as "apps" that shouldn't appear as games
TOOLS = ("Proton", "Steam Linux Runtime", "Steamworks Common Redistributables")


def steam_roots():
    cands = [os.path.join(util.HOME, p) for p in
             (".local/share/Steam", ".steam/steam", ".var/app/com.valvesoftware.Steam/.local/share/Steam")]
    seen, out = set(), []
    for c in cands:
        r = os.path.realpath(c)
        if os.path.isdir(r) and r not in seen:
            seen.add(r)
            out.append(r)
    return out


class Steam(Provider):
    id = "steam"
    name = "Steam"
    login_fields = [
        {"key": "steamid", "label": "SteamID64 (17 digits — find it at steamid.io)"},
        {"key": "api_key", "label": "Steam Web API key (steamcommunity.com/dev/apikey)", "secret": True},
    ]

    def __init__(self):
        self._cache = (0, [])

    # ---- local client -------------------------------------------------
    def _library_dirs(self):
        dirs = []
        for root in steam_roots():
            vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
            try:
                data = util.parse_vdf(open(vdf, encoding="utf-8", errors="replace").read())
                for entry in data.get("libraryfolders", {}).values():
                    if isinstance(entry, dict) and entry.get("path"):
                        dirs.append(os.path.join(entry["path"], "steamapps"))
            except OSError:
                pass
            dirs.append(os.path.join(root, "steamapps"))
        return list(dict.fromkeys(d for d in dirs if os.path.isdir(d)))

    def _manifests(self):
        out = {}
        for d in self._library_dirs():
            for path in glob.glob(os.path.join(d, "appmanifest_*.acf")):
                try:
                    st = util.parse_vdf(open(path, encoding="utf-8", errors="replace").read()).get("AppState", {})
                except OSError:
                    continue
                if st.get("appid"):
                    st["_path"] = path
                    out[st["appid"]] = st
        return out

    def _local_installed(self):
        res = {}
        for appid, st in self._manifests().items():
            name = st.get("name", appid)
            if any(name.startswith(t) for t in TOOLS):
                continue
            flags = int(st.get("StateFlags", "0") or 0)
            if flags & 4:  # StateFullyInstalled
                res[appid] = name
        return res

    # ---- Provider API -------------------------------------------------
    def status(self):
        cfg = util.load_config()["steam"]
        client = bool(util.which("steam")) or bool(steam_roots())
        linked = bool(cfg.get("api_key") and cfg.get("steamid"))
        return {"linked": linked, "account": cfg.get("steamid", "") if linked else "",
                "ready": client,
                "note": "" if client else "Steam client not installed"}

    def library(self):
        installed = self._local_installed()
        cfg = util.load_config()["steam"]
        owned = []
        if cfg.get("api_key") and cfg.get("steamid"):
            if time.time() - self._cache[0] > 600:
                data = util.http_json(OWNED.format(key=cfg["api_key"], sid=cfg["steamid"]))
                self._cache = (time.time(), data.get("response", {}).get("games", []))
            owned = self._cache[1]
        games = {str(g["appid"]): g.get("name", str(g["appid"])) for g in owned}
        games.update(installed)
        return sorted((game("steam", a, n, ART.format(a), a in installed) for a, n in games.items()),
                      key=lambda g: g["title"].lower())

    def installed(self):
        return [game("steam", a, n, ART.format(a), True) for a, n in self._local_installed().items()]

    def login(self, job, fields):
        sid, key = fields.get("steamid", "").strip(), fields.get("api_key", "").strip()
        if not (sid.isdigit() and len(sid) == 17):
            raise ValueError("SteamID64 should be 17 digits")
        job.set(0.3, "Checking key…")
        data = util.http_json(OWNED.format(key=key, sid=sid))
        n = len(data.get("response", {}).get("games", []))
        util.update_config(lambda c: c["steam"].update(api_key=key, steamid=sid))
        self._cache = (0, [])
        job.set(1, f"Found {n} games")
        if util.which("steam"):  # sign the client in too, so installs work
            util.spawn(["steam", "-silent"])

    def logout(self):
        util.update_config(lambda c: c["steam"].update(api_key="", steamid=""))
        self._cache = (0, [])

    def install(self, job, appid):
        if not util.which("steam"):
            raise RuntimeError("Steam client is not installed")
        fresh = appid not in self._manifests()        # a new install, not an update
        util.spawn(["steam", f"steam://install/{appid}"])
        job.set(0, "Waiting for Steam…")
        if fresh:
            # Steam's own uninstall removes the partly downloaded game (Steam may ask to confirm)
            job.cancel_with(lambda: util.spawn(["steam", f"steam://uninstall/{appid}"]))
        deadline = time.time() + 600
        while True:
            job.check()
            st = self._manifests().get(appid)
            if st:
                flags = int(st.get("StateFlags", "0") or 0)
                if flags & 4 and not flags & (1024 | 2):  # installed, no update pending
                    return
                done, total, phase = download_progress(st)
                if total:
                    job.set_bytes(done, total, phase)
                elif phase:
                    job.set(message=phase)
                deadline = time.time() + 3600
            elif time.time() > deadline:
                raise RuntimeError("Steam didn't start the download (is the client signed in?)")
            time.sleep(1)

    def uninstall(self, job, appid):
        util.spawn(["steam", f"steam://uninstall/{appid}"])

    def launch(self, appid, progress=None):
        """Big Picture (Steam's console UI) by default, so Steam Input and its overlay
        behave like on a Steam Deck. Crossbar hides Steam again when the game ends.

        If Steam isn't running (or is updating) it is started first and the game is only
        sent once Steam is fully up: a game URL handed to Steam while it updates gets lost."""
        progress = progress or (lambda msg: None)
        url = f"steam://rungameid/{appid}"
        bpm = util.load_config().get("steam_bigpicture", True)
        if not steam_running():
            progress("Starting Steam…")
            start_steam(bpm)
            wait_ready(bpm, progress)
        elif bpm:
            util.spawn(["steam", "steam://open/bigpicture"])
            wait_ready(bpm, progress, quick=True)
        progress("Starting the game…")
        util.spawn(["steam", url])


def _allocated(path):
    """Bytes really written under a folder (allocated blocks: Steam pre-sizes its files, so the
    plain file sizes would jump to 100% at once)."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_blocks * 512
            except OSError:
                pass
    return total


def download_progress(st):
    """(done, total, phase) for a download in progress, as close to live as Steam allows.

    Steam rewrites its appmanifest's counters only every so often, which made progress jump and
    stall. While it downloads, its steamapps/downloading/<appid> folder grows with the data, so
    progress follows that folder (against BytesToStage, the size it will reach), scaled to the
    download size; the manifest's own counters are the fallback and the floor."""
    to_dl = int(st.get("BytesToDownload", "0") or 0)
    dl = int(st.get("BytesDownloaded", "0") or 0)
    to_stage = int(st.get("BytesToStage", "0") or 0)
    staged = int(st.get("BytesStaged", "0") or 0)
    lib = os.path.dirname(st.get("_path", ""))
    folder = os.path.join(lib, "downloading", str(st.get("appid", "")))
    frac = (dl / to_dl) if to_dl else 0.0
    if to_stage and os.path.isdir(folder):
        frac = max(frac, min(1.0, max(staged, _allocated(folder)) / to_stage))
    elif to_stage:
        frac = max(frac, staged / to_stage)
    total = to_dl or to_stage
    phase = ""
    if total and frac >= 0.999:
        phase = "Installing"                     # downloaded; Steam is unpacking / verifying
    elif not total:
        phase = "Waiting for Steam…"
    return int(frac * total), total, phase


STEAM_LOG = os.path.expanduser("~/.cache/crossbar-steam.log")


def start_steam(bpm=True):
    """Start Steam with its output kept, so its update progress can be shown."""
    import subprocess
    os.makedirs(os.path.dirname(STEAM_LOG), exist_ok=True)
    log = open(STEAM_LOG, "w")
    from .. import perf
    subprocess.Popen(["steam", "-gamepadui"] if bpm else ["steam", "-silent"], stdin=subprocess.DEVNULL,
                     env={**os.environ, **perf.env()},          # Steam passes MangoHud on to its games
                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


def _update_status():
    """Steam's bootstrapper prints lines like "[ 42%] Downloading update (…)"."""
    import re
    try:
        with open(STEAM_LOG, errors="replace") as f:
            f.seek(max(0, os.path.getsize(STEAM_LOG) - 8192))
            tail = f.read().splitlines()
    except OSError:
        return None
    for line in reversed(tail):
        m = re.match(r"\[\s*(\d+%|-+)\]\s*(.+?)\.*$", line.strip())
        if m:
            what = m.group(2).lower()
            if "verif" in what:
                return "Steam is checking its files…"
            if "download" in what or "extract" in what or "install" in what:
                return f"Updating Steam… {m.group(1)}" if m.group(1).endswith("%") else "Updating Steam…"
            if "check" in what:
                return "Steam is checking for updates…"
            return None
    return None


def _steam_windows():
    from .. import system
    return [w for w in system.all_windows() if system.is_steam_client(w)]


def ready(bpm):
    """Steam is up: Big Picture's window exists (or, without Big Picture, its web helper runs)."""
    import subprocess
    if bpm:
        return any("big picture" in (w.get("title") or "").lower() for w in _steam_windows())
    return subprocess.run(["pgrep", "-f", "steamwebhelper"], capture_output=True).returncode == 0 \
        and bool(_steam_windows() or os.path.exists(os.path.expanduser("~/.steam/steam.pid")))


def wait_ready(bpm, progress, quick=False, timeout=20 * 60):
    """Wait (through updates and sign-in) until Steam can take a game URL."""
    from .. import system
    end, last, seen_ready = time.time() + (60 if quick else timeout), None, 0
    system.hold_launch(timeout)
    while time.time() < end:
        if ready(bpm):
            seen_ready += 1
            if seen_ready >= 3:          # give Steam a few seconds after its window appears
                return True
        else:
            seen_ready = 0
        msg = _update_status() or ("Waiting for Steam…" if not quick else None)
        if msg and msg != last:
            progress(msg)
            last = msg
        time.sleep(1)
    return False


def steam_running():
    import subprocess
    return subprocess.run(["pgrep", "-x", "steam"], capture_output=True).returncode == 0
