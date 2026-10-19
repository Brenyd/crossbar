"""Internet speed test (Settings › Network › Internet Speed Test): latency, jitter, download and
upload against Cloudflare's speed test servers (speed.cloudflare.com, the nearest one picked by
Cloudflare). Several connections at once, about 8 seconds each way, like the usual speed tests.
If a VPN is on, this measures the connection through it.
"""
import http.client
import os
import ssl
import statistics
import threading
import time

from . import util

HOST = "speed.cloudflare.com"
STREAMS = 4
SECONDS = 8.0
_ctx = ssl.create_default_context()


def _conn():
    return http.client.HTTPSConnection(HOST, timeout=15, context=_ctx)


def _trace():
    """Which Cloudflare city answered, and the address the internet sees."""
    try:
        c = _conn()
        c.request("GET", "/cdn-cgi/trace", headers={"User-Agent": "Crossbar"})
        txt = c.getresponse().read().decode(errors="replace")
        c.close()
        kv = dict(ln.split("=", 1) for ln in txt.splitlines() if "=" in ln)
        return {"server": kv.get("colo", ""), "ip": kv.get("ip", ""), "country": kv.get("loc", "")}
    except OSError:
        return {}


def latency(n=12):
    """Round trips of a tiny request on one open connection: (ping ms, jitter ms)."""
    c = _conn()
    times = []
    try:
        for i in range(n + 1):
            t = time.perf_counter()
            c.request("GET", "/__down?bytes=0", headers={"User-Agent": "Crossbar"})
            c.getresponse().read()
            if i:                                  # the first one includes setting up the connection
                times.append((time.perf_counter() - t) * 1000)
    finally:
        c.close()
    diffs = sorted(abs(a - b) for a, b in zip(times, times[1:]))
    jitter = statistics.mean(diffs[:max(1, int(len(diffs) * 0.8))]) if diffs else 0.0   # minus the worst fifth
    return statistics.median(times), jitter


def _run(work, seconds, progress, what):
    """Run `work(stop, add)` on several connections; returns Mbit/s (live figure to progress)."""
    total = [0]
    lock = threading.Lock()
    stop = threading.Event()
    errors = []

    def add(n):
        with lock:
            total[0] += n

    def worker():
        try:
            work(stop, add)
        except OSError as e:
            errors.append(e)
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(STREAMS)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    warm, warm_bytes = 1.0, None                    # skip the first second (TCP still speeding up)
    while time.perf_counter() - t0 < seconds + warm:
        time.sleep(0.25)
        el = time.perf_counter() - t0
        if warm_bytes is None and el >= warm:
            warm_bytes, warm_t = total[0], el
        if warm_bytes is not None and el > warm_t:
            progress(what, (total[0] - warm_bytes) * 8 / (el - warm_t) / 1e6, min(1.0, (el - warm) / seconds))
        if errors and not any(t.is_alive() for t in threads):
            break
    stop.set()
    el = time.perf_counter() - t0
    got = total[0] - (warm_bytes or 0)
    if warm_bytes is None or el <= warm_t or (errors and got <= 0):
        if errors:
            raise RuntimeError(f"{what.capitalize()} test failed: {errors[0]}")
        return 0.0
    return got * 8 / (el - warm_t) / 1e6


DOWN_BYTES = 25_000_000            # per request (Cloudflare refuses much bigger ones)


def download(progress):
    def work(stop, add):
        while not stop.is_set():
            c = _conn()
            c.request("GET", f"/__down?bytes={DOWN_BYTES}", headers={"User-Agent": "Crossbar"})
            r = c.getresponse()
            if r.status != 200:
                c.close()
                raise OSError(f"the speed test server answered {r.status} to the download")
            while not stop.is_set():
                b = r.read(65536)
                if not b:
                    break
                add(len(b))
            c.close()
    return _run(work, SECONDS, progress, "download")


def upload(progress):
    chunk = os.urandom(1 << 16)

    def work(stop, add):
        while not stop.is_set():
            size = 25_000_000
            c = _conn()
            c.putrequest("POST", "/__up")
            c.putheader("User-Agent", "Crossbar")
            c.putheader("Content-Type", "application/octet-stream")
            c.putheader("Content-Length", str(size))
            c.endheaders()
            sent = 0
            while sent < size and not stop.is_set():
                n = min(len(chunk), size - sent)
                c.send(chunk[:n])
                sent += n
                add(n)
            if sent >= size:
                c.getresponse().read()
            c.close()
    return _run(work, SECONDS, progress, "upload")


def run(job):
    res = {"when": time.time()}

    def progress(what, mbps, frac):
        base = 0.15 if what == "download" else 0.55
        job.set(base + 0.4 * frac, f"{what.capitalize()}: {mbps:.1f} Mbps")
        res[f"{what}_live"] = mbps
        job.result = dict(res)
    job.set(0.02, "Finding the nearest server…")
    res.update(_trace())
    job.set(0.06, "Latency…")
    try:
        ping, jitter = latency()
    except OSError as e:
        raise util.friendly_net_error(f"https://{HOST}", e) from None
    res.update(ping=round(ping, 1), jitter=round(jitter, 1))
    job.result = dict(res)
    res["download"] = round(download(progress), 1)
    res["upload"] = round(upload(progress), 1)
    res.pop("download_live", None)
    res.pop("upload_live", None)
    job.result = res
    util.update_config(lambda c: c.__setitem__("speedtest_last", res))
    job.set(1.0, f"↓ {res['download']} Mbps · ↑ {res['upload']} Mbps · {res['ping']} ms")
    return res


def last():
    return util.load_config().get("speedtest_last")
