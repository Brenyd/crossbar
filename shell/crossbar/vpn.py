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
        raw = socket.create_connection((self._ip, self.port), self.timeout, source_address=_tunnel_source())
        self.sock = self._context.wrap_socket(raw, server_hostname=self._name)
        cn = dict(x[0] for x in self.sock.getpeercert().get("subject", ()))
        if cn.get("commonName") != self._name:
            self.sock.close()
            raise ssl.SSLError(f"PIA server is {cn.get('commonName')}, expected {self._name}")


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
        pf = {"kind": "pia", "token": token, "gateway": srv["ip"], "hostname": srv["cn"]}
        return conf, None, pf
    srv = (servers.get("ovpnudp") or [None])[0]
    if not srv:
        raise RuntimeError("That region has no OpenVPN server right now")
    with open(PIA_CA) as f:
        ca = f.read()
    conf = PIA_OVPN.format(tun=TUN, proto="udp", ip=srv["ip"], port=8080, ca=ca if ca.endswith("\n") else ca + "\n")
    pf = {"kind": "pia", "token": token, "gateway": None, "hostname": srv["cn"]}      # gateway: the tunnel's, once up
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
    allowed = {"region", "protocol", "port_forward", "autoconnect", "split", "vpn_sites", "vpn_apps"}
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
    _set(**kw)
    if nm_state() == "activated":
        if "split" in kw and kw["split"] != was_split:
            _state["error"] = "Reconnect the VPN for the split tunneling change"
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
        vpn_dns = _conf_dns(conf)
        if split_on():
            # Split tunneling: the VPN is only a road some traffic takes (chosen apps and sites),
            # not the default route; its DNS server is only used by that traffic (see apply_split).
            _nmcli("connection", "modify", CONN, "connection.autoconnect", "no", "ipv4.never-default", "yes",
                   "ipv6.never-default", "yes", "ipv4.ignore-auto-dns", "yes", "ipv6.ignore-auto-dns", "yes",
                   "ipv4.dns", "", "ipv6.dns", "", "ipv6.method", "disabled" if protocol == "openvpn" else "ignore", check=False)
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
        try:                                     # the torrent client, if it only uses the VPN: bind again
            from . import torrent
            torrent._apply_vpn_binding()
        except Exception:
            pass
        _state["dns"] = vpn_dns or _nm_dns()
        if split_on():
            try:
                apply_split()
            except RuntimeError as e:
                _state["error"] = f"Split tunneling: {e}"
        else:
            clear_split()
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
def _tunnel_gateway():
    out = _nmcli("-g", "IP4.GATEWAY", "device", "show", TUN, timeout=10, check=False).strip()
    if out:
        return out
    try:
        r = subprocess.run(["ip", "-4", "route", "show", "dev", TUN], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"via (\d+\.\d+\.\d+\.\d+)", r.stdout)
    return m.group(1) if m else None


def _set_port(port, err=None):
    changed = port != _state["pf_port"]
    _state.update(pf_port=port, pf_error=err)
    if changed:
        for fn in list(_listeners):
            try:
                fn(port)
            except Exception as e:
                print(f"vpn: port listener: {e}", flush=True)
        _publish()


def _pia_pf_loop(pf, stop):
    gw = pf.get("gateway") or _tunnel_gateway()
    if not gw:
        _set_port(None, "Couldn't find the VPN gateway for port forwarding")
        return
    try:
        sig = _pia_get(gw, 19999, pf["hostname"], "/getSignature", {"token": pf["token"]})
        if sig.get("status") != "OK":
            raise RuntimeError(sig.get("message") or "PIA refused (is this region one with port forwarding?)")
        payload = json.loads(base64.b64decode(sig["payload"]))
        port = int(payload["port"])
    except Exception as e:
        _set_port(None, f"Port forwarding: {e}")
        return
    while not stop.is_set():
        try:
            r = _pia_get(gw, 19999, pf["hostname"], "/bindPort", {"payload": sig["payload"], "signature": sig["signature"]})
            if r.get("status") != "OK":
                raise RuntimeError(r.get("message") or "bindPort failed")
            _set_port(port)
        except Exception as e:
            _set_port(None, f"Port forwarding: {e}")
        stop.wait(900)                                          # every 15 minutes, as PIA asks


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
    while not stop.is_set():
        try:
            natpmp_map(pf["gateway"], "udp")
            port = natpmp_map(pf["gateway"], "tcp")
            _set_port(port)
        except (OSError, RuntimeError) as e:
            _set_port(None, f"Port forwarding: {e} (is this a P2P server with NAT-PMP on?)")
        stop.wait(45)


def start_port_forward(pf):
    stop_port_forward()
    stop = threading.Event()
    fn = _pia_pf_loop if pf["kind"] == "pia" else _natpmp_loop
    t = threading.Thread(target=fn, args=(pf, stop), daemon=True)
    _state.update(pf_thread=t, pf_stop=stop)
    t.start()


def stop_port_forward():
    if _state.get("pf_stop"):
        _state["pf_stop"].set()
    _state.update(pf_thread=None, pf_stop=None)
    if _state["pf_port"] is not None:
        _set_port(None)


# ---- split tunneling -----------------------------------------------------------------------------------
# On (the default): nothing uses the VPN except the apps and sites you add. Chosen apps start with
# the "crossbar-vpn" group (sg), so everything they open carries that group; the root helper marks
# that group's traffic and sends it, traffic to chosen sites, and anything using the VPN's own
# address (the torrent engine bound to it) through the VPN with its own routing table; their DNS
# goes to the VPN's DNS server too. Off: everything uses the VPN (default route, its DNS only).
# (A group works from any session — a TV login included — where moving apps into a systemd group
# needs a desktop-style session.)
VPN_GROUP = "crossbar-vpn"


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
    if gid is None or not member or not util.which("sg"):
        try:
            ensure_group()
        except RuntimeError as e:
            print(f"vpn: group: {e}", flush=True)
            return argv
        gid, member = _group()
        if not member:
            return argv
    import shlex
    return ["sg", VPN_GROUP, "-c", "exec " + shlex.join(argv)]      # same process: sg execs the shell, the shell execs it


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
    req = {"enable": True, "dev": _iface(), "gateway": None, "to": _resolve(c.get("vpn_sites") or []),
           "from": [addr] if addr else [], "gid": gid, "dns": _state.get("dns")}
    return _admin("vpn-split", req)


def split_check():
    """Is split tunneling really working? Asks the internet what it sees from Crossbar itself, from
    an app in the VPN group, and from the VPN's own address; plus what the helper set up."""
    import sys
    from . import speedtest
    out = {"split": split_on(), "connected": nm_state() == "activated", "isp_ip": cfg().get("isp_ip")}
    out["normal"] = speedtest._trace().get("ip")
    gid, member = _group()
    out["group"] = {"exists": gid is not None, "member": member}
    argv = wrap([sys.executable, "-c", "import sys,os;sys.path.insert(0,os.getcwd());from crossbar import speedtest;"
                 "print(speedtest._trace().get('ip',''));print(os.getgid())"], "leaktest")
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=30, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        lines = r.stdout.strip().splitlines()
        out["app"] = lines[0] if lines else None
        out["app_gid_ok"] = bool(gid is not None and len(lines) > 1 and lines[1].strip() == str(gid))
        out["app_error"] = r.stderr.strip()[-200:] if r.returncode else ""
    except (OSError, subprocess.TimeoutExpired) as e:
        out["app"], out["app_error"] = None, str(e)
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

