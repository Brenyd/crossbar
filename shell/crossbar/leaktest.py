"""Leak tests (Settings › Network › VPN, and Apps › Torrents):

Torrent IP leak test: what peers see from the torrent engine, checked with nothing third-party in
between — a connection made exactly the way the engine makes them (bound to its address, in its VPN
group), and the public address the BitTorrent network itself reports to the engine (qBittorrent 5's
last_external_address_v4, from DHT nodes and peers). Either one matching your own address is a leak.

DNS leak test: bash.ws's test (as in github.com/macvk/dnsleaktest): look up a few made-up names
under a fresh test id, then ask bash.ws which DNS servers did the looking up. With split
tunneling on it runs as an app that uses the VPN (in the VPN's group), since that's the traffic
whose DNS matters.

Run directly (for the VPN group): python3 -m crossbar.leaktest dns  → JSON on stdout.
"""
import concurrent.futures
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

if __package__ in (None, ""):                         # python3 -m crossbar.leaktest from the shell dir
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "crossbar"

from . import util  # noqa: E402

BASH_WS = "https://bash.ws"
_IP = re.compile(r"^(\d{1,3}(\.\d{1,3}){3}|[0-9a-fA-F:]{3,39})$")


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Crossbar"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode(errors="replace")
    except (OSError, ValueError) as e:
        raise util.friendly_net_error(url, e) from None


ENGINE_PROBE = r"""
import json, socket, ssl, sys
out = {}
src = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None
try:
    raw = socket.create_connection(("1.1.1.1", 443), timeout=10, source_address=(src, 0) if src else None)
    with ssl.create_default_context().wrap_socket(raw, server_hostname="1.1.1.1") as t:
        t.sendall(b"GET /cdn-cgi/trace HTTP/1.1\r\nHost: 1.1.1.1\r\nConnection: close\r\n\r\n")
        data = b""
        while chunk := t.recv(4096):
            data += chunk
    kv = dict(l.split("=", 1) for l in data.decode(errors="replace").splitlines() if "=" in l)
    out["ip"], out["loc"] = kv.get("ip"), kv.get("loc")
except Exception as e:
    out["error"] = str(e)[:160]
print(json.dumps(out))
"""


def _engine_probe(src, wrap):
    """What the internet sees from the torrent engine's own network path: the same address it's bound
    to, and the same VPN group it runs in. No DNS involved (Cloudflare's 1.1.1.1 directly)."""
    from . import vpn
    argv = [sys.executable or "python3", "-c", ENGINE_PROBE, src or ""]
    if wrap:
        argv = vpn.wrap(argv, "torrents")
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=40, cwd="/")
        return json.loads((r.stdout.strip().splitlines() or ["{}"])[-1])
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        return {"error": str(e)[:160]}


def _own_ip():
    try:
        from . import speedtest
        return speedtest._trace().get("ip")
    except Exception:
        return None


def torrent_test(job):
    """Which address do peers and trackers see from the torrent engine? Checked two ways, with
    nothing third-party in between: a connection made exactly the way the engine makes them (its
    bound address, its VPN group), and the address the BitTorrent network itself reports back to
    the engine (DHT nodes and peers tell each client its public address)."""
    from . import torrent, vpn
    st = vpn.status()
    connected, split = st.get("connected"), st.get("split")
    vpn_only = bool(torrent.prefs_local().get("vpn_only"))
    uses = vpn.uses_vpn("torrents")
    job.set(0.05, "Starting the torrent engine…")
    torrent.start()
    job.set(0.15, "Finding your own address…")
    isp = _own_ip() if (not connected or split) else st.get("isp_ip")      # split on: Crossbar itself uses your own line
    if isp and (not connected or split):
        vpn._set(isp_ip=isp)
    summ = torrent.summary()
    addr = vpn._vpn_addr() if connected else None
    seen, notes = [], []
    if vpn_only and not connected:
        verdict = "blocked"
        notes.append("The torrent engine only uses the VPN, and the VPN is off: it has no connection at all.")
    else:
        job.set(0.3, "Connecting the way the torrent engine does…")
        src = addr if (vpn_only and connected) else None
        pr = _engine_probe(src, uses)
        if pr.get("ip"):
            seen.append({"ip": pr["ip"], "agent": "a connection from the torrent engine's address" + (f" ({pr.get('loc')})" if pr.get("loc") else ""), "time": ""})
        elif pr.get("error"):
            notes.append(f"Test connection failed: {pr['error']}")
        job.set(0.45, "Asking the BitTorrent network what it sees…")
        ext = None
        end = time.time() + 45
        while time.time() < end:
            try:
                info = torrent.api("GET", "/api/v2/transfer/info") or {}
            except Exception:
                info = {}
            if "last_external_address_v4" not in info:
                notes.append("This qBittorrent version doesn't report what peers see (needs qBittorrent 5).")
                break
            ext = info.get("last_external_address_v4") or None
            if ext:
                break
            left = int(end - time.time())
            job.set(0.45 + 0.45 * (1 - left / 45), f"Waiting for peers and DHT nodes to report your address… ({max(0, left)} s)")
            time.sleep(3)
        if ext:
            seen.append({"ip": ext, "agent": "what peers and DHT nodes report to the engine", "time": ""})
        elif not any("doesn't report" in n for n in notes):
            notes.append("The BitTorrent network didn't report an address yet (no peers or DHT nodes reached).")
        ips = {x["ip"] for x in seen}
        if not connected:
            verdict = "exposed" if ips else "none"
        elif split and not uses:
            verdict = "not-chosen"
        elif isp and isp in ips:
            verdict = "leak"
        elif ips:
            verdict = "protected"
        else:
            verdict = "none"
    res = {"kind": "torrent", "seen": seen, "ips": sorted({x["ip"] for x in seen}), "isp_ip": isp, "vpn": connected,
           "bound": summ.get("interface") or "", "vpn_only": vpn_only, "listen_port": summ.get("listen_port"),
           "forwarded_port": st.get("forwarded_port"), "notes": notes, "verdict": verdict}
    job.result = res
    job.set(1.0, {"leak": "LEAK: peers see your real address", "protected": "Protected: peers only see the VPN",
                  "exposed": "The VPN is off: peers see your real address", "none": "Couldn't tell: nothing came back",
                  "blocked": "Protected: no VPN, no torrent traffic",
                  "not-chosen": "Torrents aren't set to use the VPN, so peers see your real address"}[verdict])
    return res


# ---- DNS ------------------------------------------------------------------------------------------------
def dns_raw(probes=10):
    """bash.ws: which DNS servers resolve for this machine (and the address seen)."""
    tid = _get(f"{BASH_WS}/id").strip()
    if not re.fullmatch(r"[0-9a-zA-Z]{1,40}", tid):
        raise RuntimeError("The DNS leak test service didn't answer properly")

    def look(i):
        try:
            socket.getaddrinfo(f"{i}.{tid}.bash.ws", None)
        except OSError:
            pass                                   # the answer doesn't matter: the question does
    with concurrent.futures.ThreadPoolExecutor(5) as ex:
        list(ex.map(look, range(1, probes + 1)))
    data = json.loads(_get(f"{BASH_WS}/dnsleak/test/{tid}?json=2"))
    err = next((e for e in data if e.get("type") == "error"), None)
    if err:
        raise RuntimeError(err.get("text") or "The DNS leak test failed")
    ip = next((e for e in data if e.get("type") == "ip"), {})
    servers = [{"ip": e.get("ip"), "country": e.get("country_name", ""), "asn": e.get("asn", "")} for e in data if e.get("type") == "dns"]
    conclusion = next((e.get("ip") for e in data if e.get("type") == "conclusion"), "")
    return {"ip": ip.get("ip"), "ip_country": ip.get("country_name", ""), "ip_asn": ip.get("asn", ""), "servers": servers,
            "conclusion": conclusion}


def dns_test(job):
    from . import vpn
    st = vpn.status()
    job.set(0.1, "Looking up test names…")
    argv = vpn.wrap([sys.executable, "-m", "crossbar.leaktest", "dns"], "leaktest")
    if argv[1:2] == [vpn.VPNRUN]:                         # as an app that uses the VPN (split tunneling on)
        r = subprocess.run(argv, capture_output=True, text=True, timeout=120,
                           cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        try:
            raw = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise RuntimeError((r.stderr or "the DNS leak test didn't answer").strip()[-200:]) from None
        if raw.get("error"):
            raise RuntimeError(raw["error"])
    else:
        raw = dns_raw()
    isp = st.get("isp_ip")
    if st.get("connected") and st.get("split"):
        isp = _own_ip() or isp                  # Crossbar's own traffic is your own line with split tunneling on
    if not st.get("connected"):
        verdict = "off"
    elif isp and raw.get("ip") == isp:
        verdict = "not-vpn"                                 # this traffic didn't even go through the VPN
    elif re.search(r"not leak", raw.get("conclusion") or "", re.I):
        verdict = "protected"
    else:
        verdict = "leak" if re.search(r"leak", raw.get("conclusion") or "", re.I) else "unknown"
    res = {"kind": "dns", **raw, "isp_ip": isp, "vpn": st.get("connected"), "split": st.get("split"), "verdict": verdict,
           "vpn_dns": st.get("dns"), "dns_all": st.get("dns_all"), "resolved": st.get("resolved")}
    job.result = res
    job.set(1.0, {"off": "The VPN is off: this shows your normal DNS", "not-vpn": "This traffic isn't going through the VPN",
                  "protected": "Protected: DNS goes through the VPN", "leak": "DNS may be leaking",
                  "unknown": raw.get("conclusion") or "Done"}[verdict])
    return res


if __name__ == "__main__":
    if sys.argv[1:] == ["dns"]:
        try:
            print(json.dumps(dns_raw()))
        except Exception as e:
            print(json.dumps({"error": str(e)}))
