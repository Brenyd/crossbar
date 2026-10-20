#!/usr/bin/env python3
"""crossbar-admin — the few system changes Crossbar makes as root (run via pkexec).

    pkexec /usr/lib/crossbar/admin.py nas-add      < {"name","type","server","share","username","password","domain"}
    pkexec /usr/lib/crossbar/admin.py nas-remove   < {"name"}
    pkexec /usr/lib/crossbar/admin.py nas-remount  < {"name"}
    pkexec /usr/lib/crossbar/admin.py boot-session < {"session": "crossbar" | "desktop"}
    pkexec /usr/lib/crossbar/admin.py ps5-fan-target < {"value": 40..95}
    pkexec /usr/lib/crossbar/admin.py ps5-led        < {"name": "<preset>" | "off"}
    pkexec /usr/lib/crossbar/admin.py ps5-control    < {"args": ["--fan", "on|off|max"] | ["--boost", "on|off"]}
    pkexec /usr/lib/crossbar/admin.py vpn-split      < {"enable", "dev", "gateway", "to": [cidr], "from": [ip], "gid", "dns"}
    pkexec /usr/lib/crossbar/admin.py vpn-group      < {}   (makes the crossbar-vpn group, adds whoever asked)

Network drives go in /etc/fstab with a marker comment (# crossbar-nas:<name>),
always mount under /mnt/nas/<name>, use x-systemd.automount + nofail so a
missing NAS never blocks boot, and keep SMB passwords in a root-only file in
/etc/crossbar/nas/ (never in fstab). Every input is validated; fstab is backed
up and checked before it's replaced. Prints one JSON result line.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

FSTAB = "/etc/fstab"
CRED_DIR = "/etc/crossbar/nas"
MOUNT_ROOT = "/mnt/nas"
MARK = "# crossbar-nas:"


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    if not s or len(s) > 40:
        fail("Name must be 1–40 letters or numbers")
    return s


def clean(value, what, pattern=r"[^\n\r\t\0]*", required=True, maxlen=200):
    value = (value or "").strip()
    if required and not value:
        fail(f"{what} is required")
    if len(value) > maxlen or not re.fullmatch(pattern, value):
        fail(f"{what} has characters that aren't allowed")
    return value


def fstab_escape(s):
    return s.replace("\\", "\\134").replace(" ", "\\040").replace("\t", "\\011")


def unit_name(path, suffix):
    r = subprocess.run(["systemd-escape", "--path", f"--suffix={suffix}", path], capture_output=True, text=True)
    return r.stdout.strip()


def read_fstab():
    with open(FSTAB) as f:
        return f.read().splitlines()


def write_fstab(lines):
    data = "\n".join(lines).rstrip("\n") + "\n"
    if not os.path.exists(FSTAB + ".crossbar-bak"):
        shutil.copy2(FSTAB, FSTAB + ".crossbar-bak")       # the original, kept once
    fd, tmp = tempfile.mkstemp(dir="/etc", prefix=".fstab.")
    with os.fdopen(fd, "w") as f:
        f.write(data)
    if shutil.which("findmnt"):
        r = subprocess.run(["findmnt", "--verify", "--tab-file", tmp], capture_output=True, text=True)
        m = re.search(r"(\d+) parse error", r.stdout + r.stderr)
        if m and int(m.group(1)) > 0:            # (other "errors" are e.g. a disk that isn't plugged in)
            os.remove(tmp)
            fail("The new fstab didn't check out; nothing was changed")
    os.chmod(tmp, 0o644)
    os.replace(tmp, FSTAB)


def without(lines, s):
    """Drop our entry for `s`: the marker comment line and the fstab line after it."""
    out, skip = [], False
    for ln in lines:
        if ln.strip() == MARK + s or ln.strip().startswith(MARK + s + " "):
            skip = True
            continue
        if skip:
            skip = False
            continue
        out.append(ln)
    return out


SMB_ERRORS = {   # mount.cifs "mount error(N)" -> what to do about it
    13: "The NAS refused the username or password (check them, and that this user may use the share)",
    2: "The NAS has no share by that name",
    6: "The NAS has no share by that name",
    112: "Couldn't reach the NAS (is it on, and is the address right?)",
    113: "Couldn't reach the NAS (no route; is the address right?)",
    115: "The NAS didn't answer in time",
    111: "The NAS refused the connection (is SMB/Windows file sharing turned on?)",
    95: "The NAS only speaks the old SMB1 protocol",
    22: "The NAS rejected the connection settings",
}


def port_open(host, port, timeout=4):
    import socket
    try:
        with socket.create_connection((host.strip("[]"), port), timeout=timeout):
            return True
    except OSError:
        return False


def smb_shares(server, cred):
    """Share names, if smbclient is installed (for a helpful 'did you mean')."""
    if not shutil.which("smbclient"):
        return []
    r = subprocess.run(["smbclient", "-g", "-L", f"//{server}", "-A", cred, "-m", "SMB3"],
                       capture_output=True, text=True, timeout=20)
    return [ln.split("|")[1] for ln in r.stdout.splitlines() if ln.startswith("Disk|")]


def test_mount(kind, server, share, cred=None, uid=0, gid=0, guest=False):
    """Mount once in a temporary folder to find problems before anything is saved.
    Returns (ok, message, extra_options)."""
    port = 445 if kind == "smb" else 2049
    if not port_open(server, port):
        if kind == "smb" and port_open(server, 139):
            pass                                   # NetBIOS-only (very old NAS): let mount.cifs try
        else:
            return False, (f"Couldn't reach {server} on the {'SMB' if kind == 'smb' else 'NFS'} port ({port}). "
                           "Check the address, that the NAS is on, and that "
                           + ("SMB (Windows file sharing)" if kind == "smb" else "NFS") + " is enabled on it."), ""
    tmp = tempfile.mkdtemp(prefix="crossbar-nas-", dir="/run")
    try:
        tries = [""] if kind == "nfs" else ["", "vers=3.0", "vers=2.0", "vers=1.0"]
        last = ""
        for extra in tries:
            if kind == "smb":
                opts = f"credentials={cred},uid={uid},gid={gid},iocharset=utf8" + (",guest" if guest else "") + (f",{extra}" if extra else "")
                r = subprocess.run(["mount", "-t", "cifs", f"//{server}/{share}", tmp, "-o", opts],
                                   capture_output=True, text=True, timeout=30)
            else:
                r = subprocess.run(["mount", "-t", "nfs", f"{server}:/{share}", tmp], capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                subprocess.run(["umount", tmp], capture_output=True)
                return True, "", extra
            last = (r.stderr or r.stdout).strip()
            m = re.search(r"mount error\((\d+)\)", last)
            code = int(m.group(1)) if m else None
            if kind == "smb" and code not in (95, 22, 112, 115, None):
                break                                   # a version change won't fix a password or a share name
        if kind == "smb":
            m = re.search(r"mount error\((\d+)\)", last)
            code = int(m.group(1)) if m else None
            msg = SMB_ERRORS.get(code, f"Mounting failed: {last[-160:]}")
            if code in (2, 6):
                shares = smb_shares(server, cred)
                if shares:
                    msg += f". Shares on {server}: " + ", ".join(shares[:8])
            return False, msg, ""
        low = last.lower()
        if "access denied" in low or "permission denied" in low:
            msg = f"The NAS refused this device: allow its IP in the NFS export settings for /{share}"
        elif "no such file" in low:
            r = subprocess.run(["showmount", "-e", server], capture_output=True, text=True, timeout=15) if shutil.which("showmount") else None
            exports = [ln.split()[0] for ln in (r.stdout.splitlines()[1:] if r and r.returncode == 0 else [])]
            msg = f"The NAS has no export /{share}" + (f". Exports: {', '.join(exports[:8])}" if exports else "")
        else:
            msg = f"Mounting failed: {last[-160:]}"
        return False, msg, ""
    finally:
        subprocess.run(["umount", "-l", tmp], capture_output=True)
        try:
            os.rmdir(tmp)
        except OSError:
            pass


def split_address(server, share):
    """Accept \\\\nas\\share, //nas/share, smb://nas/share or nfs://nas/path typed in either box."""
    server, share = (server or "").strip(), (share or "").strip()
    for text in (server, share):
        t = text.replace("\\", "/")
        m = re.match(r"^(?:smb:|nfs:|cifs:)?//([^/]+)/?(.*)$", t, re.I)
        if m:
            return m.group(1), (m.group(2) or share).strip("/")
    if ":/" in server and not server.startswith("["):        # nas:/export
        host, path = server.split(":/", 1)
        return host, (path or share).strip("/")
    return server, share.replace("\\", "/").strip("/")


def nas_add(req):
    s = slug(req.get("name"))
    kind = req.get("type", "smb")
    if kind not in ("smb", "nfs"):
        fail("Type must be SMB or NFS")
    req["server"], req["share"] = split_address(req.get("server"), req.get("share"))
    server = clean(req.get("server"), "Server", r"[A-Za-z0-9.\-:\[\]]+", maxlen=255)
    share = clean(req.get("share"), "Share", r"[^\n\r\t\0#]+").strip("/")
    point = os.path.join(MOUNT_ROOT, s)
    uid = int(os.environ.get("PKEXEC_UID", req.get("uid", 1000)))
    gid = int(req.get("gid") or uid)
    if kind == "smb":
        user = clean(req.get("username"), "Username", required=False)
        password = clean(req.get("password"), "Password", required=False, maxlen=500)
        domain = clean(req.get("domain"), "Domain", r"[A-Za-z0-9.\-_]*", required=False)
        cred = os.path.join(CRED_DIR, f"{s}.cred")
        cred_text = f"username={user or 'guest'}\npassword={password}\n" + (f"domain={domain}\n" if domain else "")
        # test first, with the credentials in a root-only temporary file; nothing is saved if it fails
        fd, tcred = tempfile.mkstemp(prefix="crossbar-cred-", dir="/run")
        with os.fdopen(fd, "w") as f:
            f.write(cred_text)
        try:
            ok, msg, extra = test_mount("smb", server, share, tcred, uid, gid, guest=not user)
        finally:
            os.remove(tcred)
        if not ok:
            fail(msg)
        opts = (f"credentials={cred},uid={uid},gid={gid},iocharset=utf8,file_mode=0664,dir_mode=0775,"
                + ("guest," if not user else "") + (f"{extra}," if extra else "") +
                "nofail,_netdev,x-systemd.automount,x-systemd.idle-timeout=600,x-systemd.mount-timeout=20")
        line = f"//{server}/{fstab_escape(share)} {point} cifs {opts} 0 0"
    else:
        ok, msg, _ = test_mount("nfs", server, share)
        if not ok:
            fail(msg)
        opts = "nofail,_netdev,x-systemd.automount,x-systemd.idle-timeout=600,x-systemd.mount-timeout=20"
        line = f"{server}:/{fstab_escape(share)} {point} nfs {opts} 0 0"
    label = clean(req.get("name"), "Name", r"[^\n\r\t\0]+", maxlen=60)
    lines = without(read_fstab(), s) + [f"{MARK}{s} {label}", line]     # fstab has no end-of-line comments
    write_fstab(lines)                                        # validated before it replaces fstab
    if kind == "smb":
        os.makedirs(CRED_DIR, mode=0o700, exist_ok=True)
        fd = os.open(cred, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(cred_text)
    os.makedirs(point, exist_ok=True)
    subprocess.run(["systemctl", "daemon-reload"])
    subprocess.run(["systemctl", "restart", unit_name(point, "automount")])
    # try it now so the user hears about a wrong password straight away
    r = subprocess.run(["timeout", "25", "ls", point], capture_output=True, text=True)
    ok = r.returncode == 0
    err = ""
    if not ok:
        j = subprocess.run(["journalctl", "-u", unit_name(point, "mount"), "-n", "5", "--no-pager", "-o", "cat"],
                           capture_output=True, text=True).stdout.strip().splitlines()
        err = (j[-1] if j else r.stderr.strip())[-200:]
    print(json.dumps({"ok": True, "mounted": ok, "path": point, "error": err}))


def nas_remove(req):
    s = slug(req.get("name"))
    point = os.path.join(MOUNT_ROOT, s)
    subprocess.run(["systemctl", "stop", unit_name(point, "automount"), unit_name(point, "mount")], capture_output=True)
    subprocess.run(["umount", "-l", point], capture_output=True)
    write_fstab(without(read_fstab(), s))
    subprocess.run(["systemctl", "daemon-reload"])
    try:
        os.remove(os.path.join(CRED_DIR, f"{s}.cred"))
    except OSError:
        pass
    try:
        os.rmdir(point)
    except OSError:
        pass
    print(json.dumps({"ok": True}))


def nas_remount(req):
    s = slug(req.get("name"))
    point = os.path.join(MOUNT_ROOT, s)
    subprocess.run(["umount", "-l", point], capture_output=True)
    subprocess.run(["systemctl", "restart", unit_name(point, "automount")])
    r = subprocess.run(["timeout", "25", "ls", point], capture_output=True)
    print(json.dumps({"ok": True, "mounted": r.returncode == 0}))


# ---- PS5 hardware (fan target, front LED, ps5_control) --------------------------------
PS5_FAN_TARGET = "/sys/devices/platform/ps5-fan/target_temp"
PS5_LEDS = "/sys/class/leds"


def ps5_fan_target(req):
    try:
        v = int(req.get("value"))
    except (TypeError, ValueError):
        fail("value must be a number")
    if not 40 <= v <= 95:
        fail("The fan target must be between 40 and 95 °C")
    if not os.path.exists(PS5_FAN_TARGET):
        fail("The PS5 fan driver isn't loaded")
    with open(PS5_FAN_TARGET, "w") as f:
        f.write(str(v))
    print(json.dumps({"ok": True, "value": v}))


def ps5_led(req):
    import glob
    name = req.get("name") or ""
    presets = {os.path.basename(p)[4:-len(":indicator")]: p for p in glob.glob(os.path.join(PS5_LEDS, "ps5:*:indicator"))}
    if not presets:
        fail("The PS5 LED driver isn't loaded")
    if name != "off" and name not in presets:
        fail("Unknown LED preset")
    for n, p in presets.items():          # one preset at a time
        if n != name:
            try:
                with open(os.path.join(p, "brightness"), "w") as f:
                    f.write("0")
            except OSError:
                pass
    if name != "off":
        with open(os.path.join(presets[name], "brightness"), "w") as f:
            f.write("1")
    print(json.dumps({"ok": True}))


def ps5_control(req):
    args = req.get("args")
    allowed = [["--fan", "on"], ["--fan", "off"], ["--fan", "max"], ["--boost", "on"], ["--boost", "off"]]
    if args not in allowed:
        fail("Not an allowed ps5_control command")
    # pkexec's PATH may leave out /usr/local/sbin, where ps5-tools.sh installs it
    exe = shutil.which("ps5_control") or next((p for p in ("/usr/local/sbin/ps5_control", "/usr/sbin/ps5_control")
                                               if os.access(p, os.X_OK)), None)
    if not exe:
        fail("ps5_control isn't installed")
    r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=20)
    if r.returncode:
        fail((r.stderr or r.stdout).strip()[-200:] or "ps5_control failed")
    print(json.dumps({"ok": True}))


# ---- which session the login manager starts (Crossbar or the Plasma desktop) ------------
WAYLAND_SESSIONS = "/usr/share/wayland-sessions"
BOOT_CONF = "zzz-crossbar.conf"      # zzz: read after the distro's own autologin files


def login_manager():
    """sddm / plasmalogin (Plasma Login Manager, an SDDM fork) / other / None."""
    try:
        target = os.path.basename(os.path.realpath("/etc/systemd/system/display-manager.service"))
    except OSError:
        return None
    for name in ("plasmalogin", "sddm"):
        if target.startswith(name):
            return name
    return target.replace(".service", "") if target != "display-manager.service" else None


def desktop_session():
    for f in ("plasma.desktop", "plasmawayland.desktop"):
        if os.path.exists(os.path.join(WAYLAND_SESSIONS, f)):
            return f
    return None


def boot_session(req):
    which = req.get("session")
    if which not in ("crossbar", "desktop", "off"):
        fail("session must be crossbar, desktop or off")
    dm = login_manager()
    if dm not in ("sddm", "plasmalogin"):
        fail("Switching sessions needs SDDM or Plasma Login Manager")
    conf_dir = f"/etc/{dm}.conf.d"
    path = os.path.join(conf_dir, BOOT_CONF)
    if which == "off":                  # back to the distro's own login behaviour
        try:
            os.remove(path)
        except OSError:
            pass
        print(json.dumps({"ok": True}))
        return
    uid = int(os.environ.get("PKEXEC_UID") or req.get("uid") or -1)
    import pwd
    try:
        user = pwd.getpwuid(uid).pw_name
    except (KeyError, OverflowError):
        fail("Couldn't tell which user asked")
    if uid == 0:
        fail("Run this as the console user, not root")
    session = "crossbar.desktop" if which == "crossbar" else desktop_session()
    if not session or not os.path.exists(os.path.join(WAYLAND_SESSIONS, session)):
        fail("That session isn't installed")
    os.makedirs(conf_dir, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=conf_dir, delete=False) as f:
        f.write("# Written by Crossbar (Settings › System › Switch to Desktop / Return to Crossbar).\n"
                "# Delete this file to go back to your previous login setup.\n"
                f"[Autologin]\nUser={user}\nSession={session}\nRelogin=true\n")
    os.chmod(f.name, 0o644)
    os.replace(f.name, path)
    print(json.dumps({"ok": True, "session": session}))


# ---- VPN split tunneling ------------------------------------------------------------------------------
# Split tunneling on: the VPN isn't the default route; traffic from the chosen apps (started with
# the crossbar-vpn group, so their sockets carry that group; marked by nftables), to the chosen sites, and from the VPN's own address (a program bound to
# it, like the torrent engine) goes through it with routing table 2000. Marked apps' DNS goes to
# the VPN's DNS server (through the tunnel), and their packets get the tunnel's address
# (masquerade). Undone completely by {"enable": false} (and before every change).
SPLIT_TABLE, SPLIT_MARK, SPLIT_PREF = "2000", "0x2000", 1000


def _run(*cmd, inp=None):
    return subprocess.run(list(cmd), input=inp, capture_output=True, text=True)


def split_clear():
    for pref in (SPLIT_PREF, SPLIT_PREF + 1):
        for _ in range(300):
            if _run("ip", "-4", "rule", "del", "pref", str(pref)).returncode:
                break
    _run("ip", "-4", "route", "flush", "table", SPLIT_TABLE)
    _run("nft", "delete", "table", "inet", "crossbar_split")


def vpn_split(req):
    import ipaddress
    split_clear()
    if not req.get("enable"):
        print(json.dumps({"ok": True}))
        return
    dev = clean(req.get("dev"), "Network device", r"[A-Za-z0-9_.-]{1,15}", maxlen=15)
    gw = None
    if req.get("gateway"):
        try:
            gw = str(ipaddress.IPv4Address(req["gateway"]))
        except ValueError:
            fail("Gateway isn't an IPv4 address")

    def v4(x, what, net=True):
        try:
            n = ipaddress.ip_network(str(x), strict=False) if net else ipaddress.ip_address(str(x))
        except ValueError:
            fail(f"Not an address ({what}): {x}")
        return str(n) if n.version == 4 else None
    to = [n for n in (v4(x, "site") for x in (req.get("to") or [])[:256]) if n]
    frm = [n for n in (v4(x, "source", net=False) for x in (req.get("from") or [])[:4]) if n]
    dns = v4(req["dns"], "DNS", net=False) if req.get("dns") else None
    relay = req.get("dns_relay")
    if relay is not None and (not isinstance(relay, int) or not 1024 <= relay <= 65535):
        fail("Bad DNS relay port")
    gid = req.get("gid")
    if gid is not None:
        import grp
        try:
            if grp.getgrgid(int(gid)).gr_name != VPN_GROUP:
                fail("Bad app group")
        except (KeyError, ValueError, TypeError):
            fail("Bad app group")
        gid = int(gid)
    for k in ("all", dev):                        # replies arrive on the VPN for traffic sent there: loose check
        _run("sysctl", "-qw", f"net.ipv4.conf.{k}.rp_filter=2")
    route = ["ip", "-4", "route", "add", "default"] + (["via", gw] if gw else []) + ["dev", dev, "table", SPLIT_TABLE]
    r = _run(*route)
    if r.returncode:
        fail(f"Couldn't add the VPN route: {r.stderr.strip()}")
    for n in to:
        _run("ip", "-4", "rule", "add", "to", n, "lookup", SPLIT_TABLE, "pref", str(SPLIT_PREF))
    for a in frm:
        _run("ip", "-4", "rule", "add", "from", a, "lookup", SPLIT_TABLE, "pref", str(SPLIT_PREF))
    # Traffic sent into the VPN by these rules was sized for your normal connection (its route was
    # chosen first): TCP would announce a segment size that doesn't fit the tunnel, and the big replies
    # vanish (connections open, then hang). Clamp it to the tunnel's MTU. And anything leaving
    # through the VPN that doesn't already have the VPN's address gets it.
    common = f"""  chain mss {{
    type filter hook postrouting priority mangle; policy accept;
    oifname "{dev}" tcp flags & (syn | rst) == syn tcp option maxseg size set rt mtu
  }}
  chain post {{
    type nat hook postrouting priority srcnat; policy accept;
    oifname "{dev}" {"ip saddr != " + frm[0] + " " if frm else ""}masquerade
  }}
"""
    # The tunnel's own encrypted packets: WireGuard encrypts an app's packet in place, so the encrypted
    # copy can still look like the app's (same socket owner) and would be marked and sent back into
    # the tunnel — a loop, and the app's connection never gets anywhere. Leave them alone: by
    # WireGuard's own mark, and by the VPN server's address.
    ex = [v4(x, "VPN server", net=False) for x in (req.get("exempt") or [])[:8]]
    ex = [x for x in ex if x]
    emark = req.get("exempt_mark")
    if emark is not None and (not isinstance(emark, int) or not 0 < emark < 2 ** 32):
        fail("Bad mark")
    exempt = (f"    meta mark {emark:#x} return\n" if emark else "") + \
             (f"    ip daddr {{ {', '.join(ex)} }} return\n" if ex else "")
    if gid is not None:
        _run("ip", "-4", "rule", "add", "fwmark", SPLIT_MARK, "lookup", SPLIT_TABLE, "pref", str(SPLIT_PREF + 1))
        # DNS from VPN apps: to a local resolver (127.x, the usual stub) → Crossbar's relay, which asks
        # the VPN's DNS through the tunnel; to any other server → the VPN's DNS directly
        local = (f"""    meta mark {SPLIT_MARK} ip daddr 127.0.0.0/8 udp dport 53 dnat ip to 127.0.0.1:{relay}
    meta mark {SPLIT_MARK} ip daddr 127.0.0.0/8 tcp dport 53 dnat ip to 127.0.0.1:{relay}
""" if relay else "")
        dnat = (f"""  chain dns {{
    type nat hook output priority -100; policy accept;
{local}    meta mark {SPLIT_MARK} ip daddr != 127.0.0.0/8 udp dport 53 dnat ip to {dns}
    meta mark {SPLIT_MARK} ip daddr != 127.0.0.0/8 tcp dport 53 dnat ip to {dns}
  }}
""" if dns else "")
        rules = f"""table inet crossbar_split {{
  chain out {{
    type route hook output priority mangle; policy accept;
{exempt}    meta skgid {gid} meta mark set {SPLIT_MARK} counter
  }}
  chain v6 {{
    type filter hook output priority filter; policy accept;
    meta skgid {gid} meta nfproto ipv6 ip6 daddr != ::1 reject
  }}
{dnat}{common}}}
"""
        r = _run("nft", "-f", "-", inp=rules)
        if r.returncode:
            split_clear()
            fail(f"Couldn't set up split tunneling: {r.stderr.strip()[-200:]}")
    else:
        # no app group: still give anything leaving through the VPN the VPN's address
        r = _run("nft", "-f", "-", inp=f"""table inet crossbar_split {{
{common}}}
""")
        if r.returncode:
            fail(f"Couldn't set up split tunneling: {r.stderr.strip()[-200:]}")
    print(json.dumps({"ok": True, "sites": len(to), "apps": gid is not None, "dns": bool(dns)}))


VPN_GROUP = "crossbar-vpn"
PORT_STATE = "/var/lib/crossbar/vpn-port.json"


def vpn_port(req):
    """Let the VPN's forwarded port in through this computer's firewall — ufw or firewalld, if one
    is on — on the VPN interface only. The previous port is closed again."""
    dev = clean(req.get("dev"), "Network device", r"[A-Za-z0-9_.-]{1,15}", maxlen=15)
    try:
        port = int(req.get("port"))
    except (TypeError, ValueError):
        fail("Bad port")
    if not 1024 <= port <= 65535:
        fail("Bad port")
    try:
        old = json.load(open(PORT_STATE))
    except (OSError, ValueError):
        old = {}
    done = []
    if shutil.which("ufw") and "Status: active" in _run("ufw", "status").stdout:
        if old.get("ufw") and (old.get("port"), old.get("dev")) != (port, dev):
            _run("ufw", "--force", "delete", "allow", "in", "on", old["dev"], "to", "any", "port", str(old["port"]))
        r = _run("ufw", "allow", "in", "on", dev, "to", "any", "port", str(port), "comment", "Crossbar VPN forwarded port")
        if r.returncode:
            fail(f"ufw: {r.stderr.strip()[-160:]}")
        done.append("ufw")
    if shutil.which("firewall-cmd") and _run("firewall-cmd", "--state").returncode == 0:
        zone = _run("firewall-cmd", f"--get-zone-of-interface={dev}").stdout.strip()
        if not zone:
            zone = "trusted"                   # the VPN interface only ever receives the forwarded port
            _run("firewall-cmd", f"--zone={zone}", f"--add-interface={dev}")
        if old.get("firewalld") and old.get("port") != port:
            for proto in ("tcp", "udp"):
                _run("firewall-cmd", f"--zone={old.get('zone') or zone}", f"--remove-port={old['port']}/{proto}")
        for proto in ("tcp", "udp"):
            _run("firewall-cmd", f"--zone={zone}", f"--add-port={port}/{proto}")
        done.append("firewalld")
    os.makedirs(os.path.dirname(PORT_STATE), exist_ok=True)
    with open(PORT_STATE, "w") as f:
        json.dump({"port": port, "dev": dev, "ufw": "ufw" in done, "firewalld": "firewalld" in done,
                   "zone": locals().get("zone")}, f)
    print(json.dumps({"ok": True, "firewalls": done}))


def vpn_group(req):
    """The group apps that use the VPN run with (split tunneling); the person asking joins it."""
    import grp
    import pwd
    try:
        uid = int(os.environ.get("PKEXEC_UID", ""))
        user = pwd.getpwuid(uid).pw_name
    except (ValueError, KeyError):
        fail("Couldn't tell who asked")
    try:
        grp.getgrnam(VPN_GROUP)
    except KeyError:
        r = _run("groupadd", "--system", VPN_GROUP)
        if r.returncode:
            fail(f"Couldn't make the {VPN_GROUP} group: {r.stderr.strip()}")
    if user not in grp.getgrnam(VPN_GROUP).gr_mem:
        r = _run("gpasswd", "-a", user, VPN_GROUP)
        if r.returncode:
            fail(f"Couldn't add {user} to {VPN_GROUP}: {r.stderr.strip()}")
    print(json.dumps({"ok": True, "gid": grp.getgrnam(VPN_GROUP).gr_gid, "user": user}))


def vpn_split_status(req):
    """What's in place (for the split tunneling check): rules, routes, and how many packets were marked."""
    out = {"rules": _run("ip", "-4", "rule", "show").stdout[-3000:], "route": _run("ip", "-4", "route", "show", "table", SPLIT_TABLE).stdout,
           "nft": _run("nft", "list", "table", "inet", "crossbar_split").stdout[-3000:]}
    print(json.dumps({"ok": True, **out}))


if __name__ == "__main__":
    if os.geteuid() != 0:
        fail("crossbar-admin must run as root (via pkexec)")
    actions = {"nas-add": nas_add, "nas-remove": nas_remove, "nas-remount": nas_remount, "boot-session": boot_session,
               "ps5-fan-target": ps5_fan_target, "ps5-led": ps5_led, "ps5-control": ps5_control,
               "vpn-split": vpn_split, "vpn-group": vpn_group, "vpn-split-status": vpn_split_status, "vpn-port": vpn_port}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        fail("usage: admin.py " + "|".join(actions))
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        fail("bad request")
    actions[sys.argv[1]](req)
