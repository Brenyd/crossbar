"""Your own folders in the XMB: in any category, holding any of that category's items
(games, apps, ROM systems, services…), referred to by their keys. Kept in the config:
  "xmb_folders": [{"id": "f3", "name": "Racing", "cat": "game", "items": ["steam:620", "app:flatpak:…"]}]
"""
import itertools
import time

from . import util

CATS = ("photo", "music", "video", "tv", "game", "apps", "store", "party", "users")


def _all():
    f = util.load_config().get("xmb_folders")
    return f if isinstance(f, list) else []


def list_folders():
    return _all()


def create(cat, name):
    if cat not in CATS:
        raise ValueError("Folders can't go in that category")
    name = (name or "").strip()[:40]
    if not name:
        raise ValueError("Give the folder a name")
    fid = f"f{int(time.time() * 1000) % 10**10}{next(_n)}"
    folder = {"id": fid, "name": name, "cat": cat, "items": []}
    util.update_config(lambda c: c.setdefault("xmb_folders", []).append(folder))
    return folder


_n = itertools.count()


def _edit(fid, fn):
    def upd(c):
        for f in c.setdefault("xmb_folders", []):
            if f.get("id") == fid:
                fn(c, f)
                return
        raise KeyError("No such folder")
    util.update_config(upd)
    return _all()


def rename(fid, name):
    name = (name or "").strip()[:40]
    if not name:
        raise ValueError("Give the folder a name")
    return _edit(fid, lambda c, f: f.__setitem__("name", name))


def delete(fid):
    """The folder goes; what was in it goes back to the category."""
    util.update_config(lambda c: c.__setitem__("xmb_folders", [f for f in c.get("xmb_folders", []) if f.get("id") != fid]))
    return _all()


def move(key, cat, fid=None):
    """Put an item in a folder (fid) or back at the top of its category (fid None)."""
    if not key:
        raise ValueError("item")

    def upd(c):
        folders = c.setdefault("xmb_folders", [])
        for f in folders:
            if f.get("cat") == cat and key in f.get("items", []):
                f["items"].remove(key)
        if fid:
            target = next((f for f in folders if f.get("id") == fid and f.get("cat") == cat), None)
            if not target:
                raise KeyError("No such folder")
            target.setdefault("items", []).append(key)
    util.update_config(upd)
    return _all()


# ---- tags: the little [STEAM] / [GOG] / [SNES] labels, editable per item ------------------------------
def tags():
    t = util.load_config().get("xmb_tags")
    return t if isinstance(t, dict) else {}


def set_tag(key, text):
    """text: what to show ("" hides the tag); None goes back to the automatic one."""
    if not key or len(key) > 300:
        raise ValueError("item")

    def upd(c):
        t = c.setdefault("xmb_tags", {})
        if text is None:
            t.pop(key, None)
        else:
            t[key] = str(text).strip()[:20]
    util.update_config(upd)
    return tags()


# ---- hidden: games and apps you don't want on the XMB (brought back from Settings) -----------------------
def hidden():
    h = util.load_config().get("xmb_hidden")
    return h if isinstance(h, dict) else {}


def set_hidden(key, label="", on=True):
    """Hide (or show again) one game / app / ROM by its key; the name is kept for the Settings list."""
    if not key or len(key) > 300:
        raise ValueError("item")

    def upd(c):
        h = c.get("xmb_hidden")
        if not isinstance(h, dict):
            h = c["xmb_hidden"] = {}
        if on:
            h[key] = str(label or key).strip()[:120]
        else:
            h.pop(key, None)
    util.update_config(upd)
    return hidden()
