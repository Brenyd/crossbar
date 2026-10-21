"""Jackett (Apps › Torrents › Jackett): one search across hundreds of torrent sites — public, semi-
private and private ones with your account — through Jackett (github.com/Jackett/Jackett, GPL-2.0),
set up entirely from the controller.

Crossbar doesn't ship Jackett: Install downloads the official self-contained Linux build from
Jackett's GitHub releases into ~/.local/share/crossbar/jackett and runs it as you, on
127.0.0.1:9117 only, with its settings in Jackett's usual place (~/.config/Jackett). A Jackett you
already run (the AUR package's service, say) is used as it is.

Everything goes through the same API Jackett's own web page uses:
  GET  /api/v2.0/indexers?configured=false        every tracker it knows
  GET  /api/v2.0/indexers/<id>/Config             a tracker's settings form (a list of items)
  POST /api/v2.0/indexers/<id>/Config             save it (Jackett signs in / tests the tracker)
  POST /api/v2.0/indexers/<id>/Test, DELETE /api/v2.0/indexers/<id>
  GET  /api/v2.0/indexers/all/results?apikey=…    search every configured tracker (JSON)
  GET  /dl/<id>?jackett_apikey=…                   a result's .torrent, or a redirect to its magnet
Those need Jackett's sign-in cookie: with no admin password Jackett hands it out on /UI/Login;
with one, Crossbar signs in with it (kept in a 0600 file).

Torrent search uses Jackett as one more source ("Jackett", in Search's Options), with each of its
trackers' results and errors shown like a plugin's.
"""
import http.cookiejar
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import util

PORT = 9117
BASE = f"http://127.0.0.1:{PORT}"
HOME_DIR = os.path.join(util.HOME, ".local", "share", "crossbar", "jackett")
DATA = os.path.join(util.HOME, ".config", "Jackett")
SECRETS = os.path.join(util.CONFIG_DIR, "jackett-secrets.json")
RELEASES = "https://api.github.com/repos/Jackett/Jackett/releases/latest"
NAME = "cb_jackett"                      # its name among the search plugins

# Crossbar's search categories → Torznab category ids
CATS = {"all": [], "movies": [2000], "tv": [5000], "music": [3000], "games": [1000, 4050], "anime": [5070],
        "software": [4000], "pictures": [], "books": [7000, 8000]}
TYPES = {"public": "Public", "semi-private": "Semi-Private", "private": "Private"}

_state = {"proc": None, "session": None, "apikey": None}
_lock = threading.Lock()


class JackettError(RuntimeError):
    pass


# ---- settings ------------------------------------------------------------------------------------------
def prefs():
    c = util.load_config().get("jackett")
    return c if isinstance(c, dict) else {}


def _set(**kw):
    util.update_config(lambda c: c.setdefault("jackett", {}).update(kw))


def _secret():
    try:
        with open(SECRETS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_secret(**kw):
    s = {**_secret(), **kw}
    os.makedirs(os.path.dirname(SECRETS), exist_ok=True)
    fd = os.open(SECRETS + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(s, f)
    os.replace(SECRETS + ".tmp", SECRETS)


# ---- the program ---------------------------------------------------------------------------------------
def _ours():
    p = os.path.join(HOME_DIR, "Jackett", "jackett")
    return p if os.access(p, os.X_OK) else None


def binary():
    """Crossbar's copy, else one installed on the system (AUR jackett / jackett-bin)."""
    for p in (_ours(), "/usr/lib/jackett/jackett", "/opt/Jackett/jackett", util.which("jackett")):
        if p and os.access(p, os.X_OK):
            return p
    return None


def version():
    try:
        with open(os.path.join(HOME_DIR, "VERSION")) as f:
            return f.read().strip()
    except OSError:
        return None


def _asset_name():
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "Jackett.Binaries.LinuxAMDx64.tar.gz"
    if m in ("aarch64", "arm64"):
        return "Jackett.Binaries.LinuxARM64.tar.gz"
    if m.startswith("arm"):
        return "Jackett.Binaries.LinuxARM32.tar.gz"
    raise JackettError(f"Jackett has no build for this processor ({m})")


def install(job):
    """Download the newest official build and put it in place (an update keeps your trackers:
    they live in ~/.config/Jackett)."""
    job.set(0.02, "Asking GitHub for the newest Jackett…")
    try:
        with urllib.request.urlopen(urllib.request.Request(RELEASES, headers={"User-Agent": "Crossbar", "Accept": "application/vnd.github+json"}),
                                    timeout=30) as r:
            rel = json.loads(r.read().decode())
    except (OSError, ValueError) as e:
        raise util.friendly_net_error(RELEASES, e) from None
    want = _asset_name()
    asset = next((a for a in rel.get("assets") or [] if a.get("name") == want), None)
    if not asset:
        raise JackettError(f"Jackett {rel.get('tag_name', '')} has no {want} download")
    os.makedirs(HOME_DIR, exist_ok=True)
    tmp = os.path.join(HOME_DIR, ".download.tar.gz")
    req = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "Crossbar"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or asset.get("size") or 0)
            done = 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                job.set_bytes(done, total, f"Downloading Jackett {rel.get('tag_name', '')}")
    except (OSError, ValueError) as e:
        raise util.friendly_net_error(asset["browser_download_url"], e) from None
    job.set(0.9, "Unpacking…")
    new = os.path.join(HOME_DIR, ".new")
    shutil.rmtree(new, ignore_errors=True)
    os.makedirs(new)
    with tarfile.open(tmp) as t:
        for m in t.getmembers():                       # nothing outside the folder, no device files
            if m.name.startswith(("/", "..")) or "/../" in m.name or not (m.isfile() or m.isdir() or m.issym()):
                raise JackettError("The Jackett download looks wrong (unsafe paths): not installed")
        t.extractall(new, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(new)
    if not os.path.isfile(os.path.join(new, "Jackett", "jackett")):
        raise JackettError("The Jackett download didn't contain the program")
    was_running = running()
    if was_running:
        stop()
    old = os.path.join(HOME_DIR, "Jackett")
    shutil.rmtree(old, ignore_errors=True)
    os.replace(os.path.join(new, "Jackett"), old)
    shutil.rmtree(new, ignore_errors=True)
    os.remove(tmp)
    os.chmod(os.path.join(old, "jackett"), 0o755)
    with open(os.path.join(HOME_DIR, "VERSION"), "w") as f:
        f.write(rel.get("tag_name", "").lstrip("v"))
    job.set(0.97, "Starting Jackett…")
    start()
    job.set(1.0, f"Jackett {version()} is ready")


def running():
    try:
        with urllib.request.urlopen(f"{BASE}/health", timeout=2) as r:
            return r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except OSError:
        return False


def start():
    """Start Jackett if it isn't running (as you, on this machine only; through the VPN when
    Torrents uses it, since Jackett is what talks to the torrent sites)."""
    if running():
        return True
    b = binary()
    if not b:
        raise JackettError("Jackett isn't installed: Torrents › Jackett › Install Jackett")
    from . import vpn
    argv = [b, "--NoUpdates", "--NoRestart"]
    if vpn.uses_vpn("torrents"):
        argv = vpn.wrap(argv, "torrents")
    env = {**os.environ, "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT": "1"}     # no ICU needed
    os.makedirs(os.path.join(util.HOME, ".cache"), exist_ok=True)
    log = open(os.path.join(util.HOME, ".cache", "crossbar-jackett.log"), "a")
    _state["proc"] = subprocess.Popen(argv, cwd=os.path.dirname(b), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                      start_new_session=True, env=env)
    _state["session"] = None
    for _ in range(120):                                # a first start sets itself up: give it a minute
        time.sleep(0.5)
        if running():
            return True
        if _state["proc"].poll() is not None:
            raise JackettError("Jackett stopped right away (see ~/.cache/crossbar-jackett.log)")
    raise JackettError("Jackett didn't start within a minute (see ~/.cache/crossbar-jackett.log)")


def stop():
    key = _state.get("apikey") or _file_apikey()
    try:
        urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/v2.0/server/Shutdown?apikey={urllib.parse.quote(key or '')}",
                                                      data=b"", method="POST"), timeout=5)
    except OSError:
        pass
    p = _state.get("proc")
    if p and p.poll() is None:
        try:
            p.terminate()
            p.wait(10)
        except Exception:
            p.kill()
    _state.update(proc=None, session=None)
    return {"running": running()}


def _file_apikey():
    for d in (DATA, "/var/lib/jackett", "/usr/lib/jackett"):
        try:
            with open(os.path.join(d, "ServerConfig.json"), encoding="utf-8-sig") as f:
                k = json.load(f).get("APIKey")
                if k:
                    return k
        except (OSError, ValueError):
            continue
    return None


# ---- talking to it -------------------------------------------------------------------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _session():
    """An opener holding Jackett's sign-in cookie."""
    with _lock:
        if _state.get("session"):
            return _state["session"]
        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        op.addheaders = [("User-Agent", "Crossbar")]
        pw = _secret().get("admin_password") or ""
        try:
            # no admin password: Jackett signs you in on the way through Login → TestCookie → Login
            op.open(f"{BASE}/UI/Login", timeout=15).read()
            if pw:
                op.open(urllib.request.Request(f"{BASE}/UI/Dashboard", data=urllib.parse.urlencode({"password": pw}).encode()),
                        timeout=15).read()
        except urllib.error.HTTPError:
            pass
        except OSError as e:
            raise JackettError(f"Jackett isn't answering: {e}") from None
        if not any(c.name == "Jackett" for c in jar):
            raise JackettError("Jackett has an admin password: enter it in Torrents › Jackett › Settings › Admin Password"
                               if not pw else "Jackett didn't accept the admin password (Jackett › Settings › Admin Password)")
        _state["session"] = op
        return op


def _api(method, path, body=None, timeout=60, retry=True):
    if not running():
        start()
    op = _session()
    data = json.dumps(body).encode() if body is not None else (b"" if method in ("POST", "PUT") else None)
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with op.open(req, timeout=timeout) as r:
            raw = r.read()
            final = r.geturl()
    except urllib.error.HTTPError as e:
        raw = e.read()
        if e.code == 401 and retry:
            _state["session"] = None
            return _api(method, path, body, timeout, retry=False)
        raise JackettError(_error_text(raw) or f"Jackett said {e.code}") from None
    except OSError as e:
        raise JackettError(f"Jackett isn't answering: {e}") from None
    if "/UI/Login" in final and retry:                   # the cookie ran out: sign in again
        _state["session"] = None
        return _api(method, path, body, timeout, retry=False)
    if not raw.strip():
        return None
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except ValueError:
        return raw.decode(errors="replace")


def _error_text(raw):
    try:
        j = json.loads(raw.decode("utf-8-sig"))
        if isinstance(j, dict):
            return str(j.get("error") or j.get("Error") or j.get("message") or j.get("title") or "")[:400]
    except ValueError:
        pass
    text = raw.decode(errors="replace")
    m = re.search(r"Exception: ([^\r\n<]+)", text)
    return (m.group(1) if m else text.strip()[:200])


def apikey():
    if not _state.get("apikey"):
        cfg = _api("GET", "/api/v2.0/server/Config") or {}
        _state["apikey"] = cfg.get("api_key") or _file_apikey()
    return _state["apikey"]


# ---- the public face ----------------------------------------------------------------------------------
def status():
    b = binary()
    st = {"installed": bool(b), "ours": bool(_ours()), "version": version(), "running": running(), "port": PORT,
          "search": prefs().get("search", True), "autostart": prefs().get("autostart", True),
          "has_password": bool(_secret().get("admin_password")), "url": BASE}
    if st["running"]:
        try:
            cfg = _api("GET", "/api/v2.0/server/Config", timeout=10) or {}
            st["version"] = cfg.get("app_version") or st["version"]
            st["flaresolverr"] = cfg.get("flaresolverrurl") or ""
            st["configured"] = len(indexers(True))
        except JackettError as e:
            st["error"] = str(e)
    return st


def _norm_indexer(i):
    caps = i.get("caps") or []
    return {"id": i.get("id"), "name": i.get("name") or i.get("id"), "description": (i.get("description") or "")[:300],
            "type": i.get("type") or "public", "type_name": TYPES.get(i.get("type"), (i.get("type") or "").title()),
            "configured": bool(i.get("configured")), "language": i.get("language") or "", "site": i.get("site_link") or "",
            "error": i.get("last_error") or "",
            "cats": sorted({str(c.get("Name") or c.get("name") or "").split("/")[0] for c in caps if (c.get("Name") or c.get("name"))})[:8]}


def indexers(configured=None):
    cache = _state.get("idx")
    if not cache or time.time() - cache[0] > 20:
        raw = _api("GET", "/api/v2.0/indexers?configured=false") or []
        cache = (time.time(), [_norm_indexer(i) for i in raw if isinstance(i, dict) and i.get("id")])
        _state["idx"] = cache
    lst = cache[1]
    if configured is not None:
        lst = [i for i in lst if i["configured"] == bool(configured)]
    return sorted(lst, key=lambda i: i["name"].lower())


def _forget_cache():
    _state.pop("idx", None)


def _check_id(iid):
    if not re.fullmatch(r"[\w.\-]{1,80}", iid or ""):
        raise ValueError("tracker")
    return iid


def config(iid):
    """A tracker's settings form, as Crossbar shows it: [{id, type, name, value, options, values}].
    Passwords never come back to the screen, only whether one is set."""
    items = _api("GET", f"/api/v2.0/indexers/{_check_id(iid)}/Config") or []
    out = []
    for it in items:
        t = it.get("type")
        row = {"id": it.get("id"), "type": t, "name": re.sub(r"<[^>]+>", "", str(it.get("name") or it.get("id") or ""))}
        if t == "password" or (t == "inputstring" and it.get("id") == "password"):
            row["set"] = bool(it.get("value"))
        elif t == "displayinfo":
            row["value"] = _html_text(it.get("value"))
        elif t == "displayimage":
            row["image"] = it.get("value")                  # a captcha picture (data: URL)
        elif t in ("inputselect", "inputcheckbox"):
            row["options"] = [[str(k), _html_text(v)] for k, v in (it.get("options") or {}).items()]
            row["value" if t == "inputselect" else "values"] = it.get("value") if t == "inputselect" else list(it.get("values") or [])
        elif t == "hiddendata":
            continue
        else:
            row["value"] = it.get("value")
        out.append(row)
    return out


def _html_text(v):
    v = re.sub(r"<br\s*/?>|</p>|</li>", "\n", str(v or ""), flags=re.I)
    v = re.sub(r"<li[^>]*>", "• ", v, flags=re.I)
    v = re.sub(r"<a [^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", r"\2 (\1)", v, flags=re.I | re.S)
    v = re.sub(r"<[^>]+>", "", v)
    import html
    return re.sub(r"\n{3,}", "\n\n", html.unescape(v)).strip()


def save_config(iid, values):
    """Fill in a tracker's form and save it: Jackett signs in to the tracker / tests it, and any
    problem (wrong password, the site is down, a captcha) comes back as the error."""
    _check_id(iid)
    items = _api("GET", f"/api/v2.0/indexers/{iid}/Config") or []
    values = values if isinstance(values, dict) else {}
    for it in items:
        k = it.get("id")
        if k not in values or values[k] is None:
            continue
        v = values[k]
        t = it.get("type")
        if t == "inputbool":
            it["value"] = bool(v)
        elif t == "inputcheckbox":
            it["values"] = [str(x) for x in (v if isinstance(v, list) else [v])]
        elif t in ("inputstring", "password", "inputtags", "inputselect", "displayimage"):
            if t == "inputselect" and str(v) not in {str(o) for o in (it.get("options") or {})}:
                raise ValueError(f"{it.get('name')}: not one of the choices")
            if len(str(v)) > 4000 or "\n" in str(v):
                raise ValueError(f"{it.get('name')}: that can't be used")
            it["value"] = str(v)
    try:
        _api("POST", f"/api/v2.0/indexers/{iid}/Config", items, timeout=120)
    finally:
        _forget_cache()
    _write_qbt_plugin_conf()
    return {"ok": True, "tracker": next((i for i in indexers() if i["id"] == iid), None)}


def test(iid):
    try:
        _api("POST", f"/api/v2.0/indexers/{_check_id(iid)}/Test", timeout=120)
    finally:
        _forget_cache()
    return {"ok": True}


def remove(iid):
    _api("DELETE", f"/api/v2.0/indexers/{_check_id(iid)}")
    _forget_cache()
    return {"ok": True}


def set_settings(**kw):
    out = {}
    if "admin_password" in kw:
        _save_secret(admin_password=str(kw["admin_password"] or ""))
        _state["session"] = None
    local = {k: bool(kw[k]) for k in ("search", "autostart") if k in kw}
    if local:
        _set(**local)
    if "flaresolverr" in kw:
        url = str(kw["flaresolverr"] or "").strip()
        if url and not re.fullmatch(r"https?://[\w.\-]+(:\d+)?/?", url):
            raise ValueError("FlareSolverr's address looks like http://127.0.0.1:8191")
        cfg = _api("GET", "/api/v2.0/server/Config") or {}
        cfg["flaresolverrurl"] = url
        _api("POST", "/api/v2.0/server/Config", cfg)
        out["restarting"] = True
    return {**status(), **out}


# ---- search -------------------------------------------------------------------------------------------
def _ts(s):
    """Jackett's PublishDate (ISO, maybe with a zone) → unix seconds, or -1."""
    if not s:
        return -1
    import datetime
    try:
        d = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")[:32])
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        t = int(d.timestamp())
        return t if t > 86400 * 365 else -1               # 0001-01-01: unknown
    except ValueError:
        return -1


def _g(d, k, default=None):
    """Jackett's JSON is PascalCase (camelCase on some versions): either."""
    if k in d:
        return d[k]
    return d.get(k[0].lower() + k[1:], default)


def search(pattern, category="all", trackers=None, timeout=120):
    """Every configured tracker (or the ones given), at once. Returns (results, per-tracker status)."""
    q = {"apikey": apikey(), "query": pattern}
    cats = CATS.get(category) or []
    if cats:
        q["Category[]"] = ",".join(str(c) for c in cats)
    if trackers:
        q["Tracker[]"] = ",".join(_check_id(t) for t in trackers)
    data = _api("GET", "/api/v2.0/indexers/all/results?" + urllib.parse.urlencode(q), timeout=timeout) or {}
    results = []
    for r in _g(data, "Results") or []:
        link = _g(r, "MagnetUri") or _g(r, "Link")
        if not link:
            continue
        seeds, peers = _g(r, "Seeders"), _g(r, "Peers")
        results.append({"url": link, "name": _g(r, "Title") or "", "size": int(_g(r, "Size") or -1),
                        "seeds": int(seeds) if seeds is not None else -1, "peers": int(peers) if peers is not None else -1,
                        "site": _g(r, "Tracker") or "", "page": _g(r, "Details") or "", "date": _ts(_g(r, "PublishDate")),
                        "engine": f"jackett:{_g(r, 'TrackerId') or ''}", "tracker": _g(r, "Tracker") or "",
                        "fallback": _g(r, "Link") if _g(r, "MagnetUri") else None})
    per = {}
    for i in _g(data, "Indexers") or []:
        st = _g(i, "Status")
        per[_g(i, "Name") or _g(i, "ID")] = {"count": int(_g(i, "Results") or 0), "running": False,
                                              "error": "" if st in (2, "OK") else (_g(i, "Error") or ("failed" if st in (1, "Error") else ""))}
    return results, per


def fetch(url):
    """A result's download: ("magnet", link) or ("torrent", bytes). Jackett's /dl/ link either sends
    the .torrent or redirects to a magnet link."""
    if url.lower().startswith("magnet:"):
        return "magnet", url
    p = urllib.parse.urlparse(url)
    if p.hostname not in ("127.0.0.1", "localhost") or p.port != PORT:
        raise ValueError("Not a Jackett link")
    op = urllib.request.build_opener(_NoRedirect)
    try:
        with op.open(urllib.request.Request(url, headers={"User-Agent": "Crossbar"}), timeout=90) as r:
            data = r.read(20 * 1024 * 1024)
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location") or ""
        if e.code in (301, 302, 303, 307, 308) and loc.lower().startswith("magnet:"):
            return "magnet", loc
        raise JackettError(_error_text(e.read()) or f"The tracker refused the download ({e.code})") from None
    except OSError as e:
        raise JackettError(f"Jackett couldn't get it: {e}") from None
    if data[:1] != b"d":
        raise JackettError("The tracker didn't send a torrent file (check the tracker's settings in Jackett)")
    return "torrent", data


# ---- qBittorrent's own Jackett plugin, if you installed it: point it here ------------------------------
def _write_qbt_plugin_conf():
    try:
        from . import torrent
        for d in torrent._engines_dirs():
            if os.path.isfile(os.path.join(d, "jackett.py")):
                path = os.path.join(d, "jackett.json")
                try:
                    with open(path) as f:
                        cur = json.load(f)
                except (OSError, ValueError):
                    cur = {}
                cur.update(api_key=apikey(), url=BASE)
                cur.setdefault("tracker_first", False)
                cur.setdefault("thread_count", 20)
                with open(path, "w") as f:
                    json.dump(cur, f, indent=4)
    except Exception as e:
        print(f"jackett: qBittorrent plugin config: {e}", flush=True)


def autostart():
    if prefs().get("autostart", True) and binary() and not running():
        threading.Thread(target=lambda: _safe(start), daemon=True).start()


def _safe(fn):
    try:
        fn()
    except Exception as e:
        print(f"jackett: {e}", flush=True)
