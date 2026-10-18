"""Trophies: RetroAchievements (by console) and Steam achievements.

RetroAchievements: your username + Web API key (retroachievements.org › Settings › Keys).
Steam: a Steam Web API key (steamcommunity.com/dev/apikey) + your SteamID (read from Steam's
own files when Steam is installed). Responses are cached for a few minutes.
GOG and Epic don't let other apps read achievements (only GOG Galaxy / the Epic launcher can).
"""
import glob
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import util

RA_API = "https://retroachievements.org/API/"
RA_MEDIA = "https://media.retroachievements.org"
STEAM_API = "https://api.steampowered.com/"
_cache = {}


def _get(url, ttl=300):
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    req = urllib.request.Request(url, headers={"User-Agent": "Crossbar/0.9"})
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode())
    _cache[url] = (time.time(), data)
    return data


# ---- RetroAchievements ------------------------------------------------------------------------
def _ra():
    ra = (util.load_config().get("emulation") or {}).get("ra") or {}
    if not ra.get("user") or not ra.get("web_key"):
        raise RuntimeError("Sign in to RetroAchievements and add your Web API key (Settings › Emulation)")
    return ra["user"], ra["web_key"]


def _ra_call(endpoint, **params):
    user, key = _ra()
    q = urllib.parse.urlencode({"u": user, "y": key, **params})
    try:
        return _get(f"{RA_API}{endpoint}?{q}")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError("RetroAchievements refused the Web API key") from None
        raise


def ra_summary():
    user, _ = _ra()
    s = _ra_call("API_GetUserSummary.php", g=0, a=0)
    return {"user": user, "points": s.get("TotalPoints") or 0, "hardcore_points": s.get("TotalTruePoints") or 0,
            "rank": s.get("Rank"), "pic": (RA_MEDIA + s["UserPic"]) if s.get("UserPic") else None}


def ra_consoles():
    """Games you've played, grouped by console, with progress."""
    res = _ra_call("API_GetUserCompletionProgress.php", c=500, o=0)
    games = res.get("Results", []) if isinstance(res, dict) else res
    consoles = {}
    for g in games:
        name = g.get("ConsoleName") or "Other"
        c = consoles.setdefault(name, {"name": name, "id": g.get("ConsoleID"), "games": [], "earned": 0, "total": 0})
        earned = max(g.get("NumAwarded") or 0, g.get("NumAwardedHardcore") or 0)
        total = g.get("MaxPossible") or 0
        c["games"].append({"id": g.get("GameID"), "title": g.get("Title"), "earned": earned, "total": total,
                           "hardcore": g.get("NumAwardedHardcore") or 0, "award": g.get("HighestAwardKind") or "",
                           "icon": (RA_MEDIA + g["ImageIcon"]) if g.get("ImageIcon") else None})
        c["earned"] += earned
        c["total"] += total
    return sorted(consoles.values(), key=lambda c: c["name"])


def ra_game(game_id):
    g = _ra_call("API_GetGameInfoAndUserProgress.php", g=int(game_id))
    out = []
    for a in (g.get("Achievements") or {}).values():
        when = a.get("DateEarnedHardcore") or a.get("DateEarned")
        badge = a.get("BadgeName")
        out.append({"title": a.get("Title"), "desc": a.get("Description"), "points": a.get("Points"),
                    "earned": bool(when), "when": (when or "")[:10], "hardcore": bool(a.get("DateEarnedHardcore")),
                    "icon": f"{RA_MEDIA}/Badge/{badge}{'' if when else '_lock'}.png" if badge else None,
                    "order": a.get("DisplayOrder") or 0})
    out.sort(key=lambda a: (not a["earned"], a["order"]))
    return {"title": g.get("Title"), "console": g.get("ConsoleName"), "achievements": out}


# ---- Steam -----------------------------------------------------------------------------------------------
def steam_id_guess():
    """The most recent account Steam on this machine signed in with (SteamID64)."""
    for path in glob.glob(os.path.expanduser("~/.local/share/Steam/config/loginusers.vdf")) + \
            glob.glob(os.path.expanduser("~/.steam/steam/config/loginusers.vdf")):
        try:
            text = open(path, errors="replace").read()
        except OSError:
            continue
        blocks = re.findall(r'"(\d{17})"\s*\{([^}]*)\}', text)
        recent = [sid for sid, body in blocks if re.search(r'"MostRecent"\s*"1"', body)]
        if recent or blocks:
            return (recent or [blocks[0][0]])[0]
    return None


def _steam():
    st = util.load_config().get("trophies", {}).get("steam") or {}
    key, sid = st.get("key"), st.get("steamid") or steam_id_guess()
    if not key:
        raise RuntimeError("Add a Steam Web API key first (Trophies › Steam › Set Up)")
    if not sid:
        raise RuntimeError("Couldn't find your SteamID: sign in to Steam once, or enter it in Set Up")
    return key, sid


def steam_games(limit=60):
    key, sid = _steam()
    q = urllib.parse.urlencode({"key": key, "steamid": sid, "include_appinfo": 1, "include_played_free_games": 1})
    data = _get(f"{STEAM_API}IPlayerService/GetOwnedGames/v1/?{q}", ttl=900).get("response", {})
    games = [g for g in data.get("games", []) if g.get("playtime_forever")]
    games.sort(key=lambda g: (g.get("rtime_last_played") or 0, g.get("playtime_forever") or 0), reverse=True)
    return [{"id": g["appid"], "title": g.get("name", str(g["appid"])), "hours": round((g.get("playtime_forever") or 0) / 60, 1),
             "icon": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{g['appid']}/header.jpg"} for g in games[:limit]]


def steam_game(appid):
    key, sid = _steam()
    q = urllib.parse.urlencode({"key": key, "steamid": sid, "appid": int(appid), "l": "english"})
    try:
        data = _get(f"{STEAM_API}ISteamUserStats/GetPlayerAchievements/v1/?{q}").get("playerstats", {})
    except urllib.error.HTTPError as e:
        if e.code == 400:
            return {"title": str(appid), "achievements": [], "note": "This game has no achievements"}
        if e.code == 403:
            raise RuntimeError("Steam refused: set Game details to Public in your Steam privacy settings") from None
        raise
    schema = {}
    try:
        q2 = urllib.parse.urlencode({"key": key, "appid": int(appid), "l": "english"})
        for a in _get(f"{STEAM_API}ISteamUserStats/GetSchemaForGame/v2/?{q2}", ttl=86400).get("game", {}) \
                .get("availableGameStats", {}).get("achievements", []):
            schema[a["name"]] = a
    except Exception:
        pass
    out = []
    for a in data.get("achievements", []):
        s = schema.get(a.get("apiname"), {})
        got = bool(a.get("achieved"))
        out.append({"title": a.get("name") or s.get("displayName") or a.get("apiname"),
                    "desc": a.get("description") or s.get("description") or ("Hidden achievement" if s.get("hidden") else ""),
                    "earned": got, "when": time.strftime("%Y-%m-%d", time.localtime(a["unlocktime"])) if got and a.get("unlocktime") else "",
                    "icon": s.get("icon") if got else s.get("icongray")})
    out.sort(key=lambda a: not a["earned"])
    return {"title": data.get("gameName") or str(appid), "achievements": out}


STATES = {1: "Online", 2: "Busy", 3: "Away", 4: "Snooze", 5: "Looking to trade", 6: "Looking to play"}


def steam_friends():
    """Steam friends who are online now, the ones in a game first: [{id, name, status, game, avatar}].

    Uses the same Steam Web API key as Trophies. Needs your profile's Friends List to be public."""
    key, sid = _steam()
    q = urllib.parse.urlencode({"key": key, "steamid": sid, "relationship": "friend"})
    try:
        ids = [f["steamid"] for f in _get(f"{STEAM_API}ISteamUser/GetFriendList/v1/?{q}", ttl=600)
               .get("friendslist", {}).get("friends", [])]
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError("Steam won't share your friends list: set Friends List to Public in your Steam privacy settings") from None
        raise
    people = []
    for i in range(0, len(ids), 100):                  # GetPlayerSummaries takes 100 at a time
        q2 = urllib.parse.urlencode({"key": key, "steamids": ",".join(ids[i:i + 100])})
        people += _get(f"{STEAM_API}ISteamUser/GetPlayerSummaries/v2/?{q2}", ttl=45).get("response", {}).get("players", [])
    out = []
    for p in people:
        state = p.get("personastate") or 0
        game = p.get("gameextrainfo") or ""
        if not state and not game:
            continue                                     # offline
        out.append({"id": p.get("steamid"), "name": p.get("personaname") or "?", "game": game,
                    "status": f"Playing {game}" if game else STATES.get(state, "Online"),
                    "away": state in (3, 4), "avatar": p.get("avatarfull") or p.get("avatarmedium")})
    out.sort(key=lambda f: (not f["game"], f["away"], f["name"].lower()))
    return out


def steam_setup(key, steamid=""):
    key = (key or "").strip()
    if not re.fullmatch(r"[0-9A-Fa-f]{32}", key):
        raise ValueError("A Steam Web API key is 32 letters and numbers (steamcommunity.com/dev/apikey)")
    steamid = (steamid or "").strip()
    if steamid and not re.fullmatch(r"\d{17}", steamid):
        raise ValueError("A SteamID64 is 17 digits")
    util.update_config(lambda c: c.setdefault("trophies", {}).__setitem__("steam", {"key": key, "steamid": steamid}))
    return status()


def status():
    ra = (util.load_config().get("emulation") or {}).get("ra") or {}
    st = util.load_config().get("trophies", {}).get("steam") or {}
    return {"ra": {"user": ra.get("user"), "ready": bool(ra.get("user") and ra.get("web_key"))},
            "steam": {"ready": bool(st.get("key")), "steamid": st.get("steamid") or steam_id_guess()}}
