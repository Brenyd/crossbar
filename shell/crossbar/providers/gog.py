"""GOG: OAuth sign-in through a web view, library + native Linux installers via GOG's API.

Uses the same public Galaxy client credentials as Minigalaxy, Heroic and
lgogdownloader. Windows-only titles are listed but not yet installable in this
prototype (next step: innoextract + Wine/Proton).
"""
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse

from .. import util
from .base import Provider, game

CLIENT_ID = "46899977096215655"
CLIENT_SECRET = "9d85c43b1482497dbbce61f6e4aa173a433796eeae2ca8c5f6129f2dc4de46d9"
REDIRECT = "https://embed.gog.com/on_login_success?origin=client"
LOGIN_URL = ("https://auth.gog.com/auth?client_id={}&redirect_uri={}&response_type=code&layout=client2"
             .format(CLIENT_ID, urllib.parse.quote(REDIRECT, safe="")))
TOKEN_URL = "https://auth.gog.com/token"
TOKEN_PATH = os.path.join(util.CONFIG_DIR, "gog_token.json")
INSTALLED_PATH = os.path.join(util.CONFIG_DIR, "gog_installed.json")


def _read(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(path, 0o600)


class GOG(Provider):
    id = "gog"
    name = "GOG"

    def __init__(self):
        self._cache = (0, [])

    def _token(self):
        tok = _read(TOKEN_PATH, None)
        if not tok:
            return None
        if time.time() > tok.get("obtained", 0) + tok.get("expires_in", 3600) - 60:
            new = util.http_json(TOKEN_URL + "?" + urllib.parse.urlencode({
                "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                "grant_type": "refresh_token", "refresh_token": tok["refresh_token"]}))
            new["obtained"] = time.time()
            _write(TOKEN_PATH, new)
            tok = new
        return tok["access_token"]

    def _api(self, url):
        return util.http_json(url, headers={"Authorization": "Bearer " + self._token()})

    def status(self):
        tok = _read(TOKEN_PATH, None)
        return {"linked": bool(tok), "account": tok.get("user_id", "") if tok else "",
                "ready": True, "note": ""}

    def library(self):
        installed = _read(INSTALLED_PATH, {})
        if not _read(TOKEN_PATH, None):
            return [game("gog", k, v["title"], v.get("art"), True) for k, v in installed.items()]
        if time.time() - self._cache[0] > 600:
            products, page, pages = [], 1, 1
            while page <= pages:
                data = self._api(f"https://embed.gog.com/account/getFilteredProducts?mediaType=1&page={page}")
                pages = data.get("totalPages", 1)
                products += data.get("products", [])
                page += 1
            self._cache = (time.time(), products)
        out = []
        for p in self._cache[1]:
            gid = str(p["id"])
            art = ("https:" + p["image"] + "_392.jpg") if p.get("image") else None
            linux = p.get("worksOn", {}).get("Linux")
            g = game("gog", gid, p["title"], art, gid in installed, "" if linux else "Windows version · runs with Proton")
            g["windows"] = (installed.get(gid, {}).get("platform") == "windows") if gid in installed else not linux
            out.append(g)
        return sorted(out, key=lambda g: g["title"].lower())

    def installed(self):
        out = []
        for k, v in _read(INSTALLED_PATH, {}).items():
            g = game("gog", k, v["title"], v.get("art"), True)
            g["windows"] = v.get("platform") == "windows"
            out.append(g)
        return out

    def login(self, job, fields):
        job.set(0.1, "Opening GOG sign-in…")
        code = fields.get("code") or run_login_helper(LOGIN_URL, "on_login_success", "code")
        tok = util.http_json(TOKEN_URL + "?" + urllib.parse.urlencode({
            "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "authorization_code",
            "code": code, "redirect_uri": REDIRECT}))
        tok["obtained"] = time.time()
        _write(TOKEN_PATH, tok)
        self._cache = (0, [])

    def logout(self):
        try:
            os.remove(TOKEN_PATH)
        except OSError:
            pass
        self._cache = (0, [])

    def install(self, job, gid):
        info = self._api(f"https://api.gog.com/products/{gid}?expand=downloads")
        title = info.get("title", gid)
        installers = info.get("downloads", {}).get("installers", [])
        pick = lambda os_: next((i for i in installers if i.get("os") == os_ and i.get("language") == "en"),  # noqa: E731
                                next((i for i in installers if i.get("os") == os_), None))
        inst = pick("linux") or pick("windows")
        if not inst:
            raise RuntimeError("GOG has no installer for this game")
        platform = inst["os"]
        cache = os.path.join(util.GAMES_DIR, ".cache", "gog", gid)
        shutil.rmtree(cache, ignore_errors=True)
        os.makedirs(cache, exist_ok=True)
        dest = os.path.join(util.GAMES_DIR, "gog", util.slug(title))
        try:
            # download every part (Windows installers are often setup.exe + .bin files)
            files = inst.get("files", [])
            total = sum(f.get("size", 0) for f in files) or 1
            done, paths = 0, []
            for f in files:
                link = self._api(f["downlink"])["downlink"]
                name = os.path.basename(urllib.parse.urlparse(link).path) or f"part{len(paths)}"
                path = os.path.join(cache, name)
                size = f.get("size", 0)
                util.download(link, path, lambda x, d=done, sz=size: job.set(
                    0.85 * (d + x * sz) / total, f"Downloading {int(100 * (d + x * sz) / total)}%"))
                done += size
                paths.append(path)
            job.set(0.88, "Installing…")
            tmp = tempfile.mkdtemp(dir=cache)
            if platform == "linux":
                # makeself script with a zip appended; unzip skips the stub
                r = subprocess.run(["unzip", "-qq", "-o", paths[0], "-d", tmp], capture_output=True)
                src = os.path.join(tmp, "data", "noarch")
                if r.returncode > 1 or not os.path.isdir(src):
                    raise RuntimeError("Couldn't unpack installer: " + r.stderr.decode()[-200:])
            else:
                if not util.which("innoextract"):
                    raise RuntimeError("innoextract is needed to install Windows games")
                exe = next((p for p in paths if p.lower().endswith(".exe")), paths[0])
                r = subprocess.run(["innoextract", "--gog", "-s", "-m", "-d", tmp, exe], capture_output=True, text=True)
                if r.returncode:
                    raise RuntimeError("Couldn't unpack installer: " + (r.stderr or r.stdout).strip()[-200:])
                src = os.path.join(tmp, "app") if os.path.isdir(os.path.join(tmp, "app")) else tmp
            shutil.rmtree(dest, ignore_errors=True)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(src, dest)
        finally:
            shutil.rmtree(cache, ignore_errors=True)
        entry = {"title": title, "path": dest, "platform": platform,
                 "art": ("https:" + info["images"]["logo2x"]) if info.get("images", {}).get("logo2x") else None}
        if platform == "windows":
            entry.update(play_task(dest, gid))
        data = _read(INSTALLED_PATH, {})
        data[gid] = entry
        _write(INSTALLED_PATH, data)

    def uninstall(self, job, gid):
        data = _read(INSTALLED_PATH, {})
        entry = data.pop(gid, None)
        if entry:
            shutil.rmtree(entry["path"], ignore_errors=True)
        _write(INSTALLED_PATH, data)

    def launch(self, gid):
        entry = _read(INSTALLED_PATH, {}).get(gid)
        if not entry:
            raise RuntimeError("Not installed")
        if entry.get("platform") != "windows":
            util.spawn(["sh", os.path.join(entry["path"], "start.sh")], cwd=entry["path"])
            return
        from .. import compat
        exe = os.path.join(entry["path"], entry["exe"])
        if not os.path.isfile(exe):
            raise RuntimeError(f"Game file missing: {entry['exe']}")
        argv, env = compat.command(exe, entry.get("args", []), f"gog:{gid}", "gog", gid)
        cwd = os.path.join(entry["path"], entry.get("cwd") or os.path.dirname(entry["exe"]))
        util.spawn(argv, cwd=cwd if os.path.isdir(cwd) else entry["path"], env=env)


def _split(args):
    try:
        return shlex.split(args)
    except ValueError:
        return args.split()


def play_task(root, gid):
    """What to run, from GOG's goggame-<id>.info (the same data GOG Galaxy uses)."""
    infos = glob.glob(os.path.join(root, f"goggame-{gid}.info")) + glob.glob(os.path.join(root, "goggame-*.info")) \
        + glob.glob(os.path.join(root, "*", "goggame-*.info"))
    for path in dict.fromkeys(infos):
        try:
            data = json.load(open(path, encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        tasks = [t for t in data.get("playTasks", []) if t.get("type") == "FileTask" and t.get("category", "game") == "game"]
        task = next((t for t in tasks if t.get("isPrimary")), tasks[0] if tasks else None)
        if task:
            base = os.path.relpath(os.path.dirname(path), root)
            norm = lambda p: os.path.normpath(os.path.join(base, (p or "").replace("\\", "/")))  # noqa: E731
            return {"exe": norm(task["path"]), "cwd": norm(task.get("workingDir") or os.path.dirname(task["path"].replace("\\", "/"))),
                    "args": _split(task.get("arguments") or "")}
    # no info file: the biggest .exe that isn't an installer/uninstaller
    exes = [p for p in glob.glob(os.path.join(root, "**", "*.exe"), recursive=True)
            if not re.search(r"unins|setup|redist|vcredist|directx|dotnet|crash", os.path.basename(p), re.I)]
    if not exes:
        raise RuntimeError("Installed, but couldn't find the game's .exe")
    exe = max(exes, key=os.path.getsize)
    return {"exe": os.path.relpath(exe, root), "cwd": os.path.relpath(os.path.dirname(exe), root), "args": []}


def run_login_helper(url, match, param=None, json_key=None):
    """Open a web view at url and return a value captured when the URL contains `match`."""
    helper = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "login_helper.py")
    args = [sys.executable, helper, url, match]
    args += ["--param", param] if param else ["--json-key", json_key]
    r = subprocess.run(args, capture_output=True, text=True, timeout=900)
    code = r.stdout.strip()
    if r.returncode or not code:
        raise RuntimeError("Sign-in cancelled" if r.returncode == 2 else (r.stderr.strip()[-200:] or "Sign-in failed"))
    return code
