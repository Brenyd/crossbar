"""Demo provider: fake libraries so the whole flow works in a VM with no accounts."""
import random
import threading
import time

from .base import Provider, game

STEAM_ART = "https://cdn.cloudflare.steamstatic.com/steam/apps/{}/header.jpg"
CATALOG = {
    "steam": [("620", "Portal 2"), ("413150", "Stardew Valley"), ("105600", "Terraria"),
              ("367520", "Hollow Knight"), ("1145360", "Hades"), ("504230", "Celeste"),
              ("588650", "Dead Cells"), ("646570", "Slay the Spire")],
    "gog": [("1207658924", "The Witcher: Enhanced Edition"), ("1207664663", "Baldur's Gate II"),
            ("1440164514", "Factorio"), ("1207659026", "FTL: Advanced Edition")],
    "epic": [("Fortnite", "Fortnite"), ("Sugar", "Rocket League"), ("Kinglet", "Control"),
             ("Moose", "Subnautica")],
}
NAMES = {"steam": "Steam", "gog": "GOG", "epic": "Epic Games"}
_state = {"installed": {("steam", "620"), ("steam", "413150"), ("gog", "1440164514"), ("epic", "Sugar")},
          "linked": {"steam", "gog", "epic"}}
_lock = threading.Lock()


class Demo(Provider):
    def __init__(self, pid):
        self.id, self.name = pid, NAMES[pid]
        self.login_fields = [{"key": "anything", "label": "Demo mode — type anything"}] if pid == "steam" else []

    def status(self):
        linked = self.id in _state["linked"]
        return {"linked": linked, "account": "demo-player" if linked else "", "ready": True, "note": "Demo library"}

    def library(self):
        out = []
        for gid, title in CATALOG[self.id]:
            art = STEAM_ART.format(gid) if self.id == "steam" else None
            out.append(game(self.id, gid, title, art, (self.id, gid) in _state["installed"]))
        return sorted(out, key=lambda g: g["title"].lower())

    def login(self, job, fields):
        time.sleep(1)
        _state["linked"].add(self.id)

    def logout(self):
        _state["linked"].discard(self.id)

    def install(self, job, gid):
        size = random.randint(800, 6000)
        for i in range(41):
            job.set(i / 40, f"{size * i // 40} / {size} MB")
            time.sleep(0.25)
        with _lock:
            _state["installed"].add((self.id, gid))

    def uninstall(self, job, gid):
        with _lock:
            _state["installed"].discard((self.id, gid))

    def launch(self, gid):
        pass  # nothing to run in demo mode; the UI shows a notification
