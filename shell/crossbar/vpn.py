"""VPN (Settings › Network › VPN): WireGuard or OpenVPN through NetworkManager, set up from the
XMB with a controller — no VPN company's app needed.

Providers with a sign-in wizard (Crossbar talks to their APIs, the way their own apps do):
  Private Internet Access  username + password → WireGuard (key registered per connection) or
                           OpenVPN; every region with its latency; port forwarding (kept alive
                           every 15 minutes), following pia-foss/manual-connections.
  Mullvad                  account number → WireGuard (one key, registered once); every city.
  NordVPN                  access token → WireGuard (NordLynx) or OpenVPN; every country.
Everything else (Proton VPN, Surfshark, Windscribe, IVPN, AirVPN, ExpressVPN, your own server):
the WireGuard (.conf) or OpenVPN (.ovpn) files from your account page, imported from a USB
stick / Downloads; each file is a location. Proton VPN's port forwarding (NAT-PMP) works too.

The connection is one NetworkManager connection, "cbvpn" (WireGuard's interface is also cbvpn,
OpenVPN's is cbtun), so the torrent client can bind to it, and its DNS is used exclusively while
it's up. Split tunneling (addresses and apps that skip the VPN) is policy routing set up by the
root helper (admin.py vpn-split). Passwords, tokens and keys stay in a 0600 file in the backend.
"""
import base64
import glob
import http.client
import json
import os
import sys
import re
import shutil
import socket
import ssl
import struct
import subprocess
import threading
import time
import urllib.parse
import urllib.request

from . import util

CONN = "cbvpn"                     # NetworkManager connection, and the WireGuard interface
TUN = "cbtun"                      # the OpenVPN interface
SECRETS = os.path.join(util.CONFIG_DIR, "vpn-secrets.json")
CONF_DIR = os.path.join(util.CONFIG_DIR, "vpn")
PIA_CA = os.path.join(os.path.dirname(__file__), "data", "pia-ca.rsa.4096.crt")
PIA_SERVERS = "https://serverlist.piaservers.net/vpninfo/servers/v6"
PIA_TOKEN_URL = "https://www.privateinternetaccess.com/api/client/v2/token"
MULLVAD_RELAYS = "https://api.mullvad.net/www/relays/wireguard/"
MULLVAD_WG = "https://api.mullvad.net/wg"
NORD_API = "https://api.nordvpn.com/v1"
ADMIN = "/usr/lib/crossbar/admin.py"

PROVIDERS = [
    {"id": "pia", "name": "Private Internet Access", "kind": "api", "protocols": ["wireguard", "openvpn"], "port_forward": "pia",
     "fields": [{"key": "username", "label": "Username (p1234567)"}, {"key": "password", "label": "Password", "secret": True}]},
    {"id": "mullvad", "name": "Mullvad", "kind": "api", "protocols": ["wireguard"], "port_forward": None,
     "fields": [{"key": "account", "label": "Account number (16 digits)"}]},
    {"id": "nord", "name": "NordVPN", "kind": "api", "protocols": ["wireguard", "openvpn"], "port_forward": None,
     "fields": [{"key": "token", "label": "Access token (Nord Account › NordVPN › Set up manually)", "secret": True}]},
    {"id": "proton", "name": "Proton VPN", "kind": "import", "protocols": ["wireguard", "openvpn"], "port_forward": "natpmp",
     "hint": "account.protonvpn.com › Downloads: WireGuard configuration (pick a P2P server and turn on NAT-PMP for port forwarding), "
             "or OpenVPN files plus your OpenVPN / IKEv2 username (add +pmp to it for port forwarding)"},
    {"id": "surfshark", "name": "Surfshark", "kind": "import", "protocols": ["wireguard", "openvpn"], "port_forward": None,
     "hint": "my.surfshark.com › VPN › Manual setup › Router: WireGuard (generate a key pair, then download a location), "
             "or OpenVPN files plus the service credentials shown there"},
    {"id": "windscribe", "name": "Windscribe", "kind": "import", "protocols": ["wireguard", "openvpn"], "port_forward": None,
     "hint": "windscribe.com › Config Generators: WireGuard or OpenVPN (OpenVPN asks for the generated credentials)"},
    {"id": "ivpn", "name": "IVPN", "kind": "import", "protocols": ["wireguard", "openvpn"], "port_forward": None,
     "hint": "ivpn.net › Account › WireGuard config generator, or the OpenVPN config files"},
    {"id": "airvpn", "name": "AirVPN", "kind": "import", "protocols": ["wireguard", "openvpn"], "port_forward": None,
     "hint": "airvpn.org › Client Area › Config Generator (WireGuard or OpenVPN). Ports forwarded there just work"},
    {"id": "expressvpn", "name": "ExpressVPN", "kind": "import", "protocols": ["openvpn"], "port_forward": None,
     "hint": "expressvpn.com › Set up other devices › Manual configuration › OpenVPN: the .ovpn files and the username/password shown"},
    {"id": "custom", "name": "Other / Your Own Server", "kind": "import", "protocols": ["wireguard", "openvpn"], "port_forward": None,
     "hint": "Any WireGuard .conf or OpenVPN .ovpn file"},
]
PROVIDER = {p["id"]: p for p in PROVIDERS}

_state = {"pf_port": None, "pf_error": None, "pf_thread": None, "pf_stop": None, "error": None, "connecting": False}
_listeners = []                    # called with the forwarded port (the torrent client)
_cache = {}


def on_port(fn):
    _listeners.append(fn)


def _publish():
    try:
        from .events import HUB
        HUB.publish({"type": "vpn"})
    except Exception:
        pass


# ---- WireGuard keys (X25519, RFC 7748), so no extra tools are needed --------------------------------
_P = 2 ** 255 - 19
_A24 = 121665


def _x25519(k, u):
    k = bytearray(k)
    k[0] &= 248
    k[31] &= 127
    k[31] |= 64
    k = int.from_bytes(k, "little")
    u = int.from_bytes(u, "little") & ((1 << 255) - 1)
    x1, x2, z2, x3, z3, swap = u, 1, 0, u, 1, 0
    for t in reversed(range(255)):
        kt = (k >> t) & 1
        swap ^= kt
        if swap:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = kt
        a, b = (x2 + z2) % _P, (x2 - z2) % _P
        aa, bb = a * a % _P, b * b % _P
        e = (aa - bb) % _P
        c, d = (x3 + z3) % _P, (x3 - z3) % _P
        da, cb = d * a % _P, c * b % _P
        x3, z3 = (da + cb) ** 2 % _P, x1 * (da - cb) ** 2 % _P
        x2, z2 = aa * bb % _P, e * (aa + _A24 * e) % _P
    if swap:
        x2, z2 = x3, z3
    return (x2 * pow(z2, _P - 2, _P) % _P).to_bytes(32, "little")


def wg_keypair():
    priv = bytearray(os.urandom(32))
    priv[0] &= 248
    priv[31] = (priv[31] & 127) | 64
    pub = _x25519(bytes(priv), (9).to_bytes(32, "little"))
    return base64.b64encode(bytes(priv)).decode(), base64.b64encode(pub).decode()


def wg_public(priv_b64):
    return base64.b64encode(_x25519(base64.b64decode(priv_b64), (9).to_bytes(32, "little"))).decode()


# ---- settings and secrets ----------------------------------------------------------------------------
def cfg():
    c = util.load_config().get("vpn")
    return c if isinstance(c, dict) else {}


def _set(**kw):
    util.update_config(lambda c: c.setdefault("vpn", {}).update(kw))


def _secrets():
    try:
        with open(SECRETS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_secrets(s):
    os.makedirs(os.path.dirname(SECRETS), exist_ok=True)
    fd = os.open(SECRETS + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(s, f)
    os.replace(SECRETS + ".tmp", SECRETS)


def _secret(provider):
    return _secrets().get(provider) or {}


def _http(url, data=None, headers=None, timeout=15, raw=False):
    body = urllib.parse.urlencode(data).encode() if isinstance(data, dict) else data
    req = urllib.request.Request(url, data=body, headers={"User-Agent": "Crossbar", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        err = util.NetError(f"{urllib.parse.urlparse(url).netloc} said {e.code}{': ' + detail.strip() if detail.strip() else ''}")
        err.code = e.code
        raise err from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise util.friendly_net_error(url, e) from None
    return out if raw else json.loads(out.decode())


# ---- NetworkManager -------------------------------------------------------------------------------------
def _nmcli(*args, timeout=60, check=True):
    if not util.which("nmcli"):
        raise RuntimeError("The VPN needs NetworkManager (nmcli)")
    r = subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        msg = (r.stderr or r.stdout).strip().replace("Error: ", "")
        raise RuntimeError(msg.splitlines()[-1] if msg else f"nmcli {args[0]} failed")
    return r.stdout


def nm_state():
    """'activated', 'activating', 'deactivating' or '' (not connected)."""
    try:
        out = _nmcli("-t", "-f", "NAME,STATE", "connection", "show", "--active", timeout=10, check=False)
    except (RuntimeError, subprocess.TimeoutExpired):
        return ""
    for ln in out.splitlines():
        name, _, state = ln.rpartition(":")
        if name == CONN:
            return state
    return ""


def _iface():
    return TUN if cfg().get("protocol") == "openvpn" else CONN


def _physical():
    """(device, gateway) of the normal internet connection (for split tunneling)."""
    out = _nmcli("-t", "-f", "DEVICE,TYPE,STATE", "device", timeout=10, check=False)
    for ln in out.splitlines():
        dev, typ, st = (ln.split(":") + ["", "", ""])[:3]
        if typ in ("ethernet", "wifi") and st == "connected":
            gw = _nmcli("-g", "IP4.GATEWAY", "device", "show", dev, timeout=10, check=False).strip()
            if gw:
                return dev, gw
    return None, None


def _import(path, kind):
    _nmcli("connection", "delete", CONN, check=False)
    _nmcli("connection", "import", "type", kind, "file", path)


# ---- Private Internet Access ---------------------------------------------------------------------------
class _PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS to a server by IP, checked against PIA's own CA and its name (like curl --connect-to)."""
    def __init__(self, ip, port, name):
        ctx = ssl.create_default_context(cafile=PIA_CA)
        ctx.check_hostname = False                     # PIA's certificates name the server in CN only
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT    # and its CA doesn't mark Basic Constraints critical
                                                       # (Python 3.13 refuses that by default; curl doesn't)
        super().__init__(name, port, context=ctx, timeout=10)
        self._ip, self._name = ip, name

    def connect(self):
        raw = _tunnel_socket((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self._name)
        cn = dict(x[0] for x in self.sock.getpeercert().get("subject", ()))
        if cn.get("commonName") != self._name:
            self.sock.close()
            raise ssl.SSLError(f"PIA server is {cn.get('commonName')}, expected {self._name}")


def _tunnel_socket(addr, timeout):
    """A TCP connection made through the tunnel the way `curl --interface <vpn>` does (PIA's own
    scripts): bound to the VPN's device as well as its address, when split tunneling is on."""
    src = _tunnel_source()
    if not src:
        return socket.create_connection(addr, timeout)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_BINDTODEVICE", 25), _iface().encode() + b"\0")
    except OSError:
        pass                                              # older kernels: the address alone routes it
    try:
        s.bind(src)
        s.connect(addr)
    except OSError:
        s.close()
        raise
    return s


def _pia_get(ip, port, name, path, params):
    c = _PinnedHTTPS(ip, port, name)
    try:
        c.request("GET", f"{path}?{urllib.parse.urlencode(params)}", headers={"Host": name})
        r = c.getresponse()
        return json.loads(r.read().decode())
    finally:
        c.close()


def pia_token(username=None, password=None):
    s = _secret("pia")
    username, password = username or s.get("username"), password or s.get("password")
    if not username or not password:
        raise RuntimeError("Sign in to Private Internet Access first")
    boundary = "----crossbar" + os.urandom(8).hex()
    body = "".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                   for k, v in (("username", username), ("password", password))) + f"--{boundary}--\r\n"
    try:
        r = _http(PIA_TOKEN_URL, data=body.encode(), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    except util.NetError as e:
        if getattr(e, "code", None) in (401, 403):
            raise RuntimeError("Private Internet Access didn't accept that username / password") from None
        raise
    if not r.get("token"):
        raise RuntimeError("Private Internet Access didn't accept that username / password")
    return r["token"]


def pia_servers():
    if _cache.get("pia") and time.time() - _cache["pia"][0] < 600:
        return _cache["pia"][1]
    raw = _http(PIA_SERVERS, raw=True).decode(errors="replace")
    data = json.loads(raw.split("\n", 1)[0])                 # first line is the JSON, then a signature
    _cache["pia"] = (time.time(), data)
    return data


def _latency(ip, port=443, timeout=1.5):
    t = time.perf_counter()
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return round((time.perf_counter() - t) * 1000)
    except OSError:
        return None


def _with_latency(regions, ip_of):
    out = list(regions)
    res = {}
    threads = []
    for r in out:
        ip = ip_of(r)
        if ip:
            t = threading.Thread(target=lambda r=r, ip=ip: res.__setitem__(r["id"], _latency(ip)), daemon=True)
            t.start()
            threads.append(t)
    for t in threads:
        t.join(2.5)
    for r in out:
        r["latency"] = res.get(r["id"])
    out.sort(key=lambda r: (r["latency"] is None, r["latency"] or 0, r["name"]))
    return out


def pia_regions():
    data = pia_servers()
    regs = [{"id": r["id"], "name": r["name"], "country": r.get("country", ""), "port_forward": bool(r.get("port_forward")),
             "geo": bool(r.get("geo")), "_meta": ((r.get("servers") or {}).get("meta") or [{}])[0].get("ip")}
            for r in data.get("regions", []) if not r.get("offline")]
    out = _with_latency(regs, lambda r: r["_meta"])
    for r in out:
        r.pop("_meta", None)
    return out


def _pia_region(rid):
    r = next((x for x in pia_servers().get("regions", []) if x["id"] == rid), None)
    if not r:
        raise RuntimeError("That PIA region isn't available any more: pick another")
    return r


PIA_OVPN = """client
dev {tun}
dev-type tun
proto {proto}
remote {ip} {port}
resolv-retry infinite
nobind
persist-key
persist-tun
cipher aes-256-cbc
data-ciphers AES-256-GCM:AES-256-CBC
auth sha256
tls-client
remote-cert-tls server
auth-user-pass
verb 1
reneg-sec 0
disable-occ
<ca>
{ca}</ca>
"""


def _pia_build(job, protocol, rid):
    token = pia_token()
    region = _pia_region(rid)
    servers = region.get("servers") or {}
    if protocol == "wireguard":
        srv = (servers.get("wg") or [None])[0]
        if not srv:
            raise RuntimeError("That region has no WireGuard server right now")
        priv, pub = wg_keypair()
        job.set(0.3, f"Registering a key with {region['name']}…")
        j = _pia_get(srv["ip"], 1337, srv["cn"], "/addKey", {"pt": token, "pubkey": pub})
        if j.get("status") != "OK":
            raise RuntimeError(f"PIA didn't accept the key: {j.get('message') or j.get('status')}")
        conf = (f"[Interface]\nAddress = {j['peer_ip']}\nPrivateKey = {priv}\nDNS = {j['dns_servers'][0]}\n\n"
                f"[Peer]\nPublicKey = {j['server_key']}\nAllowedIPs = 0.0.0.0/0, ::/0\n"
                f"Endpoint = {srv['ip']}:{j['server_port']}\nPersistentKeepalive = 25\n")
        # port forwarding talks to the server's address inside the tunnel (server_vip), as PIA's
        # manual-connections scripts do; its public address refuses port 19999
        pf = {"kind": "pia", "gateway": j.get("server_vip") or srv["ip"], "server_ip": j.get("server_ip") or srv["ip"],
              "hostname": srv["cn"], "region": rid, "region_name": region.get("name"), "region_pf": bool(region.get("port_forward"))}
        _state["pia_token"] = (time.time(), token)
        return conf, None, pf
    srv = (servers.get("ovpnudp") or [None])[0]
    if not srv:
        raise RuntimeError("That region has no OpenVPN server right now")
    with open(PIA_CA) as f:
        ca = f.read()
    conf = PIA_OVPN.format(tun=TUN, proto="udp", ip=srv["ip"], port=8080, ca=ca if ca.endswith("\n") else ca + "\n")
    pf = {"kind": "pia", "gateway": None, "server_ip": srv["ip"], "hostname": srv["cn"], "region": rid,   # gateway: the tunnel's, once up
          "region_name": region.get("name"), "region_pf": bool(region.get("port_forward"))}
    _state["pia_token"] = (time.time(), token)
    return conf, (token[:62], token[62:]), pf


# ---- Mullvad -------------------------------------------------------------------------------------------
def mullvad_relays():
    if _cache.get("mullvad") and time.time() - _cache["mullvad"][0] < 600:
        return _cache["mullvad"][1]
    data = [r for r in _http(MULLVAD_RELAYS) if r.get("active")]
    _cache["mullvad"] = (time.time(), data)
    return data


def mullvad_regions():
    cities = {}
    for r in mullvad_relays():
        cid = f"{r.get('country_code')}-{r.get('city_code')}"
        cities.setdefault(cid, {"id": cid, "name": f"{r.get('city_name')}, {r.get('country_name')}", "country": r.get("country_name", ""),
                                "port_forward": False, "_ip": r.get("ipv4_addr_in")})
    return [{k: v for k, v in r.items() if k != "_ip"} for r in _with_latency(list(cities.values()), lambda r: r["_ip"])]


def _mullvad_build(job, protocol, rid):
    s = _secrets()
    m = s.get("mullvad") or {}
    if not m.get("account"):
        raise RuntimeError("Sign in to Mullvad first")
    if not m.get("private_key"):                             # one key per console (Mullvad allows 5 devices)
        priv, pub = wg_keypair()
        job.set(0.25, "Registering this console with Mullvad…")
        addr = _http(MULLVAD_WG, data={"account": m["account"], "pubkey": pub}, raw=True).decode().strip()
        if not re.match(r"^\d+\.\d+\.\d+\.\d+/\d+", addr):
            raise RuntimeError(f"Mullvad: {addr[:160]}")
        m.update(private_key=priv, address=addr)
        s["mullvad"] = m
        _save_secrets(s)
    relays = [r for r in mullvad_relays() if f"{r.get('country_code')}-{r.get('city_code')}" == rid]
    if not relays:
        raise RuntimeError("No Mullvad server in that city right now")
    best = min(relays, key=lambda r: (_latency(r["ipv4_addr_in"]) or 9999))
    conf = (f"[Interface]\nAddress = {m['address']}\nPrivateKey = {m['private_key']}\nDNS = 10.64.0.1\n\n"
            f"[Peer]\nPublicKey = {best['pubkey']}\nAllowedIPs = 0.0.0.0/0, ::/0\nEndpoint = {best['ipv4_addr_in']}:51820\n")
    return conf, None, None


# ---- NordVPN ---------------------------------------------------------------------------------------------
def _nord_creds(token=None):
    token = token or _secret("nord").get("token")
    if not token:
        raise RuntimeError("Sign in to NordVPN first")
    auth = base64.b64encode(f"token:{token}".encode()).decode()
    try:
        return _http(f"{NORD_API}/users/services/credentials", headers={"Authorization": f"Basic {auth}"})
    except util.NetError as e:
        if getattr(e, "code", None) in (401, 403):
            raise RuntimeError("NordVPN didn't accept that access token") from None
        raise


def nord_regions():
    if not _cache.get("nord"):
        _cache["nord"] = sorted(_http(f"{NORD_API}/servers/countries"), key=lambda c: c["name"])
    return [{"id": "auto", "name": "Fastest Server", "country": "", "port_forward": False, "latency": None}] + \
           [{"id": str(c["id"]), "name": c["name"], "country": c.get("code", ""), "port_forward": False, "latency": None}
            for c in _cache["nord"]]


def _nord_build(job, protocol, rid):
    creds = _nord_creds()
    tech = "wireguard_udp" if protocol == "wireguard" else "openvpn_udp"
    q = {"filters[servers_technologies][identifier]": tech, "limit": "5"}
    if rid and rid != "auto":
        q["filters[country_id]"] = rid
    servers = _http(f"{NORD_API}/servers/recommendations?{urllib.parse.urlencode(q)}")
    if not servers:
        raise RuntimeError("No NordVPN server for that country right now")
    srv = servers[0]
    if protocol == "wireguard":
        meta = next((t for t in srv.get("technologies", []) if t.get("identifier") == "wireguard_udp"), {})
        key = next((m["value"] for m in meta.get("metadata", []) if m.get("name") == "public_key"), None)
        if not key or not creds.get("nordlynx_private_key"):
            raise RuntimeError("NordVPN didn't send what WireGuard needs: try OpenVPN")
        conf = (f"[Interface]\nAddress = 10.5.0.2/32\nPrivateKey = {creds['nordlynx_private_key']}\nDNS = 103.86.96.100, 103.86.99.100\n\n"
                f"[Peer]\nPublicKey = {key}\nAllowedIPs = 0.0.0.0/0, ::/0\nEndpoint = {srv['station']}:51820\nPersistentKeepalive = 25\n")
        return conf, None, None
    ovpn = _http(f"https://downloads.nordcdn.com/configs/files/ovpn_udp/servers/{srv['hostname']}.udp.ovpn", raw=True).decode()
    return ovpn, (creds["username"], creds["password"]), None


# ---- imported files ------------------------------------------------------------------------------------
def _import_dir(provider):
    return os.path.join(CONF_DIR, provider)


def imported(provider):
    out = []
    for p in sorted(glob.glob(os.path.join(_import_dir(provider), "*"))):
        ext = os.path.splitext(p)[1].lower()
        if ext in (".conf", ".ovpn"):
            name = os.path.splitext(os.path.basename(p))[0]
            out.append({"id": os.path.basename(p), "name": re.sub(r"[_-]+", " ", name).strip(), "country": "",
                        "protocol": "wireguard" if ext == ".conf" else "openvpn", "port_forward": False, "latency": None})
    return out


def import_files(provider, path):
    """Copy WireGuard / OpenVPN files (one file, a folder of them, or a .zip) as this provider's locations."""
    from . import media
    if provider not in PROVIDER or PROVIDER[provider]["kind"] != "import":
        raise ValueError("provider")
    path = os.path.realpath(path)
    if not media.allowed(path):
        raise PermissionError("That folder isn't allowed")
    dest = _import_dir(provider)
    os.makedirs(dest, exist_ok=True)
    found = []

    def take(name, data):
        base = os.path.basename(name)
        if os.path.splitext(base)[1].lower() in (".conf", ".ovpn") and len(data) < 512 * 1024:
            safe = re.sub(r"[^\w.\- ]+", "_", base)[:80]
            with open(os.path.join(dest, safe), "wb") as f:
                f.write(data)
            os.chmod(os.path.join(dest, safe), 0o600)
            found.append(safe)
    if os.path.isdir(path):
        for p in sorted(glob.glob(os.path.join(path, "*"))):
            if os.path.isfile(p):
                with open(p, "rb") as f:
                    take(p, f.read())
    elif path.lower().endswith(".zip"):
        import zipfile
        with zipfile.ZipFile(path) as z:
            for i in z.infolist()[:2000]:
                if not i.is_dir():
                    take(i.filename, z.read(i))
    else:
        with open(path, "rb") as f:
            take(path, f.read())
    if not found:
        raise RuntimeError("No WireGuard (.conf) or OpenVPN (.ovpn) files there")
    return {"imported": len(found), "locations": imported(provider)}


def _import_build(job, provider, protocol, rid):
    p = os.path.join(_import_dir(provider), os.path.basename(rid or ""))
    if not rid or not os.path.isfile(p):
        raise RuntimeError("Pick a location first")
    with open(p, errors="replace") as f:
        text = f.read()
    if p.lower().endswith(".conf"):
        return text, None, ({"kind": "natpmp", "gateway": "10.2.0.1"} if provider == "proton" else None)
    s = _secret(provider)
    creds = (s.get("username", ""), s.get("password", "")) if re.search(r"^\s*auth-user-pass", text, re.M) else None
    if creds and not creds[0]:
        raise RuntimeError("These OpenVPN files need a username and password: VPN › Account")
    return text, creds, ({"kind": "natpmp", "gateway": "10.2.0.1"} if provider == "proton" and creds and creds[0].endswith("+pmp") else None)


def _ovpn_for_nm(text):
    """Our device name, credentials asked for by NetworkManager (not a file), no scripts."""
    out = []
    for ln in text.splitlines():
        w = ln.strip().split()
        key = w[0].lower() if w else ""
        if key in ("dev", "dev-type", "up", "down", "script-security", "route-up", "auth-user-pass", "update-resolv-conf"):
            continue
        out.append(ln)
    return "\n".join([f"dev {TUN}", "dev-type tun", "auth-user-pass"] + out) + "\n"


# ---- the public face ----------------------------------------------------------------------------------
def providers():
    return [{k: v for k, v in p.items()} for p in PROVIDERS]


def regions(provider=None):
    provider = provider or cfg().get("provider")
    if provider == "pia":
        return pia_regions()
    if provider == "mullvad":
        return mullvad_regions()
    if provider == "nord":
        return nord_regions()
    if provider in PROVIDER:
        return imported(provider)
    raise RuntimeError("Set up a VPN first")


def setup(provider, protocol=None, fields=None):
    """Save the provider and sign-in (checked where the provider lets us)."""
    if provider not in PROVIDER:
        raise ValueError("provider")
    p = PROVIDER[provider]
    protocol = protocol if protocol in p["protocols"] else p["protocols"][0]
    fields = {k: str(v).strip() for k, v in (fields or {}).items() if isinstance(v, str)}
    s = _secrets()
    cur = dict(s.get(provider) or {})
    if provider == "pia":
        if not fields.get("username") or not fields.get("password"):
            raise ValueError("Enter your PIA username and password")
        pia_token(fields["username"], fields["password"])
        cur.update(username=fields["username"], password=fields["password"])
    elif provider == "mullvad":
        acct = re.sub(r"\D", "", fields.get("account", ""))
        if len(acct) != 16:
            raise ValueError("A Mullvad account number has 16 digits")
        if acct != cur.get("account"):
            cur = {"account": acct}                         # new account: register a new key on connect
    elif provider == "nord":
        if not fields.get("token"):
            raise ValueError("Paste your NordVPN access token")
        _nord_creds(fields["token"])
        cur.update(token=fields["token"])
    else:
        if "username" in fields:
            cur.update(username=fields["username"], password=fields.get("password", ""))
    s[provider] = cur
    _save_secrets(s)
    old = cfg()
    _set(provider=provider, protocol=protocol, region=old.get("region") if old.get("provider") == provider else None)
    return status()


def set_options(**kw):
    allowed = {"region", "protocol", "port_forward", "autoconnect", "split", "vpn_sites", "vpn_apps", "dns_all"}
    kw = {k: v for k, v in kw.items() if k in allowed}
    if "protocol" in kw and kw["protocol"] not in PROVIDER.get(cfg().get("provider"), {}).get("protocols", []):
        raise ValueError("That provider doesn't offer that protocol")
    if "split" in kw:
        kw["split"] = bool(kw["split"])
    if "vpn_sites" in kw:
        kw["vpn_sites"] = [clean_target(x) for x in kw["vpn_sites"]][:64]
    if "vpn_apps" in kw:
        kw["vpn_apps"] = [a for a in kw["vpn_apps"] if isinstance(a, str) and re.fullmatch(r"[\w:.\-]{1,120}", a)][:64]
    was_split = split_on()
    if "dns_all" in kw:
        kw["dns_all"] = None if kw["dns_all"] in (None, "auto") else bool(kw["dns_all"])
    if "port_forward" in kw:
        kw["port_forward"] = bool(kw["port_forward"])
    _set(**kw)
    if "port_forward" in kw:
        if not kw["port_forward"]:
            stop_port_forward()
            _state["pf_error"] = None
        elif nm_state() == "activated":
            resume_port_forward()                  # no reconnect needed
    if nm_state() == "activated":
        if ("split" in kw and kw["split"] != was_split) or "dns_all" in kw:
            _state["error"] = "Reconnect the VPN for this change"
        elif split_on() and ({"vpn_sites", "vpn_apps"} & set(kw)):
            apply_split()
    return status()


def clean_target(x):
    """An address, network (CIDR) or site name (for split tunneling)."""
    x = str(x).strip()
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}(/\d{1,2})?", x) or re.fullmatch(r"[0-9a-fA-F:]+(/\d{1,3})?", x) and ":" in x:
        return x
    if re.fullmatch(r"(?=.{1,253}$)([A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,63}", x):
        return x.lower()
    raise ValueError(f"“{x}” isn't an address, network or site name")


def status():
    c = cfg()
    p = PROVIDER.get(c.get("provider"))
    st = nm_state()
    reg = None
    if p and c.get("region"):
        reg = c.get("region_name") or c["region"]
    return {"available": bool(util.which("nmcli")), "configured": bool(p), "provider": c.get("provider"),
            "provider_name": p["name"] if p else None, "kind": p["kind"] if p else None,
            "protocol": c.get("protocol"), "protocols": p["protocols"] if p else [],
            "region": c.get("region"), "region_name": reg,
            "connected": st == "activated", "connecting": st == "activating" or _state["connecting"],
            "iface": _iface() if st == "activated" else None, "error": _state["error"],
            "port_forward": bool(c.get("port_forward")), "pf_supported": bool(p and p.get("port_forward")),
            "forwarded_port": _state["pf_port"] if st == "activated" else None, "pf_error": _state["pf_error"],
            "pf_state": _state.get("pf_msg") if st == "activated" else None, "pf_since": _state.get("pf_since"),
            "pf_region_ok": _pf_region_ok(c), "dns": vpn_dns() if st == "activated" else None,
            "dns_all": dns_all(), "dns_all_setting": c.get("dns_all"), "resolved": uses_resolved(),
            "autoconnect": bool(c.get("autoconnect")), "split": split_on(), "vpn_sites": c.get("vpn_sites") or [],
            "vpn_apps": c.get("vpn_apps") or [], "isp_ip": c.get("isp_ip"), "signed_in": bool(p and (_secret(p["id"]) or p["kind"] == "import")),
            "username": _secret(p["id"]).get("username", "") if p else ""}


def connect(job=None):
    class _J:
        def set(self, *a):
            pass
    job = job or _J()
    c = cfg()
    provider, protocol, rid = c.get("provider"), c.get("protocol"), c.get("region")
    if provider not in PROVIDER:
        raise RuntimeError("Set up a VPN first (VPN › Set Up)")
    if not rid:
        raise RuntimeError("Pick a location first (VPN › Location)")
    _state.update(connecting=True, error=None)
    _publish()
    try:
        if nm_state() != "activated":
            _remember_isp_ip()
        stop_port_forward()
        job.set(0.1, "Getting the connection details…")
        if provider == "pia":
            conf, creds, pf = _pia_build(job, protocol, rid)
        elif provider == "mullvad":
            conf, creds, pf = _mullvad_build(job, protocol, rid)
        elif provider == "nord":
            conf, creds, pf = _nord_build(job, protocol, rid)
        else:
            conf, creds, pf = _import_build(job, provider, protocol, rid)
            protocol = "wireguard" if rid.lower().endswith(".conf") else "openvpn"
            _set(protocol=protocol)
        work = os.path.join(CONF_DIR, ".work")
        os.makedirs(work, mode=0o700, exist_ok=True)
        job.set(0.5, "Setting up the connection…")
        if protocol == "wireguard":
            path = os.path.join(work, f"{CONN}.conf")             # NetworkManager names it after the file
            _write_private(path, conf)
            _import(path, "wireguard")
        else:
            path = os.path.join(work, f"{CONN}.ovpn")
            _write_private(path, _ovpn_for_nm(conf))
            _import(path, "openvpn")
            if creds:
                _nmcli("connection", "modify", CONN, "+vpn.data", "password-flags=0", "vpn.user-name", creds[0],
                       "vpn.secrets", f"password={creds[1]}")
        os.remove(path)
        dns = _conf_dns(conf) or DEFAULT_DNS.get(provider) or FALLBACK_DNS
        _state["dns"] = dns
        _set(dns=dns, pf_params=pf or None, endpoints=_conf_endpoints(conf))
        if split_on():
            # Split tunneling: the VPN is only a road some traffic takes (chosen apps and sites),
            # not the default route. Its DNS server is used by the VPN apps (see apply_split), and,
            # with "DNS through the VPN for everything", by the whole system: a fixed server, reached
            # through the tunnel (apply_split routes it there), so no lookup goes to your provider.
            everyone = dns_all()
            _nmcli("connection", "modify", CONN, "connection.autoconnect", "no", "ipv4.never-default", "yes",
                   "ipv6.never-default", "yes", "ipv4.ignore-auto-dns", "yes", "ipv6.ignore-auto-dns", "yes",
                   "ipv4.dns", dns if everyone else "", "ipv4.dns-priority", "-50" if everyone else "100",
                   "ipv6.dns", "", "ipv6.method", "disabled" if protocol == "openvpn" else "ignore", check=False)
            if protocol == "wireguard":         # WireGuard's own (encrypted) packets carry this mark: never re-routed
                _nmcli("connection", "modify", CONN, "wireguard.fwmark", str(WG_FWMARK), check=False)
        else:
            _nmcli("connection", "modify", CONN, "connection.autoconnect", "no", "ipv4.dns-priority", "-50",
                   "ipv6.dns-priority", "-50", check=False)
        job.set(0.7, "Connecting…")
        _nmcli("connection", "up", CONN, timeout=90)
        for _ in range(30):
            if nm_state() == "activated":
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("The VPN didn't come up")
        _up_cache.clear()
        if split_on():
            try:
                ensure_split(force=True)
            except RuntimeError as e:
                _state["error"] = f"Split tunneling: {e}"
        else:
            clear_split()
        try:                                     # the torrent client, if it only uses the VPN: bind to the new address
            from . import torrent
            torrent._apply_vpn_binding(rebind=True)
        except Exception:
            pass
        if c.get("port_forward") and pf:
            start_port_forward(pf)
        job.set(1.0, "Connected")
        return status()
    except Exception as e:
        _state["error"] = str(e)
        raise
    finally:
        _state["connecting"] = False
        _publish()


def disconnect():
    stop_port_forward()
    clear_split()
    _split_applied.clear()
    _nmcli("connection", "down", CONN, check=False)
    _state["error"] = None
    _publish()
    return status()


def forget(provider=None):
    """Sign out of a provider (keys and passwords deleted; imported files too)."""
    provider = provider or cfg().get("provider")
    if nm_state():
        disconnect()
    _nmcli("connection", "delete", CONN, check=False)
    s = _secrets()
    s.pop(provider, None)
    _save_secrets(s)
    shutil.rmtree(_import_dir(provider), ignore_errors=True) if provider in PROVIDER and PROVIDER[provider]["kind"] == "import" else None
    if cfg().get("provider") == provider:
        util.update_config(lambda c: c.__setitem__("vpn", {}))
    return status()


def _write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


def public_ip():
    from . import speedtest
    t = speedtest._trace()
    if t.get("ip") and nm_state() != "activated":
        _set(isp_ip=t["ip"])
    return t


# ---- port forwarding ------------------------------------------------------------------------------------
# PIA (pia-foss/manual-connections): getSignature once (its payload carries the port and lasts about two
# months, so it's kept and reused: the same port after a restart), then bindPort every 15 minutes. Both
# go to the server's address inside the tunnel. Proton: NAT-PMP to 10.2.0.1 every 45 s. Failures retry
# (the tunnel may still be settling, PIA may be busy) instead of giving up; the reason is shown.
PF_RETRY = (10, 20, 30, 60, 120, 300)


def _pf_region_ok(c=None):
    """None when unknown; False for a PIA location without port forwarding (PIA's US ones)."""
    c = c or cfg()
    if c.get("provider") != "pia" or not c.get("region") or not _cache.get("pia"):
        return None                                  # (only from the list already fetched: never waits on the network)
    r = next((x for x in _cache["pia"][1].get("regions", []) if x["id"] == c["region"]), None)
    return bool(r.get("port_forward")) if r else None


def _tunnel_gateway():
    """OpenVPN's end of the tunnel (PIA's port forwarding talks to it)."""
    out = _nmcli("-g", "IP4.GATEWAY", "device", "show", TUN, timeout=10, check=False).strip()
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", out or ""):
        return out
    try:
        route = subprocess.run(["ip", "-4", "route", "show", "dev", TUN], capture_output=True, text=True, timeout=10).stdout
        route += subprocess.run(["ip", "-4", "route", "show", "table", "all", "dev", TUN], capture_output=True, text=True, timeout=10).stdout
        addr = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", TUN], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"via (\d+\.\d+\.\d+\.\d+)", route) or re.search(r"peer (\d+\.\d+\.\d+\.\d+)", addr)
    if m:
        return m.group(1)
    m = re.search(r"inet (\d+)\.(\d+)\.(\d+)\.\d+/(\d+)", addr)      # a subnet: the server is .1 (PIA)
    if m and int(m.group(4)) <= 30:
        return f"{m.group(1)}.{m.group(2)}.{m.group(3)}.1"
    return None


def _set_port(port, err=None, msg=None):
    changed = port != _state["pf_port"]
    _state.update(pf_port=port, pf_error=err, pf_msg=msg if msg is not None else (None if port else _state.get("pf_msg")))
    if port and changed:
        _state["pf_since"] = time.time()
    if changed or err:
        for fn in list(_listeners) if changed else []:
            try:
                fn(port)
            except Exception as e:
                print(f"vpn: port listener: {e}", flush=True)
        _publish()
    if changed and port:
        _open_port(port)


def _open_port(port):
    """Let the forwarded port in through this computer's own firewall (ufw / firewalld), on the VPN only."""
    try:
        _admin("vpn-port", {"port": int(port), "dev": _iface()})
    except Exception as e:
        print(f"vpn: firewall: {e}", flush=True)


def _pia_fresh_token():
    t = _state.get("pia_token")
    if t and time.time() - t[0] < 6 * 3600:            # PIA tokens last a day
        return t[1]
    tok = pia_token()
    _state["pia_token"] = (time.time(), tok)
    return tok


def _pia_signature(pf, stop):
    """A saved signature for this server that hasn't expired, else a new one."""
    s = _secrets()
    saved = (s.get("pia_pf") or {})
    if saved.get("hostname") == pf["hostname"] and saved.get("expires", 0) > time.time() + 3600:
        return saved
    _state["pf_msg"] = "Asking PIA for a port…"
    _publish()
    sig, errs = None, []
    for gw in _pf_addresses(pf):
        try:
            sig = _pia_get(gw, 19999, pf["hostname"], "/getSignature", {"token": _pia_fresh_token()})
            pf["api"] = gw                                  # bindPort goes to the same place
            break
        except (ssl.SSLError, OSError) as e:
            errs.append(f"{gw}: {e.__class__.__name__.replace('Error', '')} {getattr(e, 'strerror', '') or e}".strip())
    if sig is None:
        raise RuntimeError("couldn't reach PIA's port forwarding through the VPN (" + "; ".join(errs) + ")")
    if sig.get("status") != "OK":
        _state.pop("pia_token", None)                    # an old token is the usual reason: get a new one next time
        raise RuntimeError(sig.get("message") or "PIA refused (is this a location with port forwarding?)")
    payload = json.loads(base64.b64decode(sig["payload"]))
    exp = payload.get("expires_at") or ""
    try:
        import datetime
        expires = datetime.datetime.fromisoformat(exp.replace("Z", "+00:00")[:32]).timestamp() if exp else time.time() + 86400 * 30
    except ValueError:
        expires = time.time() + 86400 * 30
    saved = {"hostname": pf["hostname"], "payload": sig["payload"], "signature": sig["signature"], "port": int(payload["port"]),
             "expires": expires, "api": pf.get("api")}
    s = _secrets()
    s["pia_pf"] = saved
    _save_secrets(s)
    return saved


def _pf_addresses(pf):
    """Where PIA's port forwarding API may answer, through the tunnel: the server's address inside the
    tunnel (server_vip, as pia-foss/manual-connections uses), then its public address (which some
    servers answer on instead), then OpenVPN's gateway."""
    out = []
    if not pf.get("server_ip") and pf.get("hostname"):      # saved by an older version: find it by the server's name
        try:
            for r in pia_servers().get("regions", []):
                for kind in ("wg", "ovpnudp", "ovpntcp"):
                    for srv in (r.get("servers") or {}).get(kind) or []:
                        if srv.get("cn") == pf["hostname"]:
                            pf["server_ip"] = pf.get("server_ip") or srv.get("ip")
        except Exception:
            pass
    for a in (pf.get("api"), pf.get("gateway"), pf.get("server_ip"), _tunnel_gateway() if cfg().get("protocol") == "openvpn" else None):
        if a and a not in out:
            out.append(a)
    return out


def _pia_pf_loop(pf, stop):
    fails = 0
    while not stop.is_set():
        try:
            if not pf.get("gateway") and not pf.get("server_ip"):
                pf = {**pf, "gateway": _tunnel_gateway()}
                if not pf["gateway"]:
                    raise RuntimeError("couldn't find the VPN's gateway yet")
            sig = _pia_signature(pf, stop)
            api_at = pf.get("api") or sig.get("api") or pf["gateway"]
            r = _pia_get(api_at, 19999, pf["hostname"], "/bindPort", {"payload": sig["payload"], "signature": sig["signature"]})
            if r.get("status") != "OK":
                msg = r.get("message") or "bindPort failed"
                if re.search(r"expired|invalid|signature", msg, re.I):    # start over with a new signature
                    s = _secrets()
                    s.pop("pia_pf", None)
                    _save_secrets(s)
                raise RuntimeError(msg)
            fails = 0
            _set_port(sig["port"], msg=f"Port {sig['port']} · kept open every 15 minutes")
            stop.wait(900)                                   # every 15 minutes, as PIA asks
        except Exception as e:
            wait = PF_RETRY[min(fails, len(PF_RETRY) - 1)]
            fails += 1
            _set_port(None, f"Port forwarding: {e} · trying again in {wait} s", msg="Retrying…")
            print(f"vpn: port forwarding: {e}", flush=True)
            stop.wait(wait)


def natpmp_map(gateway, proto, lifetime=60, timeout=3.0):
    """One NAT-PMP mapping request (RFC 6886): returns the public port."""
    op = 1 if proto == "udp" else 2
    pkt = struct.pack("!BBHHHI", 0, op, 0, 1, 0, lifetime)       # internal port 1, as Proton documents
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        src = _tunnel_source()
        if src:
            s.bind(src)
        s.sendto(pkt, (gateway, 5351))
        data, _ = s.recvfrom(64)
    ver, rop, code, _epoch, _inner, public, _life = struct.unpack("!BBHIHHI", data[:16])
    if rop != 128 + op or code:
        raise RuntimeError(f"NAT-PMP error {code}")
    return public


def _natpmp_loop(pf, stop):
    fails = 0
    while not stop.is_set():
        try:
            natpmp_map(pf["gateway"], "udp")
            port = natpmp_map(pf["gateway"], "tcp")
            fails = 0
            _set_port(port, msg=f"Port {port} · renewed every 45 s")
            stop.wait(45)
        except (OSError, RuntimeError) as e:
            wait = PF_RETRY[min(fails, len(PF_RETRY) - 1)]
            fails += 1
            _set_port(None, f"Port forwarding: {e} (is this a P2P server with NAT-PMP on?) · trying again in {wait} s", msg="Retrying…")
            stop.wait(wait)


def start_port_forward(pf):
    stop_port_forward()
    if pf.get("kind") == "pia" and pf.get("region_pf") is False:
        _state.update(pf_error="This location doesn't offer port forwarding (PIA's US locations don't): "
                               "pick one marked PORT FWD in Location", pf_msg=None)
        _publish()
        return
    stop = threading.Event()
    fn = _pia_pf_loop if pf["kind"] == "pia" else _natpmp_loop
    t = threading.Thread(target=fn, args=(pf, stop), daemon=True, name="vpn-pf")
    _state.update(pf_thread=t, pf_stop=stop, pf_error=None, pf_msg="Starting…")
    t.start()


def resume_port_forward():
    """Port forwarding switched on while connected, or Crossbar restarted with the VPN up."""
    pf = cfg().get("pf_params")
    if not pf or nm_state() != "activated":
        _state.update(pf_error="Reconnect the VPN once so port forwarding can start" if not pf else None)
        _publish()
        return False
    if pf.get("kind") == "pia" and pf.get("region_pf") is None:
        pf = {**pf, "region_pf": _pf_region_ok()}
    start_port_forward(pf)
    return True


def stop_port_forward():
    if _state.get("pf_stop"):
        _state["pf_stop"].set()
    _state.update(pf_thread=None, pf_stop=None, pf_msg=None)
    if _state["pf_port"] is not None:
        _set_port(None)


def pf_check():
    """Port forwarding, step by step (VPN › Port Forwarding › Check)."""
    c, out = cfg(), {}
    out["connected"] = nm_state() == "activated"
    out["on"] = bool(c.get("port_forward"))
    out["provider"] = c.get("provider")
    out["region_ok"] = _pf_region_ok(c)
    pf = c.get("pf_params") or {}
    out["gateway"] = pf.get("gateway") or (_tunnel_gateway() if out["connected"] and c.get("protocol") == "openvpn" else None)
    out["source"] = (_tunnel_source() or [None])[0]
    out["port"], out["error"], out["state"] = _state["pf_port"], _state["pf_error"], _state.get("pf_msg")
    out["region"] = pf.get("region_name") or c.get("region_name") or c.get("region")
    if c.get("provider") == "pia" and c.get("region"):
        try:
            out["region_ok"] = bool(_pia_region(c["region"]).get("port_forward"))      # fresh from PIA's list
        except Exception:
            pass
    if out["connected"] and c.get("provider") == "pia":
        out["tries"] = []
        for gw in _pf_addresses(pf):
            try:
                _tunnel_socket((gw, 19999), 6).close()
                out["tries"].append({"address": gw, "result": "ok"})
            except OSError as e:
                out["tries"].append({"address": gw, "result": getattr(e, "strerror", None) or str(e)})
        out["reach"] = "ok" if any(t["result"] == "ok" for t in out["tries"]) else (out["tries"][0]["result"] if out["tries"] else None)
    try:
        from . import torrent
        if torrent.running():
            out["torrent_port"] = torrent.api("GET", "/api/v2/app/preferences").get("listen_port")
    except Exception:
        pass
    return out


# ---- split tunneling -----------------------------------------------------------------------------------
# On (the default): nothing uses the VPN except the apps and sites you add. Chosen apps start with
# the "crossbar-vpn" group (sg), so everything they open carries that group; the root helper marks
# that group's traffic and sends it, traffic to chosen sites, and anything using the VPN's own
# address (the torrent engine bound to it) through the VPN with its own routing table; their DNS
# goes to the VPN's DNS server too. Off: everything uses the VPN (default route, its DNS only).
# (A group works from any session — a TV login included — where moving apps into a systemd group
# needs a desktop-style session.)
VPN_GROUP = "crossbar-vpn"
VPNRUN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vpnrun.py")


def split_on():
    return cfg().get("split", True) is not False


def _group():
    """(gid, am I in it) for the VPN apps' group."""
    import grp
    import pwd
    try:
        g = grp.getgrnam(VPN_GROUP)
    except KeyError:
        return None, False
    me = pwd.getpwuid(os.getuid()).pw_name
    return g.gr_gid, (me in g.gr_mem or os.getgid() == g.gr_gid)


def ensure_group():
    """Make the group (once, through the root helper) and join it. Returns its gid."""
    gid, member = _group()
    if gid is None or not member:
        r = _admin("vpn-group", {})
        gid = r.get("gid")
    return gid


def uses_vpn(app_id):
    """Is this app one of the ones that go through the VPN (split tunneling on)?"""
    if not split_on() or not app_id:
        return False
    apps = cfg().get("vpn_apps") or []
    if app_id == "leaktest":                    # the leak tests check what VPN traffic would do
        return True
    if app_id == "torrents":
        try:
            from . import torrent
            if torrent.prefs_local().get("vpn_only"):
                return True
        except Exception:
            pass
    return app_id in apps


def wrap(argv, app_id):
    """Start an app with the VPN apps' group when it's one that uses the VPN (it takes effect
    whenever the VPN is connected; with the VPN off the group does nothing)."""
    if not uses_vpn(app_id):
        return argv
    gid, member = _group()
    if not util.which("newgrp"):
        print("vpn: newgrp (util-linux) is missing: VPN apps can't be started in the VPN group", flush=True)
        return argv
    if gid is None or not member:
        try:
            ensure_group()
        except RuntimeError as e:
            print(f"vpn: group: {e}", flush=True)
            return argv
        gid, member = _group()
        if not member:
            return argv
    # Arch has no `sg`: vpnrun.py goes through util-linux's newgrp (same process, same environment)
    return [sys.executable or "python3", VPNRUN, "--", *argv]


VPNBIND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vpnbind")


def app_env(app_id, env=None):
    """Environment for one of Crossbar's own Python helpers that uses the VPN: its connections leave
    from the VPN's address (the route that works whatever the app-group marking does)."""
    env = dict(env if env is not None else os.environ)
    if uses_vpn(app_id) and nm_state() == "activated":
        addr = _vpn_addr()
        if addr:
            env["CROSSBAR_VPN_SRC"] = addr
            env["PYTHONPATH"] = VPNBIND + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _resolve(targets):
    out = []
    for t in targets:
        if re.match(r"^[\d.:/a-fA-F]+$", t) and (("." in t and t[0].isdigit()) or ":" in t):
            out.append(t)
            continue
        try:
            for fam, _, _, _, addr in socket.getaddrinfo(t, None, socket.AF_INET):
                out.append(f"{addr[0]}/32")
        except OSError:
            pass
    return sorted(set(out))[:256]


DEFAULT_DNS = {"mullvad": "10.64.0.1", "nord": "103.86.96.100"}
FALLBACK_DNS = "1.1.1.1"           # through the tunnel (split rules route it there): never your provider's


def vpn_dns():
    """The DNS server VPN traffic uses: from this connection, else saved, else Cloudflare (via the tunnel)."""
    return _state.get("dns") or cfg().get("dns") or FALLBACK_DNS


def uses_resolved():
    """Does this system resolve names through systemd-resolved (nss-resolve / 127.0.0.53)? Then lookups
    are made by resolved itself, not the app, so an app's VPN group can't steer its DNS."""
    hit = _cache.get("resolved")
    if hit and time.time() - hit[0] < 120:
        return hit[1]
    v = _uses_resolved()
    _cache["resolved"] = (time.time(), v)
    return v


def _uses_resolved():
    try:
        ns = open("/etc/nsswitch.conf").read()
        line = next((ln for ln in ns.splitlines() if ln.strip().startswith("hosts:")), "")
        rc = open("/etc/resolv.conf").read() if os.path.exists("/etc/resolv.conf") else ""
        active = subprocess.run(["systemctl", "is-active", "--quiet", "systemd-resolved"], timeout=5).returncode == 0
        return active and (" resolve" in line or "127.0.0.53" in rc)
    except (OSError, subprocess.TimeoutExpired):
        return False


def dns_all():
    """Split tunneling on: send every lookup (not just VPN apps') to the VPN's DNS through the tunnel?
    Automatic: yes when systemd-resolved does the lookups (otherwise VPN apps' lookups would leak)."""
    v = cfg().get("dns_all")
    if v is None:
        return uses_resolved()
    return bool(v)


WG_FWMARK = 0xCA6C                 # on WireGuard's encrypted packets (split tunneling leaves them alone)


def _conf_endpoints(conf):
    """The VPN server's own address(es): the tunnel's encrypted packets go there, and must never be
    sent into the tunnel themselves."""
    out = re.findall(r"^\s*Endpoint\s*=\s*\[?([\d.]+)\]?:\d+", conf or "", re.M | re.I)
    out += re.findall(r"^\s*remote\s+([\d.]+)\b", conf or "", re.M | re.I)
    return sorted(set(out))[:8]


def _live_endpoints():
    """The server address of the connection that's up (made before Crossbar saved it)."""
    out = _nmcli("connection", "show", CONN, timeout=10, check=False)
    eps = re.findall(r"endpoint:\s*\[?(\d+\.\d+\.\d+\.\d+)\]?:\d+", out, re.I)
    eps += re.findall(r"remote\s*=\s*(\d+\.\d+\.\d+\.\d+)", out, re.I)
    return sorted(set(eps))[:8]


def _conf_dns(conf):
    m = re.search(r"^\s*DNS\s*=\s*([\d.]+)", conf or "", re.M | re.I)
    return m.group(1) if m else None


def _nm_dns():
    out = _nmcli("-g", "IP4.DNS", "connection", "show", CONN, timeout=10, check=False).strip()
    return next((x for x in re.split(r"[\s|]+", out) if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", x)), None)


def _vpn_addr():
    out = _nmcli("-g", "IP4.ADDRESS", "device", "show", _iface(), timeout=10, check=False).strip()
    m = re.search(r"(\d+\.\d+\.\d+\.\d+)", out)
    if m:
        return m.group(1)
    try:
        r = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", _iface()], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", r.stdout)
    return m.group(1) if m else None


def apply_split():
    c = cfg()
    try:
        gid = ensure_group()
    except RuntimeError as e:
        gid = None
        _state["error"] = f"Apps can't be split off: {e}"
    addr = _vpn_addr()
    dns = vpn_dns()
    _up_cache.clear()
    relay = DNS_RELAY.start() if addr else None
    to = _resolve(c.get("vpn_sites") or [])
    if dns:
        to = sorted(set(to + [f"{dns}/32"]))      # the VPN's DNS server is always reached through the tunnel
    req = {"enable": True, "dev": _iface(), "gateway": None, "to": to,
           "from": [addr] if addr else [], "gid": gid, "dns": dns, "dns_relay": relay,
           "exempt": c.get("endpoints") or [], "exempt_mark": WG_FWMARK}
    return _admin("vpn-split", req)


class _DnsRelay:
    """VPN apps' DNS, through the tunnel. Most systems resolve through a local stub (systemd-resolved
    on 127.0.0.53, or dnsmasq on 127.0.0.1); a VPN app's question to it can't be redirected out of
    the tunnel directly (the kernel won't send a loopback-addressed packet out of a real interface),
    and the stub itself would ask your normal DNS. So the firewall hands VPN apps' local DNS
    questions to this relay instead, which asks the VPN's DNS server from the VPN's own address
    (routed through the tunnel). UDP and TCP, on 127.0.0.1:PORT."""
    PORT = 53530

    def __init__(self):
        self.started = False
        self._lock = threading.Lock()
        # a fixed set of workers, not a thread per question (a game's launcher can ask hundreds)
        from concurrent.futures import ThreadPoolExecutor
        self._pool = ThreadPoolExecutor(max_workers=12, thread_name_prefix="dnsrelay")

    def _upstream(self):
        # cached: asking NetworkManager on every lookup made each one slow
        now = time.time()
        if now - _up_cache.get("at", 0) > 15 or not _up_cache.get("src"):
            _up_cache.update(at=now, dns=vpn_dns(), src=_vpn_addr())
        return _up_cache["dns"], _up_cache["src"]

    def start(self):
        with self._lock:
            if not self.started:
                try:
                    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    u.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    u.bind(("127.0.0.1", self.PORT))
                    t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    t.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    t.bind(("127.0.0.1", self.PORT))
                    t.listen(32)
                except OSError as e:
                    print(f"vpn: dns relay: {e}", flush=True)
                    return None
                threading.Thread(target=self._udp, args=(u,), daemon=True).start()
                threading.Thread(target=self._tcp, args=(t,), daemon=True).start()
                self.started = True
        return self.PORT

    def _udp(self, srv):
        while True:
            try:
                q, peer = srv.recvfrom(4096)
            except OSError:
                time.sleep(0.2)                  # never spin on a broken socket
                continue
            self._pool.submit(self._udp_one, srv, q, peer)

    def _udp_one(self, srv, q, peer):
        dns, src = self._upstream()
        if not dns or not src:
            return
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.bind((src, 0))
                s.settimeout(4)
                s.sendto(q, (dns, 53))
                a, _ = s.recvfrom(65535)
            srv.sendto(a, peer)
        except OSError:
            pass

    def _tcp(self, srv):
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                time.sleep(0.2)
                continue
            self._pool.submit(self._tcp_one, c)

    def _tcp_one(self, c):
        dns, src = self._upstream()
        try:
            with c, socket.create_connection((dns, 53), timeout=6, source_address=(src, 0)) as up:
                c.settimeout(6)
                for a, b in ((c, up), (up, c)):          # one question, one answer (DNS over TCP)
                    head = _recv_exact(a, 2)
                    b.sendall(head + _recv_exact(a, struct.unpack("!H", head)[0]))
        except (OSError, TypeError, struct.error):
            pass


def _recv_exact(s, n):
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise OSError("closed")
        buf += chunk
    return buf


DNS_RELAY = _DnsRelay()
_up_cache = {}


_split_applied = {}

SPLIT_PROBE = r'''
import json, os, socket, ssl, time
out = {"gid": os.getegid()}
def trace(host, connect_to):
    ctx = ssl.create_default_context()
    with socket.create_connection((connect_to, 443), timeout=8) as s, ctx.wrap_socket(s, server_hostname=host) as t:
        t.sendall(b"GET /cdn-cgi/trace HTTP/1.1\r\nHost: " + host.encode() + b"\r\nConnection: close\r\n\r\n")
        data = b""
        while chunk := t.recv(4096):
            data += chunk
    return dict(l.split("=", 1) for l in data.decode(errors="replace").splitlines() if "=" in l).get("ip")
try:
    out["ip"] = trace("1.1.1.1", "1.1.1.1")
except Exception as e:
    out["conn_error"] = str(e)[:120]
t0 = time.time()
try:
    socket.getaddrinfo("speed.cloudflare.com", 443, socket.AF_INET)
    out["dns"] = "ok (%.1f s)" % (time.time() - t0)
except Exception as e:
    out["dns"] = "failed after %.0f s: %s" % (time.time() - t0, str(e)[:80])
print(json.dumps(out))
'''


def _rules_present(addr):
    """Are the split rules in place for this connection? (`ip rule` / a table's routes need no root.)"""
    try:
        rules = subprocess.run(["ip", "-4", "rule", "show"], capture_output=True, text=True, timeout=10).stdout
        route = subprocess.run(["ip", "-4", "route", "show", "table", "2000"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return True                                       # can't tell: don't keep asking the helper
    return ("fwmark 0x2000 lookup 2000" in rules and f"dev {_iface()}" in route
            and (not addr or f"from {addr} lookup 2000" in rules))


def ensure_split(force=False):
    """Split tunneling on and the VPN up, but the rules missing or for an old address (the VPN came
    up without Crossbar — at boot, or NetworkManager reconnected it): put them back."""
    if not split_on() or nm_state() != "activated":
        return False
    addr = _vpn_addr()
    key = (_iface(), addr)
    if not force and _split_applied.get("key") == key and _rules_present(addr):
        return False
    if not force and _rules_present(addr) and _split_applied.get("key") is not None:
        _split_applied["key"] = key
        return False
    try:
        apply_split()
        _split_applied["key"] = key
        _split_applied.pop("error", None)
    except RuntimeError as e:
        _split_applied["error"] = str(e)
        raise
    return True


def resume():
    """Crossbar (re)started while the VPN is up: the DNS relay that VPN apps' lookups go to lives in
    this process, so it must be running again straight away (the firewall still sends lookups to
    it), and port forwarding has to carry on."""
    if nm_state() != "activated":
        return
    if split_on():
        DNS_RELAY.start()
        if not cfg().get("endpoints"):
            try:
                _set(endpoints=_live_endpoints())
            except Exception as e:
                print(f"vpn: endpoints: {e}", flush=True)
        if cfg().get("protocol") != "openvpn":     # mark WireGuard's own packets on the live connection too
            _nmcli("connection", "modify", CONN, "wireguard.fwmark", str(WG_FWMARK), check=False)
            _nmcli("device", "reapply", CONN, check=False, timeout=20)
        try:
            ensure_split(force=True)           # once per start: an update may bring new rules (1.2.5: MSS clamping)
        except Exception as e:
            print(f"vpn: split rules: {e}", flush=True)
    try:
        from . import torrent
        torrent._apply_vpn_binding(rebind=True)
    except Exception:
        pass
    if cfg().get("port_forward"):
        resume_port_forward()


def split_watch():
    """Background: keep the split rules in step with the connection."""
    def run():
        if split_on():
            DNS_RELAY.start()                  # before anything else: lookups may already be on their way
        time.sleep(15)
        fails = 0
        while True:
            try:
                ensure_split()
                fails = 0
            except Exception as e:
                fails += 1
                print(f"vpn: split rules: {e}", flush=True)
            # failing (the helper can't run, no password agent…): back off up to 10 minutes rather
            # than starting a privileged helper every 30 s
            time.sleep(min(600, 30 * 2 ** min(fails, 5)))
    threading.Thread(target=run, daemon=True).start()


def split_check():
    """Is split tunneling really working? Asks the internet what it sees from Crossbar itself, from
    an app in the VPN group, and from the VPN's own address; plus what the helper set up."""
    import sys
    from . import speedtest
    out = {"split": split_on(), "connected": nm_state() == "activated", "isp_ip": cfg().get("isp_ip")}
    out["normal"] = speedtest._trace().get("ip")
    if out["split"] and out["connected"]:
        try:
            out["reapplied"] = ensure_split()
        except RuntimeError as e:
            out["split_error"] = str(e)
    out["iface"], out["vpn_addr"] = _iface(), _vpn_addr()
    out["rules"] = _rules_present(out["vpn_addr"]) if out["connected"] else None
    gid, member = _group()
    out["group"] = {"exists": gid is not None, "member": member}
    # the test app checks the connection without DNS (Cloudflare's 1.1.1.1) and DNS on its own,
    # so a broken one doesn't hide the other
    argv = wrap([sys.executable, "-c", SPLIT_PROBE], "leaktest")
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=45, cwd="/")
        probe = json.loads((r.stdout.strip().splitlines() or ["{}"])[-1])
        out["app"] = probe.get("ip")
        out["app_conn_error"] = probe.get("conn_error")
        out["app_dns"] = probe.get("dns")
        out["app_gid_ok"] = bool(gid is not None and probe.get("gid") == gid)
        out["app_error"] = "" if probe else (r.stderr.strip()[-200:] or f"exit {r.returncode}")
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        out["app"], out["app_error"] = None, str(e)[-200:]
    src = _tunnel_source()
    if src:
        try:
            c = http.client.HTTPSConnection("speed.cloudflare.com", timeout=10, source_address=src)
            c.request("GET", "/cdn-cgi/trace", headers={"User-Agent": "Crossbar"})
            out["vpn"] = dict(ln.split("=", 1) for ln in c.getresponse().read().decode().splitlines() if "=" in ln).get("ip")
            c.close()
        except OSError as e:
            out["vpn"] = None
            out["vpn_error"] = str(e)
    try:
        out["helper"] = _admin("vpn-split-status", {})
    except RuntimeError as e:
        out["helper"] = {"error": str(e)}
    return out


def clear_split():
    try:
        _admin("vpn-split", {"enable": False})
    except RuntimeError:
        pass


def _tunnel_source():
    """With split tunneling on, requests that must go through the tunnel (port forwarding) are
    sent from the VPN's own address, which the split rules route through it."""
    if split_on() and nm_state() == "activated":
        a = _vpn_addr()
        if a:
            return (a, 0)
    return None


def addresses():
    """What the internet sees: from ordinary traffic, and through the VPN (with split tunneling on
    those differ: only VPN apps use the VPN, and Crossbar's own checks aren't one)."""
    from . import speedtest
    t = speedtest._trace()
    out = {"normal": t.get("ip"), "country": t.get("country"), "connected": nm_state() == "activated", "split": split_on(),
           "isp_ip": cfg().get("isp_ip")}
    if out["normal"] and (not out["connected"] or out["split"]):     # split on: ordinary traffic is your own line
        _set(isp_ip=out["normal"])
    src = _tunnel_source()
    if src:
        try:
            c = http.client.HTTPSConnection("speed.cloudflare.com", timeout=10, source_address=src)
            c.request("GET", "/cdn-cgi/trace", headers={"User-Agent": "Crossbar"})
            kv = dict(ln.split("=", 1) for ln in c.getresponse().read().decode().splitlines() if "=" in ln)
            c.close()
            out["vpn"], out["vpn_country"] = kv.get("ip"), kv.get("loc")
        except OSError as e:
            out["vpn_error"] = str(e)
    elif out["connected"] and not out["split"]:
        out["vpn"], out["vpn_country"] = out["normal"], out["country"]          # everything uses the VPN
    elif out["connected"]:
        out["vpn_error"] = "Couldn't find the VPN's own address"
    return out


def _remember_isp_ip():
    """Your address without the VPN (for the leak tests: is it ever seen while the VPN is on?)."""
    try:
        from . import speedtest
        ip = speedtest._trace().get("ip")
        if ip:
            _set(isp_ip=ip)
    except Exception:
        pass


def _admin(action, req):
    if not util.which("pkexec"):
        raise RuntimeError("polkit (pkexec) isn't installed")
    r = subprocess.run(["pkexec", ADMIN, action], input=json.dumps(req), capture_output=True, text=True, timeout=60)
    try:
        out = json.loads((r.stdout.strip().splitlines() or ["{}"])[-1])
    except ValueError:
        out = {"ok": False, "error": (r.stderr or r.stdout).strip()[-200:]}
    if not out.get("ok"):
        raise RuntimeError(out.get("error") or "the system helper failed")
    return out


def autoconnect():
    """At startup: connect if asked to (in the background)."""
    if cfg().get("autoconnect") and cfg().get("region") and nm_state() != "activated":
        def run():
            time.sleep(8)                      # let the network come up first
            try:
                connect()
            except Exception as e:
                print(f"vpn: autoconnect: {e}", flush=True)
        threading.Thread(target=run, daemon=True).start()

