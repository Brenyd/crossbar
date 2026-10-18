"""Server-sent events: push input and quick-menu requests to the XMB page."""
import queue
import threading


class Hub:
    def __init__(self):
        self._subs = []
        self._lock = threading.Lock()

    def subscribe(self, role=""):
        q = queue.Queue(maxsize=200)
        q.role = role
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def listeners(self, role=None):
        with self._lock:
            return len([q for q in self._subs if role is None or q.role == role])

    def publish(self, event):
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass


HUB = Hub()
