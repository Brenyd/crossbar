"""Looks (console skins): the whole front end, swappable — Settings › Theme › Interface.

A look is a folder with three files (see docs/LOOKS.md):

    look.json   what it's called, its settings (each a list of choices) and how the Quick
                Menu overlay is styled while it's on
    look.js     registers the look's drawing code with the menu (Shell.register(id, {...}))
    look.css    its styles, scoped to body[data-shell="<id>"]

Built-in looks live in web/looks/<id>/; your own go in ~/.local/share/crossbar/looks/<id>/
and appear with no other change. This module lists them, keeps each look's settings
(config "look_settings": {id: {key: value}}), checks values against look.json, and tells the
native overlay (overlay.py) how to dress the Quick Menu.
"""
import json
import mimetypes
import os
import re

from . import util

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
BUILTIN = os.path.join(WEB, "looks")
USER = os.path.join(util.HOME, ".local", "share", "crossbar", "looks")
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_VALUE = re.compile(r"^[A-Za-z0-9 _.#()-]{1,40}$")
SERVE = {".js", ".css", ".json", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".woff", ".woff2", ".ttf", ".otf", ".ogg", ".wav", ".mp3"}
OVERLAY_STYLES = ("panel", "guide")


def _dirs():
    user = os.path.join(util.HOME, ".local", "share", "crossbar", "looks")
    return [(BUILTIN, True), (user, False)]


def _read(folder, builtin):
    try:
        with open(os.path.join(folder, "look.json")) as f:
            m = json.load(f)
    except (OSError, ValueError):
        return None
    lid = m.get("id") or os.path.basename(folder)
    if not _ID.match(str(lid)) or lid != os.path.basename(folder):
        return None
    settings = []
    for s in m.get("settings") or []:
        if not isinstance(s, dict) or not _ID.match(str(s.get("key", ""))) or not s.get("choices"):
            continue
        choices = [[str(c[0]), str(c[1]), *(c[2:3] if len(c) > 2 and isinstance(c[2], dict) else [])]
                   for c in s["choices"] if isinstance(c, (list, tuple)) and len(c) >= 2]
        if not choices:
            continue
        default = str(s.get("default", choices[0][0]))
        settings.append({"key": s["key"], "label": str(s.get("label") or s["key"])[:40], "icon": str(s.get("icon") or "settings")[:24],
                         "default": default if any(c[0] == default for c in choices) else choices[0][0], "choices": choices})
    base = f"/looks/{lid}/" if builtin else f"/look/{lid}/"
    ov = m.get("overlay") if isinstance(m.get("overlay"), dict) else {}
    return {
        "id": lid, "name": str(m.get("name") or lid)[:60], "short": str(m.get("short") or m.get("name") or lid)[:24],
        "description": str(m.get("description") or "")[:160], "author": str(m.get("author") or "")[:60],
        "builtin": builtin, "order": int(m.get("order", 50)) if str(m.get("order", "")).lstrip("-").isdigit() else 50,
        "settings": settings, "colors": m.get("colors") if isinstance(m.get("colors"), dict) else {},
        "overlay": {**ov, "style": ov.get("style") if ov.get("style") in OVERLAY_STYLES else "panel"},
        "script": base + "look.js" if os.path.isfile(os.path.join(folder, "look.js")) else None,
        "css": base + "look.css" if os.path.isfile(os.path.join(folder, "look.css")) else None,
        "_dir": folder,
    }


_CACHE = {"sig": None, "looks": []}


def _signature():
    """Changes when a look folder or its look.json changes (cheap: a few stat calls)."""
    sig = []
    for base, _ in _dirs():
        try:
            sig.append((base, os.stat(base).st_mtime_ns))
            for n in os.listdir(base):
                try:
                    sig.append((n, os.stat(os.path.join(base, n, "look.json")).st_mtime_ns))
                except OSError:
                    pass
        except OSError:
            sig.append((base, None))
    return tuple(sig)


def all_looks():
    """Every look installed (cached until a look.json changes)."""
    sig = _signature()
    if sig != _CACHE["sig"]:
        _CACHE["looks"], _CACHE["sig"] = _scan(), sig
    return [dict(m) for m in _CACHE["looks"]]


def _scan():
    """Every look installed, built-in first; a user look can't take a built-in's id."""
    out, seen = [], set()
    for base, builtin in _dirs():
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for n in names:
            m = _read(os.path.join(base, n), builtin)
            if m and m["id"] not in seen:
                seen.add(m["id"])
                out.append(m)
    out.sort(key=lambda m: (m["order"], m["name"].lower()))
    return out


def public():
    return [{k: v for k, v in m.items() if not k.startswith("_")} for m in all_looks()]


def get(lid):
    return next((m for m in all_looks() if m["id"] == lid), None)


def settings(cfg=None):
    """{look id: {key: value}}, every setting filled in (stored value, else the default)."""
    cfg = cfg or util.load_config()
    stored = cfg.get("look_settings") or {}
    # older configs: the first Xbox 360 look kept its two settings at the top level
    legacy = {"x360": {"bg": cfg.get("x360_bg"), "accent": cfg.get("x360_accent")}}
    out = {}
    for m in all_looks():
        mine = {**{k: v for k, v in legacy.get(m["id"], {}).items() if v}, **(stored.get(m["id"]) or {})}
        vals = {}
        for s in m["settings"]:
            v = mine.get(s["key"])
            vals[s["key"]] = v if any(c[0] == v for c in s["choices"]) else s["default"]
        out[m["id"]] = vals
    return out


def validate(patch):
    """{look: {key: value}} from Settings: only known looks, keys and choices."""
    if not isinstance(patch, dict):
        raise ValueError("look_settings must be {look: {setting: value}}")
    clean = {}
    for lid, vals in patch.items():
        m = get(lid)
        if not m or not isinstance(vals, dict):
            raise ValueError(f"No look called {lid}")
        for k, v in vals.items():
            s = next((x for x in m["settings"] if x["key"] == k), None)
            if not s or not any(c[0] == str(v) for c in s["choices"]):
                raise ValueError(f"{m['name']}: {k} can't be {v}")
            clean.setdefault(lid, {})[k] = str(v)
    return clean


def merge(cfg, clean):
    ls = cfg.setdefault("look_settings", {})
    for lid, vals in clean.items():
        ls.setdefault(lid, {}).update(vals)


def overlay(cfg=None):
    """How the native Quick Menu should look right now (overlay.py): style + colours."""
    cfg = cfg or util.load_config()
    m = get(cfg.get("interface", "xmb")) or get("xmb") or {"id": "xmb", "overlay": {"style": "panel"}, "colors": {}}
    ov = dict(m.get("overlay") or {})
    vals = settings(cfg).get(m["id"], {})
    acc_key = ov.get("accent_setting")
    if acc_key and vals.get(acc_key) and isinstance(m.get("colors", {}).get(acc_key), dict):
        pair = m["colors"][acc_key].get(vals[acc_key])
        if isinstance(pair, list) and pair:
            ov["accent"], ov["accent2"] = pair[0], pair[-1]
    return {"id": m["id"], "name": m.get("name", m["id"]), **ov}


def file_path(lid, rel):
    """A user look's file (served at /look/<id>/<file>)."""
    m = get(lid)
    if not m or m["builtin"] or ".." in rel.split("/"):
        return None
    full = os.path.realpath(os.path.join(m["_dir"], rel))
    if not full.startswith(os.path.realpath(m["_dir"]) + os.sep) or os.path.splitext(full)[1].lower() not in SERVE or not os.path.isfile(full):
        return None
    return full, mimetypes.guess_type(full)[0] or "application/octet-stream"
