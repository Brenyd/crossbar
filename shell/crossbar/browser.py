"""Crossbar's controller-friendly web browser.

Chromium, full screen, driven by Crossbar over its private DevTools pipe (like Discord, see
discordweb.py), so the controller works on any site without a mouse:

  D-pad / left stick  jump between links and buttons (including sites' clickable boxes), with
                      a big, clear highlight on the one that's selected
  A                   open it; on a text box, the on-screen keyboard, which types straight into
                      the page
  B                   back            L1 / R1   previous / next tab
  Right stick         scroll          L2 / R2   page up / down
  L3 (or Y › Pointer) pointer mode: a cursor for sites that need one (A clicks)
  Start               search or type an address
  Y                   the Browser page of the Quick Menu: address, tabs, bookmarks, size, close

Size: everything (pages and Chromium's own bars) is drawn at a scale made for a TV across the
room: 4K screens get 2.5x by default. Settings › Media › Browser, or the Browser page, change it.
"""
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse

from . import system, util

PROFILE = os.path.join(util.CONFIG_DIR, "browser")
START = "http://127.0.0.1:7777/browser.html"
SEARCH = "https://duckduckgo.com/?q={}"
SIZES = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0]
DEFAULT_BOOKMARKS = [
    {"name": "YouTube", "url": "https://www.youtube.com/"},
    {"name": "Wikipedia", "url": "https://en.wikipedia.org/"},
    {"name": "Reddit", "url": "https://www.reddit.com/"},
    {"name": "Twitch", "url": "https://www.twitch.tv/"},
    {"name": "DuckDuckGo", "url": "https://duckduckgo.com/"},
    {"name": "ProtonDB", "url": "https://www.protondb.com/"},
]

# Injected into every page: a highlight you can see from the couch, and the pointer.
PAGE_JS = r"""(() => {
  if (window.__cbBrowser) return; window.__cbBrowser = true;
  const css = `:focus, :focus-visible { outline: 4px solid #3ea6ff !important; outline-offset: 3px !important;
                 box-shadow: 0 0 0 8px rgba(62,166,255,.35) !important; border-radius: 6px; }
    #__cb_pointer { position: fixed; z-index: 2147483647; width: 30px; height: 30px; margin: -4px 0 0 -4px;
      pointer-events: none; display: none; filter: drop-shadow(0 2px 3px rgba(0,0,0,.6)); }`;
  const add = () => {
    if (!document.documentElement || document.getElementById('__cb_style')) return;
    const s = document.createElement('style'); s.id = '__cb_style'; s.textContent = css;
    (document.head || document.documentElement).appendChild(s);
    const p = document.createElement('div'); p.id = '__cb_pointer';
    p.innerHTML = '<svg viewBox="0 0 24 24" width="30" height="30"><path d="M3 2l17 10-7.5 1.6L9 21z" fill="#fff" stroke="#000" stroke-width="1.5" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(p);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add();
})()"""

TEXT_FIELD_JS = r"""(() => {
  let e = document.activeElement;
  while (e && e.shadowRoot && e.shadowRoot.activeElement) e = e.shadowRoot.activeElement;
  while (e && e.tagName === 'IFRAME') { try { e = e.contentDocument.activeElement; } catch (x) { break; } }
  if (!e) return false;
  if (e.isContentEditable) return true;
  if (e.tagName === 'TEXTAREA') return !e.readOnly && !e.disabled;
  if (e.tagName !== 'INPUT') return false;
  return !e.readOnly && !e.disabled && /^(|text|search|email|url|password|number|tel)$/i.test(e.type || '');
})()"""

# D-pad navigation: pick the nearest clickable thing in that direction (links, buttons, fields,
# and the click-handling divs many sites use), focus it and bring it into view. Nothing that
# way: scroll instead.
NAV_JS = r"""((dir) => {
  const sel = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [tabindex]:not([tabindex="-1"]), ' +
              '[role=button], [role=link], [role=tab], [role=menuitem], [role=option], [role=checkbox], [role=switch], ' +
              '[onclick], [contenteditable=""], [contenteditable=true], video, label[for]';
  const W = innerWidth, H = innerHeight;
  const vis = (r) => r.width > 4 && r.height > 4 && r.bottom > -H * 0.5 && r.top < H * 1.5 && r.right > 0 && r.left < W;
  const cands = [];
  const seen = new Set();
  const consider = (e) => {
    if (seen.has(e)) return; seen.add(e);
    const r = e.getBoundingClientRect();
    if (!vis(r)) return;
    const st = getComputedStyle(e);
    if (st.visibility === 'hidden' || st.display === 'none' || +st.opacity === 0 || e.disabled) return;
    cands.push([e, r]);
  };
  document.querySelectorAll(sel).forEach(consider);
  // click-handling elements without a role: anything showing the hand cursor whose parent doesn't
  for (const e of document.querySelectorAll('div, span, li, img, svg')) {
    if (cands.length > 600) break;
    if (getComputedStyle(e).cursor === 'pointer' && (!e.parentElement || getComputedStyle(e.parentElement).cursor !== 'pointer')) consider(e);
  }
  let cur = document.activeElement;
  if (!cur || cur === document.body || cur === document.documentElement) cur = null;
  if (cur) { const r0 = cur.getBoundingClientRect(); if (r0.bottom < 0 || r0.top > H) cur = null; }   // scrolled away from it
  if (!cur) {                                   // nothing highlighted yet: the first thing on screen, in reading order
    const on = cands.filter(([, r]) => r.top >= 0 && r.bottom <= H + 2).sort(([, a], [, b]) => (a.top - b.top) || (a.left - b.left));
    if (on.length) {
      const e = on[0][0];
      if (!e.matches('a[href], button, input, select, textarea, summary, [tabindex]')) e.setAttribute('tabindex', '-1');
      e.focus({ preventScroll: true });
      return 'moved';
    }
  }
  const cr = cur ? cur.getBoundingClientRect() : { left: W / 2, right: W / 2, top: dir === 'down' ? -1 : H, bottom: dir === 'down' ? -1 : H, width: 0, height: 0 };
  // from something wide (a search box, a banner) go to what's under its start, like reading
  const cx = cr.width > W * 0.45 ? cr.left + 60 : (cr.left + cr.right) / 2, cy = (cr.top + cr.bottom) / 2;
  let best = null, bestScore = Infinity;
  for (const [e, r] of cands) {
    if (e === cur || (cur && (cur.contains(e) || e.contains(cur)))) continue;
    const x = (r.left + r.right) / 2, y = (r.top + r.bottom) / 2;
    let main, side;
    if (dir === 'down') { if (r.top < cr.bottom - 2 && y <= cy + 2) continue; main = r.top - cr.bottom; side = Math.max(0, r.left - cr.right, cr.left - r.right); }
    else if (dir === 'up') { if (r.bottom > cr.top + 2 && y >= cy - 2) continue; main = cr.top - r.bottom; side = Math.max(0, r.left - cr.right, cr.left - r.right); }
    else if (dir === 'right') { if (r.left < cr.right - 2 && x <= cx + 2) continue; main = r.left - cr.right; side = Math.max(0, r.top - cr.bottom, cr.top - r.bottom); }
    else { if (r.right > cr.left + 2 && x >= cx - 2) continue; main = cr.left - r.right; side = Math.max(0, r.top - cr.bottom, cr.top - r.bottom); }
    const score = Math.max(0, main) + side * 2.5 + Math.abs(dir === 'up' || dir === 'down' ? x - cx : y - cy) * 0.15;
    if (score < bestScore) { bestScore = score; best = e; }
  }
  if (!best) {
    const dy = { down: 0.6, up: -0.6 }[dir] || 0, dx = { right: 0.6, left: -0.6 }[dir] || 0;
    scrollBy({ top: dy * H, left: dx * W, behavior: 'smooth' });
    return 'scrolled';
  }
  if (!best.matches('a[href], button, input, select, textarea, summary, [tabindex]')) best.setAttribute('tabindex', '-1');
  best.focus({ preventScroll: true });
  best.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
  return 'moved';
})"""

# Where to click for "A": the centre of the highlighted element (null: nothing highlighted).
TARGET_JS = r"""(() => {
  let e = document.activeElement;
  if (!e || e === document.body || e === document.documentElement) return null;
  if (e.tagName === 'IFRAME') return null;
  const r = e.getBoundingClientRect();
  if (r.width < 1 || r.height < 1) return null;
  const x = Math.min(innerWidth - 2, Math.max(1, r.left + Math.min(r.width / 2, 40)));
  const y = Math.min(innerHeight - 2, Math.max(1, r.top + r.height / 2));
  return [x, y];
})()"""

KEYS = {   # name: (key, code, windows virtual key code)
    "up": ("ArrowUp", "ArrowUp", 38), "down": ("ArrowDown", "ArrowDown", 40),
    "left": ("ArrowLeft", "ArrowLeft", 37), "right": ("ArrowRight", "ArrowRight", 39),
    "enter": ("Enter", "Enter", 13), "backspace": ("Backspace", "Backspace", 8), "tab": ("Tab", "Tab", 9),
    "pageup": ("PageUp", "PageUp", 33), "pagedown": ("PageDown", "PageDown", 34), "escape": ("Escape", "Escape", 27),
}


class BrowserError(RuntimeError):
    pass


def prefs():
    return util.load_config().get("browser") or {}


def auto_size():
    """A size that reads well from the couch: 1.25x at 1080p, 2.5x at 4K."""
    _, h = system.screen_size(physical=True)
    return max(1.0, min(4.0, round(h / 1080 * 1.25 * 4) / 4))


def size():
    z = prefs().get("size", "auto")
    return auto_size() if z == "auto" else float(z)


def to_url(text):
    t = (text or "").strip()
    if not t:
        return START
    if re.match(r"^[a-z][a-z0-9+.-]*://", t, re.I) or t.startswith("about:"):
        return t
    if " " not in t and re.match(r"^(localhost|[\w-]+(\.[\w-]+)+|\d+\.\d+\.\d+\.\d+)(:\d+)?(/.*)?$", t):
        return "https://" + t
    return SEARCH.format(urllib.parse.quote_plus(t))


class Browser:
    def __init__(self):
        self.proc = None
        self.wfd = self.rfd = None
        self.lock = threading.Lock()
        self.pending = {}
        self.next_id = 0
        self.sessions = {}        # targetId -> sessionId
        self.tab = None           # the tab in front (targetId)
        self.pointer = None       # [x, y] in CSS pixels while pointer mode is on
        self.speed = 0
        self.on_keyboard = None   # set by the server: open the on-screen keyboard

    # ---- process + DevTools pipe ---------------------------------------------------------------
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, urls=None):
        if self.running():
            win = self.window()
            if win:
                system.bring_to_front(win["con_id"])
            for u in urls or []:
                self.open_tab(u)
            return
        exe = os.environ.get("CROSSBAR_BROWSER", "chromium")
        if not util.which(exe):
            raise BrowserError("Chromium isn't installed")
        os.makedirs(PROFILE, exist_ok=True)
        to_r, to_w = os.pipe()
        from_r, from_w = os.pipe()

        def child():
            a, b = os.dup(to_r), os.dup(from_w)
            os.dup2(a, 3)
            os.dup2(b, 4)
        urls = urls or [START]
        args = [exe, "--ozone-platform-hint=auto", f"--user-data-dir={PROFILE}", "--remote-debugging-pipe",
                "--no-first-run", "--noerrdialogs", "--disable-infobars", "--disable-session-crashed-bubble",
                "--hide-crash-restore-bubble", "--autoplay-policy=no-user-gesture-required",
                f"--force-device-scale-factor={size()}",             # readable on a TV
                "--kiosk", *os.environ.get("CROSSBAR_BROWSER_ARGS", "").split(), urls[0]]
        from . import vpn
        self.proc = subprocess.Popen(vpn.wrap(args, "browser"), preexec_fn=child, pass_fds=(3, 4), stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        os.close(to_r)
        os.close(from_w)
        self.wfd, self.rfd, self.sessions, self.tab, self.pointer = to_w, from_r, {}, None, None
        threading.Thread(target=self._reader, args=(self.rfd,), daemon=True).start()
        for u in urls[1:]:
            try:
                self.open_tab(u)
            except Exception as e:
                print(f"browser: reopening a tab: {e}", flush=True)
        threading.Thread(target=self._front, daemon=True).start()

    def _front(self):
        for _ in range(40):
            time.sleep(0.5)
            win = self.window()
            if win:
                system.bring_to_front(win["con_id"])
                return

    def stop(self):
        if self.running():
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def window(self):
        if not self.running():
            return None
        return next((w for w in system.all_windows() if w.get("pid") == self.proc.pid), None)

    def focused(self):
        if not self.running():
            return False
        f = system.focused() or {}
        return bool(f.get("pid")) and f.get("pid") == self.proc.pid

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
                w = self.pending.pop(msg.get("id"), None)
                if w:
                    w["msg"] = msg
                    w["ev"].set()
                elif msg.get("method") == "Target.detachedFromTarget":
                    sid = (msg.get("params") or {}).get("sessionId")
                    self.sessions = {t: s for t, s in self.sessions.items() if s != sid}
        for w in list(self.pending.values()):
            w["msg"] = {"error": {"message": "The browser closed"}}
            w["ev"].set()

    def _cmd(self, method, params=None, session=None, timeout=10):
        if not self.running():
            raise BrowserError("The browser isn't open")
        with self.lock:
            self.next_id += 1
            mid = self.next_id
            waiter = {"ev": threading.Event(), "msg": None}
            self.pending[mid] = waiter
            msg = {"id": mid, "method": method, "params": params or {}}
            if session:
                msg["sessionId"] = session
            os.write(self.wfd, json.dumps(msg).encode() + b"\0")
        if not waiter["ev"].wait(timeout):
            self.pending.pop(mid, None)
            raise BrowserError("The browser didn't answer")
        m = waiter["msg"]
        if "error" in m:
            raise BrowserError(m["error"].get("message", "DevTools error"))
        return m.get("result", {})

    # ---- tabs ------------------------------------------------------------------------------------
    def tabs(self):
        out = []
        for t in self._cmd("Target.getTargets")["targetInfos"]:
            if t["type"] == "page" and not t.get("url", "").startswith(("devtools://", "chrome-extension://")):
                out.append({"id": t["targetId"], "title": t.get("title") or t.get("url", ""), "url": t.get("url", "")})
        return out

    def _current(self):
        tabs = self.tabs()
        if not tabs:
            raise BrowserError("No tabs open")
        if self.tab not in [t["id"] for t in tabs]:
            self.tab = tabs[0]["id"]
        return self.tab, tabs

    def _session(self, tid=None):
        tid = tid or self._current()[0]
        sid = self.sessions.get(tid)
        if not sid:
            sid = self._cmd("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
            self.sessions[tid] = sid
            try:
                self._cmd("Page.enable", session=sid)
                self._cmd("Page.addScriptToEvaluateOnNewDocument", {"source": PAGE_JS}, session=sid)
            except BrowserError:
                pass
        return sid

    def _page(self, method, params=None, timeout=10):
        return self._cmd(method, params, session=self._session(), timeout=timeout)

    def js(self, expr, timeout=10):
        r = self._page("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True}, timeout)
        return (r.get("result") or {}).get("value")

    def switch(self, tid):
        self._cmd("Target.activateTarget", {"targetId": tid})
        self.tab, self.pointer = tid, None

    def step_tab(self, d):
        cur, tabs = self._current()
        ids = [t["id"] for t in tabs]
        if len(ids) > 1:
            self.switch(ids[(ids.index(cur) + d) % len(ids)])

    def open_tab(self, url=START):
        tid = self._cmd("Target.createTarget", {"url": url})["targetId"]
        self.switch(tid)
        return tid

    def close_tab(self, tid=None):
        tid = tid or self._current()[0]
        if len(self.tabs()) <= 1:
            return self.close()
        self._cmd("Target.closeTarget", {"targetId": tid})
        self.sessions.pop(tid, None)
        if self.tab == tid:
            self.tab = None
            time.sleep(0.2)
            self.switch(self._current()[0])

    def close(self):
        self.stop()
        system.show_shell()

    # ---- page actions ----------------------------------------------------------------------------
    def navigate(self, text):
        url = to_url(text)
        self._page("Page.navigate", {"url": url})
        self.pointer = None
        return url

    def search(self):
        """Start: the start page's search box, keyboard up."""
        self._page("Page.navigate", {"url": START + "#search"})
        time.sleep(0.8)
        if self.on_keyboard:
            self.on_keyboard()

    def history(self, d):
        self.js(f"history.go({int(d)}); true")

    def reload(self):
        self._page("Page.reload", {})

    def key(self, name, text=None, modifiers=0):
        k, code, vk = KEYS[name]
        base = {"key": k, "code": code, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk, "modifiers": modifiers}
        down = {"type": "keyDown" if text else "rawKeyDown", **base, **({"text": text, "unmodifiedText": text} if text else {})}
        self._page("Input.dispatchKeyEvent", down)
        self._page("Input.dispatchKeyEvent", {"type": "keyUp", **base})

    def type_text(self, text="", special=None):
        """The on-screen keyboard typing into the page."""
        if special in ("backspace", "left", "right", "up", "down", "tab"):
            self.key(special)
        elif special == "enter":
            self.key("enter", "\r")
        if text:
            self._page("Input.insertText", {"text": text})
        return 1

    def scroll(self, dx, dy):
        w, h = self.js("[innerWidth, innerHeight]") or [1280, 720]
        x, y = self.pointer or (w / 2, h / 2)
        self._page("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "deltaX": dx, "deltaY": dy})

    # ---- pointer mode ----------------------------------------------------------------------------
    def set_pointer(self, on):
        if on:
            w, h = self.js("[innerWidth, innerHeight]") or [1280, 720]
            self.pointer = [w / 2, h / 2]
        else:
            self.pointer = None
        self._draw_pointer()

    def _draw_pointer(self):
        p = self.pointer
        self.js(PAGE_JS + ";(() => { const e = document.getElementById('__cb_pointer'); if (!e) return;"
                + (f"e.style.display = 'block'; e.style.left = '{p[0]:.0f}px'; e.style.top = '{p[1]:.0f}px';" if p
                   else "e.style.display = 'none';") + "})()")

    def move_pointer(self, action, repeat):
        self.speed = min(self.speed + 6, 60) if repeat else 14
        dx = {"left": -1, "right": 1}.get(action, 0) * self.speed
        dy = {"up": -1, "down": 1}.get(action, 0) * self.speed
        w, h = self.js("[innerWidth, innerHeight]") or [1280, 720]
        x, y = self.pointer
        if (dy < 0 and y < 40) or (dy > 0 and y > h - 40):          # at the edge: scroll the page
            self.scroll(0, dy * 6)
        self.pointer = [max(0, min(w - 1, x + dx)), max(0, min(h - 1, y + dy))]
        self._page("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": self.pointer[0], "y": self.pointer[1]})
        self._draw_pointer()

    def click(self):
        x, y = self.pointer
        for t in ("mousePressed", "mouseReleased"):
            self._page("Input.dispatchMouseEvent", {"type": t, "x": x, "y": y, "button": "left", "clickCount": 1})
        time.sleep(0.15)
        if self.js(TEXT_FIELD_JS) and self.on_keyboard:
            self.on_keyboard()

    # ---- the controller ---------------------------------------------------------------------------
    def act(self, action, repeat=False):
        """One controller action while the browser is in front (from gamepad.py)."""
        try:
            self._session()
            self.js(PAGE_JS)
            if self.pointer and action in ("up", "down", "left", "right"):
                return self.move_pointer(action, repeat)
            if action in ("up", "down", "left", "right"):
                if self.js(TEXT_FIELD_JS) and action in ("left", "right"):
                    return self.key(action)                 # move the cursor inside a text box
                return self.js(f"{NAV_JS}({json.dumps(action)})")
            if action == "ok":
                if self.pointer:
                    return self.click()
                if self.js(TEXT_FIELD_JS):
                    return self.on_keyboard and self.on_keyboard()
                at = self.js(TARGET_JS)
                if at:                                      # a real click on the highlighted thing
                    for t in ("mousePressed", "mouseReleased"):
                        self._page("Input.dispatchMouseEvent", {"type": t, "x": at[0], "y": at[1], "button": "left", "clickCount": 1})
                    return
                return self.key("enter", "\r")
            if action == "back":
                return self.history(-1)
            if action in ("prev", "next"):
                return self.step_tab(-1 if action == "prev" else 1)
            if action == "toggle":
                return self.search()
            if action == "pointer":
                return self.set_pointer(not self.pointer)
            if action.startswith("scroll_"):
                d = action[7:]
                return self.scroll({"left": -160, "right": 160}.get(d, 0), {"up": -160, "down": 160}.get(d, 0))
            if action in ("page_up", "page_down"):
                return self.key("pageup" if action == "page_up" else "pagedown")
        except BrowserError as e:
            print(f"browser: {action}: {e}", flush=True)

    # ---- settings + Quick Menu -------------------------------------------------------------------
    def info(self):
        if not self.running():
            return {"running": False}
        try:
            cur, tabs = self._current()
        except BrowserError:
            return {"running": True, "focused": self.focused(), "tabs": []}
        here = next((t for t in tabs if t["id"] == cur), tabs[0])
        return {"running": True, "focused": self.focused(), "tabs": tabs, "current": cur, "title": here["title"],
                "url": here["url"], "pointer": bool(self.pointer), "size": size(), "size_auto": prefs().get("size", "auto") == "auto"}

    def set_size(self, value):
        """'auto' or a factor. Chromium takes it at start, so an open browser restarts with its tabs."""
        if value != "auto":
            value = float(value)
            if not 1.0 <= value <= 4.0:
                raise ValueError("size")
        util.update_config(lambda c: c.setdefault("browser", {}).__setitem__("size", value))
        if self.running():
            try:
                urls = [t["url"] for t in self.tabs() if t["url"]]
            except BrowserError:
                urls = []
            self.stop()
            time.sleep(0.5)
            self.start(urls or None)
        return {"size": size(), "auto": value == "auto"}

    def bookmarks(self):
        b = prefs().get("bookmarks")
        return b if isinstance(b, list) else list(DEFAULT_BOOKMARKS)

    def add_bookmark(self, name=None, url=None):
        if not url:
            i = self.info()
            name, url = i.get("title"), i.get("url")
        if not url or url.startswith(START):
            raise ValueError("Nothing to bookmark here")
        marks = [b for b in self.bookmarks() if b["url"] != url] + [{"name": (name or url)[:60], "url": url}]
        util.update_config(lambda c: c.setdefault("browser", {}).__setitem__("bookmarks", marks))
        return marks

    def remove_bookmark(self, url):
        marks = [b for b in self.bookmarks() if b["url"] != url]
        util.update_config(lambda c: c.setdefault("browser", {}).__setitem__("bookmarks", marks))
        return marks


BROWSER = Browser()
