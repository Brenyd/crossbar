"""Store › Install Apps › Lutris: the community install scripts from lutris.net (thousands of games and
apps: GOG / store installers, your own disc images and setup files, emulated systems…), installed from
the controller.

Browsing (search, a game's installers, what each one needs) reads lutris.net's public API directly.
Installing runs Lutris's own installer engine — the same code as Lutris's install window — through
crossbar/lutris_install.py, with every question it asks (which version, where to install, your own
files, a disc, a menu choice, a runner download) asked on the TV. The finished game is in Lutris's
library, so it shows up in Game like any Lutris game.

Lutris itself: the Arch package (`lutris`) or the Flatpak (net.lutris.Lutris). Install Lutris here
asks the system helper to install the Arch package (checked first: it never pulls in graphics
drivers or a kernel).
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request

from . import util

SITE = "https://lutris.net"
FLATPAK = "net.lutris.Lutris"
HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lutris_install.py")
ADMIN = "/usr/lib/crossbar/admin.py"

SESSION = {"job": None, "proc": None, "pending": None, "game": None, "log": []}
_cache = {}
_hooks = {"publish": None}


class LutrisError(RuntimeError):
    pass


def on_event(fn):
    _hooks["publish"] = fn


def _publish(ev):
    if _hooks["publish"]:
        try:
            _hooks["publish"](ev)
        except Exception:
            pass


# ---- which Lutris -------------------------------------------------------------------------------------
def detect(refresh=False):
    """{"kind": "native" | "flatpak" | None, "version": …}"""
    if not refresh and _cache.get("detect") and time.time() - _cache["detect"][0] < 60:
        return _cache["detect"][1]
    out = {"kind": None, "version": None}
    py = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else util.which("python3")
    try:
        r = subprocess.run([py, "-c", "import lutris; print(lutris.__version__)"], capture_output=True, text=True, timeout=20)
        if r.returncode == 0 and r.stdout.strip():
            out = {"kind": "native", "version": r.stdout.strip().splitlines()[-1], "python": py}
    except (OSError, subprocess.TimeoutExpired):
        pass
    if not out["kind"] and util.which("flatpak"):
        r = subprocess.run(["flatpak", "info", FLATPAK], capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            m = re.search(r"Version:\s*(\S+)", r.stdout)
            out = {"kind": "flatpak", "version": m.group(1) if m else ""}
    _cache["detect"] = (time.time(), out)
    return out


def status():
    d = detect()
    s = SESSION
    return {**d, "installed": bool(d["kind"]), "busy": bool(s["proc"] and s["proc"].poll() is None),
            "game": s["game"], "pending": s["pending"], "job": s["job"].id if s["job"] else None}


def install_lutris(job):
    """Install the Arch package through the system helper (it refuses if pacman would pull in a
    kernel or graphics drivers)."""
    job.set(0.1, "Installing Lutris (the system asks pacman)…")
    r = subprocess.run(["pkexec", ADMIN, "install-lutris"], input="{}", capture_output=True, text=True, timeout=1800)
    try:
        res = json.loads((r.stdout.strip().splitlines() or ["{}"])[-1])
    except ValueError:
        res = {"ok": False, "error": (r.stderr or r.stdout).strip()[-300:]}
    if not res.get("ok"):
        raise LutrisError(res.get("error") or "Lutris didn't install")
    detect(refresh=True)
    job.set(1.0, "Lutris is installed")


# ---- lutris.net --------------------------------------------------------------------------------------
def _get(path, timeout=25):
    url = SITE + path
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Crossbar (Lutris installer)",
                                                                         "Accept": "application/json"}), timeout=timeout) as r:
            return json.loads(r.read().decode())
    except (OSError, ValueError) as e:
        raise util.friendly_net_error(url, e) from None


def _art(g):
    for k in ("coverart", "coverart_url", "banner_url", "icon_url"):
        v = g.get(k)
        if v:
            return v if v.startswith("http") else SITE + v
    return ""


def search(query, page=1):
    q = (query or "").strip()[:120]
    if not q:
        return []
    key = ("s", q.lower(), page)
    if _cache.get(key) and time.time() - _cache[key][0] < 600:
        return _cache[key][1]
    data = _get("/api/games?" + urllib.parse.urlencode({"search": q, "with-installers": "True", "page": int(page)}))
    out = [{"slug": g.get("slug"), "name": g.get("name") or g.get("slug"), "year": g.get("year"),
            "platforms": [p.get("name") if isinstance(p, dict) else str(p) for p in (g.get("platforms") or [])][:4], "art": _art(g)}
           for g in (data.get("results") or []) if g.get("slug")]
    _cache[key] = (time.time(), out)
    return out


def _files(script):
    """What an installer needs: [{id, label, user (you provide it), url, filename}]."""
    out = []
    for entry in script.get("files") or []:
        if not isinstance(entry, dict) or not entry:
            continue
        (fid, meta), = list(entry.items())[:1]
        url = meta.get("url", "") if isinstance(meta, dict) else str(meta)
        fname = meta.get("filename", "") if isinstance(meta, dict) else ""
        user = url.startswith("N/A")
        label = url[3:].lstrip(":").strip() if user else (fname or os.path.basename(urllib.parse.urlparse(url).path) or url)
        out.append({"id": str(fid), "label": label or str(fid), "user": user, "url": "" if user else url, "filename": fname,
                    "steam": url.startswith("$STEAM")})
    return out


def _norm_installer(i):
    script = i.get("script") or {}
    game = script.get("game") or {}
    return {"version": i.get("version"), "name": i.get("name") or i.get("game_name") or "", "slug": i.get("slug"),
            "game_slug": i.get("game_slug"), "runner": i.get("runner") or script.get("runner", ""),
            "description": _plain(i.get("description")), "notes": _plain(i.get("notes")), "user": (i.get("user") or "") if isinstance(i.get("user"), str) else "",
            "files": _files(script), "requires": script.get("requires") or script.get("extends") or "",
            "creates_folder": not (script.get("requires") or script.get("extends")) and "custom-name" not in str(game),
            "complete_text": _plain(script.get("install_complete_text")), "updated": i.get("updated_at") or "",
            "steps": len(script.get("installer") or []), "default_target": default_target(i.get("game_slug") or i.get("slug") or "game")}


def installers(slug):
    if not re.fullmatch(r"[\w\-]{1,120}", slug or ""):
        raise ValueError("game")
    data = _get("/api/installers/" + urllib.parse.quote(slug))
    return [_norm_installer(i) for i in (data.get("results") or []) if i.get("published", True) is not False and not i.get("draft")]


def _plain(text):
    import html
    t = re.sub(r"<br\s*/?>|</p>", "\n", str(text or ""), flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", t)).strip()[:4000]


def default_target(slug):
    """Lutris's own default: its game folder (Preferences › System › Default install folder) + the game."""
    base = None
    for p in (os.path.join(util.HOME, ".config", "lutris", "system.yml"),
              os.path.join(util.HOME, ".var", "app", FLATPAK, "config", "lutris", "system.yml")):
        try:
            m = re.search(r"^\s*game_path:\s*(.+)$", open(p).read(), re.M)
            if m:
                base = os.path.expanduser(m.group(1).strip().strip("'\""))
                break
        except OSError:
            continue
    return os.path.join(base or os.path.join(util.HOME, "Games"), slug)


def read_script(path):
    """An install script from a file (.yml / .yaml / .json), as Lutris's "Install from a local script"."""
    from . import media
    path = os.path.realpath(path)
    if not media.allowed(path) or not os.path.isfile(path):
        raise PermissionError("That file can't be used")
    text = open(path, errors="replace").read(512 * 1024)
    if path.lower().endswith(".json"):
        data = json.loads(text)
    else:
        try:
            import yaml
        except ImportError:
            raise LutrisError("Reading .yml scripts needs PyYAML (python-yaml): Lutris installs it") from None
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise LutrisError("That isn't a Lutris install script")
    if "script" not in data:                                  # a bare script: wrap it like lutris.net does
        data = {"name": data.get("name") or os.path.splitext(os.path.basename(path))[0], "game_slug": data.get("game_slug") or
                re.sub(r"[^a-z0-9]+", "-", (data.get("name") or os.path.basename(path)).lower()).strip("-") or "game",
                "version": data.get("version") or "Script file", "slug": data.get("slug") or "local", "runner": data.get("runner"),
                "script": data.get("script") or data}
    data.setdefault("game_slug", data.get("slug") or "game")
    data.setdefault("version", "Script file")
    data.setdefault("slug", "local-" + data["game_slug"])
    data.setdefault("name", data["game_slug"])
    return data


def script_info(path):
    return _norm_installer(read_script(path))


# ---- installing ---------------------------------------------------------------------------------------
def install(job, slug=None, version=None, target=None, files=None, script_path=None):
    d = detect(refresh=True)
    if not d["kind"]:
        raise LutrisError("Lutris isn't installed: Install Apps › Lutris › Install Lutris")
    if SESSION["proc"] and SESSION["proc"].poll() is None:
        raise LutrisError("Another Lutris install is running: wait for it to finish (or cancel it in Downloads)")
    files = {str(k): os.path.realpath(v) for k, v in (files or {}).items() if v}
    from . import media
    for p in files.values():
        if not media.allowed(p) or not os.path.exists(p):
            raise PermissionError(f"Can't use {p}")
    req = {"files": files}
    if script_path:
        info = read_script(script_path)                       # checks it's readable and allowed
        req.update(script_file=os.path.realpath(script_path), version=info.get("version"))
        slug = info.get("game_slug")
    else:
        req.update(slug=slug, version=version)
    if target:
        target = os.path.realpath(os.path.expanduser(target))
        if not media.allowed(os.path.dirname(target)):
            raise PermissionError("That install folder isn't allowed")
        req["target"] = target
    if d["kind"] == "native":
        argv = [d["python"], HELPER, json.dumps(req)]
    else:
        # the helper is copied where the Flatpak can read it, and the picked files / folder are shared with it
        inside = os.path.join(util.HOME, ".var", "app", FLATPAK, "cache", "crossbar_lutris_install.py")
        os.makedirs(os.path.dirname(inside), exist_ok=True)
        shutil.copyfile(HELPER, inside)
        share = sorted({os.path.dirname(p) for p in files.values()} | ({os.path.dirname(target)} if target else set())
                       | ({os.path.dirname(req["script_file"])} if req.get("script_file") else set()))
        argv = ["flatpak", "run", *[f"--filesystem={p}" for p in share], "--command=python3", FLATPAK, inside, json.dumps(req)]
    SESSION.update(job=job, pending=None, game=slug, log=[])
    p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
                         start_new_session=True, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    SESSION["proc"] = p

    def kill():
        try:
            os.killpg(p.pid, 15)
        except OSError:
            pass
    job.cancel_with(kill)
    err_tail = []
    threading.Thread(target=lambda: [err_tail.append(ln) or err_tail.__delitem__(slice(0, -40)) for ln in p.stderr], daemon=True).start()
    result = {"error": None, "finished": None}
    job.set(0.02, "Starting Lutris's installer…")
    for line in p.stdout:
        try:
            ev = json.loads(line)
        except ValueError:
            SESSION["log"] = (SESSION["log"] + [line.rstrip()])[-60:]
            continue
        kind = ev.get("event")
        if kind == "started":
            SESSION["game"] = ev.get("game") or SESSION["game"]
            job.title = f"{SESSION['game']} (Lutris)"
            job.set(0.05, f"Installing to {ev.get('target') or 'its folder'} · {ev.get('runner') or ''}".strip(" ·"))
        elif kind == "status":
            job.set(None, ev.get("text", ""))
        elif kind == "progress":
            if ev.get("total"):
                job.set_bytes(ev.get("done", 0), ev["total"], ev.get("text", ""))
            else:
                job.set(ev.get("fraction") if ev.get("fraction") is not None else None, ev.get("text") or None)
        elif kind == "log":
            SESSION["log"] = (SESSION["log"] + [ev.get("line", "")])[-60:]
        elif kind and kind.startswith("ask_"):
            SESSION["pending"] = {**ev, "id": int(time.time() * 1000), "game": SESSION["game"]}
            job.set(None, "Waiting for you: answer on the screen")
            _publish({"type": "lutris-ask", **SESSION["pending"]})
        elif kind == "error":
            result["error"] = ev
        elif kind == "finished":
            result["finished"] = ev
    p.wait()
    SESSION.update(proc=None, pending=None)
    if job.cancelled():
        return
    if result["finished"]:
        job.set(1.0, result["finished"].get("text") or "Installed")
        job.result = {"game": SESSION["game"], "text": result["finished"].get("text"), "game_id": result["finished"].get("game_id")}
        _publish({"type": "art"})                               # the Game column picks it up
        _publish({"type": "notice", "text": f"Installed: {SESSION['game']} — it's in Game", "icon": "download"})
        return
    e = result["error"] or {"text": ("".join(err_tail[-3:]).strip() or f"Lutris's installer stopped (exit {p.returncode})")[-300:]}
    if e.get("kind") == "MissingGameDependencyError" and e.get("slug"):
        raise LutrisError(f"Install {e['slug']} first (this one adds to it): search for it in Lutris")
    raise LutrisError(e.get("text") or "The install failed")


def answer(data):
    """The person's answer to the question the installer is waiting on."""
    p, pend = SESSION.get("proc"), SESSION.get("pending")
    if not p or p.poll() is not None or not pend:
        raise LutrisError("Nothing is waiting for an answer")
    if data.get("id") and data["id"] != pend["id"]:
        raise LutrisError("That question has already been answered")
    out = {}
    if pend["event"] == "ask_menu":
        keys = [k for k, _ in pend.get("options") or []]
        out["answer"] = data.get("answer") if data.get("answer") in keys else (pend.get("preselect") or (keys[0] if keys else ""))
    elif pend["event"] == "ask_yesno":
        out["answer"] = bool(data.get("answer"))
    elif pend["event"] in ("ask_disc", "ask_file"):
        path = data.get("path")
        if path:
            from . import media
            path = os.path.realpath(path)
            if not media.allowed(path):
                raise PermissionError("That place isn't allowed")
        out["path"] = path
    SESSION["pending"] = None
    p.stdin.write(json.dumps(out) + "\n")
    p.stdin.flush()
    return {"ok": True}
