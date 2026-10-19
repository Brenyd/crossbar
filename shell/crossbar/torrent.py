"""Torrents (Apps › Torrents): a console front end on qBittorrent's engine (qbittorrent-nox),
run headless in the background with its own profile, driven through its Web API on
127.0.0.1 only. qBittorrent brings the parts that matter: its search plugins (official and
the community ones, installed from the qBittorrent wiki list), binding to one network
interface (the VPN's), and a well-tested BitTorrent engine.

  Profile   ~/.local/share/crossbar/torrent (settings, resume data, search plugins)
  Web API   127.0.0.1:7778, no password from this machine (LocalHostAuth off), nothing outside
  VPN       "Use the VPN" binds to the VPN interface (no VPN = no torrent traffic); a port the
            VPN forwards (PIA, Proton) becomes the listening port automatically.
"""
import glob
import http.client
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse

from . import util

PORT = 7778
PROFILE = os.path.join(util.HOME, ".local", "share", "crossbar", "torrent")
CONF = os.path.join(PROFILE, "qBittorrent", "config", "qBittorrent.conf")
DEFAULT_SAVE = os.path.join(util.HOME, "Downloads", "Torrents")
WIKI = "https://raw.githubusercontent.com/wiki/qbittorrent/search-plugins/Unofficial-search-plugins.mediawiki"
OFFICIAL = "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/"
CATEGORIES = ["all", "movies", "tv", "music", "games", "anime", "software", "pictures", "books"]

_proc = {"p": None}
_cache = {}
_seen_done = set()


class TorrentError(RuntimeError):
    pass


def available():
    return bool(util.which("qbittorrent-nox"))


def prefs_local():
    c = util.load_config().get("torrent")
    return c if isinstance(c, dict) else {}


def _set_local(**kw):
    util.update_config(lambda c: c.setdefault("torrent", {}).update(kw))


# ---- the engine --------------------------------------------------------------------------------------
def _seed_config():
    """First start only: Web API on localhost without a password, the legal notice accepted,
    downloads in ~/Downloads/Torrents. After that, settings change through the API."""
    if os.path.exists(CONF):
        return
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    os.makedirs(DEFAULT_SAVE, exist_ok=True)
    with open(CONF, "w") as f:
        f.write(f"""[LegalNotice]
Accepted=true

[BitTorrent]
Session\\DefaultSavePath={DEFAULT_SAVE}
Session\\Port={_random_port()}
Session\\QueueingSystemEnabled=true

[Preferences]
Downloads\\SavePath={DEFAULT_SAVE}
WebUI\\Address=127.0.0.1
WebUI\\Port={PORT}
WebUI\\LocalHostAuth=false
WebUI\\CSRFProtection=false
WebUI\\ClickjackingProtection=true
WebUI\\HostHeaderValidation=true
WebUI\\ServerDomains=127.0.0.1;localhost
General\\Locale=en
""")


def _random_port():
    import random
    return random.randint(20000, 60000)


def running():
    try:
        _req("GET", "/api/v2/app/version", timeout=2)
        return True
    except (OSError, TorrentError):
        return False


def start():
    if running():
        return True
    if not available():
        raise TorrentError("The torrent engine (qbittorrent-nox) isn't installed: Settings › System › Update Crossbar installs it")
    _seed_config()
    os.makedirs(os.path.join(util.HOME, ".cache"), exist_ok=True)
    log = open(os.path.join(util.HOME, ".cache", "crossbar-torrent.log"), "a")
    argv = ["qbittorrent-nox", f"--profile={PROFILE}", f"--webui-port={PORT}"]
    if _version_tuple(_nox_version()) >= (5, 0):
        argv.append("--confirm-legal-notice")
    from . import vpn
    argv = vpn.wrap(argv, "torrents")                     # in the VPN's group when torrents use the VPN
    _cache.pop("sid", None)
    _proc["p"] = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(60):
        time.sleep(0.25)
        if running():
            _apply_vpn_binding()
            return True
        if _proc["p"].poll() is not None:
            raise TorrentError("The torrent engine stopped right away (see ~/.cache/crossbar-torrent.log)")
    raise TorrentError("The torrent engine didn't start")


def stop():
    try:
        _req("POST", "/api/v2/app/shutdown", timeout=5)
    except (OSError, TorrentError):
        pass
    return {"running": False}


def _nox_version():
    if "nox" not in _cache:
        try:
            r = subprocess.run(["qbittorrent-nox", "--version"], capture_output=True, text=True, timeout=10)
            _cache["nox"] = (re.search(r"v?(\d+\.\d+(\.\d+)?)", r.stdout) or [None, "0"])[1]
        except (OSError, subprocess.TimeoutExpired):
            _cache["nox"] = "0"
    return _cache["nox"]


def _version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3]) or (0,)


# ---- the Web API ------------------------------------------------------------------------------------
def _req(method, path, params=None, data=None, files=None, timeout=15):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    headers = {"Referer": f"http://127.0.0.1:{PORT}", "Host": f"127.0.0.1:{PORT}"}
    if _cache.get("sid"):
        # one session for everything: qBittorrent keeps searches in the session that started
        # them (a new session per request = "not found" asking for the results)
        headers["Cookie"] = f"SID={_cache['sid']}"
    body = None
    if params:
        path += "?" + urllib.parse.urlencode(params)
    if files:
        boundary = "----crossbar" + os.urandom(8).hex()
        parts = []
        for k, v in (data or {}).items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        for k, (name, blob) in files.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
                         f'Content-Type: application/x-bittorrent\r\n\r\n'.encode() + blob + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    try:
        c.request(method, path, body=body, headers=headers)
        r = c.getresponse()
        raw = r.read()
        m = re.search(r"\bSID=([^;\s]+)", r.getheader("Set-Cookie") or "")
        if m:
            _cache["sid"] = m.group(1)
    finally:
        c.close()
    if r.status == 403:
        raise TorrentError("The torrent engine refused Crossbar (its Web UI needs LocalHostAuth off)")
    if r.status == 404:
        raise TorrentError(f"not found: {path.split('?')[0]}")
    if r.status >= 400:
        raise TorrentError(raw.decode(errors="replace").strip()[:200] or f"error {r.status}")
    text = raw.decode(errors="replace")
    try:
        return json.loads(text) if text and text[0] in "[{" else text
    except ValueError:
        return text


def api(method, path, **kw):
    if time.time() - _cache.get("alive", 0) > 5:          # (re)start the engine if it's not up
        start()
    try:
        r = _req(method, path, **kw)
    except OSError:
        _cache["alive"] = 0
        start()
        r = _req(method, path, **kw)
    _cache["alive"] = time.time()
    return r


def webapi_version():
    if "webapi" not in _cache:
        _cache["webapi"] = str(api("GET", "/api/v2/app/webapiVersion"))
    return _cache["webapi"]


# ---- torrents -------------------------------------------------------------------------------------
STATES = {
    "downloading": "Downloading", "forcedDL": "Downloading (forced)", "metaDL": "Getting info…", "forcedMetaDL": "Getting info…",
    "stalledDL": "Waiting for peers", "queuedDL": "Queued", "pausedDL": "Paused", "stoppedDL": "Paused",
    "uploading": "Seeding", "forcedUP": "Seeding (forced)", "stalledUP": "Seeding", "queuedUP": "Queued to seed",
    "pausedUP": "Done", "stoppedUP": "Done", "checkingDL": "Checking…", "checkingUP": "Checking…", "checkingResumeData": "Checking…",
    "moving": "Moving…", "error": "Error", "missingFiles": "Files missing", "allocating": "Allocating…",
}


def torrents(filt="all"):
    out = []
    for t in api("GET", "/api/v2/torrents/info", params={"filter": filt, "sort": "added_on", "reverse": "true"}) or []:
        st = t.get("state", "")
        out.append({"hash": t["hash"], "name": t.get("name", ""), "progress": round(float(t.get("progress", 0)), 4),
                    "size": t.get("size", 0), "dlspeed": t.get("dlspeed", 0), "upspeed": t.get("upspeed", 0),
                    "eta": t.get("eta", 8640000), "state": st, "state_name": STATES.get(st, st), "seeds": t.get("num_seeds", 0),
                    "peers": t.get("num_leechs", 0), "ratio": round(float(t.get("ratio", 0)), 2), "save_path": t.get("save_path", ""),
                    "paused": st.startswith(("paused", "stopped")), "done": float(t.get("progress", 0)) >= 1,
                    "sequential": bool(t.get("seq_dl")), "forced": bool(t.get("force_start")),
                    "dl_limit": t.get("dl_limit", 0), "up_limit": t.get("up_limit", 0), "category": t.get("category", "")})
    return out


def summary():
    if not running():
        return {"running": False, "available": available()}
    info = api("GET", "/api/v2/transfer/info")
    ts = torrents()
    p = api("GET", "/api/v2/app/preferences")
    iface = p.get("current_network_interface") or ""
    return {"running": True, "available": True, "dl": info.get("dl_info_speed", 0), "up": info.get("up_info_speed", 0),
            "status": info.get("connection_status", ""), "count": len(ts),
            "active": sum(1 for t in ts if t["dlspeed"] or t["upspeed"]),
            "downloading": sum(1 for t in ts if not t["done"] and not t["paused"]),
            "interface": iface, "vpn_bound": iface in ("cbvpn", "cbtun"), "listen_port": p.get("listen_port"),
            "alt_speed": bool(api("GET", "/api/v2/transfer/speedLimitsMode") in (1, "1"))}


def add(urls=None, path=None, save_path=None, paused=False, sequential=False):
    data = {"savepath": save_path or "", "sequentialDownload": "true" if sequential else "false"}
    stopped_key = "stopped" if _version_tuple(webapi_version()) >= (2, 11) else "paused"
    data[stopped_key] = "true" if paused else "false"
    if path:
        from . import media
        path = os.path.realpath(path)
        if not media.allowed(path) or not path.lower().endswith(".torrent"):
            raise PermissionError("That file can't be added")
        with open(path, "rb") as f:
            blob = f.read(20 * 1024 * 1024)
        r = api("POST", "/api/v2/torrents/add", data=data, files={"torrents": (os.path.basename(path), blob)})
    else:
        links = [u.strip() for u in (urls if isinstance(urls, list) else [urls or ""]) if u and u.strip()]
        if not links or not all(re.match(r"^(magnet:\?|https?://|bc://bt/)", u, re.I) for u in links):
            raise ValueError("That isn't a magnet link or torrent address")
        data["urls"] = "\n".join(links)
        r = api("POST", "/api/v2/torrents/add", data=data)
    if isinstance(r, str) and r.strip().lower().startswith("fail"):
        raise TorrentError("The torrent engine didn't accept it (already added, or not a torrent)")
    return {"ok": True}


def action(hashes, what, **kw):
    hashes = [h for h in (hashes if isinstance(hashes, list) else [hashes]) if re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}|all", h)]
    if not hashes:
        raise ValueError("torrent")
    h = "|".join(hashes)
    new = _version_tuple(webapi_version()) >= (2, 11)
    simple = {"pause": "stop" if new else "pause", "resume": "start" if new else "resume", "recheck": "recheck",
              "reannounce": "reannounce", "sequential": "toggleSequentialDownload", "first_last": "toggleFirstLastPiecePrio",
              "top": "topPrio", "bottom": "bottomPrio", "up": "increasePrio", "down": "decreasePrio"}
    if what in simple:
        api("POST", f"/api/v2/torrents/{simple[what]}", data={"hashes": h})
    elif what == "force":
        api("POST", "/api/v2/torrents/setForceStart", data={"hashes": h, "value": "true" if kw.get("on", True) else "false"})
    elif what == "delete":
        api("POST", "/api/v2/torrents/delete", data={"hashes": h, "deleteFiles": "true" if kw.get("files") else "false"})
    elif what == "limit":
        api("POST", "/api/v2/torrents/setDownloadLimit", data={"hashes": h, "limit": int(kw.get("dl", 0))})
        api("POST", "/api/v2/torrents/setUploadLimit", data={"hashes": h, "limit": int(kw.get("up", 0))})
    elif what == "move":
        api("POST", "/api/v2/torrents/setLocation", data={"hashes": h, "location": _check_dir(kw.get("path"))})
    else:
        raise ValueError(what)
    return {"ok": True}


def files(h):
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", h or ""):
        raise ValueError("torrent")
    return [{"index": f.get("index", i), "name": f["name"], "size": f.get("size", 0), "progress": round(float(f.get("progress", 0)), 4),
             "priority": f.get("priority", 1)} for i, f in enumerate(api("GET", "/api/v2/torrents/files", params={"hash": h}) or [])]


def set_file_priority(h, ids, priority):
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", h or "") or int(priority) not in (0, 1, 6, 7):
        raise ValueError("file")
    api("POST", "/api/v2/torrents/filePrio", data={"hash": h, "id": "|".join(str(int(i)) for i in ids), "priority": int(priority)})
    return files(h)


def _check_dir(path):
    from . import media
    path = os.path.realpath(os.path.expanduser(path or ""))
    if not path or not media.allowed(path):
        raise PermissionError("That folder isn't allowed")
    os.makedirs(path, exist_ok=True)
    return path


def finished_since_last():
    """Names of torrents that finished since the last call (for "Download finished" notices)."""
    if not running():
        return []
    out = []
    for t in torrents("completed"):
        if t["hash"] not in _seen_done:
            if _seen_done or _cache.get("done_init"):
                out.append(t["name"])
            _seen_done.add(t["hash"])
    _cache["done_init"] = True
    return out


# ---- settings (the ones you actually change, console-sized) -------------------------------------------
SETTINGS = ["save_path", "current_network_interface", "listen_port", "upnp", "dl_limit", "up_limit", "alt_dl_limit",
            "alt_up_limit", "queueing_enabled", "max_active_downloads", "max_active_uploads", "max_active_torrents",
            "max_ratio_enabled", "max_ratio", "max_seeding_time_enabled", "max_seeding_time", "max_ratio_act",
            "max_connec", "max_connec_per_torrent", "encryption", "anonymous_mode", "dht", "pex", "lsd",
            "start_paused_enabled", "add_stopped_enabled", "auto_delete_mode", "random_port", "incomplete_files_ext"]


def settings():
    p = api("GET", "/api/v2/app/preferences")
    out = {k: p.get(k) for k in SETTINGS if k in p}
    try:
        out["interfaces"] = [{"name": i.get("name") or i.get("value"), "value": i.get("value", "")}
                             for i in api("GET", "/api/v2/app/networkInterfaceList") or []]
    except TorrentError:
        out["interfaces"] = []
    loc = prefs_local()
    out["use_vpn_port"] = loc.get("use_vpn_port", True)
    out["autostart"] = bool(loc.get("autostart"))
    out["notify"] = loc.get("notify", True)
    out["vpn_only"] = bool(loc.get("vpn_only"))
    return out


def set_settings(**kw):
    local = {k: bool(kw.pop(k)) for k in ("use_vpn_port", "autostart", "notify", "vpn_only") if k in kw}
    if local:
        _set_local(**local)
    bad = [k for k in kw if k not in SETTINGS]
    if bad:
        raise ValueError(f"unknown setting: {bad[0]}")
    if "save_path" in kw:
        kw["save_path"] = _check_dir(kw["save_path"])
    for lim, flag in (("max_ratio", "max_ratio_enabled"), ("max_seeding_time", "max_seeding_time_enabled")):
        if lim in kw:                                      # "Never" (-1) turns the limit off
            kw[flag] = float(kw[lim]) >= 0
    if "current_network_interface" in kw and not re.fullmatch(r"[\w.\-]{0,15}", str(kw["current_network_interface"])):
        raise ValueError("interface")
    if "current_network_interface" in kw:
        kw["current_interface_address"] = ""
    if kw:
        api("POST", "/api/v2/app/setPreferences", data={"json": json.dumps(kw)})
    if "vpn_only" in local:
        _apply_vpn_binding()
        from . import vpn
        if vpn.split_on():                     # it has to start again inside (or outside) the VPN's group
            threading.Thread(target=lambda: (stop(), time.sleep(2), _safe(start)), daemon=True).start()
    return settings()


def toggle_alt_speed():
    api("POST", "/api/v2/transfer/toggleSpeedLimitsMode")
    return summary()


def _apply_vpn_binding():
    """"Only use the VPN": bound to the VPN's interface (WireGuard cbvpn / OpenVPN cbtun)."""
    if not prefs_local().get("vpn_only"):
        return
    from . import vpn
    iface = vpn.TUN if vpn.cfg().get("protocol") == "openvpn" else vpn.CONN
    try:
        _req("POST", "/api/v2/app/setPreferences", data={"json": json.dumps({"current_network_interface": iface,
                                                                             "current_interface_address": ""})})
    except (OSError, TorrentError):
        pass


def on_vpn_port(port):
    """The VPN forwarded a port (PIA / Proton): listen on it, so peers can reach us."""
    if not port or not prefs_local().get("use_vpn_port", True) or not running():
        return
    try:
        _req("POST", "/api/v2/app/setPreferences", data={"json": json.dumps({"listen_port": int(port), "random_port": False, "upnp": False})})
    except (OSError, TorrentError):
        pass


# ---- search ----------------------------------------------------------------------------------------
def plugins():
    out = []
    for p in api("GET", "/api/v2/search/plugins") or []:
        name = p.get("name", "")
        out.append({"name": name, "full_name": p.get("fullName") or name, "version": p.get("version", ""), "enabled": bool(p.get("enabled")),
                    "url": p.get("url", ""), "categories": [c.get("id") if isinstance(c, dict) else c for c in p.get("supportedCategories") or []],
                    "login": bool(plugin_fields(name))})
    return sorted(out, key=lambda p: p["full_name"].lower())


def install_plugin(url):
    if not re.match(r"^https?://\S+\.py$", url or "", re.I):
        raise ValueError("A search plugin is a link to a .py file")
    api("POST", "/api/v2/search/installPlugin", data={"sources": url})
    name = os.path.splitext(os.path.basename(urllib.parse.urlparse(url).path))[0]
    for _ in range(40):                       # it installs in the background
        time.sleep(0.5)
        hit = next((p for p in plugins() if p["name"] == name or p["url"] == url), None)
        if hit:
            return hit
    raise TorrentError("The plugin didn't install (it may not work with this qBittorrent version)")


def plugin_action(name, what, enable=True):
    if not re.fullmatch(r"[\w.\-]{1,80}", name or ""):
        raise ValueError("plugin")
    if what == "enable":
        api("POST", "/api/v2/search/enablePlugin", data={"names": name, "enable": "true" if enable else "false"})
    elif what == "remove":
        api("POST", "/api/v2/search/uninstallPlugin", data={"names": name})
    elif what == "update":
        api("POST", "/api/v2/search/updatePlugins")
    else:
        raise ValueError(what)
    return plugins()


def search_start(pattern, category="all", plugin_names="enabled"):
    pattern = (pattern or "").strip()[:200]
    if not pattern:
        raise ValueError("Type something to search for")
    if category not in CATEGORIES:
        category = "all"
    if not any(p["enabled"] for p in plugins()):
        raise TorrentError("No search plugins are on yet: Torrents › Search Plugins")
    r = api("POST", "/api/v2/search/start", data={"pattern": pattern, "plugins": plugin_names, "category": category})
    return {"id": r.get("id") if isinstance(r, dict) else r}


def search_results(sid, offset=0, limit=200):
    sid = int(sid)
    try:
        st = api("GET", "/api/v2/search/status", params={"id": sid})
    except TorrentError as e:
        if "not found" not in str(e):
            raise
        return {"running": False, "total": 0, "results": [], "expired": True}      # engine restarted: search gone
    running_ = bool(st and st[0].get("status") == "Running")
    r = api("GET", "/api/v2/search/results", params={"id": sid, "limit": limit, "offset": int(offset)}) or {}
    res = [{"name": x.get("fileName", ""), "url": x.get("fileUrl", ""), "size": x.get("fileSize", -1), "seeds": x.get("nbSeeders", -1),
            "peers": x.get("nbLeechers", -1), "site": x.get("siteUrl", ""), "page": x.get("descrLink", ""),
            "engine": x.get("engineName", "") or urllib.parse.urlparse(x.get("siteUrl", "")).netloc}
           for x in r.get("results", [])]
    res.sort(key=lambda x: -(x["seeds"] if isinstance(x["seeds"], int) else 0))
    return {"running": running_, "total": r.get("total", len(res)), "results": res}


def search_stop(sid):
    try:
        api("POST", "/api/v2/search/stop", data={"id": int(sid)})
        api("POST", "/api/v2/search/delete", data={"id": int(sid)})
    except TorrentError:
        pass
    return {"ok": True}


def download_result(url, engine=None, save_path=None):
    """A search result: through its plugin when the engine can (private sites need the plugin's
    sign-in to fetch the .torrent), else added by its link."""
    if engine and _version_tuple(webapi_version()) >= (2, 11):
        try:
            api("POST", "/api/v2/search/downloadTorrent", data={"url": url, "pluginName": engine})
            return {"ok": True}
        except TorrentError:
            pass
    return add(urls=[url], save_path=save_path)


# ---- the community plugin list (qBittorrent wiki), and plugin sign-ins ------------------------------------
def _cell_text(cell):
    cell = re.sub(r"\[\[[^\]]*\]\]", "", cell)                                   # icons
    cell = re.sub(r"\[(https?://\S+)\s+([^\]]*)\]", r"\2", cell)                 # [url text] -> text
    cell = re.sub(r"<br\s*/?>", " · ", cell)
    cell = re.sub(r"<[^>]+>|'''|''|\*\*", "", cell)
    return re.sub(r"\s+", " ", cell).strip(" ·")


def parse_wiki(text):
    out = []
    section = None
    for block in re.split(r"\n\|-\s*\n", text):
        heads = re.findall(r"^==\s*(.+?)\s*==\s*$", block, re.M)
        if heads:
            section = heads[-1]
        lines = [ln for ln in block.split("\n") if ln.startswith("|") and not ln.startswith(("|}", "|-", "{|"))]
        if len(lines) < 5:
            continue
        cells = [ln[1:].strip() for ln in lines]
        dl = re.search(r"\[(https?://\S+?\.py)\s", cells[4] + " ")
        if not dl:
            continue
        site = re.search(r"\[(https?://[^\s\]]+)\s+([^\]\[]+)\]", re.sub(r"\[\[[^\]]*\]\]", "", cells[0]))
        comments = _cell_text(cells[5]) if len(cells) > 5 else ""
        private = bool(section and "private" in section.lower())
        login = private or bool(re.search(r"login|cookie|api ?key|passkey|account|credential|password|jackett", comments, re.I))
        help_url = re.search(r"\[(https?://\S+)\s+\[\[[^\]]*Help", cells[4])
        out.append({"name": site.group(2).strip() if site else _cell_text(cells[0]), "site": site.group(1) if site else "",
                    "author": _cell_text(cells[1]), "version": _cell_text(cells[2]), "updated": _cell_text(cells[3]),
                    "url": dl.group(1), "comments": comments, "private": private, "login": login,
                    "broken": "❌" in cells[5] if len(cells) > 5 else False,
                    "help": help_url.group(1) if help_url else ""})
    return out


def unofficial_plugins():
    if _cache.get("wiki") and time.time() - _cache["wiki"][0] < 86400:
        return _cache["wiki"][1]
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(WIKI, headers={"User-Agent": "Crossbar"}), timeout=20) as r:
            text = r.read().decode(errors="replace")
    except (OSError, ValueError) as e:
        raise util.friendly_net_error(WIKI, e) from None
    lst = parse_wiki(text)
    _cache["wiki"] = (time.time(), lst)
    return lst


def official_plugins():
    if _cache.get("official") and time.time() - _cache["official"][0] < 86400:
        return _cache["official"][1]
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(OFFICIAL + "versions.txt", headers={"User-Agent": "Crossbar"}), timeout=20) as r:
            text = r.read().decode(errors="replace")
    except (OSError, ValueError) as e:
        raise util.friendly_net_error(OFFICIAL, e) from None
    lst = []
    for ln in text.splitlines():
        m = re.match(r"^\s*([\w]+)\s*:\s*([\d.]+)", ln)
        if m:
            lst.append({"name": m.group(1), "version": m.group(2), "url": f"{OFFICIAL}{m.group(1)}.py"})
    _cache["official"] = (time.time(), lst)
    return lst


CRED = r"(user(?:_?name)?|login|e?mail|pass(?:word|wd|key)?|api_?key|apikey|token|cookies?|uid|secret)"
_PY_ASSIGN = re.compile(r"^(?P<indent>[ \t]*)(?P<name>[A-Za-z_]*" + CRED + r"[A-Za-z_0-9]*)\s*(?::\s*str\s*)?=\s*(?P<q>['\"])(?P<val>[^'\"\n]*)(?P=q)",
                        re.I | re.M)
_PY_DICT = re.compile(r"(?P<kq>['\"])(?P<name>" + CRED + r")(?P=kq)\s*:\s*(?P<q>['\"])(?P<val>[^'\"\n]*)(?P=q)", re.I)


def _engines_dirs():
    return [d for d in glob.glob(os.path.join(PROFILE, "**", "nova3", "engines"), recursive=True) if os.path.isdir(d)]


def _plugin_files(name):
    for d in _engines_dirs():
        py = os.path.join(d, f"{name}.py")
        if os.path.isfile(py):
            return py, os.path.join(d, f"{name}.json")
    return None, None


def plugin_fields(name):
    """The sign-in a plugin needs: [{key, label, secret, set}] found in its .json config or in its
    code (username = "" …). Values are never sent back to the screen, only whether they're set."""
    if not re.fullmatch(r"[\w.\-]{1,80}", name or ""):
        return []
    py, js = _plugin_files(name)
    if not py:
        return []
    fields, seen = [], set()

    def add(key, val, where):
        k = key.lower()
        if k in seen:
            return
        seen.add(k)
        fields.append({"key": key, "where": where, "set": bool(val) and not re.fullmatch(r"(your|my)?_?(user(name)?|pass(word)?|key|email)?", val, re.I),
                       "secret": bool(re.search(r"pass|key|token|cookie|secret", key, re.I)),
                       "label": re.sub(r"_", " ", key).strip().title().replace("Api", "API").replace("Uid", "UID")})
    if js and os.path.isfile(js):
        try:
            with open(js) as f:
                data = json.load(f)
            for k, v in (data.items() if isinstance(data, dict) else []):
                if isinstance(v, str) and re.fullmatch(r"[A-Za-z_0-9]*" + CRED + r"[A-Za-z_0-9]*", k, re.I):
                    add(k, v, "json")
        except (OSError, ValueError):
            pass
    try:
        with open(py, errors="replace") as f:
            src = f.read()
    except OSError:
        return fields
    for m in _PY_ASSIGN.finditer(src):
        if not re.search(r"url|path|file|agent|header|domain|host", m.group("name"), re.I):
            add(m.group("name"), m.group("val"), "py")
    for m in _PY_DICT.finditer(src):
        add(m.group("name"), m.group("val"), "pydict")
    return fields[:8]


def set_plugin_login(name, values):
    """Write a plugin's sign-in into its .json config or its code, where it keeps it."""
    fields = {f["key"]: f for f in plugin_fields(name)}
    if not fields:
        raise TorrentError("This plugin has no sign-in to fill in (see its help page)")
    py, js = _plugin_files(name)
    values = {k: str(v) for k, v in (values or {}).items() if k in fields and v is not None and str(v) != ""}
    if not values:
        return plugin_fields(name)
    for v in values.values():
        if "\n" in v or len(v) > 4000:
            raise ValueError("That value can't be used")
    if any(fields[k]["where"] == "json" for k in values) and js:
        with open(js) as f:
            data = json.load(f)
        for k, v in values.items():
            if fields[k]["where"] == "json":
                data[k] = v
        with open(js, "w") as f:
            json.dump(data, f, indent=2)
    code_vals = {k: v for k, v in values.items() if fields[k]["where"] in ("py", "pydict")}
    if code_vals:
        with open(py, errors="replace") as f:
            src = f.read()
        for k, v in code_vals.items():
            lit = json.dumps(v)                                  # a valid Python string literal too
            if fields[k]["where"] == "py":
                pat = re.compile(r"^([ \t]*" + re.escape(k) + r"\s*(?::\s*str\s*)?=\s*)(['\"])[^'\"\n]*\2", re.M)
            else:
                pat = re.compile(r"((['\"])" + re.escape(k) + r"\2\s*:\s*)(['\"])[^'\"\n]*\3")
            src = pat.sub(lambda m: m.group(1) + lit, src, count=1)
        with open(py + ".tmp", "w") as f:
            f.write(src)
        os.replace(py + ".tmp", py)
    return plugin_fields(name)


def autostart():
    """At Crossbar start: keep seeding if asked to."""
    if prefs_local().get("autostart") and available():
        threading.Thread(target=lambda: _safe(start), daemon=True).start()


def _safe(fn):
    try:
        fn()
    except Exception as e:
        print(f"torrent: {e}", flush=True)
