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
            _apply_vpn_binding(rebind=True)
            try:                                          # a port the VPN already forwards
                from . import vpn as _v
                if _v._state.get("pf_port"):
                    on_vpn_port(_v._state["pf_port"])
            except Exception:
                pass
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


def _apply_vpn_binding(rebind=False):
    """"Only use the VPN": bound to the VPN's interface (WireGuard cbvpn / OpenVPN cbtun) and its
    current address. Each connection gets a new address (PIA hands one out per connection), and
    the engine doesn't always notice, so on (re)connect it's given the new one explicitly: the
    changed setting makes it reopen its connections there."""
    if not prefs_local().get("vpn_only"):
        return
    from . import vpn
    iface = vpn.TUN if vpn.cfg().get("protocol") == "openvpn" else vpn.CONN
    addr = ""
    if rebind and vpn.nm_state() == "activated":
        addr = vpn._vpn_addr() or ""
    try:
        if not running():
            return
        cur = _req("GET", "/api/v2/app/preferences") or {}
        if cur.get("current_network_interface") == iface and cur.get("current_interface_address", "") == addr and not rebind:
            return
        _req("POST", "/api/v2/app/setPreferences", data={"json": json.dumps({"current_network_interface": iface,
                                                                             "current_interface_address": addr})})
        if rebind:
            _req("POST", "/api/v2/torrents/reannounce", data={"hashes": "all"})
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
    out = sorted(out, key=lambda p: p["full_name"].lower())
    _cache["plugins_list"] = out
    return out


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


# Searches run qBittorrent's own search runner (nova3/nova2.py, the one its search tab uses) with
# your plugins, here, rather than through the Web API: the API keeps searches per login session,
# which a headless engine with no login doesn't hold on to, so results came back "not found" or
# empty. Same plugins, same results; each search runs in the background and its results stream in.
_searches = {}
_sid = [0]


def _nova_dir():
    for d in _engines_dirs():
        nova = os.path.dirname(d)
        if os.path.isfile(os.path.join(nova, "nova2.py")):
            return nova
    return None


def search_start(pattern, category="all", plugin_names=None):
    pattern = (pattern or "").strip()[:200]
    if not pattern:
        raise ValueError("Type something to search for")
    if category not in CATEGORIES:
        category = "all"
    pl = plugins()
    names = [p["name"] for p in pl if p["enabled"]] if not plugin_names else \
        [n for n in plugin_names if n in {p["name"] for p in pl}]
    if not names:
        raise TorrentError("No search plugins are on: Torrents › Search › Search With")
    if category != "all":                       # a plugin that doesn't have this category is skipped by the runner
        cats = {p["name"]: p["categories"] for p in pl}
        fit = [n for n in names if not cats.get(n) or category in cats[n]]
        if not fit:
            raise TorrentError(f"None of your search plugins have a “{category}” category: search Everything instead")
        names = fit
    nova = _nova_dir()
    if not nova:
        raise TorrentError("The search engine files aren't there yet: reinstall a plugin (Search Plugins)")
    from . import vpn
    _sid[0] += 1
    sid = _sid[0]
    probe = vpn.wrap(["x"], "torrents")
    st = {"results": [], "running": True, "errors": [], "started": time.time(), "engines": names, "pattern": pattern,
          "per": {n: {"count": 0, "running": True, "error": ""} for n in names}, "procs": [],
          "via_vpn": probe[1:2] == [vpn.VPNRUN]}
    _searches[sid] = st
    for old in [k for k, v in _searches.items() if k < sid - 8]:      # keep the last few
        _searches.pop(old, None)
    # Each plugin runs on its own (a few at a time): one slow or broken site can't hold up or hide the
    # others, every result is credited to the plugin that found it, and each plugin's own error is
    # kept. The small runner below does what qBittorrent's nova2.py does for one engine — without
    # nova2's lower-casing of names, which left plugins whose file names have capitals unmatched.
    words = pattern.split()

    def run_one(name):
        import sys
        per = st["per"][name]
        argv = vpn.wrap([sys.executable or "python3", "-c", RUNNER, name, category, *words], "torrents")
        env = {**os.environ, "PYTHONWARNINGS": "ignore", "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            p = subprocess.Popen(argv, cwd=nova, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, encoding="utf-8", errors="replace", start_new_session=True, env=env)
        except OSError as e:
            per.update(running=False, error=str(e)[:160])
            return
        st["procs"].append(p)
        errs = []

        def read_err():
            for line in p.stderr:
                line = line.strip()
                if line and not re.search(r"Warning:|warnings\.warn|resource_tracker", line):
                    errs.append(line)
        t = threading.Thread(target=read_err, daemon=True)
        t.start()
        deadline = threading.Timer(PLUGIN_TIMEOUT, lambda: _kill(p))     # a plugin that hangs doesn't keep it "searching"
        deadline.start()
        for line in p.stdout:
            r = parse_result(line, [name])
            if r:
                st["results"].append(r)
                per["count"] += 1
        p.wait()
        deadline.cancel()
        t.join(2)
        mine = [e[6:] for e in errs if e.startswith("CBERR ")]
        last = mine[-1] if mine else next((e for e in reversed(errs) if not e.startswith(("Traceback", "File ", "^", "~"))), "")
        if p.returncode in (-15, -9) and not per["count"]:
            last = f"took too long ({PLUGIN_TIMEOUT} s)"
        per.update(running=False, error="" if per["count"] else last[:200])
        if last and not per["count"]:
            st["errors"] = (st["errors"] + [f"{name}: {last[:200]}"])[-8:]

    def run_all():
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(6, len(names))) as ex:
            list(ex.map(run_one, names))
        if not st["results"]:
            st["net"] = net_check(pl, names, st["via_vpn"])      # no results: is it the plugins or the network?
        st["running"] = False
    threading.Thread(target=run_all, daemon=True).start()
    return {"id": sid, "engines": names}


PLUGIN_TIMEOUT = 60


def _kill(p):
    try:
        os.killpg(p.pid, 15)
    except OSError:
        pass


RUNNER = r"""
import importlib, sys, traceback, urllib.parse
sys.path.insert(0, ".")
name, cat = sys.argv[1], sys.argv[2]
what = urllib.parse.quote(" ".join(sys.argv[3:]))
try:
    mod = importlib.import_module("engines." + name)
    cls = getattr(mod, name, None) or next((v for k, v in vars(mod).items()          # class named differently
                                             if isinstance(v, type) and hasattr(v, "search") and hasattr(v, "url")), None)
    if cls is None:
        raise ImportError("no search class in it")
    eng = cls()
except Exception as e:
    print("CBERR couldn't load the plugin: %s: %s" % (type(e).__name__, str(e)[:160]), file=sys.stderr)
    sys.exit(3)
cats = getattr(eng, "supported_categories", {"all": ""}) or {"all": ""}
if cat != "all" and cat not in cats:
    print("CBERR no %s category" % cat, file=sys.stderr)
    sys.exit(4)
try:
    eng.search(what, cat)
except Exception as e:
    msg = str(e)[:160]
    if "403" in msg or "Forbidden" in msg:
        msg += " (the site blocks it: often Cloudflare)"
    print("CBERR %s: %s" % (type(e).__name__, msg), file=sys.stderr)
    sys.exit(5)
"""


def parse_result(line, engines=None):
    """One line from novaprinter: link|name(quoted)|size|seeds|leech|engine_url|desc_link|pub_date."""
    parts = line.rstrip("\n").split("|")
    if len(parts) < 6 or not parts[0]:
        return None

    def num(x):
        try:
            return int(float(x))
        except ValueError:
            return -1
    date = num(parts[7]) if len(parts) > 7 else -1
    if date > 10 ** 11:                                  # milliseconds from some plugins
        date //= 1000
    return {"url": parts[0], "name": urllib.parse.unquote(parts[1]), "size": num(parts[2]), "seeds": num(parts[3]),
            "peers": num(parts[4]), "site": parts[5], "page": parts[6] if len(parts) > 6 else "", "date": date if date > 0 else -1,
            "engine": engines[0] if engines and len(engines) == 1 else _engine_for_site(parts[5])}


def _engine_for_site(site):
    try:
        for p in _cache.get("plugins_list") or plugins():
            a, b = urllib.parse.urlparse(p.get("url") or "").netloc, urllib.parse.urlparse(site or "").netloc
            if a and b and (a == b or a.endswith("." + b) or b.endswith("." + a)):
                return p["name"]
    except Exception:
        pass
    return urllib.parse.urlparse(site).netloc


SORTS = {  # key: (label, field, biggest first by default)
    "seeds": ("Seeds", "seeds", True), "peers": ("Leechers", "peers", True), "size": ("File Size", "size", True),
    "date": ("Upload Date", "date", True), "name": ("Name", "name", False), "site": ("Site", "engine", False),
}


def sort_results(res, sort="seeds", desc=None):
    label, field, big_first = SORTS.get(sort, SORTS["seeds"])
    desc = big_first if desc is None else bool(desc)
    if field in ("name", "engine"):
        key = lambda x: (str(x.get(field) or "").lower(), -(x["seeds"] if x["seeds"] >= 0 else 0))
        return sorted(res, key=key, reverse=desc)
    known = [x for x in res if isinstance(x.get(field), int) and x[field] >= 0]
    unknown = [x for x in res if not (isinstance(x.get(field), int) and x[field] >= 0)]
    # ties: more seeds first; results without that number (a plugin that doesn't give dates) go last
    known.sort(key=lambda x: (x[field], x["seeds"]), reverse=desc)
    return known + sorted(unknown, key=lambda x: -(x["seeds"] if x["seeds"] >= 0 else 0))


def search_results(sid, offset=0, limit=200, sort="seeds", desc=None):
    st = _searches.get(int(sid))
    if not st:
        return {"running": False, "total": 0, "results": [], "expired": True, "errors": []}
    res = sort_results(list(st["results"]), sort, desc)
    errs = []
    if not st["running"] and not res and st["errors"]:
        errs = [e for e in st["errors"] if not e.startswith(("Traceback", "File ", "^"))][-2:] or st["errors"][-1:]
    label, _f, big_first = SORTS.get(sort, SORTS["seeds"])
    return {"running": st["running"], "total": len(res), "results": res[int(offset):int(offset) + limit], "errors": errs,
            "engines": st["engines"], "sort": sort if sort in SORTS else "seeds", "sort_label": label,
            "desc": big_first if desc is None else bool(desc), "has_dates": any(x.get("date", -1) > 0 for x in res),
            "net": st.get("net"), "via_vpn": st.get("via_vpn"), "elapsed": round(time.time() - st["started"]),
            "per": st.get("per") or {}}


NET_PROBE = r'''
import json, socket, sys, time
out = {}
for host in sys.argv[1:4]:
    t = time.time()
    try:
        ip = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        out[host] = {"dns": "ok", "ip": ip}
        try:
            socket.create_connection((ip, 443), timeout=8).close()
            out[host]["connect"] = "ok"
        except OSError as e:
            out[host]["connect"] = str(e)[:80]
    except OSError as e:
        out[host] = {"dns": f"failed ({time.time() - t:.0f} s): {str(e)[:60]}"}
print(json.dumps(out))
'''


def net_check(pl, names, via_vpn):
    """Can the search reach the plugins' sites from where it runs (through the VPN, when it does)?
    {"ok": bool, "summary": "...", "hosts": {...}}"""
    import sys
    from . import vpn
    hosts = []
    for p in pl:
        if p["name"] in names:
            h = urllib.parse.urlparse(p.get("url") or "").hostname
            if h and h not in hosts:
                hosts.append(h)
    hosts = (hosts or ["www.google.com"])[:3]
    argv = [sys.executable or "python3", "-c", NET_PROBE, *hosts]
    if via_vpn:
        argv = vpn.wrap(argv, "torrents")
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=40, cwd="/")
        res = json.loads((r.stdout.strip().splitlines() or ["{}"])[-1])
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        return {"ok": False, "summary": f"Couldn't test the connection: {e}", "hosts": {}}
    dns_bad = [h for h, v in res.items() if v.get("dns") != "ok"]
    conn_bad = [h for h, v in res.items() if v.get("dns") == "ok" and v.get("connect") != "ok"]
    where = "through the VPN" if via_vpn else "from this console"
    if res and len(dns_bad) == len(res):
        summary = f"Site names can't be looked up {where} (DNS isn't working): " + ("check VPN › Leak Tests › Check Split Tunneling" if via_vpn else "check the network")
    elif res and len(conn_bad) + len(dns_bad) == len(res):
        summary = f"The plugins' sites can't be reached {where}" + (" (the VPN may be blocking them, or the tunnel is down)" if via_vpn else "")
    else:
        summary = f"The connection {where} works: the plugins found nothing, or their sites changed (Search Plugins › Update All)"
    return {"ok": not (dns_bad or conn_bad), "summary": summary, "hosts": res}


def search_stop(sid):
    st = _searches.get(int(sid))
    for p in (st or {}).get("procs", []):
        if p.poll() is None:
            _kill(p)
    return {"ok": True}


def download_result(url, engine=None, save_path=None):
    """A search result: a magnet link is added as it is; a .torrent link is fetched by its plugin
    (nova2dl.py, as qBittorrent does), so private sites' sign-ins and cookies are used."""
    if url.lower().startswith("magnet:"):
        return add(urls=[url], save_path=save_path)
    nova = _nova_dir()
    if nova and engine and re.fullmatch(r"[\w.\-]{1,80}", engine) and os.path.isfile(os.path.join(nova, "nova2dl.py")):
        import sys
        from . import vpn
        try:
            r = subprocess.run(vpn.wrap([sys.executable or "python3", "nova2dl.py", engine, url], "torrents"), cwd=nova,
                               capture_output=True, text=True, timeout=60)
            first = (r.stdout.strip().splitlines() or [""])[0]
            path = first.split(" ", 1)[0]
            if r.returncode == 0 and path and os.path.isfile(path):
                try:
                    with open(path, "rb") as f:
                        blob = f.read(20 * 1024 * 1024)
                    data = {"savepath": save_path or ""}
                    out = api("POST", "/api/v2/torrents/add", data=data, files={"torrents": (os.path.basename(path) + ".torrent", blob)})
                    if not (isinstance(out, str) and out.strip().lower().startswith("fail")):
                        return {"ok": True}
                finally:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
        except (OSError, subprocess.TimeoutExpired):
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
