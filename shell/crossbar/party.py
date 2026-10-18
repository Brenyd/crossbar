"""Party chat: pick a VoIP service, start it, keep quick-join links for channels."""
import os

from . import util

CHROMIUM = ["chromium", "--ozone-platform-hint=auto",
            "--user-data-dir=" + os.path.join(util.CONFIG_DIR, "party-web")]

SERVICES = {
    "discord": {"name": "Discord", "cmd": ["discord"], "fallback_web": "https://discord.com/app",
                "scheme": "discord"},
    "discord-web": {"name": "Discord (Web)", "web": "https://discord.com/app"},
    "mumble": {"name": "Mumble", "cmd": ["mumble"], "scheme": "mumble"},
    "teamspeak": {"name": "TeamSpeak", "cmd": ["teamspeak3"], "scheme": "ts3server"},
    "element": {"name": "Element (Matrix)", "cmd": ["element-desktop"], "fallback_web": "https://app.element.io"},
}


def available(sid):
    s = SERVICES[sid]
    if "web" in s or "fallback_web" in s:
        return util.which("chromium") is not None or ("cmd" in s and util.which(s["cmd"][0]) is not None)
    return util.which(s["cmd"][0]) is not None


def services():
    return [{"id": k, "name": v["name"], "available": available(k),
             "native": "cmd" in v and util.which(v["cmd"][0]) is not None} for k, v in SERVICES.items()]


def start(sid, url=None):
    s = SERVICES[sid]
    if "cmd" in s and util.which(s["cmd"][0]):
        util.spawn(s["cmd"])
        if url:
            util.spawn(["xdg-open", url])
        return s["name"]
    web = url if url and url.startswith("http") else (s.get("web") or s.get("fallback_web"))
    if not web:
        raise RuntimeError(f"{s['name']} isn't installed")
    util.spawn(CHROMIUM + ["--app=" + web])
    return s["name"]


def normalise_channel(url):
    """Accept discord.com/channels/G/C links and turn them into app links when native."""
    url = url.strip()
    if "discord.com/channels/" in url and util.which("discord"):
        return "discord://-/channels/" + url.split("discord.com/channels/", 1)[1]
    return url
