"""A tiny Wayland input-method client (zwp_input_method_v2), no extra libraries.

Sway relays text-input-v3 to one input method: when a text field gets focus in an app
that supports it (GTK, Qt, Chromium started with --enable-wayland-ime) we receive
`activate`; when it loses focus, `deactivate`. We can then commit text straight into
that field (any Unicode, independent of keyboard layout). Used by the overlay to open
the on-screen keyboard by itself. If the compositor has no input-method support, or
another input method is running, this simply reports unavailable.

Wire format: each message is [object id u32][size<<16 | opcode u32] + arguments
(u32/i32, strings as length-prefixed NUL-terminated UTF-8 padded to 4 bytes).
"""
import os
import socket
import struct
import threading

# zwp_input_method_v2 events / requests (input-method-unstable-v2.xml, in order)
EV_ACTIVATE, EV_DEACTIVATE, EV_SURROUNDING, EV_CAUSE, EV_CONTENT_TYPE, EV_DONE, EV_UNAVAILABLE = range(7)
RQ_COMMIT_STRING, RQ_SET_PREEDIT, RQ_DELETE_SURROUNDING, RQ_COMMIT = range(4)
# content purposes (text-input-v3) where a keyboard makes no sense
PURPOSE_TERMINAL = 13


def _string(s):
    b = s.encode() + b"\0"
    return struct.pack("<I", len(b)) + b + b"\0" * (-len(b) % 4)


class InputMethod:
    def __init__(self, on_change):
        """on_change(active: bool, purpose: int) - called from the reader thread."""
        self.on_change = on_change
        self.sock = None
        self.next_id = 2
        self.ids = {}
        self.serial = 0
        self.active = False
        self.pending_active = False
        self.purpose = 0
        self.available = False
        self.lock = threading.Lock()

    # ---- wire -------------------------------------------------------------------
    def _new(self, kind):
        i = self.next_id
        self.next_id += 1
        self.ids[i] = kind
        return i

    def _send(self, obj, opcode, payload=b""):
        msg = struct.pack("<II", obj, ((8 + len(payload)) << 16) | opcode) + payload
        with self.lock:
            self.sock.sendall(msg)

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("compositor closed the connection")
            buf += chunk
        return buf

    @staticmethod
    def _read_string(data, off):
        n = struct.unpack_from("<I", data, off)[0]
        s = data[off + 4:off + 4 + n - 1].decode(errors="replace") if n else ""
        return s, off + 4 + n + (-n % 4)

    # ---- setup --------------------------------------------------------------------
    def start(self):
        path = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
        if not path.startswith("/"):
            path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), path)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.registry = self._new("registry")
        self._send(1, 1, struct.pack("<I", self.registry))          # wl_display.get_registry
        self.sync_cb = self._new("callback")
        self._send(1, 0, struct.pack("<I", self.sync_cb))            # wl_display.sync
        self.globals = {}
        while True:                                                  # collect globals until the sync callback
            obj, op, data = self._read()
            if obj == self.registry and op == 0:
                name = struct.unpack_from("<I", data, 0)[0]
                iface, off = self._read_string(data, 4)
                version = struct.unpack_from("<I", data, off)[0]
                self.globals[iface] = (name, version)
            elif obj == self.sync_cb:
                break
            elif obj == 1 and op == 0:
                raise RuntimeError("compositor error during setup")
        if "zwp_input_method_manager_v2" not in self.globals or "wl_seat" not in self.globals:
            raise RuntimeError("this compositor has no input-method support")
        self.seat = self._bind("wl_seat", 1, "seat")
        self.manager = self._bind("zwp_input_method_manager_v2", 1, "manager")
        self.im = self._new("im")
        self._send(self.manager, 0, struct.pack("<II", self.seat, self.im))   # get_input_method(seat, new_id)
        self.available = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _bind(self, iface, version, kind):
        name, have = self.globals[iface]
        new = self._new(kind)
        # wl_registry.bind(name, new_id) - an untyped new_id carries interface + version
        self._send(self.registry, 0, struct.pack("<I", name) + _string(iface) + struct.pack("<II", min(version, have), new))
        return new

    def _read(self):
        obj, word = struct.unpack("<II", self._recv_exact(8))
        size, op = word >> 16, word & 0xFFFF
        return obj, op, self._recv_exact(size - 8) if size > 8 else b""

    def _loop(self):
        try:
            while True:
                obj, op, data = self._read()
                if obj != self.im:
                    continue                      # seat capabilities/name, delete_id… not needed
                if op == EV_ACTIVATE:
                    self.pending_active = True
                elif op == EV_DEACTIVATE:
                    self.pending_active = False
                elif op == EV_CONTENT_TYPE:
                    self.purpose = struct.unpack_from("<II", data, 0)[1]
                elif op == EV_DONE:
                    self.serial += 1
                    if self.pending_active != self.active:
                        self.active = self.pending_active
                        self.on_change(self.active, self.purpose)
                elif op == EV_UNAVAILABLE:     # another input method owns the seat
                    self.available = False
                    print("imclient: another input method is running; automatic keyboard is off", flush=True)
                    return
        except Exception as e:
            self.available = False
            print(f"imclient: stopped: {e}", flush=True)

    # ---- typing ------------------------------------------------------------------
    def commit_text(self, text):
        if not (self.available and self.active):
            return False
        self._send(self.im, RQ_COMMIT_STRING, _string(text))
        self._send(self.im, RQ_COMMIT, struct.pack("<I", self.serial))
        return True

    def delete_before(self, n=1):
        if not (self.available and self.active):
            return False
        self._send(self.im, RQ_DELETE_SURROUNDING, struct.pack("<II", n, 0))
        self._send(self.im, RQ_COMMIT, struct.pack("<I", self.serial))
        return True
