"""Leak tests (Settings › Network › VPN, and Apps › Torrents):

Torrent IP leak test: the torrent engine is given a made-up torrent (a random info hash) whose only
tracker is WhatIsMyIP.net's Torrent IP Checker. When the engine announces it, the checker records
the address the announce came from; Crossbar reads that page, compares the address with yours
without the VPN, then removes the torrent and clears the checker's record. Same idea as
https://www.whatismyip.net/tools/torrent-ip-checker/ — run from the XMB.

DNS leak test: bash.ws's test (as in github.com/macvk/dnsleaktest): look up a few made-up names
under a fresh test id, then ask bash.ws which DNS servers did the looking up. With split
tunneling on it runs as an app that uses the VPN (in the VPN's group), since that's the traffic
whose DNS matters.

Run directly (for the VPN group): python3 -m crossbar.leaktest dns  → JSON on stdout.
"""
import concurrent.futures
import html
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

CHECKER = "https://www.whatismyip.net/tools/torrent-ip-checker/"
BASH_WS = "https://bash.ws"
_IP = re.compile(r"^(\d{1,3}(\.\d{1,3}){3}|[0-9a-fA-F:]{3,39})$")


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Crossbar"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode(errors="replace")
    except (OSError, ValueError) as e:
        raise util.friendly_net_error(url, e) from None


def parse_checker(page):
    """Rows of the checker's table: [{"time", "ip", "agent"}]."""
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        cells = [html.unescape(re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
        cells = [re.sub(r"\s+", " ", c) for c in cells]
        ip = next((c for c in cells if _IP.match(c)), None)
        if ip:
            i = cells.index(ip)
            rows.append({"time": cells[i - 1] if i else "", "ip": ip, "agent": cells[i + 1] if i + 1 < len(cells) else ""})
    return rows


def _verdict(seen, isp_ip, vpn_on):
    if not seen:
        return "none"
    if isp_ip and isp_ip in seen:
        return "leak" if vpn_on else "exposed"
    return "protected" if vpn_on else "unknown"


def torrent_test(job):
    from . import torrent, vpn
    st = vpn.status()
    job.set(0.05, "Starting the torrent engine…")
    torrent.start()
    h = os.urandom(20).hex()
    magnet = ("magnet:?xt=urn:btih:" + h + "&dn=" + urllib.parse.quote_plus("Crossbar leak test")
              + "&tr=" + urllib.parse.quote(CHECKER, safe=""))
    save = os.path.join(util.HOME, ".cache", "crossbar", "leaktest")
    os.makedirs(save, exist_ok=True)
    job.set(0.12, "Adding a test torrent (nothing is downloaded)…")
    torrent.add(urls=[magnet], save_path=save)
    rows = []
    try:
        end = time.time() + 75
        while time.time() < end:
            job.check() if hasattr(job, "check") else None
            time.sleep(5)
            left = int(end - time.time())
            job.set(0.15 + 0.75 * (1 - left / 75), f"Waiting for the tracker to hear from the torrent engine… ({max(0, left)} s)")
            rows = parse_checker(_get(f"{CHECKER}index.php?hash={h}"))
            if rows:
                time.sleep(3)                                   # catch a second announce (IPv6) too
                rows = parse_checker(_get(f"{CHECKER}index.php?hash={h}"))
                break
    finally:
        try:
            torrent.action([h], "delete", files=True)
        except Exception:
            pass
        try:
            _get(f"{CHECKER}index.php?clear&hash={h}", timeout=10)
        except Exception:
            pass
    seen = sorted({r["ip"] for r in rows})
    verdict = _verdict(seen, st.get("isp_ip"), st.get("connected"))
    if verdict == "leak" and st.get("split") and not vpn.uses_vpn("torrents"):
        verdict = "not-chosen"                 # split tunneling on, torrents not one of the VPN apps: as set up
    res = {"kind": "torrent", "seen": rows, "ips": seen, "isp_ip": st.get("isp_ip"), "vpn": st.get("connected"),
           "bound": torrent.summary().get("interface") or "", "verdict": verdict}
    job.result = res
    job.set(1.0, {"leak": "LEAK: trackers see your real address", "protected": "Protected: trackers only see the VPN",
                  "exposed": "The VPN is off: trackers see your real address", "none": "The tracker didn't hear from the engine",
                  "unknown": "Trackers see " + ", ".join(seen),
                  "not-chosen": "Torrents aren't set to use the VPN, so trackers see your real address"}[res["verdict"]])
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
    if argv[0] == "sg":                                   # as an app that uses the VPN (split tunneling on)
        r = subprocess.run(argv, capture_output=True, text=True, timeout=120,
                           cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        try:
            raw = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise RuntimeError((r.stderr or "the DNS leak test failed").strip()[-200:]) from None
        if raw.get("error"):
            raise RuntimeError(raw["error"])
    else:
        raw = dns_raw()
    isp = st.get("isp_ip")
    if not st.get("connected"):
        verdict = "off"
    elif isp and raw.get("ip") == isp:
        verdict = "not-vpn"                                 # this traffic didn't even go through the VPN
    elif re.search(r"not leak", raw.get("conclusion") or "", re.I):
        verdict = "protected"
    else:
        verdict = "leak" if re.search(r"leak", raw.get("conclusion") or "", re.I) else "unknown"
    res = {"kind": "dns", **raw, "isp_ip": isp, "vpn": st.get("connected"), "split": st.get("split"), "verdict": verdict}
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
