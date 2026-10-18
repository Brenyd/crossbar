"""Discord voice channels for the Social category, through Discord's local RPC.

Talks to the running Discord desktop app over its IPC socket
($XDG_RUNTIME_DIR/discord-ipc-N): list your servers' voice channels, join and
leave them, mute/deafen, and see who's in a channel. Voice runs in Discord
itself (started minimized), so audio quality and noise suppression are Discord's.

One-time setup (Discord only lets "tester" accounts use RPC): create an app at
discord.com/developers, add redirect URI http://127.0.0.1:7777/discord/callback,
copy its Client ID and Client Secret into Crossbar, then approve the prompt
Discord shows once.
"""
import json
import os
import socket
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from . import util

TOKEN_PATH = os.path.join(util.CONFIG_DIR, "discord_token.json")
REDIRECT = "http://127.0.0.1:7777/discord/callback"
SCOPES = ["rpc", "rpc.voice.read", "rpc.voice.write", "identify"]
OP_HANDSHAKE, OP_FRAME, OP_CLOSE, OP_PING, OP_PONG = 0, 1, 2, 3, 4
VOICE_TYPES = (2, 13)          # voice, stage


class DiscordError(RuntimeError):
    code = 0


def socket_paths():
    bases = [os.environ.get(k) for k in ("XDG_RUNTIME_DIR", "TMPDIR", "TMP", "TEMP")] + ["/tmp"]
    out = []
    for b in filter(None, bases):
        for sub in ("", "app/com.discordapp.Discord", "snap.discord", ".flatpak/dev.vencord.Vesktop/xdg-run"):
            for n in range(10):
                out.append(os.path.join(b, sub, f"discord-ipc-{n}"))
    return list(dict.fromkeys(out))


class Discord:
    def __init__(self):
        self.sock = None
        self.lock = threading.RLock()
        self.pending = {}
        self.user = None
        self.state = {"channel": None, "mute": False, "deaf": False}
        self._watched = None
        self._cache = {}

    # ---- config / tokens -------------------------------------------------------
    def cfg(self):
        return util.load_config().get("discord") or {}

    def configured(self):
        c = self.cfg()
        return bool(c.get("client_id") and c.get("client_secret"))

    def _token(self):
        try:
            with open(TOKEN_PATH) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _save_token(self, tok):
        tok["obtained"] = time.time()
        os.makedirs(util.CONFIG_DIR, exist_ok=True)
        with open(TOKEN_PATH, "w") as f:
            json.dump(tok, f)
        os.chmod(TOKEN_PATH, 0o600)

    def _oauth(self, data):
        c = self.cfg()
        body = urllib.parse.urlencode({"client_id": c["client_id"], "client_secret": c["client_secret"], **data}).encode()
        req = urllib.request.Request("https://discord.com/api/oauth2/token", data=body,
                                     headers={"Content-Type": "application/x-www-form-urlencoded",
                                              "User-Agent": "Crossbar/0.7"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())

    def linked(self):
        return bool(self._token())

    # ---- IPC transport ---------------------------------------------------------
    def _send(self, op, payload):
        data = json.dumps(payload).encode()
        self.sock.sendall(struct.pack("<II", op, len(data)) + data)

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Discord closed the connection")
            buf += chunk
        return buf

    def _read_frame(self):
        op, length = struct.unpack("<II", self._recv_exact(8))
        return op, json.loads(self._recv_exact(length) or b"{}")

    def _reader(self, sock):
        try:
            while self.sock is sock:
                op, msg = self._read_frame()
                if op == OP_PING:
                    self._send(OP_PONG, msg)
                    continue
                if op == OP_CLOSE:
                    raise ConnectionError(msg.get("message", "closed"))
                nonce = msg.get("nonce")
                if nonce and nonce in self.pending:
                    slot = self.pending[nonce]
                    slot["msg"] = msg
                    slot["ev"].set()
                elif msg.get("cmd") == "DISPATCH":
                    self._on_event(msg.get("evt"), msg.get("data") or {})
        except Exception as e:
            print(f"discord: connection ended: {e!r}", flush=True)
        finally:
            if self.sock is sock:
                self._disconnect()

    def _disconnect(self):
        with self.lock:
            s, self.sock = self.sock, None
            self._watched = None
        if s:
            try:
                s.close()
            except OSError:
                pass
        for slot in list(self.pending.values()):
            slot["ev"].set()

    def running(self):
        return any(os.path.exists(p) for p in socket_paths())

    def connect(self):
        with self.lock:
            if self.sock:
                return
            c = self.cfg()
            if not c.get("client_id"):
                raise RuntimeError("Set up Discord first (Social › Set Up Discord)")
            last = None
            for path in socket_paths():
                if not os.path.exists(path):
                    continue
                try:
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.settimeout(10)
                    s.connect(path)
                    self.sock = s
                    self._send(OP_HANDSHAKE, {"v": 1, "client_id": c["client_id"]})
                    op, msg = self._read_frame()
                    if op == OP_CLOSE or msg.get("evt") != "READY":
                        raise ConnectionError(msg.get("message") or "Discord refused the connection (check the Client ID)")
                    s.settimeout(None)
                    threading.Thread(target=self._reader, args=(s,), daemon=True).start()
                    break
                except Exception as e:
                    last = e
                    self.sock = None
                    try:
                        s.close()
                    except OSError:
                        pass
            if not self.sock:
                raise RuntimeError("Discord isn't running" if last is None else f"Couldn't reach Discord: {last}")
        try:
            self._authenticate()
            self._subscribe_select()
        except Exception:
            self._disconnect()
            raise

    def request(self, cmd, args=None, evt=None, timeout=15):
        if not self.sock:
            self.connect()
        nonce = str(uuid.uuid4())
        slot = {"ev": threading.Event(), "msg": None}
        self.pending[nonce] = slot
        payload = {"cmd": cmd, "args": args or {}, "nonce": nonce}
        if evt:
            payload["evt"] = evt
        try:
            with self.lock:
                self._send(OP_FRAME, payload)
            if not slot["ev"].wait(timeout) or slot["msg"] is None:
                raise RuntimeError(f"Discord didn't answer ({cmd})")
        finally:
            self.pending.pop(nonce, None)
        msg = slot["msg"]
        if msg.get("evt") == "ERROR":
            err = DiscordError((msg.get("data") or {}).get("message", "Discord error"))
            err.code = (msg.get("data") or {}).get("code", 0)
            raise err
        return msg.get("data")

    # ---- auth ------------------------------------------------------------------
    def _authenticate(self):
        tok = self._token()
        if not tok:
            raise RuntimeError("Discord isn't linked yet (Social › Set Up Discord)")
        if time.time() > tok.get("obtained", 0) + tok.get("expires_in", 0) - 300 and tok.get("refresh_token"):
            tok = self._oauth({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
            self._save_token(tok)
        data = self.request("AUTHENTICATE", {"access_token": tok["access_token"]})
        self.user = (data or {}).get("user")

    def link(self, job):
        """First-time: Discord shows an 'Authorize' prompt; approve it once."""
        if not self.configured():
            raise RuntimeError("Enter the Client ID and Client Secret first")
        if not installed_cmd():
            raise RuntimeError("The Discord app isn't installed. Install it (Settings › System Settings › Terminal: "
                               "sudo pacman -S discord) and try again.")
        job.set(0.05, "Opening Discord — sign in there if it asks")
        launch(minimized=False)
        for i in range(300):                      # up to 5 minutes to sign in
            if self.running():
                break
            why = crashed()
            if why:
                raise RuntimeError(f"Discord closed by itself: {why}")
            if i == 20:
                job.set(0.1, "Waiting for Discord — finish signing in to it")
            time.sleep(1)
        else:
            raise RuntimeError("Discord didn't finish starting. Open Discord from Social and sign in, then try again.")
        self._disconnect()
        with self.lock:            # connect without authenticating
            c = self.cfg()
            for path in socket_paths():
                if os.path.exists(path):
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.connect(path)
                    self.sock = s
                    self._send(OP_HANDSHAKE, {"v": 1, "client_id": c["client_id"]})
                    op, msg = self._read_frame()
                    if op == OP_CLOSE:
                        self._disconnect()
                        raise RuntimeError(msg.get("message") or "Discord refused the Client ID")
                    threading.Thread(target=self._reader, args=(s,), daemon=True).start()
                    break
            else:
                raise RuntimeError("Discord isn't running")
        job.set(0.4, "In Discord, click Authorize to let Crossbar control voice")
        try:
            launch(minimized=False)               # bring Discord to the front for the prompt
        except RuntimeError:
            pass
        try:
            data = self.request("AUTHORIZE", {"client_id": c["client_id"], "scopes": SCOPES}, timeout=300)
        except DiscordError as e:
            self._disconnect()
            if e.code in (4000, 4002, 4006, 5000):
                raise RuntimeError(f"Discord said: {e}. Make sure your account is allowed to test the app.") from None
            raise
        job.set(0.8, "Finishing…")
        try:
            tok = self._oauth({"grant_type": "authorization_code", "code": data["code"], "redirect_uri": REDIRECT})
        except urllib.error.HTTPError as e:
            raise RuntimeError("Discord rejected the Client Secret or the redirect "
                               f"(add {REDIRECT} under OAuth2 › Redirects) — HTTP {e.code}") from None
        self._save_token(tok)
        self._disconnect()
        self.connect()
        try:
            hide()                                # done: Discord back to the background
        except Exception:
            pass

    def unlink(self):
        self._disconnect()
        try:
            os.remove(TOKEN_PATH)
        except OSError:
            pass

    # ---- events ----------------------------------------------------------------
    def _subscribe_select(self):
        try:
            self.request("SUBSCRIBE", {}, evt="VOICE_CHANNEL_SELECT")
            self.request("SUBSCRIBE", {}, evt="VOICE_SETTINGS_UPDATE")
        except DiscordError:
            pass
        self._refresh_selected()

    def _on_event(self, evt, data):
        if evt == "VOICE_CHANNEL_SELECT":
            threading.Thread(target=self._refresh_selected, daemon=True).start()
        elif evt == "VOICE_SETTINGS_UPDATE":
            self.state["mute"] = bool(data.get("mute"))
            self.state["deaf"] = bool(data.get("deaf"))
        elif evt in ("VOICE_STATE_CREATE", "VOICE_STATE_UPDATE", "VOICE_STATE_DELETE"):
            ch = self.state.get("channel")
            if not ch:
                return
            uid = ((data.get("user") or {}).get("id"))
            members = [m for m in ch["members"] if m["id"] != uid]
            if evt != "VOICE_STATE_DELETE":
                members.append(_member(data))
            ch["members"] = members

    def _refresh_selected(self):
        try:
            ch = self.request("GET_SELECTED_VOICE_CHANNEL")
            settings = self.request("GET_VOICE_SETTINGS") or {}
        except Exception:
            return
        self.state["mute"] = bool(settings.get("mute"))
        self.state["deaf"] = bool(settings.get("deaf"))
        self.state["channel"] = _channel(ch) if ch else None
        new = ch["id"] if ch else None
        if new != self._watched:
            for evt in ("VOICE_STATE_CREATE", "VOICE_STATE_UPDATE", "VOICE_STATE_DELETE"):
                try:
                    if self._watched:
                        self.request("UNSUBSCRIBE", {"channel_id": self._watched}, evt=evt)
                    if new:
                        self.request("SUBSCRIBE", {"channel_id": new}, evt=evt)
                except Exception:
                    pass
            self._watched = new

    # ---- what the menus use ----------------------------------------------------------
    def status(self):
        st = {"configured": self.configured(), "linked": self.linked(), "running": self.running(),
              "connected": bool(self.sock), "user": (self.user or {}).get("username"),
              "channel": None, "mute": False, "deaf": False}
        if st["linked"] and st["running"] and not self.sock:
            try:
                self.connect()
                st["connected"] = True
            except Exception as e:
                st["error"] = str(e)
        if self.sock:
            st.update(channel=self.state["channel"], mute=self.state["mute"], deaf=self.state["deaf"],
                      user=(self.user or {}).get("username"))
        return st

    def guilds(self):
        return [{"id": g["id"], "name": g["name"]} for g in (self.request("GET_GUILDS") or {}).get("guilds", [])]

    def voice_channels(self, guild_id):
        chans = (self.request("GET_CHANNELS", {"guild_id": guild_id}) or {}).get("channels", [])
        return [{"id": c["id"], "name": c["name"]} for c in chans if c.get("type") in VOICE_TYPES]

    def channel(self, channel_id):
        key = ("ch", channel_id)
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < 3:
            return hit[1]
        data = _channel(self.request("GET_CHANNEL", {"channel_id": channel_id}))
        self._cache[key] = (time.time(), data)
        return data

    def join(self, channel_id, force=False):
        try:
            data = self.request("SELECT_VOICE_CHANNEL", {"channel_id": channel_id, "force": force, "timeout": 10})
        except DiscordError as e:
            if e.code == 5003:
                raise RuntimeError("ALREADY_IN_VOICE") from None
            raise
        self.state["channel"] = _channel(data) if data else None
        self._refresh_selected()
        return self.state["channel"]

    def leave(self):
        self.request("SELECT_VOICE_CHANNEL", {"channel_id": None, "force": True})
        self.state["channel"] = None
        self._refresh_selected()

    def set_voice(self, mute=None, deaf=None):
        args = {}
        if mute is not None:
            args["mute"] = bool(mute)
        if deaf is not None:
            args["deaf"] = bool(deaf)
        data = self.request("SET_VOICE_SETTINGS", args) or {}
        self.state["mute"] = bool(data.get("mute", self.state["mute"]))
        self.state["deaf"] = bool(data.get("deaf", self.state["deaf"]))
        return {"mute": self.state["mute"], "deaf": self.state["deaf"]}


def _member(vs):
    u = vs.get("user") or {}
    v = vs.get("voice_state") or {}
    return {"id": u.get("id"), "name": vs.get("nick") or u.get("global_name") or u.get("username") or "?",
            "muted": bool(v.get("self_mute") or v.get("mute")), "deaf": bool(v.get("self_deaf") or v.get("deaf"))}


def _channel(data):
    if not data:
        return None
    return {"id": data.get("id"), "name": data.get("name"), "guild_id": data.get("guild_id"),
            "members": [_member(v) for v in data.get("voice_states") or []]}


LOG = os.path.join(util.HOME, ".cache", "crossbar", "discord.log")
_proc = {"p": None}


def installed_cmd():
    return next((c for c in ("discord", "discord-canary", "vesktop") if util.which(c)), None)


def _windows():
    from . import system
    return [w for w in system.all_windows() if "discord" in w["app"].lower() or "vesktop" in w["app"].lower()]


def launch(minimized=True):
    """Start Discord (or bring it forward). Minimized = keep it hidden, voice only."""
    from . import system
    import subprocess
    wins = _windows()
    if wins:
        if not minimized:
            system.bring_to_front(wins[-1]["con_id"])
        return
    cmd = installed_cmd()
    if not cmd:
        raise RuntimeError("The Discord app isn't installed (sudo pacman -S discord)")
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    log = open(LOG, "a")
    log.write(f"\n--- {time.ctime()} starting {cmd} (minimized={minimized})\n")
    log.flush()
    proc = subprocess.Popen([cmd] + (["--start-minimized"] if minimized else []),
                            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    _proc["p"] = proc

    def manage():
        # Discord shows an update splash, then its main window. Minimized: hide them as
        # they appear. Otherwise: make sure the main window ends up in front.
        seen = set()
        for _ in range(240):
            time.sleep(0.5)
            if _proc["p"] is not proc:            # a newer launch took over
                return
            for w in _windows():
                if w["con_id"] in seen:
                    continue
                if minimized:
                    system.hide_window(w["con_id"])
                    system.show_shell()
                else:
                    system.bring_to_front(w["con_id"])
                seen.add(w["con_id"])
            if proc.poll() is not None and not _windows():
                return
    threading.Thread(target=manage, daemon=True).start()


def hide():
    from . import system
    for w in _windows():
        system.hide_window(w["con_id"])
    system.show_shell()


def crashed():
    """If Discord exited by itself, the last lines of its log (else None)."""
    p = _proc["p"]
    if p is None or p.poll() is None:
        return None
    try:
        with open(LOG) as f:
            tail = [ln.strip() for ln in f.readlines()[-6:] if ln.strip()]
    except OSError:
        tail = []
    return " / ".join(tail)[-300:] or f"exit code {p.returncode}"


DISCORD = Discord()
