"""System-wide on-screen keyboard (part of the overlay process).

A layer-shell window along the bottom of the screen, above every app, that never takes
keyboard focus (so the app keeps its text field). The controller drives it (crossbard
routes the pad here while it's open); text goes into the app through the input method
when the app supports it (any character), otherwise through the virtual keyboard.
"""
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

try:
    from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402
except ImportError:            # pragma: no cover - the overlay checks this already
    LayerShell = None

LAYERS = {
    "abc": [
        ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "⌫"],
        ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "'"],
        ["a", "s", "d", "f", "g", "h", "j", "k", "l", ":", "⏎"],
        ["⇧", "z", "x", "c", "v", "b", "n", "m", ",", ".", "/", "@"],
        ["?123", "◀", "space", "▶", ".com", "Done"],
    ],
    "sym": [
        ["!", "@", "#", "$", "%", "^", "&", "*", "(", ")", "_", "⌫"],
        ["~", "`", "=", "+", "[", "]", "{", "}", "\\", "|", ";"],
        ['"', "'", "<", ">", "?", "€", "£", "¥", "°", "·", "⏎"],
        ["⇧", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", ":"],
        ["abc", "◀", "space", "▶", "https://", "Done"],
    ],
}
WIDE = {"space": 5, "Done": 2, "?123": 1.5, "abc": 1.5, ".com": 1.5, "https://": 2, "⏎": 1.5, "⇧": 1.5, "⌫": 1.5}
UNITS = 24          # grid columns per row (keys span WIDE units * 2)

CSS = """
.osk { background: rgba(12,12,16,0.86); border-radius: {r}px; padding: {p}px; }
.osk label.key { background: rgba(255,255,255,0.07); border-radius: {kr}px; color: #e9e9e9;
                 font-family: 'Noto Sans', sans-serif; font-size: {fs}px; min-height: {kh}px; }
.osk label.key.fn { color: #a9a9a9; font-size: {ffs}px; }
.osk label.key.lit { color: #fff; }
.osk label.key.on { background: rgba(255,255,255,0.9); color: #111; }
.osk label.hint { color: #a9a9a9; font-size: {hs}px; }
"""


class OskWindow:
    def __init__(self, app, api, glyph, scale=1.0):
        self.api, self.glyph, self.scale = api, glyph, scale
        self.im = None
        self.visible = False
        self.layer, self.shift, self.caps, self.r, self.c = "abc", False, False, 1, 0
        win = Gtk.Window(application=app)
        if LayerShell:
            LayerShell.init_for_window(win)
            LayerShell.set_namespace(win, "crossbar-osk")
            LayerShell.set_layer(win, LayerShell.Layer.OVERLAY)
            LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.NONE)   # the app keeps the keyboard focus
            LayerShell.set_anchor(win, LayerShell.Edge.BOTTOM, True)
            LayerShell.set_margin(win, LayerShell.Edge.BOTTOM, int(30 * scale))
        css = Gtk.CssProvider()
        text = (CSS.replace("{r}", str(int(22 * scale))).replace("{p}", str(int(20 * scale)))
                .replace("{kr}", str(int(12 * scale))).replace("{fs}", str(int(30 * scale)))
                .replace("{ffs}", str(int(20 * scale))).replace("{kh}", str(int(66 * scale)))
                .replace("{hs}", str(int(17 * scale))))
        if hasattr(css, "load_from_string"):
            css.load_from_string(text)
        else:
            css.load_from_data(text.encode())
        from gi.repository import Gdk
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=int(8 * scale))
        box.add_css_class("osk")
        box.set_size_request(int(1400 * scale), -1)
        self.grid = Gtk.Grid(row_spacing=int(9 * scale), column_spacing=int(9 * scale), column_homogeneous=True)
        self.hint = Gtk.Label()
        self.hint.add_css_class("hint")
        box.append(self.grid)
        box.append(self.hint)
        win.set_child(box)
        self.win = win
        self.cells = []

    # ---- drawing ---------------------------------------------------------------------
    def rows(self):
        return LAYERS[self.layer]

    def label(self, k):
        if len(k) == 1 and k.isalpha() and k.islower() and (self.shift or self.caps):
            return k.upper()
        return {"space": " ", "⇧": "⇪" if self.caps else "⇧"}.get(k, k)

    def render(self):
        child = self.grid.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.grid.remove(child)
            child = nxt
        self.cells = []
        for r, row in enumerate(self.rows()):
            total = sum(WIDE.get(k, 1) for k in row)
            col, cells = 0, []
            for c, k in enumerate(row):
                span = max(1, round(WIDE.get(k, 1) * UNITS / total))
                lab = Gtk.Label(label=self.label(k))
                lab.add_css_class("key")
                if len(k) > 1 and k != "space":
                    lab.add_css_class("fn")
                if k == "⇧" and (self.shift or self.caps):
                    lab.add_css_class("lit")
                if (r, c) == (self.r, self.c):
                    lab.add_css_class("on")
                self.grid.attach(lab, col, r, span, 1)
                cells.append((col, span))
                col += span
            self.cells.append(cells)
        g = self.glyph
        self.hint.set_text(g("{ok} Type     {back} Delete     {menu} Shift     {prev} {next} Cursor     {toggle} Done"))

    # ---- show / hide ---------------------------------------------------------------------
    def show(self, on):
        if on == self.visible:
            return False
        self.visible = on
        if on:
            self.layer, self.shift, self.caps, self.r, self.c = "abc", False, False, 1, 0
            self.render()
            self.win.present()
        else:
            self.win.set_visible(False)
        return False

    def close(self):
        self.api.post("/api/osk/show", {"on": False})

    # ---- typing ----------------------------------------------------------------------------
    def type_text(self, text):
        if self.im and self.im.commit_text(text):
            return
        self.api.post("/api/osk/type", {"text": text})

    def special(self, name):
        self.api.post("/api/osk/type", {"special": name})

    def press(self):
        k = self.rows()[self.r][self.c]
        if k == "⌫":
            self.special("backspace")
        elif k == "⇧":
            if self.shift and not self.caps:
                self.caps, self.shift = True, False
            elif self.caps:
                self.caps = False
            else:
                self.shift = True
        elif k in ("?123", "abc"):
            self.layer = "sym" if k == "?123" else "abc"
            self.c = min(self.c, len(self.rows()[self.r]) - 1)
        elif k == "◀":
            self.special("left")
        elif k == "▶":
            self.special("right")
        elif k == "⏎":
            self.special("enter")
        elif k == "Done":
            self.close()
            return
        else:
            self.type_text(" " if k == "space" else self.label(k))
            self.shift = False
        self.render()

    def move_row(self, d):
        nr = max(0, min(len(self.rows()) - 1, self.r + d))
        if nr == self.r:
            return
        col, span = self.cells[self.r][self.c]
        x = col + span / 2
        self.c = min(range(len(self.cells[nr])), key=lambda i: abs(self.cells[nr][i][0] + self.cells[nr][i][1] / 2 - x))
        self.r = nr

    def act(self, a):
        if not self.visible:
            return False
        if a in ("up", "down"):
            self.move_row(-1 if a == "up" else 1)
        elif a in ("left", "right"):
            n = len(self.rows()[self.r])
            self.c = (self.c + (-1 if a == "left" else 1)) % n
        elif a == "ok":
            self.press()
            return False
        elif a == "back":
            self.special("backspace")
        elif a == "menu":
            self.shift, self.caps = not self.shift, False
        elif a == "prev":
            self.special("left")
        elif a == "next":
            self.special("right")
        elif a in ("toggle", "home"):
            self.close()
            return False
        self.render()
        return False

    # ---- input method: open by itself when an app's text field gets focus ----------------------
    def start_input_method(self):
        try:
            from crossbar.imclient import InputMethod, PURPOSE_TERMINAL
        except ImportError:
            return

        def changed(active, purpose):
            if active and purpose != PURPOSE_TERMINAL:
                self.api.post("/api/osk/show", {"on": True, "auto": True})
            elif not active and self.visible:
                self.api.post("/api/osk/show", {"on": False})
        import threading
        try:
            self.im = InputMethod(lambda a, p: threading.Thread(target=changed, args=(a, p), daemon=True).start())
            self.im.start()
            print("overlay: input method ready (keyboard opens on its own in supported apps)", flush=True)
        except Exception as e:
            self.im = None
            print(f"overlay: no input method ({e}); keyboard opens from the Quick Menu", flush=True)
