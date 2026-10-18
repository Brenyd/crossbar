#!/usr/bin/env python3
"""crossbar-overlay — the Quick Menu drawn on top of whatever is running.

A full-screen, transparent GTK4 window on the Wayland *overlay* layer (via
gtk4-layer-shell), so it appears above games, videos and fullscreen web apps
without switching away from them. It hosts a WebKit view of
http://127.0.0.1:7777/overlay.html and shows/hides when crossbard says so.

Needs: gtk4-layer-shell, webkitgtk-6.0, python-gobject.
"""
from ctypes import CDLL

CDLL("libgtk4-layer-shell.so")   # must be loaded before libwayland-client (i.e. before gi)

import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gdk, GLib, Gtk, WebKit  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

BASE = "http://127.0.0.1:7777"


class Overlay(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.crossbar.Overlay")
        self.win = None
        self.view = None

    def do_activate(self):
        win = Gtk.Window(application=self)
        LayerShell.init_for_window(win)
        LayerShell.set_namespace(win, "crossbar-overlay")
        LayerShell.set_layer(win, LayerShell.Layer.OVERLAY)
        for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(win, edge, True)
        LayerShell.set_exclusive_zone(win, -1)          # cover everything, don't push anything aside
        LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.NONE)

        css = Gtk.CssProvider()
        css.load_from_data(b"window, window.background { background: transparent; }")
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        view = WebKit.WebView()
        clear = Gdk.RGBA()
        clear.parse("rgba(0,0,0,0)")
        view.set_background_color(clear)
        settings = view.get_settings()
        settings.set_enable_developer_extras(False)
        view.load_uri(f"{BASE}/overlay.html")
        win.set_child(view)
        self.win, self.view = win, view
        self.hold()                                    # keep running while hidden
        threading.Thread(target=self.listen, daemon=True).start()

    def show(self, visible):
        if visible:
            LayerShell.set_keyboard_mode(self.win, LayerShell.KeyboardMode.EXCLUSIVE)
            self.win.present()
            self.view.grab_focus()
        else:
            LayerShell.set_keyboard_mode(self.win, LayerShell.KeyboardMode.NONE)
            self.win.set_visible(False)
        return False

    def listen(self):
        """Follow crossbard's event stream; show/hide on request."""
        while True:
            try:
                with urllib.request.urlopen(f"{BASE}/api/events?role=overlay-host", timeout=60) as r:
                    for raw in r:
                        line = raw.decode().strip()
                        if not line.startswith("data:"):
                            continue
                        ev = json.loads(line[5:])
                        if ev.get("type") == "overlay":
                            GLib.idle_add(self.show, bool(ev.get("visible")))
            except Exception as e:
                print(f"overlay: event stream: {e!r}", flush=True)
            GLib.idle_add(self.show, False)
            time.sleep(1.5)


if __name__ == "__main__":
    os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")   # safer in VMs / without GPU accel
    Overlay().run(None)
