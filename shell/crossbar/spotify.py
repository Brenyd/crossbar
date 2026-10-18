"""Spotify: the console becomes a Spotify Connect speaker (librespot) and the XMB
browses your library and controls playback through the Spotify Web API.

Why two pieces: Spotify's Web API can't play audio itself, and librespot can't
browse. Together they behave like the console app: pick a playlist on the XMB,
it plays out of this machine.

One-time setup (Spotify's rules since Feb 2026): the account owner needs
Premium and must register a free app at developer.spotify.com to get a
Client ID, with redirect URI http://127.0.0.1:7777/spotify/callback.
"""
import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import util

DEVICE_NAME = "Crossbar"
REDIRECT = "http://127.0.0.1:7777/spotify/callback"
SCOPES = ("user-read-playback-state user-modify-playback-state user-read-currently-playing "
          "playlist-read-private playlist-read-collaborative user-library-read user-read-recently-played")
CACHE = os.path.join(util.CONFIG_DIR, "librespot")
TOKEN_PATH = os.path.join(util.CONFIG_DIR, "spotify_token.json")
BROWSER_PROFILE = os.path.join(util.CONFIG_DIR, "spotify-login")
API = "https://api.spotify.com/v1"
LOG = os.path.join(util.HOME, ".cache", "crossbar", "librespot.log")


class SpotifyError(RuntimeError):
    code = 0


class Spotify:
    def __init__(self):
        self.receiver = None
        self._pkce = {}
        self._got_token = threading.Event()
        self._lock = threading.Lock()

    # ---- librespot receiver ------------------------------------------------
    def _librespot_args(self):
        return ["librespot", "--name", DEVICE_NAME, "--device-type", "gameconsole", "--bitrate", "320",
                "--cache", CACHE, "--disable-audio-cache", "--initial-volume", "80",
                "--enable-volume-normalisation"]

    def receiver_signed_in(self):
        try:
            return any(n.startswith("credentials") for n in os.listdir(CACHE))
        except OSError:
            return False

    def receiver_running(self):
        return self.receiver is not None and self.receiver.poll() is None

    def ensure_receiver(self):
        with self._lock:
            if self.receiver_running() or not self.receiver_signed_in() or not util.which("librespot"):
                return
            os.makedirs(os.path.dirname(LOG), exist_ok=True)
            log = open(LOG, "a")
            self.receiver = subprocess.Popen(self._librespot_args(), stdin=subprocess.DEVNULL,
                                             stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

    def _login_window(self, url):
        return subprocess.Popen(["chromium", "--ozone-platform-hint=auto", f"--user-data-dir={BROWSER_PROFILE}",
                                 "--no-first-run", f"--app={url}"],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)

    def _receiver_login(self, job):
        """Run librespot's OAuth flow; it prints a URL and catches the redirect itself."""
        if not util.which("librespot"):
            raise RuntimeError("librespot is not installed")
        os.makedirs(CACHE, exist_ok=True)
        if self.receiver_running():
            self.receiver.terminate()
        p = subprocess.Popen(self._librespot_args() + ["--enable-oauth"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                             start_new_session=True)
        self.receiver = p
        win = None
        deadline = time.time() + 600
        watchdog = threading.Timer(600, lambda: self.receiver_signed_in() or p.terminate())
        watchdog.start()
        url_re = re.compile(r"https://accounts\.spotify\.com/\S+")
        for line in p.stdout:
            m = url_re.search(line)
            if m and win is None:
                job.set(0.2, "Sign in to Spotify in the window that opened")
                win = self._login_window(m.group(0))
            if self.receiver_signed_in() or time.time() > deadline:
                break
        # keep draining librespot's output so it never blocks on a full pipe
        watchdog.cancel()
        def drain():
            with open(LOG, "a") as log:
                for ln in p.stdout:
                    log.write(ln)
                    log.flush()
        threading.Thread(target=drain, daemon=True).start()
        if win:
            win.terminate()
        if not self.receiver_signed_in():
            raise RuntimeError("Spotify sign-in didn't finish")

    # ---- Web API (PKCE) ----------------------------------------------------
    def _client_id(self):
        cid = util.load_config()["spotify"].get("client_id", "").strip()
        if not cid:
            raise RuntimeError("Add your Spotify Client ID first")
        return cid

    def auth_url(self):
        verifier = secrets.token_urlsafe(64)[:96]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        state = secrets.token_urlsafe(16)
        self._pkce = {"verifier": verifier, "state": state}
        return "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
            "client_id": self._client_id(), "response_type": "code", "redirect_uri": REDIRECT,
            "code_challenge_method": "S256", "code_challenge": challenge, "scope": SCOPES, "state": state})

    def callback(self, code, state):
        if not self._pkce or state != self._pkce.get("state"):
            raise RuntimeError("Sign-in expired, try again")
        tok = self._token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
                                   "client_id": self._client_id(), "code_verifier": self._pkce["verifier"]})
        self._save(tok)
        self._pkce = {}
        self._got_token.set()

    def _token_request(self, data):
        req = urllib.request.Request("https://accounts.spotify.com/api/token",
                                     data=urllib.parse.urlencode(data).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())

    def _save(self, tok):
        old = self._load() or {}
        tok.setdefault("refresh_token", old.get("refresh_token"))
        tok["obtained"] = time.time()
        os.makedirs(util.CONFIG_DIR, exist_ok=True)
        with open(TOKEN_PATH, "w") as f:
            json.dump(tok, f)
        os.chmod(TOKEN_PATH, 0o600)

    def _load(self):
        try:
            with open(TOKEN_PATH) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _token(self):
        tok = self._load()
        if not tok:
            raise RuntimeError("Not signed in to Spotify")
        if time.time() > tok["obtained"] + tok.get("expires_in", 3600) - 60:
            tok = self._token_request({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                       "client_id": self._client_id()})
            self._save(tok)
            tok = self._load()
        return tok["access_token"]

    def api(self, method, path, body=None, **params):
        url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(body).encode() if body is not None else (b"" if method in ("PUT", "POST") else None)
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + self._token(), "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read()
                try:     # play/pause/next now answer 200 with a non-JSON body
                    return json.loads(raw) if raw.strip() else None
                except ValueError:
                    return None
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("error", {}).get("message", "")
            except Exception:
                msg = ""
            if e.code == 403 and "premium" in msg.lower():
                msg = "Spotify Premium is required for playback control"
            err = SpotifyError(f"Spotify: {msg or e.reason} ({e.code})")
            err.code = e.code
            raise err from None

    # ---- combined sign-in --------------------------------------------------
    def login(self, job):
        self._client_id()
        if not self.receiver_signed_in():
            job.set(0.05, "Signing in the speaker…")
            self._receiver_login(job)
        else:
            self.ensure_receiver()
        job.set(0.6, "Allow Crossbar to see your library…")
        self._got_token.clear()
        win = self._login_window(self.auth_url())   # same browser profile: already signed in
        ok = self._got_token.wait(600)
        win.terminate()
        if not ok:
            raise RuntimeError("Spotify sign-in timed out")

    def logout(self):
        for p in (TOKEN_PATH, os.path.join(CACHE, "credentials.json")):
            try:
                os.remove(p)
            except OSError:
                pass
        if self.receiver_running():
            self.receiver.terminate()

    def status(self):
        cfg = util.load_config()["spotify"]
        return {"client_id": bool(cfg.get("client_id")), "speaker": self.receiver_signed_in(),
                "speaker_running": self.receiver_running(), "linked": bool(self._load()),
                "installed": bool(util.which("librespot"))}

    # ---- browsing ----------------------------------------------------------
    @staticmethod
    def _img(images):
        return images[0]["url"] if images else None

    def playlists(self):
        data = self.api("GET", "/me/playlists", limit=50)
        return [{"id": p["id"], "uri": p["uri"], "name": p["name"], "art": self._img(p.get("images") or []),
                 "owner": (p.get("owner") or {}).get("display_name", ""),
                 "total": (p.get("items") or p.get("tracks") or {}).get("total", 0)}
                for p in data.get("items", []) if p]

    def _track(self, t):
        return {"uri": t["uri"], "name": t["name"], "artist": ", ".join(a["name"] for a in t.get("artists", [])),
                "album": (t.get("album") or {}).get("name", ""), "art": self._img((t.get("album") or {}).get("images", [])),
                "duration": t.get("duration_ms", 0) // 1000}

    def liked(self):
        data = self.api("GET", "/me/tracks", limit=50)
        return [self._track(i["track"]) for i in data.get("items", []) if i.get("track")]

    def playlist_items(self, pid):
        data = self.api("GET", f"/playlists/{pid}/items", limit=100)
        out = []
        for i in data.get("items", []):
            t = i.get("item") or i.get("track")
            if t and t.get("type", "track") == "track":
                out.append(self._track(t))
        return out

    def search(self, q):
        data = self.api("GET", "/search", q=q, type="track,playlist,album", limit=10)
        out = [{"kind": "track", **self._track(t)} for t in (data.get("tracks") or {}).get("items", []) if t]
        out += [{"kind": "album", "uri": a["uri"], "name": a["name"],
                 "artist": ", ".join(x["name"] for x in a.get("artists", [])), "art": self._img(a.get("images", []))}
                for a in (data.get("albums") or {}).get("items", []) if a]
        out += [{"kind": "playlist", "uri": p["uri"], "name": p["name"],
                 "artist": (p.get("owner") or {}).get("display_name", ""), "art": self._img(p.get("images") or [])}
                for p in (data.get("playlists") or {}).get("items", []) if p]
        return out

    # ---- playback ----------------------------------------------------------
    def device_id(self):
        if not self.receiver_signed_in():
            raise RuntimeError("The Crossbar speaker isn't signed in — use Set Up Spotify again")
        self.ensure_receiver()
        for _ in range(12):
            for d in self.api("GET", "/me/player/devices").get("devices", []):
                if d.get("name") == DEVICE_NAME:
                    return d["id"]
            if not self.receiver_running():   # librespot exited: start it again
                self.ensure_receiver()
            time.sleep(0.7)
        raise RuntimeError("The Crossbar speaker isn't showing up in Spotify — see ~/.cache/crossbar/librespot.log")

    def play(self, context_uri=None, uris=None, offset=None, shuffle=False):
        dev = self.device_id()
        body = {}
        if context_uri:
            body["context_uri"] = context_uri
        if uris:
            body["uris"] = uris
        if offset is not None:
            body["offset"] = {"position": int(offset)}
        # Spotify rejects player commands sent to a device that isn't active yet,
        # so make Crossbar the active device first, then start playback, then shuffle.
        now = self.now() or {}
        if not now.get("here"):
            self.api("PUT", "/me/player", {"device_ids": [dev], "play": False})
            time.sleep(0.8)
        for attempt in range(3):
            try:
                self.api("PUT", "/me/player/play", body, device_id=dev)
                break
            except SpotifyError as e:
                if e.code not in (404, 502, 503) or attempt == 2:
                    raise
                time.sleep(1.0)
        try:
            self.api("PUT", "/me/player/shuffle", state="true" if shuffle else "false", device_id=dev)
        except SpotifyError:
            pass  # shuffle is a nicety; never fail playback over it

    def transfer(self):
        self.api("PUT", "/me/player", {"device_ids": [self.device_id()], "play": True})

    def restart_speaker(self):
        if self.receiver_running():
            self.receiver.terminate()
            try:
                self.receiver.wait(3)
            except subprocess.TimeoutExpired:
                self.receiver.kill()
        self.receiver = None
        self.ensure_receiver()

    def now(self):
        if not self._load():
            return None
        try:
            d = self.api("GET", "/me/player")
        except RuntimeError:
            return None
        if not d or not d.get("item"):
            return None
        t = self._track(d["item"]) if d["item"].get("type") == "track" else {
            "uri": d["item"]["uri"], "name": d["item"]["name"], "artist": "", "album": "", "art": None,
            "duration": d["item"].get("duration_ms", 0) // 1000}
        return {**t, "playing": d.get("is_playing", False), "position": (d.get("progress_ms") or 0) // 1000,
                "device": (d.get("device") or {}).get("name", ""), "here": (d.get("device") or {}).get("name") == DEVICE_NAME,
                "shuffle": d.get("shuffle_state", False), "repeat": d.get("repeat_state", "off")}

    def control(self, action):
        """Returns what's playing afterwards (for the "Now Playing" notice)."""
        now = self.now() or {}
        if action == "toggle":
            self.api("PUT", "/me/player/pause" if now.get("playing") else "/me/player/play")
            return {**now, "playing": not now.get("playing")}
        elif action == "pause":
            if now.get("playing") and now.get("here"):
                self.api("PUT", "/me/player/pause")
        elif action == "next":
            self.api("POST", "/me/player/next")
        elif action == "prev":
            self.api("POST", "/me/player/previous")
        elif action == "shuffle":
            self.api("PUT", "/me/player/shuffle", state="false" if now.get("shuffle") else "true")
        elif action == "repeat":
            self.api("PUT", "/me/player/repeat", state="off" if now.get("repeat") != "off" else "context")
        if action in ("next", "prev"):
            time.sleep(0.6)          # Spotify takes a moment to report the new track
            return self.now() or now
        return self.now() or now


SPOTIFY = Spotify()
