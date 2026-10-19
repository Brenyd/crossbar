"""Apps: Flatpaks and AppImages in the XMB, and installing them.

  * Installed Flatpaks (yours and the system's) and AppImages in ~/Applications show up in the
    Apps category (or whichever category you put each one in).
  * Store › Install Apps › Flatpak browses Flathub (popular, new, categories, search) and installs
    for your user (no password). Store › Install Apps › AppImage moves an AppImage you pick into
    ~/Applications, makes it runnable and reads its name and icon.
Keys: "flatpak:<app id>" and "appimage:<file name>"; the category for each lives in the config
("app_category"), so moving an app to Game, TV & Video etc. is one setting.
"""
import glob
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from . import util

APPIMAGE_DIR = os.path.join(util.HOME, "Applications")
CACHE = os.path.join(util.HOME, ".cache", "crossbar", "appimages")
FLATHUB_API = "https://flathub.org/api/v2"
FLATHUB_REPO = "https://dl.flathub.org/repo/flathub.flatpakrepo"
CATEGORIES = ("apps", "game", "tv", "video", "music", "photo", "party")      # XMB categories an app can live in
FLATHUB_CATEGORIES = {
    "audiovideo": "Audio & Video", "development": "Developer Tools", "education": "Education", "game": "Games",
    "graphics": "Graphics & Photography", "network": "Networking", "office": "Productivity", "science": "Science",
    "system": "System", "utility": "Utilities",
}
ICON_DIRS = [os.path.join(util.HOME, ".local/share/flatpak/exports/share/icons/hicolor"),
             "/var/lib/flatpak/exports/share/icons/hicolor"]
_cache = {}


# ---- where each app shows up --------------------------------------------------------------------
def categories():
    return util.load_config().get("app_category") or {}


def set_category(key, cat):
    if cat not in CATEGORIES:
        raise ValueError("category")
    util.update_config(lambda c: c.setdefault("app_category", {}).__setitem__(key, cat))
    return {"key": key, "category": cat}


# ---- installed apps -----------------------------------------------------------------------------
_fp_cache = [0.0, None]


def forget():
    """Something was installed or removed: list again next time."""
    _fp_cache[0] = 0.0


def _flatpaks():
    if _fp_cache[1] is not None and time.time() - _fp_cache[0] < 8:
        return _fp_cache[1]
    _fp_cache[:] = [time.time(), _flatpaks_now()]
    return _fp_cache[1]


def _flatpaks_now():
    if not util.which("flatpak"):
        return []
    try:
        out = subprocess.run(["flatpak", "list", "--app", "--columns=application,name,installation"],
                             capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    apps = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and re.match(r"^[\w.-]+$", parts[0]):
            apps.append({"key": f"flatpak:{parts[0]}", "id": parts[0], "name": parts[1] or parts[0], "kind": "flatpak",
                         "user": (parts[2] if len(parts) > 2 else "user") == "user"})
    return apps


def icon_path(app_id):
    """The icon Flatpak exported for an installed app (largest PNG, else the SVG)."""
    if not re.match(r"^[\w.-]+$", app_id or ""):
        return None
    for base in ICON_DIRS:
        for size in ("512x512", "256x256", "128x128", "scalable", "64x64"):
            for ext in ("png", "svg"):
                p = os.path.join(base, size, "apps", f"{app_id}.{ext}")
                if os.path.isfile(p):
                    return p
    return None


def _appimage_meta(path):
    """Name and icon from inside an AppImage (cached by size+mtime)."""
    st = os.stat(path)
    h = hashlib.sha1(f"{path}:{st.st_size}:{st.st_mtime}".encode()).hexdigest()[:16]
    d = os.path.join(CACHE, h)
    meta_file = os.path.join(d, "meta.json")
    try:
        with open(meta_file) as f:
            return json.load(f)
    except (OSError, ValueError):
        pass
    meta = {"name": _nice(os.path.basename(path)), "icon": None}
    os.makedirs(d, exist_ok=True)
    work = tempfile.mkdtemp(dir=d)
    try:
        for pattern in ("*.desktop", ".DirIcon"):
            subprocess.run([path, "--appimage-extract", pattern], cwd=work, capture_output=True, timeout=40,
                           env={**os.environ, "APPIMAGE_EXTRACT_AND_RUN": "1"})
        root = os.path.join(work, "squashfs-root")
        for desk in glob.glob(os.path.join(root, "*.desktop")):
            for line in open(desk, errors="replace"):
                if line.startswith("Name=") and line[5:].strip():
                    meta["name"] = line[5:].strip()[:60]
                    break
            break
        icon = os.path.join(root, ".DirIcon")
        if os.path.islink(icon):
            icon = os.path.join(root, os.readlink(icon).lstrip("/"))
        if os.path.isfile(icon) and os.path.realpath(icon).startswith(os.path.realpath(root)):
            with open(icon, "rb") as f:
                head = f.read(8)
            ext = ".png" if head.startswith(b"\x89PNG") else ".svg"
            shutil.copy(icon, os.path.join(d, "icon" + ext))
            meta["icon"] = os.path.join(d, "icon" + ext)
    except (OSError, subprocess.TimeoutExpired):
        pass
    finally:
        shutil.rmtree(work, ignore_errors=True)
    with open(meta_file, "w") as f:
        json.dump(meta, f)
    return meta


def _nice(fname):
    n = re.sub(r"\.appimage$", "", fname, flags=re.I)
    n = re.sub(r"[-_.](x86[-_]64|amd64|aarch64|arm64|linux|x64)\b.*$", "", n, flags=re.I)
    n = re.sub(r"[-_]v?\d+(\.\d+)+.*$", "", n)
    return n.replace("_", " ").replace("-", " ").strip() or fname


def _appimages():
    out = []
    if not os.path.isdir(APPIMAGE_DIR):
        return out
    for n in sorted(os.listdir(APPIMAGE_DIR)):
        p = os.path.join(APPIMAGE_DIR, n)
        if n.lower().endswith(".appimage") and os.path.isfile(p):
            meta = _appimage_meta(p)
            out.append({"key": f"appimage:{n}", "id": n, "name": meta["name"], "kind": "appimage", "user": True,
                        "icon_file": meta.get("icon")})
    return out


def installed():
    cats = categories()
    hidden = {e for e in _emulator_ids()}           # emulators already live in Game › Emulation
    out = []
    for a in _flatpaks() + _appimages():
        if a["kind"] == "flatpak" and a["id"] in hidden and a["key"] not in cats:
            continue
        a["category"] = cats.get(a["key"], "apps")
        a["icon"] = f"/api/apps/icon?key={urllib.parse.quote(a['key'])}"
        a.pop("icon_file", None)
        out.append(a)
    out.sort(key=lambda a: a["name"].lower())
    from . import artwork
    return artwork.apply(out, key_of=lambda a: f"app:{a['key']}", fill=False)   # only art you picked


def _emulator_ids():
    try:
        from .emulation import EMULATORS
        return [e["id"] for e in EMULATORS.values() if e.get("kind") == "flatpak"]
    except Exception:
        return []


def icon_file(key):
    if key.startswith("flatpak:"):
        return icon_path(key[8:])
    if key.startswith("appimage:"):
        name = os.path.basename(key[9:])
        p = os.path.join(APPIMAGE_DIR, name)
        if os.path.isfile(p):
            return _appimage_meta(p).get("icon")
    return None


def argv(key):
    if key.startswith("flatpak:") and re.match(r"^[\w.-]+$", key[8:]):
        return ["flatpak", "run", key[8:]], {}
    if key.startswith("appimage:"):
        p = os.path.join(APPIMAGE_DIR, os.path.basename(key[9:]))
        if not os.path.isfile(p):
            raise RuntimeError("That AppImage isn't in ~/Applications any more")
        os.chmod(p, os.stat(p).st_mode | 0o755)
        # works without FUSE too (unpacks to a temp folder instead of mounting)
        env = {} if shutil.which("fusermount") or shutil.which("fusermount3") else {"APPIMAGE_EXTRACT_AND_RUN": "1"}
        return [p], env
    raise ValueError("Not an app")


def uninstall(job, key):
    if key.startswith("flatpak:"):
        app = next((a for a in _flatpaks() if a["key"] == key), None)
        if not app:
            raise RuntimeError("Not installed")
        if not app["user"]:
            raise RuntimeError("Installed for every user: remove it from the desktop's software centre")
        job.set(0.3, "Removing…")
        forget()
        r = subprocess.run(["flatpak", "uninstall", "--user", "-y", "--noninteractive", key[8:]],
                           capture_output=True, text=True, timeout=600)
        forget()
        if r.returncode:
            raise RuntimeError((r.stderr or r.stdout).strip()[-200:] or "flatpak uninstall failed")
    elif key.startswith("appimage:"):
        p = os.path.join(APPIMAGE_DIR, os.path.basename(key[9:]))
        if os.path.isfile(p):
            os.remove(p)
    util.update_config(lambda c: (c.setdefault("app_category", {}).pop(key, None)))


# ---- AppImage install ------------------------------------------------------------------------------
def install_appimage(path, category="apps"):
    """Move an AppImage into ~/Applications, make it runnable, put it in a category."""
    path = os.path.realpath(os.path.expanduser(path))
    if not os.path.isfile(path) or not path.lower().endswith(".appimage"):
        raise ValueError("Pick a .AppImage file")
    with open(path, "rb") as f:
        head = f.read(16)
    if not head.startswith(b"\x7fELF"):
        raise ValueError("That file isn't an AppImage (not a Linux program)")
    os.makedirs(APPIMAGE_DIR, exist_ok=True)
    dest = os.path.join(APPIMAGE_DIR, os.path.basename(path))
    if os.path.realpath(dest) != path:
        if os.path.exists(dest):
            os.remove(dest)                          # a newer copy of the same file replaces it
        shutil.move(path, dest)
    os.chmod(dest, os.stat(dest).st_mode | 0o755)
    key = f"appimage:{os.path.basename(dest)}"
    set_category(key, category)
    meta = _appimage_meta(dest)
    return {"key": key, "name": meta["name"], "category": category, "path": dest}


# ---- Flathub ------------------------------------------------------------------------------------------
def _get(url, data=None, ttl=600):
    key = (url, json.dumps(data, sort_keys=True) if data is not None else None)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    body = key[1].encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": "Crossbar/0.14", "Accept": "application/json",
                                                         **({"Content-Type": "application/json"} if body else {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            out = json.loads(r.read().decode())
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise util.friendly_net_error(url, e) from None
    _cache[key] = (time.time(), out)
    return out


def _hits(res):
    hits = (res.get("hits") or res.get("results") or []) if isinstance(res, dict) else res
    out = []
    for h in hits or []:
        if not isinstance(h, dict):
            continue
        aid = h.get("app_id") or h.get("id") or h.get("flatpakAppId")
        if not aid or not re.match(r"^[\w.-]+$", str(aid)):
            continue
        icon = h.get("icon") or h.get("iconDesktopUrl") or h.get("iconMobileUrl")
        if icon and icon.startswith("/"):
            icon = "https://dl.flathub.org" + icon
        out.append({"id": aid, "name": h.get("name") or aid, "summary": h.get("summary") or "",
                    "icon": icon if icon and icon.startswith("https://") else None,
                    "developer": h.get("developer_name") or "", "installs": h.get("installs_last_month") or 0,
                    "verified": bool(h.get("verification_verified") or h.get("verified"))})
    return out


def _page(res, page):
    total = (res.get("totalHits") or res.get("total") or res.get("estimatedTotalHits")) if isinstance(res, dict) else None
    pages = res.get("totalPages") if isinstance(res, dict) else None
    return {"apps": _hits(res), "page": page, "pages": pages or (max(1, -(-int(total) // 30)) if total else page)}


def flathub_collection(kind, page=1):
    if kind not in ("popular", "trending", "recently-added", "recently-updated", "verified"):
        raise ValueError("collection")
    return _page(_get(f"{FLATHUB_API}/collection/{kind}?page={int(page)}&per_page=30"), int(page))


def flathub_categories():
    try:
        names = _get(f"{FLATHUB_API}/collection/category", ttl=86400)
    except Exception:
        names = list(FLATHUB_CATEGORIES)
    out = []
    for n in names if isinstance(names, list) else FLATHUB_CATEGORIES:
        key = str(n)
        out.append({"id": key, "name": FLATHUB_CATEGORIES.get(key.lower(), key.replace("-", " ").title())})
    return out


def flathub_category(cat, page=1):
    if not re.match(r"^[\w-]+$", cat or ""):
        raise ValueError("category")
    return _page(_get(f"{FLATHUB_API}/collection/category/{cat}?page={int(page)}&per_page=30"), int(page))


def flathub_search(q):
    q = (q or "").strip()[:80]
    if not q:
        return {"apps": [], "page": 1, "pages": 1}
    return _page(_get(f"{FLATHUB_API}/search", data={"query": q, "filters": []}, ttl=300), 1)


def _num(v):
    try:
        return int(str(v).split("x")[0])
    except (TypeError, ValueError):
        return 0


def _best_shot(s):
    """The biggest picture of one screenshot. Flathub has served `sizes` both as
    {"1248x702": url} and as [{"width": "1248", "height": "702", "src": url}]."""
    if not isinstance(s, dict):
        return None
    sizes = s.get("sizes")
    cands = []
    if isinstance(sizes, dict):
        cands = [(_num(k), v) for k, v in sizes.items()]
    elif isinstance(sizes, list):
        cands = [(_num(x.get("width")), x.get("src") or x.get("url")) for x in sizes if isinstance(x, dict)]
    if not cands and s.get("src"):
        cands = [(0, s["src"])]
    cands = [(w, u) for w, u in cands if str(u or "").startswith("https://")]
    return max(cands, key=lambda c: c[0])[1] if cands else None


def flathub_app(app_id):
    if not re.match(r"^[\w.-]+$", app_id or ""):
        raise ValueError("app")
    a = _get(f"{FLATHUB_API}/appstream/{app_id}", ttl=3600)
    desc = re.sub(r"<li>", "• ", a.get("description") or "")
    desc = re.sub(r"</(p|li)>", "\n", desc)
    desc = re.sub(r"<[^>]+>", "", desc)
    desc = re.sub(r"\n{3,}", "\n\n", desc).strip()
    shots = []
    for s in a.get("screenshots") or []:
        url = _best_shot(s)
        if url:
            shots.append(url)
    installed_ids = {x["id"] for x in _flatpaks()}
    return {"id": app_id, "name": a.get("name") or app_id, "summary": a.get("summary") or "",
            "description": desc[:2500], "developer": a.get("developer_name") or "",
            "icon": a.get("icon") if str(a.get("icon") or "").startswith("https://") else None,
            "screenshots": shots[:6], "installed": app_id in installed_ids}


def install_flatpak(job, app_id, category="apps"):
    if not re.match(r"^[\w.-]+$", app_id or ""):
        raise ValueError("app")
    if not util.which("flatpak"):
        raise RuntimeError("Flatpak isn't installed (Settings › System › Update Crossbar installs it)")
    set_category(f"flatpak:{app_id}", category)
    job.set(0.03, "Adding Flathub…")
    subprocess.run(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB_REPO],
                   capture_output=True, text=True, timeout=120)
    job.set(0.06, "Starting the download…")
    p = subprocess.Popen(["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", app_id],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True)

    def stop():                                  # flatpak cleans up its own partial download
        try:
            os.killpg(p.pid, signal.SIGINT)
            p.wait(timeout=10)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    job.cancel_with(stop)
    tail = []
    buf = ""
    while True:
        ch = p.stdout.read(1)
        if not ch:
            break
        if ch in "\r\n":                         # flatpak redraws its progress line with \r
            line, buf = buf.strip(), ""
            if not line:
                continue
            tail = (tail + [line])[-4:]
            m = re.search(r"(\d{1,3})%", line)
            step = re.search(r"Installing (\d+)/(\d+)", line)
            if m:
                pct = int(m.group(1)) / 100
                if step:
                    i, n = int(step.group(1)), int(step.group(2))
                    pct = ((i - 1) + pct) / max(1, n)
                speed = re.search(r"([\d.]+\s*[kMG]?B/s)", line)
                left = re.search(r"\b(\d+:\d{2}(?::\d{2})?)\b", line)
                job.set(0.06 + 0.92 * pct, " · ".join(x for x in (f"{int(pct * 100)}%", speed and speed.group(1),
                                                                   left and f"{left.group(1)} left") if x))
        else:
            buf += ch
    forget()
    if p.wait():
        if job.cancelled():
            return
        raise RuntimeError(next((x for x in reversed(tail) if "error" in x.lower()), tail[-1] if tail else "flatpak install failed"))
