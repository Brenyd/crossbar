"""Running Windows games: Proton / Wine picker and GE-Proton download manager.

Games run through umu-launcher (umu-run), the runner Heroic and Lutris use: it
sets up a Proton prefix with the Steam runtime and applies per-game fixes.

Tools:
  umu         UMU-Proton (umu downloads and updates it itself) — the default
  GE-Proton   newest GE-Proton (umu fetches it)
  <name>      a Proton build in Steam's compatibilitytools.d (e.g. GE-Proton9-20,
              downloaded here) or Steam's own "Proton 9.0" in steamapps/common
  wine        the system's Wine, no Proton
"""
import glob
import os
import re
import shutil
import tarfile
import time
import urllib.parse

from . import util

STEAM_ROOT = os.path.join(util.HOME, ".local", "share", "Steam")
COMPAT_DIR = os.path.join(STEAM_ROOT, "compatibilitytools.d")
PREFIXES = os.path.join(util.GAMES_DIR, "prefixes")
GE_RELEASES = "https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases?per_page=12"
UMU_API = "https://umu.openwinecomponents.org/umu_api.php"
_umu_ids = {}


def cfg():
    return util.load_config().get("compat") or {}


def _natural(path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", os.path.basename(path))]


def installed_protons():
    out = []
    for d in sorted(glob.glob(os.path.join(COMPAT_DIR, "*")), key=_natural, reverse=True):
        if os.path.isfile(os.path.join(d, "proton")):
            out.append({"id": os.path.basename(d), "name": os.path.basename(d), "path": d, "removable": True})
    for root in [STEAM_ROOT] + _steam_libraries():
        for d in sorted(glob.glob(os.path.join(root, "steamapps", "common", "Proton*")), reverse=True):
            if os.path.isfile(os.path.join(d, "proton")):
                out.append({"id": os.path.basename(d), "name": os.path.basename(d) + " (Steam)", "path": d, "removable": False})
    return out


def _steam_libraries():
    try:
        data = util.parse_vdf(open(os.path.join(STEAM_ROOT, "steamapps", "libraryfolders.vdf"), errors="replace").read())
        return [e["path"] for e in data.get("libraryfolders", {}).values() if isinstance(e, dict) and e.get("path")]
    except OSError:
        return []


def tools():
    """Everything the picker can offer, best first."""
    umu = bool(util.which("umu-run"))
    out = []
    if umu:
        out.append({"id": "umu", "name": "UMU-Proton (recommended)", "note": "Downloaded and updated automatically"})
        out.append({"id": "GE-Proton", "name": "GE-Proton (newest)", "note": "Downloaded automatically"})
        out += [{"id": p["id"], "name": p["name"], "note": "Installed"} for p in installed_protons()]
    if util.which("wine"):
        out.append({"id": "wine", "name": "System Wine", "note": "No Proton"})
    return out


def default_tool():
    ids = [t["id"] for t in tools()]
    d = cfg().get("default", "umu")
    return d if d in ids else (ids[0] if ids else None)


def tool_for(game_key):
    t = (cfg().get("games") or {}).get(game_key)
    return t if t in [x["id"] for x in tools()] else default_tool()


def set_default(tool_id):
    util.update_config(lambda c: c.setdefault("compat", {}).__setitem__("default", tool_id))


def set_game(game_key, tool_id):
    def f(c):
        games = c.setdefault("compat", {}).setdefault("games", {})
        if tool_id:
            games[game_key] = tool_id
        else:
            games.pop(game_key, None)
    util.update_config(f)


def prefix_for(game_key):
    p = os.path.join(PREFIXES, util.slug(game_key))
    os.makedirs(p, exist_ok=True)
    return p


def umu_id(store, codename):
    """umu-database id for per-game fixes (e.g. 'umu-1207658924'); 'umu-default' if unknown."""
    key = (store, str(codename))
    if key not in _umu_ids:
        try:
            res = util.http_json(f"{UMU_API}?{urllib.parse.urlencode({'store': store, 'codename': codename})}", timeout=8)
            _umu_ids[key] = (res[0].get("umu_id") if isinstance(res, list) and res else None) or "umu-default"
        except Exception:
            _umu_ids[key] = "umu-default"
    return _umu_ids[key]


def env_for(game_key, store, codename):
    """(tool, env) for a game — used when another launcher (legendary) runs the exe."""
    argv, env = command("game.exe", [], game_key, store, codename)
    return tool_for(game_key), env


def command(exe, args, game_key, store, codename):
    """(argv, env) to run a Windows exe with the game's chosen tool."""
    tool = tool_for(game_key)
    if tool is None:
        raise RuntimeError("No way to run Windows games: install umu-launcher (or wine)")
    env = {"WINEPREFIX": prefix_for(game_key)}
    if tool == "wine":
        return ["wine", exe, *args], env
    env.update({"GAMEID": umu_id(store, codename), "STORE": store, "PROTON_VERB": "waitforexitandrun"})
    if tool != "umu":
        proton = next((p for p in installed_protons() if p["id"] == tool), None)
        env["PROTONPATH"] = proton["path"] if proton else tool          # "GE-Proton" = newest, fetched by umu
    return ["umu-run", exe, *args], env


# ---- GE-Proton download manager -----------------------------------------------
_releases = [0, []]


def ge_releases():
    if time.time() - _releases[0] > 900:
        data = util.http_json(GE_RELEASES, headers={"Accept": "application/vnd.github+json"})
        rel = []
        for r in data:
            asset = next((a for a in r.get("assets", []) if a["name"].endswith(".tar.gz")), None)
            if asset:
                rel.append({"id": r["tag_name"], "date": (r.get("published_at") or "")[:10],
                            "url": asset["browser_download_url"], "size": asset.get("size", 0)})
        _releases[:] = [time.time(), rel]
    have = {p["id"] for p in installed_protons()}
    return [{**r, "installed": r["id"] in have} for r in _releases[1]]


def install_ge(job, tag):
    rel = next((r for r in ge_releases() if r["id"] == tag), None)
    if not rel:
        raise RuntimeError(f"{tag} not found")
    os.makedirs(COMPAT_DIR, exist_ok=True)
    tmp = os.path.join(COMPAT_DIR, f".{tag}.tar.gz")
    util.download(rel["url"], tmp, lambda f: job.set(f * 0.85, f"Downloading {int(f * 100)}%"))
    job.set(0.9, "Unpacking…")
    try:
        with tarfile.open(tmp) as tf:
            root = os.path.realpath(COMPAT_DIR)
            for m in tf.getmembers():          # refuse anything escaping the folder
                target = os.path.realpath(os.path.join(COMPAT_DIR, m.name))
                if not target.startswith(root + os.sep) or m.issym() and os.path.isabs(m.linkname):
                    raise RuntimeError(f"unexpected path in archive: {m.name}")
            tf.extractall(COMPAT_DIR, filter="tar") if hasattr(tarfile, "data_filter") else tf.extractall(COMPAT_DIR)
    finally:
        os.remove(tmp)


def remove_proton(tool_id):
    p = next((x for x in installed_protons() if x["id"] == tool_id and x["removable"]), None)
    if not p:
        raise RuntimeError("Only versions downloaded here can be removed")
    shutil.rmtree(p["path"])


def summary():
    return {"tools": tools(), "default": default_tool(), "umu": bool(util.which("umu-run")),
            "games": cfg().get("games") or {}}

