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

    def post(self, path, body, timeout=10):
        req = urllib.request.Request(BASE + path, data=json.dumps(body or {}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:            # the backend's own message ("Join a voice channel first")
            try:
                return {"error": json.loads(e.read() or b"{}").get("error") or str(e)}
            except ValueError:
                return {"error": str(e)}
        except Exception as e:
            print(f"overlay: {path}: {e}", flush=True)
            return None


def guide_css(scale, look):
    """The Guide (a look whose look.json has "overlay": {"style": "guide"}): a dark panel, tabs
    across the top, rows lit in the look's accent colour."""
    px = lambda n: f"{max(1, round(n * scale))}px"  # noqa: E731
    acc, acc2 = look.get("accent", "#107c10"), look.get("accent2", look.get("accent", "#5dc21e"))
    p1, p2 = look.get("panel", "#26272b"), look.get("panel2", "#1c1d20")
    text, dim = look.get("text", "#ffffff"), look.get("dim", "rgba(255,255,255,0.62)")
    return f"""
    .panel.guide {{ background: linear-gradient({p1}, {p2}); padding: 0; border-radius: 0;
      box-shadow: 0 {px(20)} {px(60)} rgba(0,0,0,0.6); }}
    .panel.guide .g-top {{ padding: {px(20)} {px(30)} {px(10)}; }}
    .panel.guide .g-pic {{ background: linear-gradient(135deg, {acc2}, {acc}); color: white; font-size: {px(28)};
      min-width: {px(56)}; min-height: {px(56)}; }}
    .panel.guide .g-name {{ color: {text}; font-size: {px(24)}; }}
    .panel.guide .g-now, .panel.guide .g-time {{ color: {dim}; font-size: {px(18)}; }}
    .panel.guide .g-time {{ font-size: {px(24)}; }}
    .panel.guide .g-tabs {{ padding: 0 {px(24)}; border-bottom: 1px solid rgba(255,255,255,0.12); }}
    .panel.guide .g-tab {{ padding: {px(10)} 0 {px(12)}; color: rgba(255,255,255,0.45); border-bottom: {px(4)} solid transparent; }}
    .panel.guide .g-tab label {{ font-size: {px(17)}; }}
    .panel.guide .g-tab.on {{ color: {text}; border-bottom-color: {acc2}; }}
    .panel.guide .g-head {{ color: {dim}; font-size: {px(20)}; padding: {px(12)} {px(32)} 0; }}
    .panel.guide .rows {{ padding: {px(8)} 0; }}
    .panel.guide .g-tab image {{ -gtk-icon-size: {px(28)}; }}
    .panel.guide .row {{ border-radius: 0; padding: {px(7)} {px(30)}; color: rgba(255,255,255,0.86); }}
    .panel.guide .label {{ font-size: {px(21)}; }}
    .panel.guide .sub {{ font-size: {px(15)}; }}
    .panel.guide .row.on {{ background: {acc}; color: white; box-shadow: none; }}
    .panel.guide .row.on .sub {{ color: rgba(255,255,255,0.85); }}
    .panel.guide .row.danger.on {{ background: #a4161a; }}
    .panel.guide .label {{ font-weight: 400; }}
    .panel.guide progressbar progress {{ background: {acc2}; }}
    .panel.guide .foot {{ padding: {px(10)} {px(30)} {px(14)}; border-top: 1px solid rgba(255,255,255,0.12); margin: 0; }}
    .panel.guide .notice {{ padding: 0 {px(32)}; }}
    """


def blade_css(scale, look):
    """The Guide blade (a look whose look.json has "overlay": {"style": "blade"}): a glossy
    coloured blade down the left, your card at the top, rows lit like glass."""
    px = lambda n: f"{max(1, round(n * scale))}px"  # noqa: E731
    acc, acc2 = look.get("accent", "#3f9b2a"), look.get("accent2", look.get("accent", "#86cf3c"))
    text, dim = look.get("text", "#ffffff"), look.get("dim", "rgba(255,255,255,0.75)")
    return f"""
    .panel.blade {{ background: linear-gradient(180deg, {acc2} 0%, {acc} 100%); padding: {px(34)} {px(30)} {px(26)} {px(30)};
      border-radius: 0 {px(22)} {px(22)} 0; box-shadow: {px(10)} 0 {px(40)} rgba(0,0,0,0.5), inset 0 {px(2)} 0 rgba(255,255,255,0.55); }}
    .panel.blade .g-top {{ padding: {px(12)} {px(18)} {px(12)} {px(12)}; border-radius: {px(10)}; margin-bottom: {px(18)};
      background: linear-gradient(rgba(255,255,255,0.32), rgba(255,255,255,0.08)); }}
    .panel.blade .g-pic {{ background-color: {acc}; background-image: linear-gradient(145deg, rgba(255,255,255,0.55), rgba(0,0,0,0.25)); color: white;
      font-size: {px(30)}; min-width: {px(62)}; min-height: {px(62)}; border-radius: {px(6)}; }}
    .panel.blade .g-name {{ color: {text}; font-size: {px(25)}; }}
    .panel.blade .g-now, .panel.blade .g-time {{ color: {dim}; font-size: {px(18)}; }}
    .panel.blade .g-time {{ font-size: {px(22)}; }}
    .panel.blade .title {{ color: {text}; font-size: {px(40)}; font-weight: 300; margin: 0 {px(10)} {px(6)}; }}
    .panel.blade .sep {{ background: rgba(255,255,255,0.6); min-height: {px(2)}; margin: 0 {px(10)} {px(10)}; }}
    .panel.blade .row {{ border-radius: {px(8)}; padding: {px(8)} {px(16)}; color: {text}; }}
    .panel.blade .label {{ font-size: {px(23)}; font-weight: 400; }}
    .panel.blade .sub {{ font-size: {px(15)}; color: {dim}; }}
    .panel.blade .row.on {{ background: linear-gradient(180deg, #ffffff 0%, #f1f4f6 48%, #dfe5ea 52%, #f6f8f9 100%); color: #16181a;
      box-shadow: 0 0 {px(16)} rgba(255,255,255,0.7); }}
    .panel.blade .row.on .sub {{ color: #4a5056; }}
    .panel.blade .row.on image {{ color: {acc}; }}
    .panel.blade .row.danger.on {{ background: linear-gradient(180deg, #ffd7d7, #ff9c9c); }}
    .panel.blade progressbar trough {{ background: rgba(255,255,255,0.3); }}
    .panel.blade progressbar progress {{ background: white; }}
    .panel.blade .row.on progressbar progress {{ background: {acc}; }}
    .panel.blade .foot {{ color: {text}; margin-top: {px(12)}; }}
    .panel.blade .hint, .panel.blade .more, .panel.blade .notice {{ color: {dim}; }}
    """


def css(scale, theme=None):
    px = lambda n: f"{max(1, round(n * scale))}px"  # noqa: E731
    t = theme or {}
    qm, col, font = t.get("quick_menu") or {}, t.get("colors") or {}, t.get("font") or {}
    panel, hl, acc = qm.get("panel", "rgba(8,8,10,0.90)"), qm.get("highlight", "rgba(255,255,255,0.15)"), qm.get("accent", "white")
    text, dim = col.get("text", "white"), col.get("dim", "rgba(255,255,255,0.6)")
    family = font.get("family", "Noto Sans")
    return f"""
    window, window.background {{ background: transparent; }}
    .panel, .panel label {{ font-family: "{family}", "Noto Sans", sans-serif; }}
    .panel {{ background: {panel}; padding: {px(48)} {px(36)} {px(36)} {px(56)}; }}
    .shade {{ background: rgba(0,0,0,0.30); }}
    .kicker {{ color: {dim}; font-size: {px(15)}; letter-spacing: {px(5)}; }}
    .title {{ color: {text}; font-size: {px(34)}; font-weight: 300; margin-bottom: {px(14)}; }}
    .sep {{ background: rgba(255,255,255,0.22); min-height: 1px; margin-bottom: {px(10)}; }}
    .row {{ padding: {px(10)} {px(18)}; border-radius: {px(8)}; color: {dim}; }}
    .row.on {{ background: {hl}; color: {text}; box-shadow: inset {px(3)} 0 {acc}; }}
    .row.danger.on {{ background: rgba(255,90,90,0.30); box-shadow: inset {px(3)} 0 #ff8080; }}
    .label {{ font-size: {px(23)}; font-weight: 300; }}
    .sub {{ font-size: {px(16)}; color: {dim}; }}
    .hint {{ font-size: {px(14)}; color: {dim}; }}
    .foot {{ color: {dim}; font-size: {px(15)}; margin-top: {px(12)}; }}
    .notice {{ color: {text}; font-size: {px(17)}; margin-top: {px(8)}; }}
    progressbar trough {{ min-height: {px(4)}; background: rgba(255,255,255,0.18); border: none; }}
    progressbar progress {{ min-height: {px(4)}; background: {acc}; border: none; }}
    .more {{ color: rgba(255,255,255,0.55); font-size: {px(16)}; }}
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
        try:
            self.theme = self.api.get("/api/theme") or {}
        except Exception:
            self.theme = {}
        provider = Gtk.CssProvider()
        self.provider, self.css_scale = provider, scale
        self._load_css(provider, css(scale, self.theme) + guide_css(scale, {}))
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        panel.add_css_class("panel")
        panel.set_size_request(int(min(width * 0.40, 760 * scale)), -1)
        # the Guide's header (profile, time) and tabs: shown only for a look with a Guide
        self.g_top = Gtk.Box(spacing=int(18 * scale))
        self.g_top.add_css_class("g-top")
        self.g_pic = Gtk.Label(label="P")
        self.g_pic.add_css_class("g-pic")
        who = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        who.set_hexpand(True)
        self.g_name = Gtk.Label(label="Player", xalign=0)
        self.g_name.add_css_class("g-name")
        self.g_now = Gtk.Label(label="", xalign=0)
        self.g_now.add_css_class("g-now")
        self.g_now.set_ellipsize(Pango.EllipsizeMode.END)
        who.append(self.g_name)
        who.append(self.g_now)
        self.g_time = Gtk.Label(label="")
        self.g_time.add_css_class("g-time")
        for w in (self.g_pic, who, self.g_time):
            self.g_top.append(w)
        self.g_tabs = Gtk.Box(homogeneous=True)
        self.g_tabs.add_css_class("g-tabs")
        self.g_tab_widgets = {}
        from crossbar.overlay_model import GUIDE_TABS
        for key, label, icon in GUIDE_TABS:
            t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=int(4 * scale))
            t.add_css_class("g-tab")
            img = Gtk.Image.new_from_icon_name(icon)
            img.set_pixel_size(int((34 if key == "main" else 28) * scale))
            t.append(img)
            t.append(Gtk.Label(label=label.lower()))
            self.g_tabs.append(t)
            self.g_tab_widgets[key] = t
        self.g_head = Gtk.Label(label="", xalign=0)
        self.g_head.add_css_class("g-head")
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
        self.sep = sep
        self.rows.add_css_class("rows")
        for w in (self.g_top, self.g_tabs, self.g_head, self.kicker, self.title, sep, self.rows, self.notice, self.foot):
            panel.append(w)
        self.panel, self.look_sig = panel, None
        # layout: the XMB's panel runs down the left edge; the Guide sits centred, a fixed size
        # like the 360's (style_for_look switches): [shade-left] [column: panel] [shade]
        shade = Gtk.Box()
        shade.add_css_class("shade")
        shade.set_hexpand(True)
        shade_l = Gtk.Box()
        shade_l.add_css_class("shade")
        shade_l.set_hexpand(True)
        shade_l.set_visible(False)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        col.append(panel)
        root.append(shade_l)
        root.append(col)
        root.append(shade)
        self.shade_l, self.col, self.screen = shade_l, col, (width, height)
        self.panel_w = int(min(width * 0.40, 760 * scale))
        win.set_child(root)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        win.add_controller(keys)

        self.win, self.scale = win, scale
        # rows that fit between the header and the footer; the list scrolls past that
        self.max_rows = self.panel_rows = max(4, int((height - 330 * scale) / (92 * scale)))
        self.guide_rows = 6
        self.offset = 0
        self.make_hud(scale)
        self.glyph_data = {}
        self.osk = OskWindow(self, self.api, lambda t: glyphs.render(t, self.glyph_data or self.model.data.get("glyphs")), scale)
        self.osk.set_theme(self.theme)
        self.osk.start_input_method()
        self.hold()
        threading.Thread(target=self.listen, daemon=True).start()
        threading.Thread(target=self.poll, daemon=True).start()
        print(f"overlay: ready ({width}x{height}, scale {scale:.2f})", flush=True)

    @staticmethod
    def _load_css(provider, text):
        if hasattr(provider, "load_from_string"):
            provider.load_from_string(text)
        else:
            provider.load_from_data(text.encode())

    def apply_theme(self):
        """Theme changed in Settings: restyle the Quick Menu and the keyboard right away."""
        try:
            self.theme = self.api.get("/api/theme") or {}
        except Exception:
            return False
        self.look_sig = None                      # restyled with the look on the next draw
        self._load_css(self.provider, css(self.css_scale, self.theme) + guide_css(self.css_scale, {}))
        self.osk.set_theme(self.theme)
        return False

    # ---- PS5 temperature HUD: a small click-through box above everything, games included ----
    def make_hud(self, scale):
        hud = Gtk.Window(application=self)
        LayerShell.init_for_window(hud)
        LayerShell.set_namespace(hud, "crossbar-hud")
        LayerShell.set_layer(hud, LayerShell.Layer.OVERLAY)
        LayerShell.set_keyboard_mode(hud, LayerShell.KeyboardMode.NONE)
        LayerShell.set_exclusive_zone(hud, -1)
        css = Gtk.CssProvider()
        self.hud_css, self.hud_size = css, None
        self.hud_style("auto")
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        box = Gtk.Box(spacing=int(14 * scale))
        box.add_css_class("hud")
        hud.set_child(box)
        self.hud, self.hud_box, self.hud_labels, self.hud_corner = hud, box, {}, None
        if hasattr(hud, "set_can_target"):
            box.set_can_target(False)                          # clicks and input go straight through
        threading.Thread(target=self.hud_loop, daemon=True).start()

    HUD_SCALE = {"small": 0.8, "auto": 1.0, "medium": 1.4, "large": 2.0, "huge": 2.8}

    def hud_style(self, size):
        """Text size (Quick Menu › Performance › Temperature Size): readable on a big TV too."""
        if size == self.hud_size:
            return
        self.hud_size = size
        k = self.scale * self.HUD_SCALE.get(size, 1.0)
        text = (f".hud {{ background: rgba(0,0,0,0.55); border-radius: {int(10 * k)}px; padding: {int(6 * k)}px {int(12 * k)}px; }}"
                f" .hud label {{ color: #eee; font-size: {int(17 * k)}px; font-family: 'Noto Sans', sans-serif; }}"
                " .hud .warm { color: #ffc56b; } .hud .hot { color: #ff7b7b; }")
        self._load_css(self.hud_css, text)
        if getattr(self, "hud_box", None):
            self.hud_box.set_spacing(int(14 * k))

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
        self.hud_style(p.get("hud_size") or "auto")
        corner = p.get("hud_corner") or "top-left"
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

    def show(self, on, page=None):
        if on == self.visible:
            return False
        self.visible = on
        if on:
            self.model.reset()
            self.model.refresh()
            if page:
                self.model.open_on(page)
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

    def style_for_look(self):
        """Panel or Guide, in the look's colours (looks.py overlay(), via /api/quick)."""
        look = self.model.data.get("look") or {}
        sig = json.dumps(look, sort_keys=True)
        if sig == self.look_sig:
            return look
        self.look_sig = sig
        self._load_css(self.provider, css(self.css_scale, self.theme) + guide_css(self.css_scale, look) + blade_css(self.css_scale, look))
        guide = look.get("style") == "guide"
        blade = look.get("style") == "blade"
        (self.panel.add_css_class if guide else self.panel.remove_css_class)("guide")
        (self.panel.add_css_class if blade else self.panel.remove_css_class)("blade")
        # the Guide: centred on the screen, 960 × 640 at 1080p (the 360's Guide is a box in the
        # middle, about half the screen wide); the panel: full height down the left
        s = self.scale
        self.shade_l.set_visible(guide)
        (self.col.add_css_class if guide else self.col.remove_css_class)("shade")
        self.panel.set_valign(Gtk.Align.CENTER if guide else Gtk.Align.FILL)
        self.panel.set_vexpand(True)              # (with CENTER: the spare height splits above and below)
        self.panel.set_size_request(int(960 * s) if guide else self.panel_w, int(640 * s) if guide else -1)
        self.max_rows = self.guide_rows if guide else self.panel_rows
        for w in (self.g_top, self.g_tabs):
            w.set_visible(guide)
        self.g_top.set_visible(guide or blade)     # the Guide blade: your card on top, no tabs
        for w in (self.kicker, self.title, self.sep):
            w.set_visible(not guide)
        self.kicker.set_visible(not guide and not blade)
        return look

    def render(self):
        m = self.model
        look = self.style_for_look()
        guide = look.get("style") == "guide"
        blade = look.get("style") == "blade"
        self.title.set_text("Guide" if blade and m.page == "main" else m.title())
        if guide or blade:
            d = m.data
            user = d.get("user") or "Player"
            self.g_pic.set_text(user[:1].upper())
            self.g_name.set_text(user)
            app = d.get("app")
            self.g_now.set_text(f"Playing {app['title']}" if app else "In Crossbar")
            self.g_time.set_text(time.strftime("%-I:%M %p"))
            if blade:
                self.g_head.set_visible(False)
                self.foot.set_text(self.g(f"{{ok}}  Select      ◀ ▶  Adjust      {{back}}  {'Close' if m.is_tab() else 'Back'}"))
            else:
                for key, w in self.g_tab_widgets.items():
                    (w.add_css_class if key == m.tab() else w.remove_css_class)("on")
                head = None if m.is_tab() else m.title()
                self.g_head.set_visible(bool(head))
                self.g_head.set_text((head or "").lower())
                self.foot.set_text(self.g(f"{{ok}}  Select      ◀ ▶  Adjust      {{back}}  {'Close' if m.is_tab() else 'Back'}      LB RB  Tabs"))
        else:
            self.g_head.set_visible(False)
            self.foot.set_text(self.g(f"{{ok}}  Select      ◀ ▶  Adjust      {{back}}  Back to {m.back_to()}"))
        self.notice.set_text(self.g(m.notice))
        child = self.rows.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.rows.remove(child)
            child = nxt
        # scroll: keep the selected row in view, show ▲ / ▼ when there's more
        n = self.max_rows
        if m.sel < self.offset:
            self.offset = m.sel
        elif m.sel >= self.offset + n:
            self.offset = m.sel - n + 1
        self.offset = max(0, min(self.offset, max(0, len(m.rows) - n)))
        more_up, more_down = self.offset > 0, self.offset + n < len(m.rows)
        if more_up:
            up = Gtk.Label(label="▲")
            up.add_css_class("more")
            self.rows.append(up)
        for i, r in enumerate(m.rows):
            if i < self.offset or i >= self.offset + n:
                continue
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
        if more_down:
            down = Gtk.Label(label="▼")
            down.add_css_class("more")
            self.rows.append(down)
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
                            GLib.idle_add(self.show, bool(ev.get("visible")), ev.get("page"))
                        elif ev.get("type") == "input" and ev.get("to") == "overlay":
                            GLib.idle_add(self.act, ev["action"])
                        elif ev.get("type") == "input" and ev.get("to") == "osk":
                            GLib.idle_add(self.osk.act, ev["action"])
                        elif ev.get("type") == "osk":
                            if ev.get("open"):
                                try:
                                    q = self.api.get("/api/quick") or {}
                                    self.glyph_data = q.get("glyphs") or {}
                                    look = q.get("look") or {}
                                    GLib.idle_add(lambda look=look: self.osk.set_theme(self.theme, look) and False)
                                except Exception:
                                    pass
                            GLib.idle_add(self.osk.show, bool(ev.get("open")))
                        elif ev.get("type") == "theme":
                            GLib.idle_add(self.apply_theme)
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


def single_instance():
    """Only one overlay may run: two would draw two Quick Menus / keyboards and act on every
    press twice. A newer overlay (a restart) replaces an older one that's still around."""
    import fcntl
    import signal
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "crossbar-overlay.lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    for _ in range(30):
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            try:
                old = int(os.pread(fd, 32, 0).decode().strip() or 0)
                if old and old != os.getpid():
                    os.kill(old, signal.SIGTERM)
            except (ValueError, ProcessLookupError, PermissionError):
                pass
            time.sleep(0.2)
    else:
        print("overlay: another overlay is still running; exiting", flush=True)
        sys.exit(0)
    os.ftruncate(fd, 0)
    os.pwrite(fd, str(os.getpid()).encode(), 0)
    return fd                         # kept open (and locked) for the life of the process


if __name__ == "__main__":
    _lock = single_instance()
    Overlay().run(None)
