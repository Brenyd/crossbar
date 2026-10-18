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


class Model:
    """api: object with get(path) -> dict and post(path, body) -> dict."""

    def __init__(self, api):
        self.api = api
        self.data = {}
        self.armed = None          # "close" while waiting for the confirming second press
        self.page = "main"         # main | apps | app | power | mixer
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

    def title(self):
        if self.page == "apps":
            return "Switch App"
        if self.page == "app" and self.app:
            return self.app["title"]
        if self.page == "power":
            return "Power"
        if self.page == "mixer":
            return "App Volume"
        app = self.data.get("app")
        return app["title"] if app else "Crossbar"

    def back_to(self):
        if self.page != "main":
            return "previous"
        k = kind_of(self.data.get("app"))
        return k.lower() if k else "menu"

    def go(self, page, app=None):
        if page != "main" and self.page == "main" and self.rows and self.sel < len(self.rows):
            self._from = self.rows[self.sel]["key"]       # so Back returns to that row
        self.page, self.app, self.sel, self.armed = page, app, 0, None
        self.rebuild()

    def build(self, d):
        if self.page == "apps":
            return self.build_apps(d)
        if self.page == "app":
            return self.build_app()
        if self.page == "power":
            return self.build_power()
        if self.page == "mixer":
            return self.build_mixer(d)
        return self.build_main(d)

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
        if out.get("volume") is not None:
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
        rows.append({"key": "home", "icon": "go-home-symbolic", "label": "Go to Home",
                     "sub": f"{app['title']} stays open" if app else "The Crossbar menu",
                     "ok": lambda: api.post("/api/overlay/home", {})})

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
                         "sub": f"{len(ch.get('members', []))} in channel · {'Muted' if voice.get('mute') else 'Mic on'}",
                         "hint": "{ok} mute · ◀ leave",
                         "ok": lambda: (api.post("/api/discord/mute", {}), self.refresh()),
                         "adjust": lambda d_: (api.post("/api/discord/leave", {}), self.refresh()) if d_ < 0 else None})

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
        n = len(d.get("apps_audio") or [])
        rows.append({"key": "mixer", "icon": "multimedia-volume-control-symbolic", "label": "App Volume",
                     "sub": f"{n} app{'s' if n != 1 else ''} playing sound" if n else "Nothing playing right now",
                     "ok": lambda: self.go("mixer")})
        if len(d.get("outputs") or []) > 1:
            rows.append({"key": "out", "icon": "audio-speakers-symbolic", "label": "Sound Output",
                         "sub": (d.get("output") or {}).get("name") or "Default", "hint": "{ok} switch",
                         "ok": self._next_output})
        mic = (d.get("audio") or {}).get("mic") or {}
        if mic.get("volume") is not None:
            rows.append({"key": "mic", "icon": "audio-input-microphone-symbolic", "label": "Microphone",
                         "sub": "Muted" if mic.get("muted") else f"{mic['volume']}%", "hint": "{ok} mute",
                         "ok": lambda: (api.post("/api/audio", {"target": "mic", "mute": True}), self.refresh())})
        wins = d.get("windows") or []
        rows.append({"key": "apps", "icon": "view-app-grid-symbolic", "label": "Switch App",
                     "sub": f"{len(wins)} open" if wins else "Nothing else open", "ok": lambda: self.go("apps")})
        rows.append({"key": "pad", "icon": "input-gaming-symbolic", "label": "Controller & Keyboard", "sub": "Button mapping",
                     "ok": lambda: api.post("/api/overlay/settings", {"folder": "controls"})})
        rows.append({"key": "settings", "icon": "emblem-system-symbolic", "label": "Settings", "sub": "Display, sound, network…",
                     "ok": lambda: api.post("/api/overlay/settings", {"folder": ""})})
        rows.append({"key": "power", "icon": "system-shutdown-symbolic", "label": "Power…",
                     "sub": "Restart Crossbar, restart or turn off", "ok": lambda: self.go("power")})
        return rows

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

    def _next_output(self):
        r = self.api.post("/api/quick/output", {}) or {}
        if r.get("name"):
            self.notice = f"Sound output: {r['name']}"
        self.refresh()

    def close(self, resume=True):
        self.api.post("/api/overlay/close", {"resume": resume})

    def reset(self):
        self.sel, self.armed, self.notice, self.page, self.app = 0, None, "", "main", None

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
            elif self.page != "main" and a == "back":
                back = "apps" if self.page == "app" else "main"
                self.go(back)
                if back == "main":            # land on the row we came from
                    keys = [r["key"] for r in self.rows]
                    self.sel = next((i for i, k in enumerate(keys) if k == self._from), self.sel) if getattr(self, "_from", None) else self.sel
            else:
                self.close(True)
        elif a in ("toggle", "prev", "next"):
            media = next((x for x in self.rows if x["key"] == "media"), None)
            if media:
                media["ok"]() if a == "toggle" else media["adjust"](1 if a == "next" else -1)
