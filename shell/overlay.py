#!/usr/bin/env python3
"""crossbar-overlay — the Quick Menu, drawn on top of every application.

A native GTK4 window on the Wayland *overlay* layer (gtk4-layer-shell): it sits
above games, videos and fullscreen web apps — like the Steam or Discord
overlay — without switching away from them. While it's open it takes the
keyboard (exclusive) and crossbard sends the controller to it and holds the
controller so the app underneath doesn't react.

No web engine: plain GTK widgets, Cairo rendering — starts instantly and works
in VMs without 3D. Contents and actions live in crossbar/overlay_model.py.
"""
import os
import sys
from ctypes import CDLL

os.environ.setdefault("GSK_RENDERER", "cairo")        # no GPU needed; safest in VMs
CDLL("libgtk4-layer-shell.so")                         # must load before libwayland-client (before gi)

import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crossbar.overlay_model import Model  # noqa: E402
from crossbar import glyphs  # noqa: E402
from osk_window import OskWindow  # noqa: E402

BASE = "http://127.0.0.1:7777"
# keyboard: browser key names (the shared mapping) -> GDK names
GDK_KEYS = {"ArrowUp": "Up", "ArrowDown": "Down", "ArrowLeft": "Left", "ArrowRight": "Right", "Enter": "Return",
            "Escape": "Escape", "Tab": "Tab", "Space": "space", "Backspace": "BackSpace", "Home": "Home",
            "PageUp": "Page_Up", "PageDown": "Page_Down"}


class Api:
    def get(self, path):
        with urllib.request.urlopen(BASE + path, timeout=5) as r:
            return json.loads(r.read() or b"null")

    def post(self, path, body):
        req = urllib.request.Request(BASE + path, data=json.dumps(body or {}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read() or b"null")
        except Exception as e:
            print(f"overlay: {path}: {e}", flush=True)
            return None


def css(scale):
    px = lambda n: f"{max(1, round(n * scale))}px"  # noqa: E731
    return f"""
    window, window.background {{ background: transparent; }}
    .panel {{ background: rgba(8,8,10,0.90); padding: {px(48)} {px(36)} {px(36)} {px(56)}; }}
    .shade {{ background: rgba(0,0,0,0.30); }}
    .kicker {{ color: rgba(255,255,255,0.6); font-size: {px(15)}; letter-spacing: {px(5)}; }}
    .title {{ color: white; font-size: {px(34)}; font-weight: 300; margin-bottom: {px(14)}; }}
    .sep {{ background: rgba(255,255,255,0.22); min-height: 1px; margin-bottom: {px(10)}; }}
    .row {{ padding: {px(10)} {px(18)}; border-radius: {px(8)}; color: rgba(255,255,255,0.62); }}
    .row.on {{ background: rgba(255,255,255,0.15); color: white; box-shadow: inset {px(3)} 0 white; }}
    .row.danger.on {{ background: rgba(255,90,90,0.30); box-shadow: inset {px(3)} 0 #ff8080; }}
    .label {{ font-size: {px(23)}; font-weight: 300; }}
    .sub {{ font-size: {px(16)}; color: rgba(255,255,255,0.6); }}
    .hint {{ font-size: {px(14)}; color: rgba(255,255,255,0.6); }}
    .foot {{ color: rgba(255,255,255,0.6); font-size: {px(15)}; margin-top: {px(12)}; }}
    .notice {{ color: white; font-size: {px(17)}; margin-top: {px(8)}; }}
    progressbar trough {{ min-height: {px(4)}; background: rgba(255,255,255,0.18); border: none; }}
    progressbar progress {{ min-height: {px(4)}; background: white; border: none; }}
    image {{ color: inherit; }}
    """


class Overlay(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.crossbar.Overlay")
        self.api = Api()
        self.model = Model(self.api)
        self.visible = False
        self.keymap = {}
        self.win = None

    # ---- window ---------------------------------------------------------------
    def do_activate(self):
        win = Gtk.Window(application=self)
        LayerShell.init_for_window(win)
        LayerShell.set_namespace(win, "crossbar-overlay")
        LayerShell.set_layer(win, LayerShell.Layer.OVERLAY)
        for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(win, edge, True)
        LayerShell.set_exclusive_zone(win, -1)
        LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.NONE)

        display = Gdk.Display.get_default()
        mons = display.get_monitors()
        height = mons.get_item(0).get_geometry().height if mons.get_n_items() else 1080
        width = mons.get_item(0).get_geometry().width if mons.get_n_items() else 1920
        scale = max(0.6, height / 1080)
        provider = Gtk.CssProvider()
        if hasattr(provider, "load_from_string"):
            provider.load_from_string(css(scale))
        else:
            provider.load_from_data(css(scale).encode())
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        panel.add_css_class("panel")
        panel.set_size_request(int(min(width * 0.40, 760 * scale)), -1)
        self.kicker = Gtk.Label(label="QUICK MENU", xalign=0)
        self.kicker.add_css_class("kicker")
        self.title = Gtk.Label(label="Crossbar", xalign=0)
        self.title.add_css_class("title")
        self.title.set_ellipsize(Pango.EllipsizeMode.END)
        sep = Gtk.Box()
        sep.add_css_class("sep")
        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=int(4 * scale))
        self.rows.set_vexpand(True)
        self.notice = Gtk.Label(label="", xalign=0)
        self.notice.add_css_class("notice")
        self.foot = Gtk.Label(label="", xalign=0)
        self.foot.add_css_class("foot")
        for w in (self.kicker, self.title, sep, self.rows, self.notice, self.foot):
            panel.append(w)
        shade = Gtk.Box()
        shade.add_css_class("shade")
        shade.set_hexpand(True)
        root.append(panel)
        root.append(shade)
        win.set_child(root)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        win.add_controller(keys)

        self.win, self.scale = win, scale
        self.make_hud(scale)
        self.glyph_data = {}
        self.osk = OskWindow(self, self.api, lambda t: glyphs.render(t, self.glyph_data or self.model.data.get("glyphs")), scale)
        self.osk.start_input_method()
        self.hold()
        threading.Thread(target=self.listen, daemon=True).start()
        threading.Thread(target=self.poll, daemon=True).start()
        print(f"overlay: ready ({width}x{height}, scale {scale:.2f})", flush=True)

    # ---- PS5 temperature HUD: a small click-through box above everything, games included ----
    def make_hud(self, scale):
        hud = Gtk.Window(application=self)
        LayerShell.init_for_window(hud)
        LayerShell.set_namespace(hud, "crossbar-hud")
        LayerShell.set_layer(hud, LayerShell.Layer.OVERLAY)
        LayerShell.set_keyboard_mode(hud, LayerShell.KeyboardMode.NONE)
        LayerShell.set_exclusive_zone(hud, -1)
        css = Gtk.CssProvider()
        text = (f".hud {{ background: rgba(0,0,0,0.55); border-radius: {int(10 * scale)}px; padding: {int(6 * scale)}px {int(12 * scale)}px; }}"
                f" .hud label {{ color: #eee; font-size: {int(17 * scale)}px; font-family: 'Noto Sans', sans-serif; }}"
                " .hud .warm { color: #ffc56b; } .hud .hot { color: #ff7b7b; }")
        if hasattr(css, "load_from_string"):
            css.load_from_string(text)
        else:
            css.load_from_data(text.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        box = Gtk.Box(spacing=int(14 * scale))
        box.add_css_class("hud")
        hud.set_child(box)
        self.hud, self.hud_box, self.hud_labels, self.hud_corner = hud, box, {}, None
        if hasattr(hud, "set_can_target"):
            box.set_can_target(False)                          # clicks and input go straight through
        threading.Thread(target=self.hud_loop, daemon=True).start()

    def hud_loop(self):
        while True:
            try:
                p = self.api.get("/api/ps5") or {}
            except Exception:
                p = {}
            GLib.idle_add(self.hud_update, p)
            time.sleep(2 if p.get("hud") else 6)

    def hud_update(self, p):
        if not (p.get("available") and p.get("hud")):
            self.hud.set_visible(False)
            return False
        corner = p.get("hud_corner") or "top-right"
        if corner != self.hud_corner:
            for edge, on in ((LayerShell.Edge.TOP, "top" in corner), (LayerShell.Edge.BOTTOM, "bottom" in corner),
                             (LayerShell.Edge.LEFT, "left" in corner), (LayerShell.Edge.RIGHT, "right" in corner)):
                LayerShell.set_anchor(self.hud, edge, on)
                LayerShell.set_margin(self.hud, edge, int(18 * self.scale))
            self.hud_corner = corner
        t = p.get("temps") or {}
        for key, name in (("cpu", "CPU"), ("gpu", "GPU"), ("nvme", "NVMe")):
            v = t.get(key)
            lab = self.hud_labels.get(key)
            if v is None:
                if lab:
                    lab.set_visible(False)
                continue
            if not lab:
                lab = self.hud_labels[key] = Gtk.Label()
                self.hud_box.append(lab)
            lab.set_visible(True)
            lab.set_text(f"{name} {v}°")
            for c in ("warm", "hot"):
                lab.remove_css_class(c)
            if v >= 85:
                lab.add_css_class("hot")
            elif v >= 70:
                lab.add_css_class("warm")
        self.hud.set_visible(True)
        return False

    def show(self, on):
        if on == self.visible:
            return False
        self.visible = on
        if on:
            self.model.reset()
            self.model.refresh()
            self.render()
            LayerShell.set_keyboard_mode(self.win, LayerShell.KeyboardMode.EXCLUSIVE)
            self.win.present()
            # tell crossbard we're really on screen (otherwise it takes the controller back)
            GLib.timeout_add(150, lambda: threading.Thread(
                target=lambda: self.api.post("/api/overlay/ack", {}), daemon=True).start() or False)
        else:
            LayerShell.set_keyboard_mode(self.win, LayerShell.KeyboardMode.NONE)
            self.win.set_visible(False)
        return False

    def g(self, text):
        """Controller glyphs ({ok} -> A / ✕ / B) in the style chosen in Settings."""
        return glyphs.render(text, self.model.data.get("glyphs"))

    def render(self):
        m = self.model
        self.title.set_text(m.title())
        self.foot.set_text(self.g(f"{{ok}}  Select      ◀ ▶  Adjust      {{back}}  Back to {m.back_to()}"))
        self.notice.set_text(self.g(m.notice))
        child = self.rows.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.rows.remove(child)
            child = nxt
        for i, r in enumerate(m.rows):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=int(16 * self.scale))
            row.add_css_class("row")
            if i == m.sel:
                row.add_css_class("on")
            if r.get("danger"):
                row.add_css_class("danger")
            img = Gtk.Image.new_from_icon_name(r.get("icon") or "applications-system-symbolic")
            img.set_pixel_size(int(30 * self.scale))
            row.append(img)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            col.set_hexpand(True)
            lab = Gtk.Label(label=self.g(r["label"]), xalign=0)
            lab.add_css_class("label")
            lab.set_ellipsize(Pango.EllipsizeMode.END)
            col.append(lab)
            if r.get("sub"):
                sub = Gtk.Label(label=self.g(r["sub"]), xalign=0)
                sub.add_css_class("sub")
                sub.set_ellipsize(Pango.EllipsizeMode.END)
                col.append(sub)
            if r.get("bar") is not None:
                bar = Gtk.ProgressBar()
                bar.set_fraction(max(0.0, min(1.0, float(r["bar"]))))
                bar.set_margin_top(int(6 * self.scale))
                col.append(bar)
            row.append(col)
            if r.get("hint") and i == m.sel:
                hint = Gtk.Label(label=self.g(r["hint"]))
                hint.add_css_class("hint")
                row.append(hint)
            self.rows.append(row)
        return False

    # ---- input -----------------------------------------------------------------
    def act(self, action):
        if not self.visible:
            return False
        self.model.handle(action)
        self.render()
        return False

    def on_key(self, _ctrl, keyval, _code, _state):
        name = Gdk.keyval_name(keyval) or ""
        if name == "KP_Enter":
            name = "Return"
        for action, keys in self.keymap.items():
            if name in keys:
                self.act(action)
                return True
        return True        # swallow everything else while the menu is open

    # ---- crossbard ---------------------------------------------------------------
    def load_keymap(self):
        try:
            kb = self.api.get("/api/controls").get("keyboard", {})
        except Exception:
            kb = {}
        km = {}
        for action, keys in kb.items():
            km[action] = {GDK_KEYS.get(k, k) for k in keys}
        km.setdefault("ok", set()).update({"Return"})
        km.setdefault("back", set()).update({"Escape"})
        self.keymap = km

    def listen(self):
        while True:
            try:
                self.load_keymap()
                with urllib.request.urlopen(f"{BASE}/api/events?role=overlay-host", timeout=60) as r:
                    for raw in r:
                        line = raw.decode().strip()
                        if not line.startswith("data:"):
                            continue
                        ev = json.loads(line[5:])
                        if ev.get("type") == "overlay":
                            GLib.idle_add(self.show, bool(ev.get("visible")))
                        elif ev.get("type") == "input" and ev.get("to") == "overlay":
                            GLib.idle_add(self.act, ev["action"])
                        elif ev.get("type") == "input" and ev.get("to") == "osk":
                            GLib.idle_add(self.osk.act, ev["action"])
                        elif ev.get("type") == "osk":
                            if ev.get("open"):
                                try:
                                    self.glyph_data = (self.api.get("/api/quick") or {}).get("glyphs") or {}
                                except Exception:
                                    pass
                            GLib.idle_add(self.osk.show, bool(ev.get("open")))
                        elif ev.get("type") == "physical-input" and self.osk.visible:
                            threading.Thread(target=self.osk.close, daemon=True).start()
            except Exception as e:
                print(f"overlay: event stream: {e!r}", flush=True)
            GLib.idle_add(self.show, False)
            time.sleep(1.5)

    def poll(self):
        while True:
            time.sleep(1)
            if self.visible:
                self.model.refresh()
                GLib.idle_add(self.render)


if __name__ == "__main__":
    Overlay().run(None)
