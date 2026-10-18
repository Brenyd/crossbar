"""IPTV through the Xtream Codes API (player_api.php).

Sign in once (Settings › Media Settings › IPTV); Live TV shows under TV & Video
Services, Movies and TV Shows under Video. You choose which categories appear
and can hide channels. Streams play in Crossbar's video player; the password
stays here (in a 0600 file) and never goes to the menu.
"""
import hashlib
import json
import os
import time
import urllib.parse

from . import util

ACCOUNT = os.path.join(util.CONFIG_DIR, "iptv_account.json")
CACHE = os.path.join(util.HOME, ".cache", "crossbar", "iptv")
TTL = {"get_live_categories": 43200, "get_vod_categories": 43200, "get_series_categories": 43200,
       "get_live_streams": 21600, "get_vod_streams": 21600, "get_series": 21600, "get_series_info": 3600}
KINDS = {"live": ("get_live_categories", "get_live_streams"),
         "vod": ("get_vod_categories", "get_vod_streams"),
         "series": ("get_series_categories", "get_series")}


def _account():
    try:
        with open(ACCOUNT) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def normalise(server):
    server = (server or "").strip().rstrip("/")
    if not server:
        raise ValueError("Enter the server address")
    if "://" not in server:
        server = "http://" + server
    for tail in ("/player_api.php", "/get.php", "/c"):
        if server.endswith(tail):
            server = server[: -len(tail)]
    p = urllib.parse.urlparse(server)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("That doesn't look like a server address")
    return f"{p.scheme}://{p.netloc}{p.path}".rstrip("/")


def _call(acct, action=None, use_cache=True, **params):
    q = {"username": acct["username"], "password": acct["password"], **params}
    if action:
        q["action"] = action
    url = f"{acct['server']}/player_api.php?{urllib.parse.urlencode(q)}"
    key = hashlib.sha1(f"{acct['server']}|{acct['username']}|{action}|{sorted(params.items())}".encode()).hexdigest()
    path = os.path.join(CACHE, key + ".json")
    if use_cache and action and os.path.exists(path) and time.time() - os.path.getmtime(path) < TTL.get(action, 3600):
        with open(path) as f:
            return json.load(f)
    data = util.http_json(url, timeout=30)
    if action:
        os.makedirs(CACHE, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)
    return data


def require():
    a = _account()
    if not a:
        raise RuntimeError("Sign in to IPTV first (Settings › Media Settings › IPTV)")
    return a


# ---- account -----------------------------------------------------------------
def login(job, server, username, password):
    acct = {"server": normalise(server), "username": (username or "").strip(), "password": password or ""}
    if not acct["username"]:
        raise ValueError("Enter the username")
    job.set(0.3, "Checking the account…")
    try:
        info = _call(acct, None, use_cache=False)
    except Exception as e:
        raise RuntimeError(f"Couldn't reach the server: {e}") from None
    ui = (info or {}).get("user_info") or {}
    if str(ui.get("auth")) != "1":
        raise RuntimeError("The server rejected that username or password")
    if ui.get("status") and ui["status"] != "Active":
        raise RuntimeError(f"The account is {ui['status']}")
    os.makedirs(util.CONFIG_DIR, exist_ok=True)
    fd = os.open(ACCOUNT, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(acct, f)
    util.update_config(lambda c: c.setdefault("iptv", {}).update(exp=ui.get("exp_date"), connections=ui.get("max_connections")))
    job.set(0.7, "Loading channel list…")
    for kind in KINDS:
        try:
            _call(acct, KINDS[kind][0])
        except Exception:
            pass


def logout():
    try:
        os.remove(ACCOUNT)
    except OSError:
        pass
    for f in os.listdir(CACHE) if os.path.isdir(CACHE) else []:
        os.remove(os.path.join(CACHE, f))


def prefs():
    return util.load_config().get("iptv") or {}


def status():
    a = _account()
    p = prefs()
    exp = p.get("exp")
    return {"linked": bool(a), "server": a["server"] if a else "", "username": a["username"] if a else "",
            "expires": time.strftime("%Y-%m-%d", time.localtime(int(exp))) if exp and str(exp).isdigit() else None,
            "shown": {k: len(p.get(f"{k}_shown") or []) for k in KINDS}}


def refresh():
    for f in os.listdir(CACHE) if os.path.isdir(CACHE) else []:
        os.remove(os.path.join(CACHE, f))


# ---- what to show ----------------------------------------------------------------
def categories(kind, only_shown=False):
    a = require()
    shown = set(map(str, prefs().get(f"{kind}_shown") or []))
    cats = [{"id": str(c["category_id"]), "name": c.get("category_name", "?"), "shown": str(c["category_id"]) in shown}
            for c in _call(a, KINDS[kind][0]) or []]
    if only_shown:
        order = [str(x) for x in prefs().get(f"{kind}_shown") or []]
        cats = sorted((c for c in cats if c["shown"]), key=lambda c: order.index(c["id"]))
    return cats


def set_shown(kind, cat_id, on):
    def f(c):
        lst = [str(x) for x in c.setdefault("iptv", {}).get(f"{kind}_shown") or []]
        if on and str(cat_id) not in lst:
            lst.append(str(cat_id))
        if not on:
            lst = [x for x in lst if x != str(cat_id)]
        c["iptv"][f"{kind}_shown"] = lst
    util.update_config(f)


def set_channel_hidden(stream_id, hidden):
    def f(c):
        lst = [str(x) for x in c.setdefault("iptv", {}).get("hidden") or []]
        if hidden and str(stream_id) not in lst:
            lst.append(str(stream_id))
        if not hidden:
            lst = [x for x in lst if x != str(stream_id)]
        c["iptv"]["hidden"] = lst
    util.update_config(f)


def items(kind, cat_id, include_hidden=False):
    a = require()
    hidden = set(map(str, prefs().get("hidden") or []))
    raw = _call(a, KINDS[kind][1], category_id=cat_id) or []
    out = []
    for s in raw:
        if kind == "series":
            sid = str(s.get("series_id"))
            out.append({"id": sid, "name": s.get("name", "?"), "icon": s.get("cover") or None,
                        "year": (s.get("releaseDate") or s.get("release_date") or "")[:4], "rating": s.get("rating") or ""})
            continue
        sid = str(s.get("stream_id"))
        if sid in hidden and not include_hidden:
            continue
        out.append({"id": sid, "name": s.get("name", "?"), "icon": s.get("stream_icon") or None,
                    "num": s.get("num"), "rating": s.get("rating") or "", "hidden": sid in hidden})
    return out


def series_info(series_id):
    a = require()
    data = _call(a, "get_series_info", series_id=series_id) or {}
    seasons = []
    for num, eps in sorted((data.get("episodes") or {}).items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0):
        seasons.append({"season": str(num), "episodes": [
            {"id": str(e.get("id")), "num": e.get("episode_num"), "title": e.get("title") or f"Episode {e.get('episode_num')}",
             "ext": e.get("container_extension") or "mp4", "plot": ((e.get("info") or {}).get("plot") or "")[:200]}
            for e in eps]})
    info = data.get("info") or {}
    return {"name": info.get("name", ""), "plot": (info.get("plot") or "")[:400], "cover": info.get("cover"), "seasons": seasons}


# ---- playback (URLs built here so the password never leaves the backend) ---------------
def playlist(kind, cat_id=None, item_id=None, series_id=None):
    """[(title, url)] and the index to start at."""
    a = require()
    base, u, p = a["server"], urllib.parse.quote(a["username"]), urllib.parse.quote(a["password"])
    if kind == "live":
        chans = items("live", cat_id)
        entries = [(c["name"], f"{base}/live/{u}/{p}/{c['id']}.ts") for c in chans]
        idx = next((i for i, c in enumerate(chans) if c["id"] == str(item_id)), 0)
        return entries, idx
    if kind == "vod":
        raw = _call(a, "get_vod_streams", category_id=cat_id) or []
        s = next((x for x in raw if str(x.get("stream_id")) == str(item_id)), None)
        if not s:
            raise RuntimeError("That movie isn't available anymore")
        return [(s.get("name", "Movie"), f"{base}/movie/{u}/{p}/{s['stream_id']}.{s.get('container_extension') or 'mp4'}")], 0
    if kind == "episode":
        info = series_info(series_id)
        eps = [(f"{info['name']} S{se['season']}E{e['num']} · {e['title']}", f"{base}/series/{u}/{p}/{e['id']}.{e['ext']}", e["id"])
               for se in info["seasons"] for e in se["episodes"]]
        idx = next((i for i, e in enumerate(eps) if e[2] == str(item_id)), 0)
        return [(t, url) for t, url, _ in eps], idx
    raise ValueError(kind)
