"""Quick Menu contents and actions, independent of any toolkit.

The native overlay window (overlay.py) renders the rows this builds and calls
row["ok"] / row["adjust"] on input. Kept separate so it can be tested headless.
"""


def fmt(t):
    t = max(0, int(t or 0))
    return f"{t // 60}:{t % 60:02d}"


def kind_of(app):
    if not app:
        return None
    if app.get("video"):
        return "Video"
    return "App" if "chrom" in (app.get("app") or "").lower() else "Game"


PAGE_TITLES = {"sound": "Sound", "perf": "Performance", "settings": "Settings", "browser": "Browser", "tabs": "Tabs", "trophies": "Trophies"}
# The Guide (looks whose look.json says "overlay": {"style": "guide"}, like the Dashboard): the
# same rows, grouped into tabs walked with LB / RB; Home is where it opens. Which rows each
# tab shows, by row key:
GUIDE_TABS = [("games", "Games & Apps", "applications-games-symbolic"), ("media", "Media", "audio-x-generic-symbolic"),
              ("main", "Home", "go-home-symbolic"), ("social", "Social", "system-users-symbolic"),
              ("guide-settings", "Settings", "emblem-system-symbolic")]
GUIDE_ROWS = {"main": ["resume", "close", "browser", "home", "media", "look", "power"],
              "games": ["resume", "close", "trophies", "all-trophies", "apps", "osk"],
              "media": ["media", "vol", "sound"],
              "social": ["voice", "share", "go-social"],
              "guide-settings": ["look", "perf", "settings", "power"]}
BROWSER_SIZES = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0]
FPS_MODES = ["off", "fps", "graph", "full"]
FPS_NAMES = {"off": "Off", "fps": "FPS", "graph": "FPS + frame time", "full": "FPS, frame time, CPU/GPU"}
CORNERS = ["top-right", "top-left", "bottom-left", "bottom-right"]
SIZES = ["auto", "small", "medium", "large", "huge"]
SIZE_NAMES = {"auto": "Automatic (fits the screen)", "small": "Small", "medium": "Medium", "large": "Large", "huge": "Huge"}


def cycle(seq, cur, d):
    i = seq.index(cur) if cur in seq else 0
    return seq[(i + (1 if d > 0 else -1)) % len(seq)]


class Model:
    """api: object with get(path) -> dict and post(path, body) -> dict."""

    def __init__(self, api):
        self.api = api
        self.data = {}
        self.armed = None          # "close" while waiting for the confirming second press
        self.page = "main"         # main | apps | app | power | sound | perf | settings
        self.app = None            # the app picked in the switcher
        self.sel = 0
        self.rows = []
        self.notice = ""

    # ---- data ---------------------------------------------------------------
    def refresh(self):
        try:
            self.data = self.api.get("/api/quick") or {}
        except Exception:
            pass
        self.rebuild()

    def rebuild(self):
        key = self.rows[self.sel]["key"] if self.rows and self.sel < len(self.rows) else None
        self.rows = self.build(self.data)
        keys = [r["key"] for r in self.rows]
        self.sel = keys.index(key) if key in keys else min(self.sel, len(self.rows) - 1)

    # ---- the Guide ----------------------------------------------------------------
    def style(self):
        return ((self.data.get("look") or {}).get("style")) or "panel"

    def guide(self):
        return self.style() == "guide"

    def is_tab(self, page=None):
        page = page or self.page
        return page == "main" or (self.guide() and page in GUIDE_ROWS)

    def tab(self):
        """The tab to light up: the page, or the tab a sub-page was opened from."""
        return self.page if self.is_tab() else (getattr(self, "parent", None) or "main")

    def switch_tab(self, d):
        tabs = [t[0] for t in GUIDE_TABS]
        i = tabs.index(self.tab()) if self.tab() in tabs else tabs.index("main")
        self.parent = None
        self.go(tabs[(i + (1 if d > 0 else -1)) % len(tabs)])

    def title(self):
        if self.page == "apps":
            return "Switch App"
        if self.page == "app" and self.app:
            return self.app["title"]
        if self.page == "power":
            return "Power"
        if self.page in PAGE_TITLES:
            return PAGE_TITLES[self.page]
        app = self.data.get("app")
        return app["title"] if app else "Crossbar"

    def back_to(self):
        if self.page != "main":
            return "previous"
        k = kind_of(self.data.get("app"))
        return k.lower() if k else "menu"

    def go(self, page, app=None):
        if not self.is_tab(page) and self.is_tab() and self.rows and self.sel < len(self.rows):
            self._from = self.rows[self.sel]["key"]       # so Back returns to that row
            self.parent = self.page                       # …on the tab it came from
        self.page, self.app, self.sel, self.armed = page, app, 0, None
        if page == "trophies":
            self.trophies = None
            __import__("threading").Thread(target=self._load_trophies, daemon=True).start()
        self.rebuild()

    def _load_trophies(self):
        try:
            self.trophies = self.api.get("/api/quick/trophies") or {}
        except Exception as e:
            self.trophies = {"note": f"Couldn't get the trophies: {e}"}
        if self.page == "trophies":
            self.rebuild()

    def build(self, d):
        if self.page == "apps":
            return self.build_apps(d)
        if self.page == "app":
            return self.build_app()
        if self.page == "power":
            return self.build_power()
        if self.page == "sound":
            return self.build_sound(d)
        if self.page == "perf":
            return self.build_perf(d)
        if self.page == "settings":
            return self.build_settings()
        if self.page == "browser":
            return self.build_browser(d)
        if self.page == "tabs":
            return self.build_tabs(d)
        if self.page == "trophies":
            return self.build_trophies()
        rows = self.build_main(d)
        if self.guide():
            keys = GUIDE_ROWS.get(self.page, GUIDE_ROWS["main"])
            by = {r["key"]: r for r in rows}
            rows = [by[k] for k in keys if k in by]
            if self.page == "social" and not any(r["key"] in ("voice", "share") for r in rows):
                rows.insert(0, {"key": "no-voice", "icon": "call-start-symbolic", "label": "Not in a voice chat",
                                "sub": "Join one from Social in the menu"})
        else:
            rows = [r for r in rows if r["key"] not in ("all-trophies", "go-social")]
        return rows

    def build_trophies(self):
        t = getattr(self, "trophies", None)
        if t is None:
            return [{"key": "loading", "icon": "content-loading-symbolic", "label": "Loading…", "sub": ""}]
        rows = []
        if t.get("total"):
            rows.append({"key": "sum", "icon": "starred-symbolic", "label": f"{t['earned']} of {t['total']} unlocked",
                         "sub": t.get("game") or "", "bar": t["earned"] / t["total"]})
            for i, a in enumerate(t.get("achievements") or []):
                rows.append({"key": f"a{i}", "icon": "starred-symbolic" if a.get("earned") else "non-starred-symbolic",
                             "label": a.get("title") or "?",
                             "sub": " · ".join(x for x in ((f"Unlocked {a['when']}" if a.get("when") else "Unlocked") if a.get("earned") else "Locked",
                                                           a.get("desc") or "") if x)})
        else:
            rows.append({"key": "none", "icon": "dialog-information-symbolic", "label": t.get("game") or "No game running",
                         "sub": t.get("note") or "No trophies to show"})
        rows.append({"key": "all-trophies", "icon": "starred-symbolic", "label": "All Trophies", "sub": "Every game, in the menu",
                     "ok": lambda: self.api.post("/api/overlay/open", {"cat": "game", "folder": "trophies"})})
        return rows

    # ---- the browser (Y in the browser opens this page directly) ---------------------------------
    def build_browser(self, d):
        api, b = self.api, d.get("browser") or {}
        if not b.get("running"):
            return [{"key": "open", "icon": "web-browser-symbolic", "label": "Open the Browser", "sub": "",
                     "ok": lambda: (api.post("/api/browser/open", {}), self.close(False))}]

        def do(what, body=None, close=True):
            api.post(f"/api/browser/{what}", body or {})
            if close:
                self.close(True)
            else:
                self.refresh()
        size = b.get("size") or 1.0
        si = min(range(len(BROWSER_SIZES)), key=lambda i: abs(BROWSER_SIZES[i] - size))
        url = (b.get("url") or "").replace("http://127.0.0.1:7777/browser.html", "Start page")
        n = len(b.get("tabs") or [])
        return [
            {"key": "search", "icon": "system-search-symbolic", "label": "Search or Type Address", "sub": url[:80],
             "ok": lambda: do("search")},
            {"key": "back", "icon": "go-previous-symbolic", "label": "Back", "sub": "", "ok": lambda: do("history", {"delta": -1})},
            {"key": "fwd", "icon": "go-next-symbolic", "label": "Forward", "sub": "", "ok": lambda: do("history", {"delta": 1})},
            {"key": "reload", "icon": "view-refresh-symbolic", "label": "Reload", "sub": "", "ok": lambda: do("reload")},
            {"key": "tabs", "icon": "view-paged-symbolic", "label": "Tabs", "sub": f"{n} open · L1 / R1 switch while browsing",
             "ok": lambda: self.go("tabs")},
            {"key": "mark", "icon": "starred-symbolic", "label": "Bookmark This Page", "sub": "Shows on the start page",
             "ok": lambda: (api.post("/api/browser/bookmark", {}), setattr(self, "notice", "Bookmarked"), self.refresh())},
            {"key": "pointer", "icon": "input-mouse-symbolic", "label": "Pointer: " + ("On" if b.get("pointer") else "Off"),
             "sub": "A cursor for sites that need one (also L3)", "ok": lambda: do("pointer", {"on": not b.get("pointer")})},
            {"key": "size", "icon": "zoom-in-symbolic", "label": f"Size: {int(size * 100)}%" + (" (automatic)" if b.get("size_auto") else ""),
             "sub": "◀ ▶ bigger / smaller · {ok} automatic — the browser reopens with your tabs", "hint": "◀ ▶ size",
             "ok": lambda: do("size", {"value": "auto"}),
             "adjust": lambda d_: do("size", {"value": BROWSER_SIZES[max(0, min(len(BROWSER_SIZES) - 1, si + (1 if d_ > 0 else -1)))]}, close=False)},
            {"key": "close-b", "icon": "window-close-symbolic", "label": "Close Browser", "sub": "", "danger": True,
             "ok": lambda: (api.post("/api/browser/close", {}), self.close(False))},
        ]

    def build_tabs(self, d):
        api, b = self.api, d.get("browser") or {}
        rows = []
        for t in b.get("tabs") or []:
            here = t["id"] == b.get("current")
            rows.append({"key": f"t:{t['id']}", "icon": "web-browser-symbolic", "label": (t["title"] or t["url"])[:70],
                         "sub": ("Showing · " if here else "") + t["url"][:80], "hint": "{ok} show · {menu} close",
                         "ok": lambda t=t: (api.post("/api/browser/tab", {"id": t["id"]}), self.close(True)),
                         "menu": lambda t=t: (api.post("/api/browser/close-tab", {"id": t["id"]}), self.refresh())})
        rows.append({"key": "new", "icon": "tab-new-symbolic", "label": "New Tab", "sub": "Opens the start page",
                     "ok": lambda: (api.post("/api/browser/new-tab", {}), self.close(True))})
        return rows

    def build_sound(self, d):
        api, rows = self.api, []
        if len(d.get("outputs") or []) > 1:
            rows.append({"key": "out", "icon": "audio-speakers-symbolic", "label": "Sound Output",
                         "sub": (d.get("output") or {}).get("name") or "Default", "hint": "{ok} switch",
                         "ok": self._next_output})
        mic = (d.get("audio") or {}).get("mic") or {}
        if mic.get("volume") is not None:
            rows.append({"key": "mic", "icon": "audio-input-microphone-symbolic", "label": "Microphone",
                         "sub": "Muted" if mic.get("muted") else f"{mic['volume']}%", "hint": "{ok} mute",
                         "ok": lambda: (api.post("/api/audio", {"target": "mic", "mute": True}), self.refresh())})
        rows += self.build_mixer(d)
        return rows

    def build_mixer(self, d):
        api, rows = self.api, []
        apps = d.get("apps_audio") or []

        def change(a, **kw):
            r = api.post("/api/audio/app", {"ids": a["ids"], **kw}) or {}
            if "apps" in r:                       # update right away, no full refresh needed
                self.data["apps_audio"] = r["apps"]
                self.rebuild()
        for a in apps:
            rows.append({"key": f"mix:{a['key']}", "icon": "audio-volume-high-symbolic" if not a["muted"] else "audio-volume-muted-symbolic",
                         "label": a["name"],
                         "sub": ("Muted" if a["muted"] else f"{a['volume']}%") + (f" · {a['sub']}" if a.get("sub") else ""),
                         "bar": 0 if a["muted"] else min(1, a["volume"] / 100), "hint": "◀ ▶ volume · {ok} mute",
                         "ok": lambda a=a: change(a, mute=not a["muted"]),
                         "adjust": lambda d_, a=a: change(a, delta=5 if d_ > 0 else -5)})
        if not rows:
            rows.append({"key": "mix:none", "icon": "audio-volume-muted-symbolic", "label": "Nothing is playing sound",
                         "sub": "Apps show up here while they play audio", "ok": lambda: self.go("main")})
        out = (d.get("audio") or {}).get("output") or {}
        if out.get("volume") is not None and self.page != "sound":
            def vol(delta):
                api.post("/api/audio", {"target": "output", "delta": delta})
                self.refresh()
            rows.append({"key": "mix:master", "icon": "audio-speakers-symbolic", "label": "Everything (master volume)",
                         "sub": "Muted" if out.get("muted") else f"{out['volume']}%",
                         "bar": 0 if out.get("muted") else min(1, out["volume"] / 100), "hint": "◀ ▶ adjust",
                         "ok": lambda: (api.post("/api/audio", {"target": "output", "mute": True}), self.refresh()),
                         "adjust": lambda d_: vol(5 if d_ > 0 else -5)})
        return rows

    def build_apps(self, d):
        rows = [{"key": "xmb", "icon": "go-home-symbolic", "label": "Crossbar", "sub": "The menu",
                 "ok": lambda: self.api.post("/api/overlay/switch", {"con_id": None})}]
        for w in d.get("windows") or []:
            rows.append({"key": f"w{w['con_id']}", "icon": "video-x-generic-symbolic" if w.get("video") else "applications-games-symbolic",
                         "label": w["title"], "sub": w["app"], "hint": "{ok} switch · {menu} close",
                         "ok": lambda w=w: self.api.post("/api/overlay/switch", {"con_id": w["con_id"]}),
                         "menu": lambda w=w: self.go("app", w)})
        return rows

    def build_app(self):
        w, api = self.app, self.api
        if not w:
            return []

        def close(kind):
            api.post(f"/api/window/{kind}", {"con_id": w["con_id"]})
            self.notice = f"{'Force closed' if kind == 'kill' else 'Closed'} {w['title']}"
            self.go("apps")
            self.refresh()
        return [
            {"key": "switch", "icon": "go-next-symbolic", "label": "Switch To", "sub": w["title"],
             "ok": lambda: api.post("/api/overlay/switch", {"con_id": w["con_id"]})},
            {"key": "close", "icon": "window-close-symbolic", "label": "Close", "sub": "Ask it to quit", "danger": True,
             "ok": lambda: close("close")},
            {"key": "kill", "icon": "process-stop-symbolic", "label": "Force Close", "danger": True,
             "sub": "End it now — unsaved progress is lost", "ok": lambda: close("kill")},
            {"key": "back", "icon": "go-previous-symbolic", "label": "Back", "sub": "", "ok": lambda: self.go("apps")},
        ]

    def build_power(self):
        api = self.api
        return [   # Cancel first and selected: a stray press never turns the machine off
            {"key": "cancel", "icon": "go-previous-symbolic", "label": "Cancel", "sub": "Back to the Quick Menu",
             "ok": lambda: self.go("main")},
            {"key": "restart-crossbar", "icon": "view-refresh-symbolic", "label": "Restart Crossbar", "sub": "Restart the menu, keep the computer on",
             "ok": lambda: api.post("/api/session/restart", {})},
            {"key": "reboot", "icon": "system-reboot-symbolic", "label": "Restart Computer", "sub": "", "danger": True,
             "ok": lambda: api.post("/api/power/reboot", {})},
            {"key": "off", "icon": "system-shutdown-symbolic", "label": "Turn Off Computer", "sub": "", "danger": True,
             "ok": lambda: api.post("/api/power/poweroff", {})},
        ]

    def build_main(self, d):
        api, rows = self.api, []
        app = d.get("app")
        what = kind_of(app)
        if app:
            rows.append({"key": "resume", "icon": "media-playback-start-symbolic", "label": f"Resume {what}",
                         "sub": app["title"], "ok": lambda: self.close(True)})
            armed = self.armed == "close"
            rows.append({"key": "close", "icon": "window-close-symbolic", "danger": True,
                         "label": "Press {ok} again to close" if armed else f"Close {what}",
                         "sub": (app["title"] + ("" if app.get("video") else " — unsaved progress may be lost")) if armed else app["title"],
                         "ok": self._close_app})
        if (d.get("browser") or {}).get("focused"):
            rows.append({"key": "browser", "icon": "web-browser-symbolic", "label": "Browser",
                         "sub": "Address, tabs, bookmarks, size", "ok": lambda: self.go("browser")})
        rows.append({"key": "home", "icon": "go-home-symbolic", "label": "Go to Home",
                     "sub": f"{app['title']} stays open" if app else "The Crossbar menu",
                     "ok": lambda: api.post("/api/overlay/home", {})})
        if app and not app.get("video"):
            rows.append({"key": "trophies", "icon": "starred-symbolic", "label": "Trophies",
                         "sub": f"{app['title']}: what you've unlocked", "ok": lambda: self.go("trophies")})
        rows.append({"key": "all-trophies", "icon": "starred-symbolic", "label": "All Trophies", "sub": "Every game, in the menu",
                     "ok": lambda: api.post("/api/overlay/open", {"cat": "game", "folder": "trophies"})})

        m, sp = d.get("music"), d.get("spotify")
        if m:
            def ctl(a):
                return lambda: (api.post("/api/music/control", {"action": a}), self.refresh())
            rows.append({"key": "media", "icon": "audio-x-generic-symbolic", "label": m.get("title") or "Music",
                         "sub": f"{(m.get('artist') + ' · ') if m.get('artist') else ''}{'Paused' if m.get('paused') else 'Playing'}"
                                f" · {fmt(m.get('position'))} / {fmt(m.get('duration'))}",
                         "bar": (m["position"] / m["duration"]) if m.get("duration") else None,
                         "hint": "◀ ▶ skip · {ok} play/pause", "ok": ctl("toggle"),
                         "adjust": lambda d_: ctl("next" if d_ > 0 else "prev")()})
        elif sp:
            def sctl(a):
                return lambda: (api.post("/api/spotify/control", {"action": a}), self.refresh())
            rows.append({"key": "media", "icon": "audio-x-generic-symbolic", "label": sp.get("name") or "Spotify",
                         "sub": f"Spotify · {sp.get('artist', '')}{'' if sp.get('here') else ' · on ' + str(sp.get('device'))}"
                                f" · {'Playing' if sp.get('playing') else 'Paused'}",
                         "bar": (sp["position"] / sp["duration"]) if sp.get("duration") else None,
                         "hint": "◀ ▶ skip · {ok} play/pause", "ok": sctl("toggle"),
                         "adjust": lambda d_: sctl("next" if d_ > 0 else "prev")()})

        voice = d.get("voice")
        if voice and voice.get("channel"):
            ch = voice["channel"]
            rows.append({"key": "voice", "icon": "call-start-symbolic", "label": f"Voice: {ch.get('name')}",
                         "sub": f"{ch.get('guild') or 'Discord'} · {'Deafened' if voice.get('deaf') else 'Muted' if voice.get('mute') else 'Mic on'}",
                         "hint": "{ok} mute · ◀ leave",
                         "ok": lambda: (api.post("/api/discord/mute", {}), self.refresh()),
                         "adjust": lambda d_: (api.post("/api/discord/leave", {}), self.refresh()) if d_ < 0 else None})
            sharing = bool(voice.get("sharing"))

            def share():
                self.notice = "Stopping…" if sharing else "Starting screen share…"
                self.rebuild()

                def run():                            # can take several seconds: don't freeze the menu
                    try:
                        r = api.post("/api/discord/share", {"on": not sharing}, timeout=40) or {}
                    except TypeError:                 # an api without timeouts (tests)
                        r = api.post("/api/discord/share", {"on": not sharing}) or {}
                    self.notice = r.get("error") or ("Sharing your screen" if r.get("sharing") else "Screen share stopped")
                __import__("threading").Thread(target=run, daemon=True).start()
            rows.append({"key": "share", "icon": "video-display-symbolic", "label": "Stop Sharing Screen" if sharing else "Share Screen",
                         "sub": "Your friends see what's on the TV" if not sharing else "Live on Discord", "ok": share})

        out = (d.get("audio") or {}).get("output") or {}
        if out.get("volume") is not None:
            def vol(delta):
                api.post("/api/audio", {"target": "output", "delta": delta})
                self.refresh()
            rows.append({"key": "vol", "icon": "audio-volume-high-symbolic", "label": "Volume",
                         "sub": "Muted" if out.get("muted") else f"{out['volume']}%",
                         "bar": 0 if out.get("muted") else min(1, out["volume"] / 100), "hint": "◀ ▶ adjust · {ok} mute",
                         "ok": lambda: (api.post("/api/audio", {"target": "output", "mute": True}), self.refresh()),
                         "adjust": lambda d_: vol(5 if d_ > 0 else -5)})
        rows.append({"key": "sound", "icon": "multimedia-volume-control-symbolic", "label": "Sound",
                     "sub": self._sound_sub(d), "ok": lambda: self.go("sound")})
        rows.append({"key": "perf", "icon": "utilities-system-monitor-symbolic", "label": "Performance",
                     "sub": self._perf_sub(d), "ok": lambda: self.go("perf")})
        wins = d.get("windows") or []
        rows.append({"key": "apps", "icon": "view-app-grid-symbolic", "label": "Switch App",
                     "sub": f"{len(wins)} open" if wins else "Nothing else open", "ok": lambda: self.go("apps")})
        rows.append({"key": "osk", "icon": "input-keyboard-symbolic", "label": "Keyboard",
                     "sub": "Type into the app with the controller", "ok": self._keyboard})
        looks = d.get("looks") or []
        if len(looks) > 1:
            cur = (d.get("look") or {}).get("id")
            ids = [x["id"] for x in looks]
            i = ids.index(cur) if cur in ids else 0

            def swap(dd):
                api.post("/api/settings", {"interface": ids[(i + (1 if dd > 0 else -1)) % len(ids)]})
                self.refresh()
            rows.append({"key": "look", "icon": "preferences-desktop-theme-symbolic", "label": "Interface",
                         "sub": looks[i]["name"], "hint": "◀ ▶ or {ok} switch", "ok": lambda: swap(1), "adjust": swap})
        rows.append({"key": "go-social", "icon": "system-users-symbolic", "label": "Social", "sub": "Friends, chat, voice — in the menu",
                     "ok": lambda: api.post("/api/overlay/open", {"cat": "party"})})
        rows.append({"key": "settings", "icon": "emblem-system-symbolic", "label": "Settings",
                     "sub": "Controller, all settings", "ok": lambda: self.go("settings")})
        rows.append({"key": "power", "icon": "system-shutdown-symbolic", "label": "Power",
                     "sub": "Restart Crossbar, restart or turn off", "ok": lambda: self.go("power")})
        return rows

    def _sound_sub(self, d):
        n = len(d.get("apps_audio") or [])
        out = (d.get("output") or {}).get("name")
        return " · ".join(x for x in (out, f"{n} app{'s' if n != 1 else ''} playing" if n else "") if x) or "Outputs, microphone, app volume"

    def _perf_sub(self, d):
        perf, ps5 = d.get("perf") or {}, d.get("ps5") or {}
        parts = [f"Frame rate: {FPS_NAMES.get(perf.get('fps', 'off'), 'Off')}"]
        t = (ps5.get("temps") or {}) if ps5.get("available") else {}
        if t.get("cpu") is not None:
            parts.append(f"CPU {t['cpu']}°")
        return " · ".join(parts)

    def build_perf(self, d):
        api, rows = self.api, []
        perf, ps5 = d.get("perf") or {}, d.get("ps5") or {}
        mode = perf.get("fps", "off")

        def set_fps(m):
            api.post("/api/perf/fps", {"mode": m})
            self.refresh()
        if perf.get("available"):
            i = FPS_MODES.index(mode) if mode in FPS_MODES else 0
            rows.append({"key": "fps", "icon": "utilities-system-monitor-symbolic", "label": "Frame Rate Overlay",
                         "sub": FPS_NAMES[mode] + ("" if mode == "off" else " — shows in games"),
                         "hint": "◀ ▶ choose · {ok} on/off",
                         "ok": lambda: set_fps("off" if mode != "off" else (perf.get("last") or "fps")),
                         "adjust": lambda d_: set_fps(FPS_MODES[(i + (1 if d_ > 0 else -1)) % len(FPS_MODES)])})
        else:
            rows.append({"key": "fps", "icon": "utilities-system-monitor-symbolic", "label": "Frame Rate Overlay",
                         "sub": "Needs MangoHud (Settings › System › Update Crossbar installs it)"})
        if ps5.get("available"):
            t = ps5.get("temps") or {}
            parts = [f"{k.upper() if k != 'nvme' else 'NVMe'} {v}°" for k, v in (("cpu", t.get("cpu")), ("gpu", t.get("gpu")), ("nvme", t.get("nvme"))) if v is not None]
            hot = max([v for v in t.values() if v is not None] or [0])
            rows.append({"key": "temps", "icon": "temperature-symbolic" if hot < 80 else "dialog-warning-symbolic",
                         "label": "Temperature Overlay", "sub": (" · ".join(parts) or "No sensors") + (" · on screen" if ps5.get("hud") else ""),
                         "hint": "{ok} " + ("hide" if ps5.get("hud") else "show"),
                         "ok": lambda: (api.post("/api/ps5/hud", {"on": not ps5.get("hud")}), self.refresh())})
            hc, hs = ps5.get("hud_corner") or "top-left", ps5.get("hud_size") or "auto"
            rows.append({"key": "hud-corner", "icon": "view-restore-symbolic", "label": "Temperature Position",
                         "sub": hc.replace("-", " ").capitalize() + (" — same corner as the frame rate" if hc == perf.get("corner") and perf.get("fps", "off") != "off" else ""),
                         "hint": "◀ ▶ move",
                         "adjust": lambda d_: (api.post("/api/ps5/hud", {"corner": cycle(CORNERS, hc, d_)}), self.refresh())})
            rows.append({"key": "hud-size", "icon": "zoom-in-symbolic", "label": "Temperature Size", "sub": SIZE_NAMES.get(hs, hs),
                         "hint": "◀ ▶ size",
                         "adjust": lambda d_: (api.post("/api/ps5/hud", {"size": cycle(SIZES, hs, d_)}), self.refresh())})
            if ps5.get("fan_target") is not None:
                lo, hi = ps5.get("target_range") or (40, 95)
                ft = ps5["fan_target"]
                rows.append({"key": "fan", "icon": "weather-windy-symbolic", "label": "Fan Target",
                             "sub": f"{ft} °C — lower keeps it cooler (louder)" if ps5.get("fan_mode", "auto") == "auto"
                                    else f"Fixed pattern: {ps5['fan_mode']}",
                             "bar": (ft - lo) / (hi - lo), "hint": "◀ ▶ adjust",
                             "adjust": lambda d_: (api.post("/api/ps5/fan-target", {"delta": 5 if d_ > 0 else -5}), self.refresh())})
        if perf.get("available"):
            corner, size = perf.get("corner", "top-right"), perf.get("size", "auto")
            # straight after the frame-rate row, so its own settings sit together
            at = next((i for i, r in enumerate(rows) if r["key"] == "fps"), 0) + 1
            rows[at:at] = [
                {"key": "corner", "icon": "view-restore-symbolic", "label": "Frame Rate Position",
                 "sub": corner.replace("-", " ").capitalize(), "hint": "◀ ▶ move",
                 "adjust": lambda d_: (api.post("/api/perf/corner", {"corner": cycle(CORNERS, corner, d_)}), self.refresh())},
                {"key": "size", "icon": "zoom-in-symbolic", "label": "Frame Rate Size",
                 "sub": SIZE_NAMES.get(size, size) + (f" · {perf['font_size']} px" if perf.get("font_size") else ""), "hint": "◀ ▶ size",
                 "adjust": lambda d_: (api.post("/api/perf/size", {"size": cycle(SIZES, size, d_)}), self.refresh())}]
        return rows

    def build_settings(self):
        api = self.api
        return [
            {"key": "pad", "icon": "input-gaming-symbolic", "label": "Controller & Keyboard", "sub": "Button mapping, glyphs",
             "ok": lambda: api.post("/api/overlay/settings", {"folder": "controls"})},
            {"key": "display", "icon": "video-display-symbolic", "label": "Display & Sound", "sub": "Resolution, outputs",
             "ok": lambda: api.post("/api/overlay/settings", {"folder": "display"})},
            {"key": "net", "icon": "network-wireless-symbolic", "label": "Network & Bluetooth", "sub": "Wi-Fi, pairing",
             "ok": lambda: api.post("/api/overlay/settings", {"folder": "network"})},
            {"key": "all", "icon": "emblem-system-symbolic", "label": "All Settings", "sub": "Opens Settings in the menu",
             "ok": lambda: api.post("/api/overlay/settings", {"folder": ""})},
        ]

    # ---- actions --------------------------------------------------------------
    def _close_app(self):
        if self.armed != "close":
            self.armed = "close"
            self.rebuild()
            return
        self.armed = None
        title = (self.data.get("app") or {}).get("title", "")
        self.api.post("/api/overlay/close-app", {})
        self.notice = f"Closed {title}"

    def _keyboard(self):
        self.close(True)
        self.api.post("/api/osk/show", {"on": True})

    def _next_output(self):
        r = self.api.post("/api/quick/output", {}) or {}
        if r.get("name"):
            self.notice = f"Sound output: {r['name']}"
        self.refresh()

    def close(self, resume=True):
        self.api.post("/api/overlay/close", {"resume": resume})

    def reset(self):
        self.sel, self.armed, self.notice, self.page, self.app = 0, None, "", "main", None
        self.parent = None
        self.direct = None

    def open_on(self, page):
        """Opened straight on a page (the browser's Y): Back then closes instead of going to main."""
        self.go(page)
        self.direct = page

    # ---- input ----------------------------------------------------------------
    def handle(self, a):
        if not self.rows:
            return
        r = self.rows[self.sel]
        if a in ("up", "down"):
            n = max(0, min(len(self.rows) - 1, self.sel + (-1 if a == "up" else 1)))
            if n != self.sel:
                self.sel = n
                if self.armed:
                    self.armed = None
                    self.rebuild()
        elif a in ("left", "right") and r.get("adjust"):
            r["adjust"](1 if a == "right" else -1)
        elif a == "ok" and r.get("ok"):
            r["ok"]()
        elif a == "menu" and r.get("menu"):
            r["menu"]()
        elif a in ("back", "menu", "home"):
            if self.armed and a == "back":
                self.armed = None
                self.rebuild()
            elif a == "back" and self.page == getattr(self, "direct", None):
                self.close(True)
            elif not self.is_tab() and a == "back":
                back = "apps" if self.page == "app" else "browser" if self.page == "tabs" else (getattr(self, "parent", None) or "main")
                self.go(back)
                if self.is_tab(back):         # land on the row we came from
                    keys = [r["key"] for r in self.rows]
                    self.sel = next((i for i, k in enumerate(keys) if k == self._from), self.sel) if getattr(self, "_from", None) else self.sel
            else:
                self.close(True)
        elif a in ("prev", "next") and self.guide():
            self.switch_tab(1 if a == "next" else -1)
        elif a in ("toggle", "prev", "next"):
            media = next((x for x in self.rows if x["key"] == "media"), None)
            if media:
                media["ok"]() if a == "toggle" else media["adjust"](1 if a == "next" else -1)
