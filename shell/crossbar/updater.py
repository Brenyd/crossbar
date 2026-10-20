"""Update Crossbar from a branch of the GitHub repo (Settings › System › Update Branch).

main is the default; a test branch (like testing/xbox-360-interface) can be picked, and main
picked again later — every update installs the chosen branch as a whole, so switching back and
forth is just another update. The installed branch is recorded next to the code (BRANCH).
"""
import json
import os
import re
import shlex
import urllib.request

from . import util

REPO = "Brenyd/crossbar"
DEFAULT = "main"
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
SHELL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def valid(name):
    return bool(name and _BRANCH_RE.match(name) and ".." not in name and not name.endswith((".", "/", ".lock")))


def chosen():
    b = util.load_config().get("update_branch") or DEFAULT
    return b if valid(b) else DEFAULT


def installed():
    """The branch this copy of Crossbar came from (unknown for copies installed before 1.1.5)."""
    try:
        with open(os.path.join(SHELL_DIR, "BRANCH")) as f:
            b = f.read().strip()
        return b if valid(b) else None
    except OSError:
        return None


def installed_version():
    try:
        with open(os.path.join(SHELL_DIR, "VERSION")) as f:
            return f.read().strip()
    except OSError:
        return None


def branches():
    """Branches on GitHub, main first."""
    names = []
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/branches?per_page=100",
                                     headers={"User-Agent": "Crossbar", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            names = [b["name"] for b in json.loads(r.read().decode()) if valid(b.get("name"))]
        error = None
    except (OSError, ValueError, KeyError, TypeError) as e:
        error = f"Couldn't list the branches on GitHub: {util.friendly_net_error('https://api.github.com', e)}"
    for b in (DEFAULT, chosen(), installed()):
        if b and b not in names:
            names.append(b)
    names.sort(key=lambda n: (n != DEFAULT, n.lower()))
    return {"branches": names, "chosen": chosen(), "installed": installed(), "version": installed_version(), "error": error}


def choose(name):
    name = (name or "").strip()
    if not valid(name):
        raise ValueError("That isn't a branch name")
    util.update_config(lambda c: c.__setitem__("update_branch", name))
    return {"chosen": name}


def command():
    """The update, as run in the terminal: download the chosen branch, record which branch and
    version it is inside the copy (so it's installed with it), then run that branch's own
    update-system.sh."""
    b = chosen()
    url = f"https://github.com/{REPO}/archive/refs/heads/{b}.tar.gz"
    return ('d=$(mktemp -d) && mkdir "$d/src" && cd "$d/src" && '
            f"echo {shlex.quote('Downloading Crossbar (' + b + ')…')} && "
            f"curl -fL {shlex.quote(url)} | tar xz --strip-components=1 && "
            f"printf '%s\\n' {shlex.quote(b)} > shell/BRANCH && cp VERSION shell/VERSION 2>/dev/null; "
            "sudo ./update-system.sh")
