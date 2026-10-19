"""Games from other launchers, in the XMB: Lutris, and Steam's "non-Steam games".

Lutris (native or the Flathub version): its own game list (pga.db, read-only), launched with
`lutris:rungameid/<id>` so Lutris sets up Wine, runners and so on as usual.
Steam's non-Steam games: userdata/<you>/config/shortcuts.vdf, launched through Steam (so the
Proton / compatibility settings you gave them in Steam apply), with their Steam grid artwork.
Both show up in Game unless you move them (Y › Show In…); keys "lutris:<id>" / "shortcut:<appid>".
"""
import glob
import os
import sqlite3
import urllib.parse

from . import util
from .providers.steam import steam_roots

LUTRIS_FLATPAK = "net.lutris.Lutris"
LUTRIS_DIRS = [os.path.join(util.HOME, ".local/share/lutris"),
               os.path.join(util.HOME, ".var/app/net.lutris.Lutris/data/lutris")]
LUTRIS_CACHE = [os.path.join(util.HOME, ".cache/lutris"), os.path.join(util.HOME, ".var/app/net.lutris.Lutris/cache/lutris")]


def _file_url(p):
    return f"/api/file?path={urllib.parse.quote(p)}" if p else None


# ---- Lutris ------------------------------------------------------------------------------------------
def _lutris_flatpak():
    return any(os.path.isdir(os.path.join(base, "app", LUTRIS_FLATPAK)) for base in
               (os.path.join(util.HOME, ".local/share/flatpak"), "/var/lib/flatpak"))


def _lutris_art(base, slug):
    for d in (os.path.join(base, "banners"), os.path.join(base, "coverart"),
              *[os.path.join(c, "banners") for c in LUTRIS_CACHE], *[os.path.join(c, "coverart") for c in LUTRIS_CACHE]):
        for ext in ("jpg", "png"):
            p = os.path.join(d, f"{slug}.{ext}")
            if os.path.isfile(p):
                return p, "coverart" in d
    return None, False


def lutris_games():
    out, seen = [], set()
    for base in LUTRIS_DIRS:
        db = os.path.join(base, "pga.db")
        if not os.path.isfile(db):
            continue
        flatpak = ".var/app" in base
        try:
            con = sqlite3.connect(f"file:{urllib.parse.quote(db)}?mode=ro&immutable=1", uri=True, timeout=2)
            cols = {r[1] for r in con.execute("PRAGMA table_info(games)")}
            hidden = "AND (hidden IS NULL OR hidden = 0)" if "hidden" in cols else ""
            rows = con.execute(f"SELECT id, name, slug, runner, platform FROM games WHERE installed = 1 {hidden} ORDER BY name").fetchall()
            con.close()
        except sqlite3.Error as e:
            print(f"extgames: lutris {db}: {e}", flush=True)
            continue
        for gid, name, slug, runner, platform in rows:
            if (name, runner) in seen:
                continue
            seen.add((name, runner))
            art, poster = _lutris_art(base, slug or "")
            out.append({"key": f"lutris:{gid}", "kind": "lutris", "id": str(gid), "launch_id": f"{gid}{'@flatpak' if flatpak else ''}",
                        "name": name or slug, "art": _file_url(art), "poster": poster,
                        "sub": " · ".join(x for x in (runner and runner.capitalize(), platform) if x), "tag": "LUTRIS"})
    return out


class LutrisProvider:
    """For the normal game launcher (Starting… screen, Quick Menu close)."""
    id = "lutris"

    def launch(self, launch_id):
        gid, _, where = str(launch_id).partition("@")
        if not gid.isdigit():
            raise ValueError("game")
        url = f"lutris:rungameid/{gid}"
        if where == "flatpak" or (not util.which("lutris") and _lutris_flatpak()):
            argv = ["flatpak", "run", LUTRIS_FLATPAK, url]
        elif util.which("lutris"):
            argv = ["lutris", url]
        else:
            raise RuntimeError("Lutris isn't installed any more")
        util.spawn_checked(argv, what="Lutris", wait=4)


LUTRIS = LutrisProvider()


# ---- Steam non-Steam games ---------------------------------------------------------------------------------
def parse_binary_vdf(data, i=0):
    """Steam's binary KeyValues (shortcuts.vdf). Returns (dict, next index)."""
    out = {}
    n = len(data)
    while i < n:
        t = data[i]
        i += 1
        if t == 8:
            return out, i
        end = data.index(b"\0", i)
        name = data[i:end].decode("utf-8", "replace")
        i = end + 1
        if t == 0:
            val, i = parse_binary_vdf(data, i)
        elif t == 1:
            end = data.index(b"\0", i)
            val = data[i:end].decode("utf-8", "replace")
            i = end + 1
        elif t == 2:
            val = int.from_bytes(data[i:i + 4], "little", signed=False)
            i += 4
        elif t == 7:
            val = int.from_bytes(data[i:i + 8], "little", signed=False)
            i += 8
        else:
            break                                   # unknown type: stop rather than misread
        out[name] = val
    return out, i


def _grid(config_dir, appid):
    g = os.path.join(config_dir, "grid")
    for name, poster in ((f"{appid}", False), (f"{appid}_hero", False), (f"{appid}p", True)):
        for ext in ("png", "jpg", "jpeg", "webp"):
            p = os.path.join(g, f"{name}.{ext}")
            if os.path.isfile(p):
                return p, poster
    return None, False


def steam_shortcuts():
    out, seen = [], set()
    for root in steam_roots():
        for vdf in glob.glob(os.path.join(root, "userdata", "*", "config", "shortcuts.vdf")):
            try:
                with open(vdf, "rb") as f:
                    data = f.read()
                top = parse_binary_vdf(data)[0]
            except (OSError, ValueError, IndexError):
                continue
            entries = next((v for k, v in top.items() if k.lower() == "shortcuts"), {}) or {}
            for e in entries.values():
                if not isinstance(e, dict):
                    continue
                low = {k.lower(): v for k, v in e.items()}
                appid = int(low.get("appid") or 0) & 0xFFFFFFFF
                name = low.get("appname") or os.path.basename(str(low.get("exe", "")).strip('"')) or "Game"
                if not appid or low.get("ishidden") or (appid in seen):
                    continue
                seen.add(appid)
                art, poster = _grid(os.path.dirname(vdf), appid)
                out.append({"key": f"shortcut:{appid}", "kind": "shortcut", "id": str(appid),
                            "launch_id": str((appid << 32) | 0x02000000), "name": name, "art": _file_url(art), "poster": poster,
                            "sub": "Added to Steam", "tag": "NON-STEAM"})
    out.sort(key=lambda g: g["name"].lower())
    return out


class ShortcutProvider:
    """Non-Steam games start through Steam, like on a Steam Deck."""
    id = "shortcut"

    def launch(self, gameid, progress=None):
        if not str(gameid).isdigit():
            raise ValueError("game")
        from .providers.steam import Steam
        Steam().launch(str(gameid), progress=progress)


SHORTCUT = ShortcutProvider()


def games():
    """Every Lutris and non-Steam game, each with the category it shows up in (default Game)."""
    from . import apps, artwork
    cats = apps.categories()
    out = lutris_games() + steam_shortcuts()
    for g in out:
        g["category"] = cats.get(g["key"], "game")
        if not g["art"]:
            g.pop("art")
    artwork.apply(out, key_of=lambda g: g["key"])
    for g in out:
        g.setdefault("art", None)
    return out
