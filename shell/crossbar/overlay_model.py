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
        self.armed = None          # "close" | "power" while waiting for the confirming second press
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
        app = self.data.get("app")
        return app["title"] if app else "Crossbar"

    def back_to(self):
        k = kind_of(self.data.get("app"))
        return k.lower() if k else "menu"

    def build(self, d):
        api, rows = self.api, []
        app = d.get("app")
        what = kind_of(app)
        if app:
            rows.append({"key": "resume", "icon": "media-playback-start-symbolic", "label": f"Resume {what}",
                         "sub": app["title"], "ok": lambda: self.close(True)})
            armed = self.armed == "close"
            rows.append({"key": "close", "icon": "window-close-symbolic", "danger": True,
                         "label": "Press A again to close" if armed else f"Close {what}",
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
                         "hint": "◀ ▶ skip · A play/pause", "ok": ctl("toggle"),
                         "adjust": lambda d_: ctl("next" if d_ > 0 else "prev")()})
        elif sp:
            def sctl(a):
                return lambda: (api.post("/api/spotify/control", {"action": a}), self.refresh())
            rows.append({"key": "media", "icon": "audio-x-generic-symbolic", "label": sp.get("name") or "Spotify",
                         "sub": f"Spotify · {sp.get('artist', '')}{'' if sp.get('here') else ' · on ' + str(sp.get('device'))}"
                                f" · {'Playing' if sp.get('playing') else 'Paused'}",
                         "bar": (sp["position"] / sp["duration"]) if sp.get("duration") else None,
                         "hint": "◀ ▶ skip · A play/pause", "ok": sctl("toggle"),
                         "adjust": lambda d_: sctl("next" if d_ > 0 else "prev")()})

        voice = d.get("voice")
        if voice and voice.get("channel"):
            ch = voice["channel"]
            rows.append({"key": "voice", "icon": "call-start-symbolic", "label": f"Voice: {ch.get('name')}",
                         "sub": f"{len(ch.get('members', []))} in channel · {'Muted' if voice.get('mute') else 'Mic on'}",
                         "hint": "A mute · ◀ leave",
                         "ok": lambda: (api.post("/api/discord/mute", {}), self.refresh()),
                         "adjust": lambda d_: (api.post("/api/discord/leave", {}), self.refresh()) if d_ < 0 else None})

        out = (d.get("audio") or {}).get("output") or {}
        if out.get("volume") is not None:
            def vol(delta):
                api.post("/api/audio", {"target": "output", "delta": delta})
                self.refresh()
            rows.append({"key": "vol", "icon": "audio-volume-high-symbolic", "label": "Volume",
                         "sub": "Muted" if out.get("muted") else f"{out['volume']}%",
                         "bar": 0 if out.get("muted") else min(1, out["volume"] / 100), "hint": "◀ ▶ adjust · A mute",
                         "ok": lambda: (api.post("/api/audio", {"target": "output", "mute": True}), self.refresh()),
                         "adjust": lambda d_: vol(5 if d_ > 0 else -5)})
        if len(d.get("outputs") or []) > 1:
            rows.append({"key": "out", "icon": "audio-speakers-symbolic", "label": "Sound Output",
                         "sub": (d.get("output") or {}).get("name") or "Default", "hint": "A switch",
                         "ok": self._next_output})
        mic = (d.get("audio") or {}).get("mic") or {}
        if mic.get("volume") is not None:
            rows.append({"key": "mic", "icon": "audio-input-microphone-symbolic", "label": "Microphone",
                         "sub": "Muted" if mic.get("muted") else f"{mic['volume']}%", "hint": "A mute",
                         "ok": lambda: (api.post("/api/audio", {"target": "mic", "mute": True}), self.refresh())})
        rows.append({"key": "pad", "icon": "input-gaming-symbolic", "label": "Controller & Keyboard", "sub": "Button mapping",
                     "ok": lambda: api.post("/api/overlay/settings", {"folder": "controls"})})
        rows.append({"key": "settings", "icon": "emblem-system-symbolic", "label": "Settings", "sub": "Display, sound, network…",
                     "ok": lambda: api.post("/api/overlay/settings", {"folder": ""})})
        armed = self.armed == "power"
        rows.append({"key": "power", "icon": "system-shutdown-symbolic", "danger": True,
                     "label": "Press A again to turn off" if armed else "Turn Off System", "sub": "",
                     "ok": self._power})
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

    def _power(self):
        if self.armed != "power":
            self.armed = "power"
            self.rebuild()
            return
        self.api.post("/api/power/poweroff", {})

    def _next_output(self):
        r = self.api.post("/api/quick/output", {}) or {}
        if r.get("name"):
            self.notice = f"Sound output: {r['name']}"
        self.refresh()

    def close(self, resume=True):
        self.api.post("/api/overlay/close", {"resume": resume})

    def reset(self):
        self.sel, self.armed, self.notice = 0, None, ""

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
        elif a in ("back", "menu", "home"):
            if self.armed and a == "back":
                self.armed = None
                self.rebuild()
            else:
                self.close(True)
        elif a in ("toggle", "prev", "next"):
            media = next((x for x in self.rows if x["key"] == "media"), None)
            if media:
                media["ok"]() if a == "toggle" else media["adjust"](1 if a == "next" else -1)
