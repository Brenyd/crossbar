#!/usr/bin/env python3
"""crossbar-admin — the few system changes Crossbar makes as root (run via pkexec).

    pkexec /usr/lib/crossbar/admin.py nas-add      < {"name","type","server","share","username","password","domain"}
    pkexec /usr/lib/crossbar/admin.py nas-remove   < {"name"}
    pkexec /usr/lib/crossbar/admin.py nas-remount  < {"name"}

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


def nas_add(req):
    s = slug(req.get("name"))
    kind = req.get("type", "smb")
    if kind not in ("smb", "nfs"):
        fail("Type must be SMB or NFS")
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
        opts = (f"credentials={cred},uid={uid},gid={gid},iocharset=utf8,file_mode=0664,dir_mode=0775,"
                + ("guest," if not user else "") +
                "nofail,_netdev,x-systemd.automount,x-systemd.idle-timeout=600,x-systemd.mount-timeout=20")
        line = f"//{server}/{fstab_escape(share)} {point} cifs {opts} 0 0"
    else:
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


if __name__ == "__main__":
    if os.geteuid() != 0:
        fail("crossbar-admin must run as root (via pkexec)")
    actions = {"nas-add": nas_add, "nas-remove": nas_remove, "nas-remount": nas_remount}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        fail("usage: admin.py " + "|".join(actions))
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        fail("bad request")
    actions[sys.argv[1]](req)
