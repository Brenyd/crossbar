"""Social › Friends › Steam: who's online and what they're playing.

Uses the same Steam Web API key as Trophies (steamcommunity.com/dev/apikey). Your Steam
profile's Friends List has to be visible (Public, or Friends Only works for your own key's
account in most cases). Refreshed every 30 seconds at most.
"""
import urllib.error
import urllib.parse

from . import trophies

API = trophies.STEAM_API
STATES = {1: "Online", 2: "Busy", 3: "Away", 4: "Snooze", 5: "Looking to trade", 6: "Looking to play"}


def steam_friends():
    key, sid = trophies._steam()
    q = urllib.parse.urlencode({"key": key, "steamid": sid, "relationship": "friend"})
    try:
        ids = [f["steamid"] for f in trophies._get(f"{API}ISteamUser/GetFriendList/v1/?{q}", ttl=300)
               .get("friendslist", {}).get("friends", [])]
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError("Steam won't share your friends list: set Friends List to Public in your Steam privacy settings") from None
        raise
    people = []
    for i in range(0, len(ids), 100):
        q = urllib.parse.urlencode({"key": key, "steamids": ",".join(ids[i:i + 100])})
        people += trophies._get(f"{API}ISteamUser/GetPlayerSummaries/v2/?{q}", ttl=30).get("response", {}).get("players", [])
    online = []
    for p in people:
        state = p.get("personastate") or 0
        if not state:
            continue
        game = p.get("gameextrainfo") or ""
        online.append({"id": p.get("steamid"), "name": p.get("personaname") or "?", "game": game,
                       "game_id": p.get("gameid") or "", "status": f"Playing {game}" if game else STATES.get(state, "Online"),
                       "away": state in (3, 4), "avatar": p.get("avatarfull") or p.get("avatarmedium")})
    # playing first, then online, then away; by name
    online.sort(key=lambda f: (not f["game"], f["away"], f["name"].lower()))
    return {"online": online, "total": len(ids)}
