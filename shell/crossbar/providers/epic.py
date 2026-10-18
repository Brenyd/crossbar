"""Epic Games Store, driven through the open-source `legendary` CLI.

Sign-in captures Epic's authorization code in a web view and hands it to
`legendary auth --code`. Installs run `legendary install` and parse its progress.
Games run through Wine (configure Proton later in ~/.config/legendary/config.ini).
"""
import json
import os
import re
import subprocess
import time

from .. import util
from .base import Provider, game
from .gog import run_login_helper

LOGIN_URL = "https://legendary.gl/epiclogin"
PROGRESS = re.compile(r"Progress: ([\d.]+)%.*?ETA: ([\d:]+)")


def _art(meta):
    imgs = {i.get("type"): i.get("url") for i in (meta or {}).get("keyImages", [])}
    return imgs.get("DieselGameBox") or imgs.get("OfferImageWide") or imgs.get("DieselGameBoxTall")


class Epic(Provider):
    id = "epic"
    name = "Epic Games"

    def __init__(self):
        self._cache = (0, [])

    def _run(self, *args, timeout=300):
        r = subprocess.run(["legendary", *args], capture_output=True, text=True, timeout=timeout)
        if r.returncode:
            raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "legendary failed")
        return r.stdout

    def status(self):
        if not util.which("legendary"):
            return {"linked": False, "account": "", "ready": False, "note": "legendary is not installed"}
        try:
            st = json.loads(self._run("status", "--json", "--offline", timeout=30))
        except Exception:
            return {"linked": False, "account": "", "ready": True, "note": ""}
        acct = st.get("account") or ""
        linked = bool(acct) and "not logged in" not in acct
        return {"linked": linked, "account": acct if linked else "", "ready": True, "note": ""}

    def _installed_map(self):
        if not util.which("legendary"):
            return {}
        try:
            return {g["app_name"]: g for g in json.loads(self._run("list-installed", "--json", timeout=60))}
        except Exception:
            return {}

    def library(self):
        installed = self._installed_map()
        if time.time() - self._cache[0] > 600:
            self._cache = (time.time(), json.loads(self._run("list", "--json")))
        out = [dict(game("epic", g["app_name"], g.get("app_title", g["app_name"]), _art(g.get("metadata")),
                         g["app_name"] in installed), windows=True) for g in self._cache[1]]
        return sorted(out, key=lambda g: g["title"].lower())

    def installed(self):
        return [dict(game("epic", k, v.get("title", k), None, True), windows=True) for k, v in self._installed_map().items()]

    def login(self, job, fields):
        job.set(0.1, "Opening Epic sign-in…")
        code = fields.get("code") or run_login_helper(LOGIN_URL, "/id/api/redirect", json_key="authorizationCode")
        job.set(0.6, "Linking legendary…")
        self._run("auth", "--code", code, timeout=120)
        self._cache = (0, [])

    def logout(self):
        self._run("auth", "--delete", timeout=60)
        self._cache = (0, [])

    def install(self, job, app):
        base = os.path.join(util.GAMES_DIR, "epic")
        os.makedirs(base, exist_ok=True)
        p = subprocess.Popen(["legendary", "-y", "install", app, "--base-path", base],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        tail = []
        for line in p.stdout:
            tail = (tail + [line.strip()])[-5:]
            m = PROGRESS.search(line)
            if m:
                job.set(float(m.group(1)) / 100, f"{m.group(1)}% · ETA {m.group(2)}")
        if p.wait():
            raise RuntimeError(tail[-1] if tail else "legendary install failed")
        self._cache = (0, [])

    def uninstall(self, job, app):
        self._run("-y", "uninstall", app, timeout=600)

    def launch(self, app):
        """Run through the chosen Proton (umu) or Wine, picked in Game Settings."""
        from .. import compat
        try:
            tool, env = compat.env_for(f"epic:{app}", "egs", app)
        except RuntimeError:
            tool, env = None, {}
        title = (self._installed_map().get(app) or {}).get("title", app)
        base = ["legendary", "launch", app, "--skip-version-check"]
        if tool == "wine":
            util.spawn_checked(base + ["--wine", "wine", "--wine-prefix", env["WINEPREFIX"]], what=title)
        elif tool:
            util.spawn_checked(base + ["--no-wine", "--wrapper", "umu-run"], env=env, what=title)
        else:
            util.spawn_checked(base, what=title)
