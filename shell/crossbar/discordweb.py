"""Discord without Discord's API: its own web client, driven like a person would.

Crossbar runs discord.com/app in a Chromium app window it owns, and talks to that
browser over Chromium's DevTools *pipe* (--remote-debugging-pipe: two private file
descriptors, so no other program can attach - unlike a debugging port). Through it,
Crossbar reads the server and voice-channel lists from the page and clicks the same
buttons you would (join a voice channel, Disconnect, Mute, Deafen). Elements are found
by their accessibility labels and Discord's list ids, not by screen positions, so
layout changes rarely break it; when Discord changes something, the worst case is that
an action reports "couldn't find" and the window can still be used directly.

Sign-in happens once in that window (Discord shows a QR code: scan it with the Discord
app on your phone - no typing needed). Voice keeps running while the window is hidden.
"""
import json
import os
import re
import subprocess
import threading
import time

from . import system, util

URL = "https://discord.com/app"
PROFILE = os.path.join(util.CONFIG_DIR, "discord-web")


class DiscordError(RuntimeError):
    pass


class DiscordWeb:
    def __init__(self):
        self.proc = None
        self.wfd = self.rfd = None
        self.lock = threading.Lock()
        self.pending = {}
        self.next_id = 0
        self.session = None
        self.cache = {"guilds": [], "voice": None, "t": 0}

    # ---- browser process + DevTools pipe ----------------------------------------
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, show=False):
        if self.running():
            if show:
                self.show()
            return
        browser = os.environ.get("CROSSBAR_DISCORD_BROWSER", "chromium")      # tests can point elsewhere
        if not util.which(browser):
            raise DiscordError("Chromium isn't installed")
        os.makedirs(PROFILE, exist_ok=True)
        to_chrome_r, to_chrome_w = os.pipe()       # browser reads DevTools commands on fd 3
        from_chrome_r, from_chrome_w = os.pipe()   # ...and writes replies on fd 4

        def child():
            # copy to fresh numbers first, so placing one on fd 3/4 can't clobber the other
            a, b = os.dup(to_chrome_r), os.dup(from_chrome_w)
            os.dup2(a, 3)
            os.dup2(b, 4)
        w, h = system.screen_size()
        args = [browser, "--ozone-platform-hint=auto", f"--user-data-dir={PROFILE}", "--remote-debugging-pipe",
                "--no-first-run", "--noerrdialogs", "--disable-infobars", "--disable-session-crashed-bubble",
                "--hide-crash-restore-bubble", "--autoplay-policy=no-user-gesture-required",
                "--enable-wayland-ime", "--wayland-text-input-version=3",
                f"--window-size={w},{h}", "--window-position=0,0",
                *os.environ.get("CROSSBAR_DISCORD_ARGS", "").split(),          # tests only
                f"--app={os.environ.get('CROSSBAR_DISCORD_URL', URL)}"]
        self.proc = subprocess.Popen(args, preexec_fn=child, pass_fds=(3, 4), stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        os.close(to_chrome_r)
        os.close(from_chrome_w)
        self.wfd, self.rfd, self.session = to_chrome_w, from_chrome_r, None
        threading.Thread(target=self._reader, args=(self.rfd,), daemon=True).start()
        # the microphone without a permission bubble (only for discord.com)
        try:
            self._cmd("Browser.grantPermissions", {"origin": "https://discord.com", "permissions": ["audioCapture"]},
                      session=False, timeout=15)
        except Exception as e:
            print(f"discord: permissions: {e}", flush=True)
        threading.Thread(target=self._place, args=(show,), daemon=True).start()

    def _place(self, show):
        """Tuck the new window away unless it was opened to be used."""
        for _ in range(60):
            time.sleep(0.5)
            win = self.window()
            if win:
                if show:
                    system.bring_to_front(win["con_id"])
                else:
                    system.hide_window(win["con_id"])
                    system.show_shell()
                return

    def stop(self):
        if self.running():
            self.proc.terminate()
        self.proc = None

    def _reader(self, fd):
        buf = b""
        while True:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                chunk = b""
            if not chunk:
                break
            buf += chunk
            while b"\0" in buf:
                raw, buf = buf.split(b"\0", 1)
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                waiter = self.pending.pop(msg.get("id"), None)
                if waiter:
                    waiter["msg"] = msg
                    waiter["ev"].set()
        for w in list(self.pending.values()):      # the browser went away
            w["msg"] = {"error": {"message": "Discord window closed"}}
            w["ev"].set()

    def _cmd(self, method, params=None, session=True, timeout=10):
        if not self.running():
            raise DiscordError("Discord isn't running")
        if session:
            self._attach()
        with self.lock:
            self.next_id += 1
            mid = self.next_id
            waiter = {"ev": threading.Event(), "msg": None}
            self.pending[mid] = waiter
            msg = {"id": mid, "method": method, "params": params or {}}
            if session:
                msg["sessionId"] = self.session
            os.write(self.wfd, json.dumps(msg).encode() + b"\0")
        if not waiter["ev"].wait(timeout):
            self.pending.pop(mid, None)
            raise DiscordError("Discord didn't answer")
        m = waiter["msg"]
        if "error" in m:
            raise DiscordError(m["error"].get("message", "DevTools error"))
        return m.get("result", {})

    def _attach(self):
        if self.session:
            return
        targets = self._cmd("Target.getTargets", session=False)["targetInfos"]
        page = next((t for t in targets if t["type"] == "page" and "discord.com" in t.get("url", "")), None) \
            or next((t for t in targets if t["type"] == "page"), None)
        if not page:
            raise DiscordError("Discord's page isn't open")
        self.session = self._cmd("Target.attachToTarget", {"targetId": page["targetId"], "flatten": True},
                                 session=False)["sessionId"]

    def js(self, expr, timeout=10):
        try:
            r = self._cmd("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True},
                          timeout=timeout)
        except DiscordError as e:
            if "session" in str(e).lower() or "target" in str(e).lower():
                self.session = None           # the page was replaced (e.g. after sign-in): attach again
                r = self._cmd("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True},
                              timeout=timeout)
            else:
                raise
        if r.get("exceptionDetails"):
            raise DiscordError(r["exceptionDetails"].get("text", "script error"))
        return (r.get("result") or {}).get("value")

    # ---- the window ---------------------------------------------------------------
    def window(self):
        if not self.running():
            return None
        pid = self.proc.pid
        wins = system.all_windows()
        return next((w for w in wins if w.get("pid") == pid), None) \
            or next((w for w in wins if "discord" in (w.get("title") or "").lower() and "chrom" in (w.get("app") or "").lower()), None)

    def show(self):
        self.start()
        win = self.window()
        if win:
            system.bring_to_front(win["con_id"])

    def hide(self):
        win = self.window()
        if win:
            system.hide_window(win["con_id"])

    # ---- reading the page -------------------------------------------------------------
    STATE_JS = r"""(() => {
      const signedIn = !!document.querySelector('[data-list-item-id^="guildsnav___"]');
      const sw = (re) => [...document.querySelectorAll('button[role="switch"],button[aria-label]')]
                            .find(b => re.test(b.getAttribute('aria-label') || ''));
      const mute = sw(/^(mute|unmute)$/i), deaf = sw(/^(deafen|undeafen)$/i);
      const disc = document.querySelector('button[aria-label="Disconnect"]');
      let voice = null;
      if (disc) {
        let box = disc;
        for (let i = 0; i < 6 && box && !box.querySelector('a[href^="/channels/"]'); i++) box = box.parentElement;
        const a = box && box.querySelector('a[href^="/channels/"]');
        const parts = a ? a.getAttribute('href').split('/') : [];
        const text = a ? (a.textContent || '').trim() : '';
        const [chan, guild] = text.includes(' / ') ? text.split(' / ') : [text, ''];
        voice = { channel: chan || 'Voice channel', guild, guild_id: parts[2] || '', channel_id: parts[3] || '' };
      }
      const on = (b) => b ? (b.getAttribute('aria-checked') === 'true' || /^un/i.test(b.getAttribute('aria-label'))) : false;
      return { signedIn, login: location.pathname.startsWith('/login'), voice,
               mute: on(mute), deaf: on(deaf) };
    })()"""

    def status(self):
        if not self.running():
            return {"running": False, "signed_in": bool(util.load_config()["discord"].get("signed_in"))}
        try:
            st = self.js(self.STATE_JS, timeout=6) or {}
        except DiscordError as e:
            return {"running": True, "signed_in": False, "error": str(e)}
        if st.get("signedIn") and not util.load_config()["discord"].get("signed_in"):
            util.update_config(lambda c: c["discord"].__setitem__("signed_in", True))
        self.cache["voice"] = st.get("voice")
        return {"running": True, "signed_in": bool(st.get("signedIn")), "login": bool(st.get("login")),
                "voice": st.get("voice"), "mute": bool(st.get("mute")), "deaf": bool(st.get("deaf"))}

    def guilds(self):
        self.start()
        g = self.js(r"""(() => [...document.querySelectorAll('[data-list-item-id^="guildsnav___"]')].map(e => {
            const id = e.getAttribute('data-list-item-id').split('___')[1];
            let name = (e.getAttribute('aria-label') || e.textContent || '').trim();
            name = name.replace(/^(\d+\s+mentions?,\s*|unread,\s*)+/i, '').trim();
            return { id, name };
          }).filter(g => /^\d+$/.test(g.id) && g.name))()""") or []
        if not g:
            raise DiscordError("Sign in to Discord first (Social › Discord › Sign In)")
        self.cache["guilds"] = g
        return g

    def voice_channels(self, guild_id):
        self._open_guild(guild_id)
        chans = []
        for _ in range(20):                       # the channel list renders a moment after switching
            chans = self.js(r"""(() => [...document.querySelectorAll('[data-list-item-id^="channels___"]')].map(e => {
                const label = e.getAttribute('aria-label') || '';
                const m = label.match(/^(.*?)\s*\((voice|stage) channel\)(?:,\s*(\d+)\s+users?)?/i);
                if (!m) return null;
                return { id: e.getAttribute('data-list-item-id').split('___')[1], name: m[1].trim(),
                         kind: m[2].toLowerCase(), users: m[3] ? parseInt(m[3], 10) : 0 };
              }).filter(Boolean))()""") or []
            if chans:
                break
            time.sleep(0.25)
        return chans

    # ---- actions ---------------------------------------------------------------------
    def _open_guild(self, guild_id):
        if not re.fullmatch(r"\d+", str(guild_id)):
            raise ValueError("guild id")
        self.start()
        ok = self.js(f"""(() => {{ const e = document.querySelector('[data-list-item-id="guildsnav___{guild_id}"]');
                         if (!e) return false; e.click(); return true; }})()""")
        if not ok:
            raise DiscordError("That server isn't in your Discord list")
        time.sleep(0.6)

    def join(self, guild_id, channel_id):
        if not re.fullmatch(r"\d+", str(channel_id)):
            raise ValueError("channel id")
        self._open_guild(guild_id)
        for _ in range(20):
            ok = self.js(f"""(() => {{ const e = document.querySelector('[data-list-item-id="channels___{channel_id}"]');
                             if (!e) return false; e.click(); return true; }})()""")
            if ok:
                break
            time.sleep(0.25)
        else:
            raise DiscordError("Couldn't find that voice channel (it may be in a collapsed category)")
        for _ in range(30):                      # connected when the Disconnect button appears
            time.sleep(0.25)
            st = self.status()
            if st.get("voice") and st["voice"].get("channel_id") in ("", str(channel_id)):
                return st
        raise DiscordError("Discord didn't connect to the channel")

    def _click_label(self, pattern, what):
        ok = self.js(f"""(() => {{ const b = [...document.querySelectorAll('button[aria-label]')]
                           .find(x => /{pattern}/i.test(x.getAttribute('aria-label'))); if (!b) return false; b.click(); return true; }})()""")
        if not ok:
            raise DiscordError(f"Couldn't find Discord's {what} button")
        time.sleep(0.3)
        return self.status()

    def leave(self):
        return self._click_label("^Disconnect$", "Disconnect")

    def toggle_mute(self):
        return self._click_label("^(Mute|Unmute)$", "Mute")

    def toggle_deaf(self):
        return self._click_label("^(Deafen|Undeafen)$", "Deafen")

    def sign_out_local(self):
        """Forget the Discord sign-in on this console (deletes the window's profile)."""
        self.stop()
        import shutil
        shutil.rmtree(PROFILE, ignore_errors=True)
        util.update_config(lambda c: c["discord"].__setitem__("signed_in", False))


DISCORD = DiscordWeb()
