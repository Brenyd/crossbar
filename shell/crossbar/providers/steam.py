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
        util.spawn(["steam", f"steam://install/{appid}"])
        job.set(0, "Waiting for Steam…")
        deadline = time.time() + 600
        while True:
            st = self._manifests().get(appid)
            if st:
                flags = int(st.get("StateFlags", "0") or 0)
                total = int(st.get("BytesToDownload", "0") or 0)
                done = int(st.get("BytesDownloaded", "0") or 0)
                if flags & 4 and not flags & (1024 | 2):  # installed, no update pending
                    return
                if total:
                    job.set(done / total, f"{done >> 20} / {total >> 20} MB")
                deadline = time.time() + 3600
            elif time.time() > deadline:
                raise RuntimeError("Steam didn't start the download (is the client signed in?)")
            time.sleep(2)

    def uninstall(self, job, appid):
        util.spawn(["steam", f"steam://uninstall/{appid}"])

    def launch(self, appid):
        """Big Picture (Steam's console UI) by default, so Steam Input and its overlay
        behave like on a Steam Deck. Crossbar hides Steam again when the game ends."""
        url = f"steam://rungameid/{appid}"
        if not util.load_config().get("steam_bigpicture", True):
            util.spawn(["steam", url])
            return
        if not steam_running():
            util.spawn(["steam", "-gamepadui", url])
        else:
            util.spawn(["steam", "steam://open/bigpicture"])
            time.sleep(1.5)
            util.spawn(["steam", url])


def steam_running():
    import subprocess
    return subprocess.run(["pgrep", "-x", "steam"], capture_output=True).returncode == 0
