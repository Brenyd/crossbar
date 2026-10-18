"""Background job tracking (downloads, logins) so the XMB can show progress."""
import itertools
import threading
import time
import traceback

_ids = itertools.count(1)


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

    def set(self, progress=None, message=None):
        if progress is not None:
            self.progress = max(0.0, min(1.0, progress))
        if message is not None:
            self.message = message

    def as_dict(self):
        return {k: getattr(self, k) for k in
                ("id", "kind", "title", "provider", "game_id", "progress", "status", "message", "started", "finished")}


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
                job.status, job.progress = "done", 1.0
            except Exception as e:  # surface the error in the UI
                traceback.print_exc()
                job.status, job.message = "error", str(e) or e.__class__.__name__
            job.finished = time.time()

        threading.Thread(target=run, daemon=True).start()
        return job

    def list(self):
        now = time.time()
        with self._lock:
            # keep finished jobs around for 2 minutes so the UI can notify
            for jid in [j.id for j in self._jobs.values() if j.finished and now - j.finished > 120]:
                del self._jobs[jid]
            return [j.as_dict() for j in self._jobs.values()]
