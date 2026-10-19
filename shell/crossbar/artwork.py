"""Game artwork from SteamGridDB (steamgriddb.com).

Needs a free API key: steamgriddb.com › sign in › Preferences › API. With it you can:
  * pick new artwork for any game (store games and ROMs) from the XMB's options menu;
  * have games with no artwork (most ROMs, some GOG / Epic games) filled in automatically.
Your choices live in config "art_overrides" keyed "provider:id" (ROMs: "rom:<system>:<file>").
Automatic matches are cached in ~/.cache/crossbar/steamgriddb.json and looked up in the background,
a few at a time, so lists never wait on the network.
"""
import json
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import util

API = "https://www.steamgriddb.com/api/v2"
DIMS = "460x215,920x430"                      # the XMB's landscape tiles
CACHE = os.path.expanduser("~/.cache/crossbar/steamgriddb.json")
_lock = threading.Lock()
_queue = queue.Queue()
_pending = set()
_worker = None
_auto = None                                 # {lookup key: url or ""}
on_change = None                             # set by server: called when background art arrives


# ---- settings -------------------------------------------------------------------------------------------
def _cfg():
    return util.load_config().get("steamgriddb") or {}


def api_key():
    return _cfg().get("key") or ""


def status():
    c = _cfg()
    return {"ready": bool(c.get("key")), "auto": c.get("auto", True),
            "overrides": len(util.load_config().get("art_overrides") or {})}


def _call(path, key=None, **params):
    key = key or api_key()
    if not key:
        raise RuntimeError("Add a SteamGridDB API key first (Settings › Games & Emulation › Artwork)")
    url = f"{API}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": "Crossbar/0.11"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError("SteamGridDB refused the API key") from None
        if e.code == 404:
            return []
        raise
    if not data.get("success", True):
        raise RuntimeError("; ".join(data.get("errors") or ["SteamGridDB error"]))
    return data.get("data") or []


def set_settings(key=None, auto=None):
    if key is not None:
        key = key.strip()
        if key and not re.fullmatch(r"[0-9a-fA-F]{32}", key):
            raise ValueError("A SteamGridDB API key is 32 letters and numbers (steamgriddb.com › Preferences › API)")
        if key:
            _call("/search/autocomplete/" + urllib.parse.quote("portal"), key=key)   # proves the key works
    def upd(c):
        s = c.setdefault("steamgriddb", {})
        if key is not None:
            s["key"] = key
        if auto is not None:
            s["auto"] = bool(auto)
    util.update_config(upd)
    if key:
        with _lock:                           # retry earlier misses now that there's a (new) key
            _load_auto()
            for k in [k for k, v in _auto.items() if not v]:
                del _auto[k]
    return status()


# ---- picking artwork ---------------------------------------------------------------------------------
def search(term):
    term = (term or "").strip()
    if not term:
        return []
    out = []
    for g in _call("/search/autocomplete/" + urllib.parse.quote(term, safe="")):
        year = time.strftime("%Y", time.gmtime(g["release_date"])) if g.get("release_date") else ""
        out.append({"id": g["id"], "name": g.get("name", ""), "year": year, "verified": bool(g.get("verified"))})
    return out


def _grids(items):
    out = []
    for g in items:
        if g.get("nsfw"):
            continue
        out.append({"id": g.get("id"), "url": g.get("url"), "thumb": g.get("thumb") or g.get("url"),
                    "style": g.get("style") or "", "size": f"{g.get('width')}×{g.get('height')}",
                    "votes": (g.get("upvotes") or 0) - (g.get("downvotes") or 0), "author": (g.get("author") or {}).get("name", "")})
    return out


def grids(game_id=None, steam_appid=None):
    params = {"dimensions": DIMS, "types": "static", "nsfw": "false"}
    if steam_appid:
        return _grids(_call(f"/grids/steam/{int(steam_appid)}", **params))
    return _grids(_call(f"/grids/game/{int(game_id)}", **params))


def set_override(key, url):
    if not key or not isinstance(url, str) or not url.startswith("https://"):
        raise ValueError("bad artwork")
    util.update_config(lambda c: c.setdefault("art_overrides", {}).__setitem__(key, url))
    return {"key": key, "art": url}


LOCAL = os.path.join(util.HOME, ".local", "share", "crossbar", "art")
LOCAL_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def set_local(key, path):
    """Artwork from a picture on this console (USB stick, Downloads…): copied into Crossbar's own folder."""
    import hashlib
    import shutil
    path = os.path.realpath(os.path.expanduser(path))
    ext = os.path.splitext(path)[1].lower()
    if ext not in LOCAL_EXT or not os.path.isfile(path):
        raise ValueError("Pick a picture (.png, .jpg, .webp or .gif)")
    if os.path.getsize(path) > 25 << 20:
        raise ValueError("That picture is too big (25 MB at most)")
    with open(path, "rb") as f:
        digest = hashlib.sha1(f.read()).hexdigest()[:20]
    os.makedirs(LOCAL, exist_ok=True)
    name = digest + (".jpg" if ext == ".jpeg" else ext)
    shutil.copy(path, os.path.join(LOCAL, name))
    url = f"/art/{name}"
    util.update_config(lambda c: c.setdefault("art_overrides", {}).__setitem__(key, url))
    return {"key": key, "art": url}


def local_file(name):
    """Path of a copied picture, for the web server (None if it isn't one)."""
    import re as _re
    if not _re.fullmatch(r"[0-9a-f]{20}\.(png|jpg|webp|gif)", name or ""):
        return None
    p = os.path.join(LOCAL, name)
    return p if os.path.isfile(p) else None


def reset(key):
    util.update_config(lambda c: (c.setdefault("art_overrides", {}).pop(key, None)))
    with _lock:
        _load_auto()
        _auto.pop(key, None)
        _save_auto()
    return {"key": key}


def reset_all():
    util.update_config(lambda c: c.__setitem__("art_overrides", {}))
    with _lock:
        global _auto
        _auto = {}
        _save_auto()
    return status()


# ---- applying to lists -----------------------------------------------------------------------------
def _load_auto():
    global _auto
    if _auto is None:
        try:
            with open(CACHE) as f:
                _auto = json.load(f)
        except (OSError, ValueError):
            _auto = {}


def _save_auto():
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = CACHE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_auto, f)
    os.replace(tmp, CACHE)


def apply(games, key_of=lambda g: f"{g.get('provider')}:{g.get('id')}", fill=True):
    """Set g['art'] from your picks, else (for games with none) from automatic matches.

    Games still without art are queued for a background lookup. Returns the list (changed in place)."""
    overrides = util.load_config().get("art_overrides") or {}
    st = _cfg()
    auto = fill and bool(st.get("key")) and st.get("auto", True)
    with _lock:
        _load_auto()
        for g in games:
            k = key_of(g)
            if overrides.get(k):
                g["art"] = overrides[k]
                g["art_custom"] = True
            elif not g.get("art") and auto:
                hit = _auto.get(k)
                if hit:
                    g["art"] = hit
                elif hit is None and k not in _pending:
                    _pending.add(k)
                    _queue.put((k, g.get("title") or "", g.get("id") if g.get("provider") == "steam" else None))
    if auto and not _queue.empty():
        _start_worker()
    return games


def _clean_title(t):
    t = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", t)            # (USA) [!] (Disc 1) …
    return re.sub(r"\s+", " ", t.replace("_", " ")).strip()


def _lookup(title, steam_appid):
    if steam_appid and str(steam_appid).isdigit():
        g = grids(steam_appid=steam_appid)
        if g:
            return g[0]["url"]
    found = search(_clean_title(title))
    if not found:
        return ""
    g = grids(game_id=found[0]["id"])
    return g[0]["url"] if g else ""


def _work():
    changed = 0
    while True:
        try:
            k, title, appid = _queue.get(timeout=3)
        except queue.Empty:
            break
        try:
            url = _lookup(title, appid)
        except RuntimeError:                  # bad key etc.: stop, retry next time
            with _lock:
                _pending.discard(k)
            break
        except Exception:
            url = None                        # network hiccup: try again later
        with _lock:
            _pending.discard(k)
            if url is not None:
                _auto[k] = url
                _save_auto()
                changed += bool(url)
        time.sleep(0.25)                       # be gentle with the API
    if changed and on_change:
        on_change()


def _start_worker():
    global _worker
    with _lock:
        if _worker and _worker.is_alive():
            return
        _worker = threading.Thread(target=_work, daemon=True, name="steamgriddb")
        _worker.start()
