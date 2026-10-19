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
import subprocess
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
    """(argv, env) to run a Windows exe with the game's chosen tool, plus the game's own
    launch options (Y › Launch Options…: variables, a command in front, extra arguments)."""
    from . import launchopts
    tool = tool_for(game_key)
    if tool is None:
        raise RuntimeError("No way to run Windows games: install umu-launcher (or wine)")
    extra_env, pre, post = launchopts.native(game_key)
    env = {"WINEPREFIX": prefix_for(game_key)}
    if tool == "wine":
        return [*pre, "wine", exe, *args, *post], {**env, **extra_env}
    env.update({"GAMEID": umu_id(store, codename), "STORE": store, "PROTON_VERB": "waitforexitandrun"})
    if tool != "umu":
        proton = next((p for p in installed_protons() if p["id"] == tool), None)
        env["PROTONPATH"] = proton["path"] if proton else tool          # "GE-Proton" = newest, fetched by umu
    return [*pre, "umu-run", exe, *args, *post], {**env, **extra_env}


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



# ---- Compatibility tools (ProtonUp-Qt's catalogue) ------------------------------------------------
# The tools ProtonUp-Qt (github.com/DavidoTek/ProtonUp-Qt) installs, from the same GitHub releases,
# into the same places: Steam's compatibilitytools.d, Lutris' runners/wine and runtime folders.
# kind: "steam" / "lutris-wine" / "lutris-dxvk" / "lutris-vkd3d". pick(name) chooses the asset.
def _x86_level():
    try:
        flags = open("/proc/cpuinfo").read()
    except OSError:
        return ""
    return "_v3" if all(f" {f}" in flags for f in ("avx2", "bmi2", "fma", "movbe")) else ""


CATALOGUE = {
    "ge-proton": {"name": "GE-Proton", "repo": "GloriousEggroll/proton-ge-custom", "kind": "steam",
                  "about": "Proton with extra fixes and codecs — the usual pick", "pick": lambda n: n.endswith(".tar.gz")},
    "proton-cachyos": {"name": "Proton-CachyOS", "repo": "CachyOS/proton-cachyos", "kind": "steam",
                       "about": "CachyOS' Proton, built for newer CPUs",
                       "pick": lambda n: n.endswith(f"x86_64{_x86_level()}.tar.xz")},
    "luxtorpeda": {"name": "Luxtorpeda", "repo": "luxtorpeda-dev/luxtorpeda", "kind": "steam",
                   "about": "Native Linux engines for some Windows games", "pick": lambda n: n.endswith(".tar.xz")},
    "boxtron": {"name": "Boxtron", "repo": "dreamer/boxtron", "kind": "steam",
                "about": "DOS games through DOSBox", "pick": lambda n: n.endswith(".tar.xz")},
    "wine-ge": {"name": "Wine-GE", "repo": "GloriousEggroll/wine-ge-custom", "kind": "lutris-wine",
                "about": "Wine for Lutris with GE's fixes", "pick": lambda n: n.endswith("x86_64.tar.xz") and "lutris" in n.lower()},
    "kron4ek": {"name": "Kron4ek Wine", "repo": "Kron4ek/Wine-Builds", "kind": "lutris-wine",
                "about": "Plain and staging Wine builds for Lutris",
                "pick": lambda n: n.endswith("-amd64.tar.xz") and "wow64" not in n},
    "lutris-wine": {"name": "Lutris-Wine", "repo": "lutris/wine", "kind": "lutris-wine",
                    "about": "Lutris' own Wine", "pick": lambda n: n.endswith("x86_64.tar.xz")},
    "dxvk": {"name": "DXVK", "repo": "doitsujin/dxvk", "kind": "lutris-dxvk",
             "about": "Direct3D 9–11 on Vulkan (for Lutris)", "pick": lambda n: re.fullmatch(r"dxvk-[\d.]+\.tar\.gz", n)},
    "vkd3d": {"name": "vkd3d-proton", "repo": "HansKristian-Work/vkd3d-proton", "kind": "lutris-vkd3d",
              "about": "Direct3D 12 on Vulkan (for Lutris)", "pick": lambda n: n.endswith(".tar.zst")},
}
_cat_cache = {}


def _steam_compat_dirs():
    out = []
    for root in (os.path.join(util.HOME, ".local/share/Steam"), os.path.join(util.HOME, ".var/app/com.valvesoftware.Steam/data/Steam")):
        if os.path.isdir(root):
            out.append(os.path.join(root, "compatibilitytools.d"))
    return out or [COMPAT_DIR]


def _lutris_dirs():
    return [d for d in (os.path.join(util.HOME, ".local/share/lutris"), os.path.join(util.HOME, ".var/app/net.lutris.Lutris/data/lutris"))
            if os.path.isdir(d)]


def target_dirs(kind):
    """Where a tool of this kind goes (every Steam / Lutris install found)."""
    if kind == "steam":
        return _steam_compat_dirs()
    sub = {"lutris-wine": "runners/wine", "lutris-dxvk": "runtime/dxvk", "lutris-vkd3d": "runtime/vkd3d"}[kind]
    return [os.path.join(d, sub) for d in _lutris_dirs()]


def _installed_names(kind):
    names = set()
    for d in target_dirs(kind):
        if os.path.isdir(d):
            names.update(n for n in os.listdir(d) if not n.startswith("."))
    return names


def catalogue():
    out = []
    for tid, t in CATALOGUE.items():
        dirs = target_dirs(t["kind"])
        out.append({"id": tid, "name": t["name"], "about": t["about"], "for": "Steam" if t["kind"] == "steam" else "Lutris",
                    "available": bool(dirs), "installed": len(_installed(tid))})
    return out


def _installed(tid):
    rec = (cfg().get("tools") or {}).get(tid) or {}
    have = _installed_names(CATALOGUE[tid]["kind"])
    return {tag: folder for tag, folder in rec.items() if folder in have}


def tool_releases(tid):
    t = CATALOGUE[tid]
    hit = _cat_cache.get(tid)
    if not hit or time.time() - hit[0] > 900:
        data = util.http_json(f"https://api.github.com/repos/{t['repo']}/releases?per_page=15",
                              headers={"Accept": "application/vnd.github+json"})
        rel = []
        for r in data if isinstance(data, list) else []:
            if r.get("draft"):
                continue
            asset = next((a for a in r.get("assets", []) if t["pick"](a["name"])), None)
            if asset:
                rel.append({"id": r["tag_name"], "date": (r.get("published_at") or "")[:10], "url": asset["browser_download_url"],
                            "file": asset["name"], "size": asset.get("size", 0), "pre": bool(r.get("prerelease"))})
        _cat_cache[tid] = hit = (time.time(), rel)
    have = _installed(tid)
    names = _installed_names(t["kind"])
    return [{**r, "installed": r["id"] in have or any(r["id"] in n for n in names)} for r in hit[1]]


def _safe_extract(archive, dest):
    """Unpack into dest; refuse anything that would land outside it. Returns the top folder."""
    os.makedirs(dest, exist_ok=True)
    root = os.path.realpath(dest)
    if archive.endswith(".zst"):
        if not util.which("zstd") and not util.which("unzstd"):
            raise RuntimeError("zstd is needed to unpack this one")
        lst = subprocess.run(["tar", "-I", "zstd", "-tf", archive], capture_output=True, text=True, timeout=300)
        names = [n for n in lst.stdout.splitlines() if n]
        for n in names:
            if not os.path.realpath(os.path.join(dest, n)).startswith(root + os.sep) and n.rstrip("/") not in ("", "."):
                raise RuntimeError(f"unexpected path in archive: {n}")
        r = subprocess.run(["tar", "-I", "zstd", "-xf", archive, "-C", dest, "--no-same-owner"], capture_output=True, text=True, timeout=900)
        if r.returncode:
            raise RuntimeError(r.stderr.strip()[-200:] or "unpacking failed")
    else:
        with tarfile.open(archive) as tf:
            members = tf.getmembers()
            for m in members:
                target = os.path.realpath(os.path.join(dest, m.name))
                if not target.startswith(root + os.sep) and m.name.rstrip("/") not in ("", "."):
                    raise RuntimeError(f"unexpected path in archive: {m.name}")
                if (m.issym() or m.islnk()) and os.path.isabs(m.linkname):
                    raise RuntimeError(f"unexpected link in archive: {m.name}")
            names = [m.name for m in members]
            tf.extractall(dest, filter="tar") if hasattr(tarfile, "data_filter") else tf.extractall(dest)
    tops = {n.lstrip("./").split("/")[0] for n in names if n.lstrip("./")}
    return sorted(tops)[0] if len(tops) == 1 else None


def install_tool(job, tid, tag):
    t = CATALOGUE[tid]
    rel = next((r for r in tool_releases(tid) if r["id"] == tag), None)
    if not rel:
        raise RuntimeError(f"{tag} not found")
    dirs = target_dirs(t["kind"])
    if not dirs:
        raise RuntimeError("Install Lutris first (Store › Install Apps › Flatpak, or your package manager)")
    tmp_dir = os.path.join(dirs[0], ".crossbar-download")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp = os.path.join(tmp_dir, rel["file"])
    job.cancel_with(lambda: None)                     # stops at the next chunk; the partial file is deleted
    try:
        util.download(rel["url"], tmp, on_bytes=lambda d, s: job.set_bytes(d, s or rel["size"]))
        job.cancellable = False
        job.speed, job.eta = 0.0, None
        folder = None
        for i, d in enumerate(dirs):
            job.set(0.9 + 0.09 * i / len(dirs), f"Unpacking{' for ' + ('Steam' if t['kind'] == 'steam' else 'Lutris') if len(dirs) > 1 else ''}…")
            folder = _safe_extract(tmp, d) or folder
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    if folder:
        util.update_config(lambda c: c.setdefault("compat", {}).setdefault("tools", {}).setdefault(tid, {}).__setitem__(tag, folder))
    _cat_cache.pop(tid, None)


def remove_tool(tid, tag):
    folder = _installed(tid).get(tag)
    if not folder:
        names = [n for n in _installed_names(CATALOGUE[tid]["kind"]) if tag in n]
        folder = names[0] if len(names) == 1 else None
    if not folder or "/" in folder or folder.startswith("."):
        raise RuntimeError("Only versions installed here can be removed")
    for d in target_dirs(CATALOGUE[tid]["kind"]):
        p = os.path.join(d, folder)
        if os.path.isdir(p):
            shutil.rmtree(p)
    util.update_config(lambda c: c.setdefault("compat", {}).setdefault("tools", {}).setdefault(tid, {}).pop(tag, None))


PUPGUI = "net.davidotek.pupgui2"


def protonup_qt():
    """ProtonUp-Qt itself (the desktop app), if it's installed as a Flatpak."""
    import subprocess as sp
    if not util.which("flatpak"):
        return {"installed": False}
    r = sp.run(["flatpak", "info", PUPGUI], capture_output=True, text=True)
    return {"installed": r.returncode == 0, "id": PUPGUI}
