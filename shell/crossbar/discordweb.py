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
import contextlib
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
      const ss = window.__cbShareStream;
      const sharing = !!(ss && ss.active && ss.getVideoTracks().some((t) => t.readyState === 'live')) ||
        !![...document.querySelectorAll('[aria-label]')].find((x) => /^(stop streaming|stop sharing)/i.test(x.getAttribute('aria-label')));
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
      const c0 = window.__cbStores;
      if (c0 && c0.RelationshipStore && c0.ChannelStore) return c0;
      const chunk = window.webpackChunkdiscord_app;
      if (!chunk || !chunk.push) return c0 || null;
      let req = null;
      try { chunk.push([[Symbol('crossbar')], {}, (r) => { req = r; }]); chunk.pop(); } catch (e) { return c0 || null; }
      if (!req || !req.c) return c0 || null;
      const want = ['RelationshipStore', 'PresenceStore', 'UserStore', 'ChannelStore', 'ApplicationStreamingStore'];
      const found = Object.assign({}, c0 || {});
      const has = (v, n) => { try { return typeof v[n] === 'function'; } catch (e) { return false; } };
      const check = (v) => {
        if (!v || (typeof v !== 'object' && typeof v !== 'function')) return;
        try { if (typeof v.getName === 'function') { const n = v.getName(); if (want.includes(n) && !found[n]) found[n] = v; } } catch (e) { /* lazy export */ }
        // by what they can do, in case a store is renamed: the one that knows your DM with someone
        if (!found.ChannelStore && has(v, 'getDMFromUserId') && has(v, 'getChannel')) found.ChannelStore = v;
        if (!found.RelationshipStore && has(v, 'getFriendIDs') && has(v, 'isFriend')) found.RelationshipStore = v;
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
        acts = self.js(f"(() => {{ const A = {self.ACTIONS_JS}; return A ? Object.keys(A) : null; }})()", timeout=15)
        return {**(self.js(self.DEBUG_JS % self.STORES_JS, timeout=15) or {}), "via": self.cache.get("friends_via"),
                "call_functions": acts,
                "voice_buttons": self.js(f"{self.LABELS_JS}('share|screen|stream|call|disconnect|mute|deafen')"),
                "voice_panel": [c.get("name") or "?" for c in (self.js(f"{self.CONTROLS_JS}('voice')") or [])][:20]}

    # ---- finding Discord's buttons ---------------------------------------------------------
    # Discord keeps renaming and relabelling its buttons; some (the voice panel's Camera /
    # Share Your Screen row) now only name themselves in a hover tooltip. So a control is
    # found by its accessible name if it has one, else by hovering it (a real mouse move)
    # and reading the tooltip Discord shows, the way you'd find it yourself.
    CONTROLS_JS = r"""((scope) => {
      const visible = (x) => { const r = x.getBoundingClientRect();
        return r.width > 2 && r.height > 2 && r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth; };
      const nameOf = (x) => {
        let n = x.getAttribute('aria-label') || '';
        if (!n && x.getAttribute('aria-labelledby'))
          n = x.getAttribute('aria-labelledby').split(/\s+/).map((id) => ((document.getElementById(id) || {}).textContent || '')).join(' ');
        n = n || x.getAttribute('title') || x.getAttribute('data-tooltip') || '';
        if (!n) { const s = x.querySelector('[aria-label]'); if (s) n = s.getAttribute('aria-label') || ''; }
        if (!n) n = (x.innerText || '').trim().split('\n')[0];
        return n.trim().slice(0, 60);
      };
      let root = document;
      if (scope === 'voice') {
        let box = document.querySelector('[aria-label="Disconnect"]');
        for (let i = 0; i < 7 && box; i++) {
          box = box.parentElement;
          if (box && box.querySelectorAll('button, [role="button"]').length >= 4) break;
        }
        root = box || document;
      } else if (scope === 'header') {
        const t = document.querySelector('[class*="toolbar"]');
        root = t ? (t.closest('section') || t.parentElement || t) : document;
      }
      return [...root.querySelectorAll('button, [role="button"]')].filter(visible).map((x) => {
        const r = x.getBoundingClientRect();
        return { name: nameOf(x), x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
      });
    })"""
    TOOLTIP_JS = r"""(() => {
      const t = [...document.querySelectorAll('[role="tooltip"], [class*="tooltipContent"], [class*="tooltip_"]')]
        .map((x) => (x.innerText || '').trim()).filter(Boolean);
      return t.length ? t[t.length - 1].split('\n')[0].slice(0, 60) : '';
    })()"""

    def _find_control(self, pattern, scope="all", avoid=None, hover=True, limit=16):
        """((x, y) or None, [names seen]) for the first visible button whose name matches."""
        rx = re.compile(pattern, re.I)
        bad = re.compile(avoid, re.I) if avoid else None
        good = lambda n: bool(n) and bool(rx.search(n)) and not (bad and bad.search(n))   # noqa: E731
        ctrls = self.js(f"{self.CONTROLS_JS}({json.dumps(scope)})") or []
        seen = []
        for c in ctrls:
            if good(c.get("name")):
                return (c["x"], c["y"]), seen
            if c.get("name") and c["name"] not in seen:
                seen.append(c["name"])
        if hover:
            unnamed = [c for c in ctrls if len(c.get("name") or "") < 2][:limit]
            try:
                for c in unnamed:
                    self._cmd("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": c["x"], "y": c["y"]})
                    tip = ""
                    for _ in range(4):           # tooltips appear after a short delay
                        time.sleep(0.15)
                        tip = self.js(self.TOOLTIP_JS) or ""
                        if tip:
                            break
                    if tip and tip not in seen:
                        seen.append(f"{tip} (tooltip)")
                    if good(tip):
                        return (c["x"], c["y"]), seen
            finally:
                try:
                    self._cmd("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 2, "y": 2})
                except DiscordError:
                    pass
            if unnamed and not any(s.endswith("(tooltip)") for s in seen):
                seen.append(f"{len(unnamed)} unlabelled")
        return None, seen

    def _trusted_click(self, xy):
        self._cmd("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": xy[0], "y": xy[1]})
        for t in ("mousePressed", "mouseReleased"):
            self._cmd("Input.dispatchMouseEvent", {"type": t, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1})

    @contextlib.contextmanager
    def _laid_out(self):
        """While Crossbar works the page: lay it out at desktop size and treat it as focused.
        Hidden away, the window can be small (Discord then tucks buttons like Share Your Screen
        and Start Voice Call out of sight) and unfocused (keyboard shortcuts don't fire)."""
        try:
            self._cmd("Emulation.setFocusEmulationEnabled", {"enabled": True})
            self._cmd("Emulation.setDeviceMetricsOverride", {"width": 1600, "height": 900, "deviceScaleFactor": 0, "mobile": False})
            time.sleep(0.5)                       # let Discord re-layout
        except DiscordError:
            pass
        try:
            yield
        finally:
            for m, p in (("Emulation.clearDeviceMetricsOverride", {}), ("Emulation.setFocusEmulationEnabled", {"enabled": False})):
                try:
                    self._cmd(m, p)
                except DiscordError:
                    pass

    # labels on the voice panel / chat header, for error messages ("what Crossbar could see")
    LABELS_JS = r"""((re) => [...new Set([...document.querySelectorAll('[aria-label]')].map((x) => x.getAttribute('aria-label'))
                       .filter((l) => l && new RegExp(re, 'i').test(l)))].slice(0, 12))"""

    # ---- calling a friend ------------------------------------------------------------------
    CALL_RE = r"^start (a )?(voice )?call$|voice call|^call$|^start call"
    CALL_AVOID = r"video|end|leave|disconnect|settings|missed|decline|camera"
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

    def _go_home(self):
        self.js(r"""(() => { const h = document.querySelector('[data-list-item-id="guildsnav___home"]') ||
                                       document.querySelector('a[href="/channels/@me"]');
                             if (h) h.click(); return !!h; })()""")
        time.sleep(0.6)

    def _open_dm(self, uid):
        """Open the DM with a friend, the way clicking it would. True once its chat has loaded."""
        if uid.isdigit():
            # 1) Discord's own "open DM" (what clicking Message on a friend does)
            r = self.js(f"""(async () => {{
                const S = {self.STORES_JS}, A = {self.ACTIONS_JS};
                const C = S && S.ChannelStore;
                let cid = null;
                try {{ cid = C && C.getDMFromUserId ? C.getDMFromUserId('{uid}') : null; }} catch (e) {{}}
                if (cid && A && A.transitionTo) {{ try {{ A.transitionTo('/channels/@me/' + cid); return 'nav'; }} catch (e) {{}} }}
                const open = A && (A.openPrivateChannel || A.ensurePrivateChannel);
                if (open) {{ try {{ const p = open('{uid}'); if (p && p.then) await p; return 'open'; }} catch (e) {{}} }}
                return cid ? 'cid:' + cid : null;
              }})()""", timeout=20)
            if r in ("nav", "open") and self._wait(self.DM_READY_JS, 8):
                return True
            # 2) its entry in the Direct Messages list (found by the friend's avatar or id)
            self._go_home()
            cid = r[4:] if isinstance(r, str) and r.startswith("cid:") else ""
            xy = self.js(f"""(() => {{
                const links = [...document.querySelectorAll('a[href^="/channels/@me/"]')];
                const a = links.find((x) => {json.dumps(cid)} && x.getAttribute('href') === '/channels/@me/{cid}') ||
                          links.find((x) => x.querySelector('img[src*="/avatars/{uid}/"]'));
                if (!a) return null;
                a.scrollIntoView({{ block: 'center' }});
                const b = a.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2];
              }})()""")
            if xy:
                self._trusted_click(xy)
                if self._wait(self.DM_READY_JS, 8):
                    return True
            if cid:                              # 3) load the page there (slow, but always works)
                try:
                    self.js(f"location.assign('/channels/@me/{cid}'); true", timeout=5)
                except DiscordError:
                    pass
                self.session = None
                if self._wait(self.DM_READY_JS, 45):
                    return True
        # 4) click the friend on Home › Friends › Online (a real click), which opens the DM
        self.js(self.GO_FRIENDS_JS, timeout=15)
        if uid.isdigit():
            find = f"""r.getAttribute('data-list-item-id') === 'people-list___{uid}' || !!r.querySelector('img[src*="/avatars/{uid}/"]')"""
        else:
            find = f"""(r.innerText || '').split('\\n')[0].trim() === {json.dumps(uid[5:])}"""
        for _ in range(20):
            xy = self.js(f"""(() => {{ const r = ({self.ROWS_JS}).find((r) => {find});
                             if (!r) return null; r.scrollIntoView({{ block: 'center' }});
                             const n = r.querySelector('[class*="name"], [class*="username"]') || r;
                             const b = n.getBoundingClientRect(); return [b.left + Math.min(40, b.width / 2), b.top + b.height / 2]; }})()""")
            if xy:
                self._trusted_click(xy)
                if self._wait(self.DM_READY_JS, 8):
                    return True
                # the row's Message button opens the DM too
                mxy = self.js(f"""(() => {{ const r = ({self.ROWS_JS}).find((r) => {find});
                                  const m = r && r.querySelector('[aria-label="Message"]'); if (!m) return null;
                                  const b = m.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; }})()""")
                if mxy:
                    self._trusted_click(mxy)
                    return self._wait(self.DM_READY_JS, 8)
                return False
            time.sleep(0.25)
        raise DiscordError("Couldn't find that friend in Discord's Friends list")

    # Discord's own functions, found among the page's modules the way its code finds them:
    # open a DM (openPrivateChannel), go to a page (transitionTo), start or join a call
    # (selectVoiceChannel: in a DM that's exactly what the call button does, and it rings them).
    ACTIONS_JS = r"""(() => {
      if (window.__cbActions && window.__cbActions.selectVoiceChannel && window.__cbActions.transitionTo) return window.__cbActions;
      const chunk = window.webpackChunkdiscord_app;
      if (!chunk || !chunk.push) return window.__cbActions || null;
      let req = null;
      try { chunk.push([[Symbol('crossbar-actions')], {}, (r) => { req = r; }]); chunk.pop(); } catch (e) { return null; }
      if (!req || !req.c) return null;
      const out = {};
      const fn = (o, n) => { try { return typeof o[n] === 'function'; } catch (e) { return false; } };
      const take = (obj) => {
        if (!obj || (typeof obj !== 'object' && typeof obj !== 'function')) return;
        // the channel actions object has both (a look-alike elsewhere wouldn't)
        if (!out.selectVoiceChannel && fn(obj, 'selectVoiceChannel') && fn(obj, 'selectChannel')) out.selectVoiceChannel = obj.selectVoiceChannel.bind(obj);
        if (!out.openPrivateChannel && fn(obj, 'openPrivateChannel')) out.openPrivateChannel = obj.openPrivateChannel.bind(obj);
        if (!out.ensurePrivateChannel && fn(obj, 'ensurePrivateChannel')) out.ensurePrivateChannel = obj.ensurePrivateChannel.bind(obj);
        if (!out.getOrEnsurePrivateChannel && fn(obj, 'getOrEnsurePrivateChannel')) out.getOrEnsurePrivateChannel = obj.getOrEnsurePrivateChannel.bind(obj);
        if (!out.ring && fn(obj, 'ring') && fn(obj, 'stopRinging')) out.ring = obj.ring.bind(obj);
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
          if (v && typeof v === 'object') take(v.default);
          if (!out.transitionTo && typeof v === 'function') {
            try { if (/transitionTo - Transitioning to/.test(Function.prototype.toString.call(v))) out.transitionTo = v; } catch (e) { /* native */ }
          }
        }
        if (out.selectVoiceChannel && out.openPrivateChannel && out.transitionTo && out.ring) break;
      }
      window.__cbActions = out;
      return out;
    })()"""

    def _internal_call(self, uid):
        """Start the call with Discord's own functions. Returns a note of what was missing, or None."""
        r = self.js(f"""(async () => {{
            const S = {self.STORES_JS}, A = {self.ACTIONS_JS};
            const have = 'stores: ' + (S ? Object.keys(S).join('/') : 'none') + ', functions: ' + (A ? Object.keys(A).join('/') || 'none' : 'none');
            if (!A || !A.selectVoiceChannel) return {{ ok: false, why: 'start-call function not found (' + have + ')' }};
            const C = S && S.ChannelStore;
            const dm = () => {{
              try {{ const c = C && C.getDMFromUserId ? C.getDMFromUserId('{uid}') : null; if (c) return c; }} catch (e) {{}}
              const m = location.pathname.match(/^\\/channels\\/@me\\/(\\d+)/); return m ? m[1] : null;
            }};
            let cid = C ? dm() : null;
            if (!cid) {{
              for (const name of ['getOrEnsurePrivateChannel', 'ensurePrivateChannel', 'openPrivateChannel']) {{
                if (!A[name]) continue;
                try {{ const p = A[name]('{uid}'); const v = p && p.then ? await p : p;
                       if (typeof v === 'string' && /^\\d+$/.test(v)) cid = v; }} catch (e) {{ /* try the next */ }}
                for (let i = 0; i < 20 && !cid; i++) {{ await new Promise(r => setTimeout(r, 150)); cid = dm(); }}
                if (cid) break;
              }}
              if (!cid) return {{ ok: false, why: "couldn't open your DM with them (" + have + ')' }};
            }}
            try {{ if (A.transitionTo) A.transitionTo('/channels/@me/' + cid); }} catch (e) {{ /* showing it is optional */ }}
            A.selectVoiceChannel(cid);
            if (A.ring) {{ await new Promise(r => setTimeout(r, 1200)); try {{ A.ring(cid); }} catch (e) {{ /* already ringing */ }} }}
            return {{ ok: true, cid }};
          }})()""", timeout=25) or {}
        return None if r.get("ok") else (r.get("why") or "unknown")

    def call(self, user_id):
        """Call a friend: Discord's own "start call" for your DM with them (it rings them),
        falling back to opening the DM and pressing its call button / Ctrl+'."""
        uid = str(user_id)
        if not re.fullmatch(r"\d+|name:.{1,100}", uid):
            raise ValueError("user id")
        self.start()
        with self._laid_out():
            return self._call(uid)

    def _call(self, uid):
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
            time.sleep(0.6)
            xy = seen = None
            for i in range(8):                   # the header fills in a moment after the chat
                xy, seen = self._find_control(self.CALL_RE, "header", self.CALL_AVOID, hover=(i == 7 or i == 3))
                if xy:
                    break
                time.sleep(0.4)
            if xy:
                self._trusted_click(xy)
                st = self._in_call(10)
                if st:
                    return st
            self._press_call_shortcut()
            st = self._in_call(10)
            if st:
                return st
            notes.append("chat buttons: " + (", ".join(seen or []) or "none"))
        else:
            notes.append(f"chat didn't open (at {self.js('location.pathname')})")
        raise DiscordError("Couldn't start the call: " + "; ".join(n for n in notes if n))

    # ---- screen share (Go Live) -----------------------------------------------------------
    # The button must be pressed with a real (trusted) click: browsers only allow screen
    # capture from one. The screen is picked automatically (no picker to use on a TV).
    # Crossbar keeps a hand on the captured stream, so it can tell sharing is on (whatever
    # Discord's buttons are called this month) and stop it by ending the capture.
    SHARE_HOOK_JS = r"""(() => {
      const md = navigator.mediaDevices;
      if (!md || !md.getDisplayMedia) return false;
      if (!window.__cbGDM) {
        const orig = md.getDisplayMedia.bind(md);
        window.__cbGDM = orig;
        md.getDisplayMedia = async (...a) => { const s = await orig(...a); window.__cbShareStream = s; return s; };
      }
      return true;
    })()"""
    SHARING_JS = r"""(() => {
      const s = window.__cbShareStream;
      if (s && s.active && s.getVideoTracks().some((t) => t.readyState === 'live')) return true;
      try { const A = window.__cbStores && window.__cbStores.ApplicationStreamingStore;
            if (A && A.getCurrentUserActiveStream && A.getCurrentUserActiveStream()) return true; } catch (e) {}
      return !![...document.querySelectorAll('[aria-label]')].find((x) => /^(stop streaming|stop sharing)/i.test(x.getAttribute('aria-label')));
    })()"""
    SHARE_RE = r"share (your )?screen|screen ?share|^screen$|go live|^stream( your screen)?$"
    SHARE_AVOID = r"stop|settings|end|quality|watch|join"

    def sharing(self):
        return bool(self.js(self.SHARING_JS))

    def _stop_share(self):
        xy, _ = self._find_control(r"^stop (streaming|sharing|stream)|stop screen ?share", "voice", hover=False)
        if xy:
            self._trusted_click(xy)
            time.sleep(0.6)
        if self.sharing():                       # end the capture itself: Discord stops the stream
            self.js("(() => { const s = window.__cbShareStream; if (s) s.getTracks().forEach((t) => t.stop()); return true; })()")
        return {"sharing": False}

    def share_screen(self, on=True):
        self.start()
        st = self.status()
        if not st.get("voice"):
            raise DiscordError("Join a voice channel or call first")
        if not on:
            with self._laid_out():
                return self._stop_share()
        if self.sharing():
            return {"sharing": True}
        if not self.js(self.SHARE_HOOK_JS):
            raise DiscordError("This Discord window can't share the screen (no screen capture in the browser)")
        with self._laid_out():
            xy, seen = self._find_control(self.SHARE_RE, "voice", self.SHARE_AVOID)
            if not xy:
                more_xy, more = self._find_control(self.SHARE_RE, "all", self.SHARE_AVOID, hover=False)
                xy, seen = more_xy, seen + [m for m in more if m not in seen][:6]
            if not xy and (st["voice"] or {}).get("channel_id"):
                # the call's own page has the same button in its control bar
                v = st["voice"]
                path = f"/channels/{v.get('guild_id') or '@me'}/{v['channel_id']}"
                if re.fullmatch(r"/channels/(@me|\d+)/\d+", path):
                    self.js(f"""(() => {{ const A = {self.ACTIONS_JS};
                        if (A && A.transitionTo) {{ A.transitionTo('{path}'); return true; }}
                        const a = document.querySelector('a[href="{path}"]'); if (a) a.click(); return !!a; }})()""", timeout=15)
                    time.sleep(1.2)
                    xy, more = self._find_control(self.SHARE_RE, "all", self.SHARE_AVOID, limit=24)
                    seen += [m for m in more if m not in seen][:8]
            if not xy:
                raise DiscordError("Couldn't find Discord's Share Your Screen button (buttons seen: "
                                   + (", ".join(seen[:14]) or "none") + ")")
            self._trusted_click(xy)
            for _ in range(30):                 # Discord may ask for quality first: press its Go Live
                time.sleep(0.4)
                if self.sharing():
                    return {"sharing": True}
                golive, _ = self._find_control(r"^go live$", "all", hover=False)
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
