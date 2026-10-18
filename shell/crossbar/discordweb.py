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
                # screen share: through PipeWire / the desktop portal, the whole screen picked for you
                "--enable-features=WebRTCPipeWireCapturer", "--auto-select-desktop-capture-source=Entire screen",
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
      const sharing = !![...document.querySelectorAll('[aria-label]')].find((x) => /^(stop streaming|stop sharing)/i.test(x.getAttribute('aria-label')));
      return { signedIn, login: location.pathname.startsWith('/login'), voice,
               mute: on(mute), deaf: on(deaf), sharing };
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
                "voice": st.get("voice"), "mute": bool(st.get("mute")), "deaf": bool(st.get("deaf")),
                "sharing": bool(st.get("sharing"))}

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

    # ---- friends ----------------------------------------------------------------------------
    # First choice: the friends list and online status the Discord page already has in memory
    # (its RelationshipStore / PresenceStore / UserStore, found the way Discord's own modules
    # find them). Nothing is sent to Discord: it's what the Friends page shows, read directly,
    # so it works whatever page the window is on. Fallback: read the Friends › Online page.
    STORES_JS = r"""(() => {
      if (window.__cbStores && window.__cbStores.RelationshipStore) return window.__cbStores;
      const chunk = window.webpackChunkdiscord_app;
      if (!chunk || !chunk.push) return null;
      let req = null;
      try { chunk.push([[Symbol('crossbar')], {}, (r) => { req = r; }]); chunk.pop(); } catch (e) { return null; }
      if (!req || !req.c) return null;
      const want = ['RelationshipStore', 'PresenceStore', 'UserStore', 'ChannelStore'];
      const found = {};
      const check = (v) => {
        try { if (v && typeof v.getName === 'function') { const n = v.getName(); if (want.includes(n) && !found[n]) found[n] = v; } } catch (e) { /* lazy export */ }
      };
      for (const m of Object.values(req.c)) {
        const ex = m && m.exports;
        if (!ex || (typeof ex !== 'object' && typeof ex !== 'function')) continue;
        check(ex);
        let keys = [];
        try { keys = Object.keys(ex); } catch (e) { continue; }
        for (const k of keys) { let v; try { v = ex[k]; } catch (e) { continue; } check(v); if (v && typeof v === 'object') check(v.default); }
        if (want.every((n) => found[n])) break;
      }
      if (!found.RelationshipStore) return null;
      window.__cbStores = found;
      return found;
    })()"""

    FRIENDS_STORE_JS = r"""(() => {
      const S = %s;
      if (!S || !S.RelationshipStore || !S.UserStore) return null;
      const R = S.RelationshipStore, P = S.PresenceStore, U = S.UserStore;
      let ids = [];
      try { if (typeof R.getFriendIDs === 'function') ids = R.getFriendIDs() || []; } catch (e) { /* older client */ }
      if (!ids.length) {
        let rel = {};
        try { rel = (R.getMutableRelationships || R.getRelationships).call(R) || {}; } catch (e) { /* ignore */ }
        const entries = rel instanceof Map ? [...rel.entries()] : Object.entries(rel);
        ids = entries.filter(([, t]) => t === 1 || (t && t.type === 1)).map(([id]) => id);
      }
      const rank = { online: 0, idle: 2, dnd: 3 };
      const out = [];
      for (const id of ids) {
        const status = P && P.getStatus ? P.getStatus(id) : 'online';
        if (!(status in rank)) continue;                        // offline / invisible
        const acts = (P && P.getActivities ? P.getActivities(id) : []) || [];
        const game = acts.find((a) => a.type === 0), listen = acts.find((a) => a.type === 2), custom = acts.find((a) => a.type === 4);
        const u = U.getUser(id) || {};
        const line = game ? `Playing ${game.name}` : listen ? `Listening to ${listen.name}`
          : custom && custom.state ? custom.state : ({ online: 'Online', idle: 'Idle', dnd: 'Do Not Disturb' })[status];
        out.push({ id, name: u.globalName || u.global_name || u.username || id, status: line, game: game ? game.name : '',
                   presence: status, avatar: u.avatar ? `https://cdn.discordapp.com/avatars/${id}/${u.avatar}.png?size=128` : null,
                   r: (game ? 0 : 1) + rank[status] });
      }
      out.sort((a, b) => a.r - b.r || a.name.localeCompare(b.name));
      return out;
    })()"""

    # Fallback: Home › Friends › Online, read off the page (rows found several ways, since
    # Discord renames its classes; the user id comes from the row id or the avatar picture).
    GO_FRIENDS_JS = r"""(async () => {
      const wait = (ms) => new Promise(r => setTimeout(r, ms));
      const home = document.querySelector('[data-list-item-id="guildsnav___home"]') ||
                   document.querySelector('a[href="/channels/@me"]');
      if (!home) return false;
      if (!location.pathname.startsWith('/channels/@me') || /\/channels\/@me\/\d/.test(location.pathname)) {
        home.click(); await wait(600);
        const link = document.querySelector('a[href="/channels/@me"]'); if (link) { link.click(); await wait(600); }
      }
      const tab = [...document.querySelectorAll('[role="tab"]')].find(t => /^online/i.test((t.textContent || '').trim()));
      if (tab && tab.getAttribute('aria-selected') !== 'true') { tab.click(); await wait(600); }
      return true;
    })()"""
    ROWS_JS = r"""(() => {
      const rows = new Set(document.querySelectorAll('[data-list-item-id^="people-list___"], [class*="peopleListItem"]'));
      document.querySelectorAll('[aria-label="Message"], [aria-label="More"]').forEach((b) => {
        const r = b.closest('[role="listitem"], [class*="peopleListItem"], [class*="listItem"]'); if (r) rows.add(r); });
      return [...rows];
    })()"""
    FRIENDS_PAGE_JS = r"""(async () => {
      const wait = (ms) => new Promise(r => setTimeout(r, ms));
      const rowsNow = () => %s;
      const out = new Map();
      const grab = () => rowsNow().forEach((e) => {
        const lid = e.getAttribute('data-list-item-id') || '';
        const img = e.querySelector('img[src*="/avatars/"]');
        const m = (img && img.src.match(/\/avatars\/(\d+)\//)) || lid.match(/___(\d+)$/);
        const btn = new Set([...e.querySelectorAll('button, [role="button"]')].map((b) => (b.innerText || '').trim()).filter(Boolean));
        const lines = (e.innerText || '').split('\n').map((x) => x.trim()).filter((x) => x && !btn.has(x));
        if (!lines.length) return;
        const id = m ? m[1] : 'name:' + lines[0];
        out.set(id, { id, name: lines[0], status: lines[1] || 'Online',
                      avatar: img ? img.src : null });
      });
      grab();
      const first = rowsNow()[0];
      let list = first;
      while (list && list.scrollHeight <= list.clientHeight + 4) list = list.parentElement;
      for (let i = 0; list && i < 40 && list.scrollTop + list.clientHeight < list.scrollHeight - 4; i++) {
        list.scrollTop += list.clientHeight * 0.8; await wait(150); grab();
      }
      if (list) list.scrollTop = 0;
      return [...out.values()];
    })()"""

    def friends(self):
        """Friends who are online now: [{id, name, status, avatar}], people in a game first."""
        self.start()
        for attempt in range(4):
            if not self.js("!!document.querySelector('[data-list-item-id^=\"guildsnav___\"]')", timeout=6):
                time.sleep(1.5)                     # still loading (or signed out)
                continue
            try:
                r = self.js(self.FRIENDS_STORE_JS % self.STORES_JS, timeout=15)
                if r is not None:
                    self.cache["friends_via"] = "stores"
                    return r
            except DiscordError as e:
                print(f"discord: friends from stores: {e}", flush=True)
            if self.js(self.GO_FRIENDS_JS, timeout=15):
                time.sleep(0.4)
                r = self.js(self.FRIENDS_PAGE_JS % self.ROWS_JS, timeout=25) or []
                self.cache["friends_via"] = "page"
                return r
        raise DiscordError("Sign in to Discord first (Social › Sign In to Discord)")

    DEBUG_JS = r"""(() => {
      const S = %s;
      const q = (sel) => document.querySelectorAll(sel).length;
      let friendIds = null;
      try { friendIds = S && S.RelationshipStore && S.RelationshipStore.getFriendIDs ? S.RelationshipStore.getFriendIDs().length : null; } catch (e) { friendIds = 'error: ' + e; }
      return { path: location.pathname, webpack: !!window.webpackChunkdiscord_app,
               stores: S ? Object.keys(S) : null, friendIds,
               guilds: q('[data-list-item-id^="guildsnav___"]'), peopleRows: q('[data-list-item-id^="people-list___"]'),
               peopleClass: q('[class*="peopleListItem"]'), messageButtons: q('[aria-label="Message"]'),
               tabs: [...document.querySelectorAll('[role="tab"]')].map((t) => (t.textContent || '').trim()).slice(0, 8) };
    })()"""

    def debug(self):
        """What the friends reader can see (for bug reports)."""
        self.start()
        return {**(self.js(self.DEBUG_JS % self.STORES_JS, timeout=15) or {}), "via": self.cache.get("friends_via")}

    # The call button in a DM's header. Its label has been "Start Voice Call"; match loosely
    # (never the video one), so small wording changes don't break calling.
    CALL_BTN_JS = r"""(() => {
      const ok = (l) => /call/i.test(l) && !/video|end|leave|disconnect|ring|settings|missed/i.test(l);
      const all = [...document.querySelectorAll('[aria-label]')].filter((x) => ok(x.getAttribute('aria-label') || ''));
      const b = all.find((x) => /^start (a )?(voice )?call$/i.test(x.getAttribute('aria-label'))) ||
                all.find((x) => /voice call/i.test(x.getAttribute('aria-label'))) ||
                all.find((x) => /^call$/i.test(x.getAttribute('aria-label')));
      if (!b) return false;
      b.click(); return true;
    })()"""
    HEADER_LABELS_JS = r"""(() => {
      const box = document.querySelector('section[class*="title"], [class*="toolbar"]') || document;
      return [...box.querySelectorAll('[aria-label]')].map((x) => x.getAttribute('aria-label')).filter(Boolean).slice(0, 15);
    })()"""
    DM_READY_JS = r"""(() => /^\/channels\/@me\/\d+/.test(location.pathname) &&
      !!document.querySelector('[role="textbox"], form [contenteditable="true"], [data-slate-editor="true"]'))()"""

    def _wait(self, expr, seconds):
        end = time.time() + seconds
        while time.time() < end:
            try:
                if self.js(expr, timeout=6):
                    return True
            except DiscordError:
                self.session = None              # mid-navigation: attach again
            time.sleep(0.4)
        return False

    def _press_call_shortcut(self):
        """Discord's own shortcut for "start a call in this DM": Ctrl + ' (sent as real key presses)."""
        key = {"key": "'", "code": "Quote", "windowsVirtualKeyCode": 222, "nativeVirtualKeyCode": 222, "modifiers": 2}
        self._cmd("Input.dispatchKeyEvent", {"type": "rawKeyDown", **key})
        self._cmd("Input.dispatchKeyEvent", {"type": "keyUp", **key})

    def _in_call(self, seconds=8):
        end = time.time() + seconds
        while time.time() < end:
            time.sleep(0.4)
            st = self.status()
            if st.get("voice"):
                return st
        return None

    def _open_dm(self, uid):
        """Open the DM with a friend, the way clicking it would. True once its chat has loaded."""
        if uid.isdigit():
            cid = self.js(f"""(() => {{ const S = {self.STORES_JS};
                const C = S && S.ChannelStore;
                try {{ return C && C.getDMFromUserId ? C.getDMFromUserId('{uid}') : null; }} catch (e) {{ return null; }} }})()""", timeout=15)
            if cid:
                path = f"/channels/@me/{cid}"
                # 1) its entry in the Direct Messages list (a real link, handled by Discord's router)
                self.js(r"""(() => { const h = document.querySelector('[data-list-item-id="guildsnav___home"]'); if (h) h.click(); return true; })()""")
                time.sleep(0.6)
                if self.js(f"""(() => {{ const a = document.querySelector('a[href="{path}"]'); if (!a) return false; a.click(); return true; }})()"""):
                    if self._wait(self.DM_READY_JS, 8):
                        return True
                # 2) the router, told the address changed
                self.js(f"""(() => {{ history.pushState(null, '', '{path}'); dispatchEvent(new PopStateEvent('popstate', {{ state: null }})); return true; }})()""")
                if self._wait(self.DM_READY_JS, 6):
                    return True
                # 3) load the page there (slow, but always works)
                try:
                    self.js(f"location.assign('{path}'); true", timeout=5)
                except DiscordError:
                    pass
                self.session = None
                if self._wait(self.DM_READY_JS, 45):
                    return True
        # no DM yet: click the friend on Home › Friends › Online, which opens one
        self.js(self.GO_FRIENDS_JS, timeout=15)
        if uid.isdigit():
            find = f"""r.getAttribute('data-list-item-id') === 'people-list___{uid}' || !!r.querySelector('img[src*="/avatars/{uid}/"]')"""
        else:
            find = f"""(r.innerText || '').split('\\n')[0].trim() === {json.dumps(uid[5:])}"""
        for _ in range(20):
            if self.js(f"""(() => {{ const r = ({self.ROWS_JS}).find((r) => {find});
                             if (!r) return false; r.click(); return true; }})()"""):
                return self._wait(self.DM_READY_JS, 10)
            time.sleep(0.25)
        raise DiscordError("Couldn't find that friend in Discord's Friends list")

    # Discord's own functions, found among the page's modules the way its code finds them:
    # open a DM (openPrivateChannel), go to a page (transitionTo), start or join a call
    # (selectVoiceChannel: in a DM that's exactly what the call button does, and it rings them).
    ACTIONS_JS = r"""(() => {
      if (window.__cbActions && window.__cbActions.selectVoiceChannel) return window.__cbActions;
      const chunk = window.webpackChunkdiscord_app;
      if (!chunk || !chunk.push) return null;
      let req = null;
      try { chunk.push([[Symbol('crossbar-actions')], {}, (r) => { req = r; }]); chunk.pop(); } catch (e) { return null; }
      if (!req || !req.c) return null;
      const out = {};
      const take = (obj) => {
        if (!obj || (typeof obj !== 'object' && typeof obj !== 'function')) return;
        for (const name of ['selectVoiceChannel', 'openPrivateChannel', 'ensurePrivateChannel']) {
          try { if (!out[name] && typeof obj[name] === 'function') out[name] = obj[name].bind(obj); } catch (e) { /* lazy */ }
        }
      };
      for (const m of Object.values(req.c)) {
        const ex = m && m.exports;
        if (!ex) continue;
        take(ex);
        let keys = [];
        try { keys = Object.keys(ex); } catch (e) { continue; }
        for (const k of keys) {
          let v; try { v = ex[k]; } catch (e) { continue; }
          take(v);
          if (!out.transitionTo && typeof v === 'function') {
            try { if (/transitionTo - Transitioning to/.test(Function.prototype.toString.call(v))) out.transitionTo = v; } catch (e) { /* native */ }
          }
        }
        if (out.selectVoiceChannel && out.openPrivateChannel && out.transitionTo) break;
      }
      window.__cbActions = out;
      return out;
    })()"""

    def _internal_call(self, uid):
        """Start the call with Discord's own functions. Returns a note of what was missing, or None."""
        r = self.js(f"""(async () => {{
            const S = {self.STORES_JS}, A = {self.ACTIONS_JS};
            if (!S || !S.ChannelStore || !A) return {{ ok: false, why: 'modules not found' }};
            const C = S.ChannelStore;
            let cid = null;
            try {{ cid = C.getDMFromUserId('{uid}'); }} catch (e) {{ /* older client */ }}
            if (!cid) {{
              const open = A.openPrivateChannel || A.ensurePrivateChannel;
              if (!open) return {{ ok: false, why: 'no DM yet, and openPrivateChannel not found' }};
              try {{ const r = open('{uid}'); if (r && r.then) await r; }} catch (e) {{ /* it may still have opened */ }}
              for (let i = 0; i < 40 && !cid; i++) {{ await new Promise(r => setTimeout(r, 150)); try {{ cid = C.getDMFromUserId('{uid}'); }} catch (e) {{}} }}
              if (!cid) return {{ ok: false, why: "Discord didn't create the DM" }};
            }}
            try {{ if (A.transitionTo) A.transitionTo('/channels/@me/' + cid); }} catch (e) {{ /* showing it is optional */ }}
            if (!A.selectVoiceChannel) return {{ ok: false, why: 'selectVoiceChannel not found', cid }};
            A.selectVoiceChannel(cid);
            return {{ ok: true, cid }};
          }})()""", timeout=20) or {}
        return None if r.get("ok") else (r.get("why") or "unknown")

    def call(self, user_id):
        """Call a friend: Discord's own "start call" for your DM with them (it rings them),
        falling back to opening the DM and pressing its call button / Ctrl+'."""
        uid = str(user_id)
        if not re.fullmatch(r"\d+|name:.{1,100}", uid):
            raise ValueError("user id")
        self.start()
        notes = []
        if uid.isdigit():
            try:
                why = self._internal_call(uid)
            except DiscordError as e:
                why = str(e)
            if not why:
                st = self._in_call(12)
                if st:
                    return st
                why = "the call didn't start"
            notes.append(why)
        try:
            opened = self._open_dm(uid)
        except DiscordError as e:
            opened, _ = False, notes.append(str(e))
        if opened:
            time.sleep(0.5)
            for _ in range(15):
                if self.js(self.CALL_BTN_JS):
                    st = self._in_call()
                    if st:
                        return st
                    break
                time.sleep(0.4)
            self._press_call_shortcut()
            st = self._in_call(10)
            if st:
                return st
            notes.append("header buttons: " + (", ".join(self.js(self.HEADER_LABELS_JS) or []) or "none"))
        else:
            notes.append(f"chat didn't open (at {self.js('location.pathname')})")
        raise DiscordError("Couldn't start the call — " + "; ".join(n for n in notes if n))

    # ---- screen share (Go Live) -----------------------------------------------------------
    # The button must be pressed with a real (trusted) click: browsers only allow screen
    # capture from one. The screen is picked automatically (no picker to use on a TV).
    SHARE_BTN_JS = r"""((want) => {
      const re = want === 'stop' ? /^(stop streaming|stop sharing|stop screen ?share)/i : /^(share your screen|share screen|screen ?share|go live)/i;
      const b = [...document.querySelectorAll('button[aria-label], [role=button][aria-label]')].find((x) => re.test(x.getAttribute('aria-label')))
             || (want === 'golive' ? [...document.querySelectorAll('button')].find((x) => /^go live$/i.test((x.innerText || '').trim())) : null);
      if (!b) return null;
      const r = b.getBoundingClientRect();
      return [r.left + r.width / 2, r.top + r.height / 2];
    })"""

    def _trusted_click(self, xy):
        for t in ("mousePressed", "mouseReleased"):
            self._cmd("Input.dispatchMouseEvent", {"type": t, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1})

    def sharing(self):
        return bool(self.js(f"!!{self.SHARE_BTN_JS}('stop')"))

    def share_screen(self, on=True):
        self.start()
        if not self.status().get("voice"):
            raise DiscordError("Join a voice channel or call first")
        if not on:
            xy = self.js(f"{self.SHARE_BTN_JS}('stop')")
            if not xy:
                return {"sharing": False}
            self._trusted_click(xy)
            return {"sharing": False}
        if self.sharing():
            return {"sharing": True}
        xy = self.js(f"{self.SHARE_BTN_JS}('start')")
        if not xy:
            raise DiscordError("Couldn't find Discord's Share Your Screen button")
        self._trusted_click(xy)
        for _ in range(30):                     # Discord may ask for quality first: press its Go Live
            time.sleep(0.4)
            if self.sharing():
                return {"sharing": True}
            golive = self.js(f"{self.SHARE_BTN_JS}('golive')")
            if golive:
                self._trusted_click(golive)
        raise DiscordError("Screen sharing didn't start (the screen-capture portal may be missing: update Crossbar)")

    def sign_out_local(self):
        """Forget the Discord sign-in on this console (deletes the window's profile)."""
        self.stop()
        import shutil
        shutil.rmtree(PROFILE, ignore_errors=True)
        util.update_config(lambda c: c["discord"].__setitem__("signed_in", False))


DISCORD = DiscordWeb()
