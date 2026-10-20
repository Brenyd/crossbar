"""Start a program in the crossbar-vpn group, so split tunneling sends it through the VPN.

The firewall marks traffic from sockets whose group is crossbar-vpn (nft `meta skgid`), and the
marked traffic is routed through the VPN. Switching a process to that group needs a set-id
program: Arch has no `sg`, so this uses util-linux's `newgrp` (on every Arch system; it lets you
in without a password because you're listed in the group). newgrp only starts your login shell,
so the program is handed over in two steps:

  outer:  vpnrun.py -- PROGRAM ARGS…   saves the program, its environment and folder to a private
          file, puts a one-line `exec … inner FILE` on newgrp's standard input and becomes newgrp
  inner:  vpnrun.py inner FILE         (run by that shell, now in the group) reads the file back,
          deletes it, and becomes the program — same process all the way, same environment.

Stand-alone (standard library only) so the shell can run it by path.
"""
import grp
import json
import os
import shlex
import sys
import tempfile

GROUP = "crossbar-vpn"


def _gid():
    try:
        return grp.getgrnam(GROUP).gr_gid
    except KeyError:
        return None


def outer(argv):
    gid = _gid()
    if gid is None:
        sys.exit(f"vpnrun: the {GROUP} group doesn't exist yet")
    if os.getgid() == gid and os.getegid() == gid:
        os.execvp(argv[0], argv)
    base = os.environ.get("XDG_RUNTIME_DIR") or None
    fd, path = tempfile.mkstemp(prefix="cbvpn-", suffix=".json", dir=base if base and os.path.isdir(base) else None)
    with os.fdopen(fd, "w") as f:
        json.dump({"argv": argv, "env": dict(os.environ), "cwd": os.getcwd()}, f)
    line = "exec " + " ".join(shlex.quote(x) for x in (sys.executable or "/usr/bin/python3", os.path.abspath(__file__), "inner", path)) + "\n"
    r, w = os.pipe()
    os.write(w, line.encode())
    os.close(w)
    os.dup2(r, 0)
    os.close(r)
    try:
        os.execvp("newgrp", ["newgrp", GROUP])
    except OSError as e:
        os.unlink(path)
        sys.exit(f"vpnrun: couldn't start newgrp: {e}")


def inner(path):
    with open(path) as f:
        job = json.load(f)
    os.unlink(path)
    if os.getegid() != _gid():
        sys.exit("vpnrun: didn't get the VPN group (are you in crossbar-vpn?)")
    null = os.open(os.devnull, os.O_RDONLY)          # the shell's command pipe isn't the program's input
    os.dup2(null, 0)
    os.close(null)
    try:
        os.chdir(job.get("cwd") or "/")
    except OSError:
        pass
    os.execvpe(job["argv"][0], job["argv"], job["env"])


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == "inner":
        inner(a[1])
    elif a[:1] == ["--"] and len(a) > 1:
        outer(a[1:])
    else:
        sys.exit("usage: vpnrun.py -- PROGRAM [ARGS…]")
