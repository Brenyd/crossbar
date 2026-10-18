"""GOG: OAuth sign-in through a web view, library + native Linux installers via GOG's API.

Uses the same public Galaxy client credentials as Minigalaxy, Heroic and
lgogdownloader. Windows-only titles are listed but not yet installable in this
prototype (next step: innoextract + Wine/Proton).
"""
import json
import os
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
            out.append(game("gog", gid, p["title"], art, gid in installed,
                            "" if linux else "Windows only — install coming soon"))
        return sorted(out, key=lambda g: g["title"].lower())

    def installed(self):
        return [game("gog", k, v["title"], v.get("art"), True) for k, v in _read(INSTALLED_PATH, {}).items()]

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
        installers = [i for i in info.get("downloads", {}).get("installers", []) if i.get("os") == "linux"]
        if not installers:
            raise RuntimeError("No native Linux build — Windows installs aren't supported in this prototype yet")
        inst = next((i for i in installers if i.get("language") == "en"), installers[0])
        link = self._api(inst["files"][0]["downlink"])["downlink"]
        title = info.get("title", gid)
        cache = os.path.join(util.GAMES_DIR, ".cache", "gog", f"{gid}.sh")
        job.set(0, "Downloading…")
        util.download(link, cache, lambda f: job.set(f * 0.9, f"Downloading {int(f * 100)}%"))
        job.set(0.92, "Installing…")
        dest = os.path.join(util.GAMES_DIR, "gog", util.slug(title))
        tmp = tempfile.mkdtemp(dir=os.path.dirname(cache))
        try:
            # GOG Linux installers are a makeself script with a zip appended; unzip skips the stub.
            r = subprocess.run(["unzip", "-qq", "-o", cache, "-d", tmp], capture_output=True)
            src = os.path.join(tmp, "data", "noarch")
            if r.returncode > 1 or not os.path.isdir(src):
                raise RuntimeError("Couldn't unpack installer: " + r.stderr.decode()[-200:])
            shutil.rmtree(dest, ignore_errors=True)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(src, dest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            os.remove(cache)
        art = ("https:" + info["images"]["logo2x"]) if info.get("images", {}).get("logo2x") else None
        data = _read(INSTALLED_PATH, {})
        data[gid] = {"title": title, "path": dest, "art": art}
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
        util.spawn(["sh", os.path.join(entry["path"], "start.sh")], cwd=entry["path"])


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
