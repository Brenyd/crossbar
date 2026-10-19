"""Theme packs: colours, wave background, background image, font, icons, sounds, keyboard and
Quick Menu colours, in one folder. See docs/THEMES.md for how to make one.

Where themes live:
  <crossbar>/themes/<id>/                 stock themes (come with Crossbar)
  ~/.local/share/crossbar/themes/<id>/    yours (same id as a stock theme replaces it)
Each has a theme.json, and optionally background.* / icons/*.svg|png / sounds/*.ogg / font files /
theme.css. Everything is checked here (colours must be colours, files must be inside the theme
folder), so a theme can't break the menu or reach other files.
"""
import json
import os
import re
import shutil
import tempfile
import zipfile

from . import util

STOCK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "themes")
USER = os.path.join(util.HOME, ".local", "share", "crossbar", "themes")
DEFAULT = "classic"

IMAGE = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif")
VIDEO = (".mp4", ".webm")
FONT = (".woff2", ".woff", ".ttf", ".otf")
SOUND = (".ogg", ".oga", ".mp3", ".wav", ".opus")
TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml",
         ".gif": "image/gif", ".mp4": "video/mp4", ".webm": "video/webm", ".woff2": "font/woff2", ".woff": "font/woff",
         ".ttf": "font/ttf", ".otf": "font/otf", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".mp3": "audio/mpeg",
         ".wav": "audio/wav", ".opus": "audio/ogg", ".css": "text/css", ".json": "application/json"}
SOUNDS = ("move", "ok", "back", "err")

_COLOR = re.compile(r"^(#[0-9a-fA-F]{3,8}|(rgb|rgba|hsl|hsla)\(\s*[0-9.,%\s/deg]+\)|[a-zA-Z]{3,20})$")
_FAMILY = re.compile(r"^[\w .\-']{1,60}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")

# Classic: what Crossbar looks like with no theme (every key a theme can set)
BASE = {
    "name": "Classic", "author": "Crossbar", "description": "Flowing waves in a colour that changes every month",
    "colors": {"accent": None, "text": "#ffffff", "dim": "rgba(255,255,255,.55)", "highlight": "rgba(255,255,255,.15)",
               "panel": "rgba(8,8,10,.90)", "glyph": "#ffffff"},
    "waves": {"mode": "month", "high": "#3a78c8", "low": "#0a1e3a", "lines": "#ffffff", "sparkles": True, "opacity": 1.0},
    "background": {"image": None, "dim": 0.35, "blur": 0, "waves_on_top": True},
    "font": {"family": "Noto Sans", "weight": 300, "file": None},
    "icons": {"glow": True, "color": None},
    "keyboard": {"background": "rgba(12,12,16,.86)", "key": "rgba(255,255,255,.07)", "key_text": "#e9e9e9",
                 "highlight": "rgba(255,255,255,.9)", "highlight_text": "#111111", "radius": 12},
    "quick_menu": {"panel": "rgba(8,8,10,.90)", "highlight": "rgba(255,255,255,.15)", "accent": "#ffffff"},
}


def _dirs():
    out = {}
    for base, user in ((STOCK, False), (USER, True)):
        if os.path.isdir(base):
            for d in sorted(os.listdir(base)):
                p = os.path.join(base, d)
                if _ID.match(d) and os.path.isfile(os.path.join(p, "theme.json")):
                    out[d] = (p, user)
    return out


def _file(folder, name, exts):
    """A file inside the theme folder (never outside it), or None."""
    if not isinstance(name, str) or not name or name.startswith("/") or "\\" in name:
        return None
    p = os.path.realpath(os.path.join(folder, name))
    if not p.startswith(os.path.realpath(folder) + os.sep) or not os.path.isfile(p):
        return None
    return name if p.lower().endswith(exts) else None


def _color(v, fallback):
    return v.strip() if isinstance(v, str) and _COLOR.match(v.strip()) else fallback


def _num(v, fallback, lo, hi):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return fallback


def load(tid):
    """The theme, checked and complete (missing keys come from Classic), with file URLs."""
    dirs = _dirs()
    if tid not in dirs:
        tid = DEFAULT if DEFAULT in dirs else next(iter(dirs), None)
    if tid is None:
        return {"id": "classic", **json.loads(json.dumps(BASE)), "user": False, "base": None}
    folder, user = dirs[tid]
    try:
        with open(os.path.join(folder, "theme.json")) as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raw = {}
    except (OSError, ValueError):
        raw = {}
    url = f"/theme/{tid}/"
    t = json.loads(json.dumps(BASE))
    t.update(id=tid, user=user, base=url)
    for k in ("name", "author", "description"):
        if isinstance(raw.get(k), str):
            t[k] = raw[k][:80]

    def section(name):
        v = raw.get(name)
        return v if isinstance(v, dict) else {}
    c = section("colors")
    for k in t["colors"]:
        t["colors"][k] = _color(c.get(k), t["colors"][k])
    w = section("waves")
    if w.get("mode") in ("month", "fixed", "off"):
        t["waves"]["mode"] = w["mode"]
    for k in ("high", "low", "lines"):
        t["waves"][k] = _color(w.get(k), t["waves"][k])
    t["waves"]["sparkles"] = bool(w.get("sparkles", t["waves"]["sparkles"]))
    t["waves"]["opacity"] = _num(w.get("opacity"), 1.0, 0, 1)
    b = section("background")
    img = _file(folder, b.get("image"), IMAGE + VIDEO)
    t["background"].update(image=(url + img) if img else None, video=bool(img and img.lower().endswith(VIDEO)),
                           dim=_num(b.get("dim"), 0.35, 0, 1), blur=_num(b.get("blur"), 0, 0, 40),
                           waves_on_top=bool(b.get("waves_on_top", True)))
    fo = section("font")
    if isinstance(fo.get("family"), str) and _FAMILY.match(fo["family"]):
        t["font"]["family"] = fo["family"]
    t["font"]["weight"] = int(_num(fo.get("weight"), 300, 100, 900))
    ff = _file(folder, fo.get("file"), FONT)
    t["font"]["file"] = (url + ff) if ff else None
    ic = section("icons")
    t["icons"]["glow"] = bool(ic.get("glow", True))
    t["icons"]["color"] = _color(ic.get("color"), None)
    over = {}
    idir = os.path.join(folder, "icons")
    if os.path.isdir(idir):
        for n in sorted(os.listdir(idir)):
            stem, ext = os.path.splitext(n)
            if re.match(r"^[a-z0-9_-]{1,30}$", stem) and ext.lower() in (".svg", ".png", ".webp") and _file(folder, f"icons/{n}", IMAGE):
                over[stem] = url + f"icons/{n}"
    t["icons"]["overrides"] = over
    for sec in ("keyboard", "quick_menu"):
        s = section(sec)
        for k, v in t[sec].items():
            t[sec][k] = _num(s.get(k), v, 0, 40) if k == "radius" else _color(s.get(k), v)
    snd = {}
    sdir = os.path.join(folder, "sounds")
    if os.path.isdir(sdir):
        for n in os.listdir(sdir):
            stem = os.path.splitext(n)[0]
            if stem in SOUNDS and _file(folder, f"sounds/{n}", SOUND):
                snd[stem] = url + f"sounds/{n}"
    t["sounds"] = snd
    t["css"] = (url + "theme.css") if _file(folder, "theme.css", (".css",)) else None
    prev = _file(folder, raw.get("preview") or "preview.png", IMAGE)
    t["preview"] = (url + prev) if prev else (t["background"]["image"] if not t["background"]["video"] else None)
    return t


def current_id():
    return util.load_config().get("theme_pack") or DEFAULT


def current():
    return load(current_id())


def available():
    out = []
    for tid, (folder, user) in _dirs().items():
        t = load(tid)
        out.append({"id": tid, "name": t["name"], "author": t["author"], "description": t["description"],
                    "user": user, "preview": t["preview"], "accent": t["colors"]["accent"] or t["waves"]["high"]})
    return out


def set_theme(tid):
    if tid not in _dirs():
        raise ValueError("No such theme")
    util.update_config(lambda c: c.__setitem__("theme_pack", tid))
    return current()


def file_path(tid, rel):
    """Path of one of a theme's files, for the web server (None if not a theme file)."""
    d = _dirs().get(tid)
    if not d:
        return None
    ext = os.path.splitext(rel)[1].lower()
    if ext not in TYPES:
        return None
    ok = _file(d[0], rel, tuple(TYPES))
    return (os.path.join(d[0], ok), TYPES[ext]) if ok else None


# ---- installing ---------------------------------------------------------------------------------
MAX_FILES, MAX_BYTES = 400, 200 << 20


def install(path):
    """Install a theme from a folder or a .zip (with theme.json at the top or one folder down)."""
    path = os.path.realpath(os.path.expanduser(path))
    os.makedirs(USER, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="theme-", dir=USER)
    try:
        if os.path.isdir(path):
            src = path
        elif zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                names = z.infolist()
                if len(names) > MAX_FILES or sum(i.file_size for i in names) > MAX_BYTES:
                    raise ValueError("That theme is too big (at most 400 files, 200 MB)")
                for i in names:                         # nothing may land outside the folder
                    target = os.path.realpath(os.path.join(tmp, i.filename))
                    if not target.startswith(os.path.realpath(tmp) + os.sep) or i.filename.startswith("/"):
                        raise ValueError("That zip has unsafe file names")
                z.extractall(tmp)
            src = tmp
        else:
            raise ValueError("Pick a theme folder or a .zip")
        if not os.path.isfile(os.path.join(src, "theme.json")):
            subs = [os.path.join(src, d) for d in os.listdir(src) if os.path.isfile(os.path.join(src, d, "theme.json"))]
            if len(subs) != 1:
                raise ValueError("No theme.json found (it goes at the top of the theme folder)")
            src = subs[0]
        with open(os.path.join(src, "theme.json")) as f:
            meta = json.load(f)
        if not isinstance(meta, dict):
            raise ValueError("theme.json isn't a theme")
        tid = re.sub(r"[^a-z0-9_-]+", "-", str(meta.get("id") or meta.get("name") or os.path.basename(src)).lower()).strip("-")[:40] or "theme"
        if not _ID.match(tid):
            tid = "theme-" + tid
        dest = os.path.join(USER, tid)
        stage = dest + ".new"
        shutil.rmtree(stage, ignore_errors=True)
        shutil.copytree(src, stage, symlinks=True, ignore=shutil.ignore_patterns(".*", "__MACOSX"))
        shutil.rmtree(dest, ignore_errors=True)
        os.replace(stage, dest)
        return load(tid)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def remove(tid):
    d = _dirs().get(tid)
    if not d or not d[1]:
        raise ValueError("Only themes you added can be removed")
    shutil.rmtree(os.path.join(USER, tid), ignore_errors=True)
    if current_id() == tid:
        util.update_config(lambda c: c.__setitem__("theme_pack", DEFAULT))
    return available()
