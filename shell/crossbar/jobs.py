"""Background job tracking (downloads, logins) so the XMB can show progress."""
import itertools
import threading
import time
import traceback

_ids = itertools.count(1)


class Cancelled(Exception):
    """Raised inside a job when you cancel it (job.check() / a download's progress callback)."""


def human_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def human_eta(sec):
    sec = int(sec)
    if sec < 60:
        return f"{max(1, sec)} s left"
    if sec < 3600:
        return f"{sec // 60} min left"
    return f"{sec // 3600} h {sec % 3600 // 60} min left"


class Job:
    def __init__(self, kind, title, provider=None, game_id=None):
        self.id = next(_ids)
        self.kind = kind            # "install" | "login" | "uninstall"
        self.title = title
        self.provider = provider
        self.game_id = game_id
        self.progress = 0.0
        self.status = "running"     # running | done | error
        self.message = ""
        self.started = time.time()
        self.finished = None
        self.done_bytes = self.total_bytes = 0
        self.speed = 0.0            # bytes per second (smoothed)
        self.eta = None             # seconds left
        self.cancellable = False
        self._cancel = threading.Event()
        self._cleanup = []          # run when cancelled (kill a process, delete partial files)
        self._last = None           # (time, bytes) of the previous byte update

    # ---- cancelling --------------------------------------------------------------------
    def cancel_with(self, fn):
        """Make the job cancellable; fn() runs on cancel (e.g. stop the downloader)."""
        self.cancellable = True
        self._cleanup.append(fn)

    def cancelled(self):
        return self._cancel.is_set()

    def check(self):
        if self._cancel.is_set():
            raise Cancelled()

    # ---- progress ----------------------------------------------------------------------
    def set_bytes(self, done, total, prefix=""):
        """Progress from bytes: works out speed and time left, and the message."""
        now = time.time()
        done, total = int(done or 0), int(total or 0)
        if self._last and now - self._last[0] >= 0.5:
            rate = max(0.0, (done - self._last[1]) / (now - self._last[0]))
            self.speed = rate if not self.speed else 0.7 * self.speed + 0.3 * rate
            self._last = (now, done)
        elif not self._last:
            self._last = (now, done)
        self.done_bytes, self.total_bytes = done, total
        if total and self.speed > 1024:
            self.eta = (total - done) / self.speed
        parts = [f"{int(100 * done / total)}%" if total else human_bytes(done)]
        if total:
            parts.append(f"{human_bytes(done)} of {human_bytes(total)}")
        if self.speed > 1024:
            parts.append(f"{human_bytes(self.speed)}/s")
        if self.eta is not None and self.speed > 1024:
            parts.append(human_eta(self.eta))
        self.set(done / total if total else None, (prefix + " " if prefix else "") + " · ".join(parts))
        self.check()

    def set(self, progress=None, message=None):
        if progress is not None:
            self.progress = max(0.0, min(1.0, progress))
        if message is not None:
            self.message = message

    def as_dict(self):
        return {k: getattr(self, k) for k in
                ("id", "kind", "title", "provider", "game_id", "progress", "status", "message", "started", "finished",
                 "done_bytes", "total_bytes", "speed", "eta", "cancellable")}


class JobManager:
    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()

    def start(self, kind, title, fn, provider=None, game_id=None):
        """Run fn(job) on a thread; returns the Job immediately."""
        with self._lock:
            for j in self._jobs.values():
                if j.status == "running" and j.kind == kind and j.provider == provider and j.game_id == game_id:
                    return j  # already in progress
            job = Job(kind, title, provider, game_id)
            self._jobs[job.id] = job

        def run():
            try:
                fn(job)
                job.check()
                job.status, job.progress = "done", 1.0
            except Cancelled:
                job.status, job.message = "cancelled", "Cancelled"
            except Exception as e:  # surface the error in the UI
                if job.cancelled():           # the process we stopped reported an error: that's the cancel
                    job.status, job.message = "cancelled", "Cancelled"
                    job.finished = time.time()
                    return
                traceback.print_exc()
                job.status, job.message = "error", str(e) or e.__class__.__name__
            job.finished = time.time()

        threading.Thread(target=run, daemon=True).start()
        return job

    def cancel(self, jid):
        """Stop a running job and clean up after it (partial downloads are deleted)."""
        job = self._jobs.get(int(jid))
        if not job or job.status != "running":
            raise RuntimeError("That download isn't running")
        if not job.cancellable:
            raise RuntimeError("This one can't be stopped part-way")
        job._cancel.set()
        job.set(message="Cancelling…")
        for fn in job._cleanup:
            try:
                fn()
            except Exception:
                traceback.print_exc()
        return job.as_dict()

    def list(self):
        now = time.time()
        with self._lock:
            # keep finished jobs around for 2 minutes so the UI can notify
            for jid in [j.id for j in self._jobs.values() if j.finished and now - j.finished > 120]:
                del self._jobs[jid]
            return [j.as_dict() for j in self._jobs.values()]
