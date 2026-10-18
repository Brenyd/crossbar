"""Network drives (Settings › Network Settings › Network Drives).

Reading is done here (fstab is world-readable); changes go through the root
helper admin.py via pkexec, which polkit allows for the console user.
"""
import json
import os
import subprocess

from . import util

ADMIN = "/usr/lib/crossbar/admin.py"
MARK = "# crossbar-nas:"


def _unescape(s):
    return s.replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")


def drives():
    try:
        lines = open("/etc/fstab").read().splitlines()
    except OSError:
        return []
    mounted = set()
    try:
        mounted = {ln.split()[1] for ln in open("/proc/mounts")}
    except OSError:
        pass
    out = []
    for i, ln in enumerate(lines[:-1]):
        if not ln.strip().startswith(MARK):
            continue
        name, _, label = ln.strip()[len(MARK):].partition(" ")
        parts = lines[i + 1].split()
        if len(parts) < 3:
            continue
        src, point, fstype = parts[0], parts[1], parts[2]
        out.append({"name": name, "label": label or name, "source": _unescape(src), "path": point, "type": "smb" if fstype == "cifs" else "nfs",
                    "mounted": point in mounted})
    return out


def _admin(action, req):
    if not os.path.exists(ADMIN):
        raise RuntimeError("Network drives need the Crossbar system helper (update Crossbar)")
    if not util.which("pkexec"):
        raise RuntimeError("polkit (pkexec) isn't installed")
    r = subprocess.run(["pkexec", ADMIN, action], input=json.dumps(req), capture_output=True, text=True, timeout=90)
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        msg = (r.stderr or r.stdout).strip()[-200:]
        if r.returncode in (126, 127):
            msg = "Not allowed — your account needs to be an administrator (in the 'wheel' group)"
        raise RuntimeError(msg or "The system helper failed") from None
    if not res.get("ok"):
        raise RuntimeError(res.get("error", "failed"))
    return res


def add(job, req):
    job.set(0.2, "Checking the NAS…")
    req = {k: req.get(k, "") for k in ("name", "type", "server", "share", "username", "password", "domain")}
    req["gid"] = os.getgid()
    res = _admin("nas-add", req)
    if not res.get("mounted"):
        raise RuntimeError(f"Saved, but it didn't connect: {res.get('error') or 'check the server, share and password'}")


def remove(name):
    return _admin("nas-remove", {"name": name})


def remount(name):
    return _admin("nas-remount", {"name": name})
