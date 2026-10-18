"""File browser operations (Users › File Browser).

Limited to places a console user should manage: the home folder, removable
drives (/run/media, /media) and network/extra mounts (/mnt). Deleting moves to
the freedesktop Trash (~/.local/share/Trash) so mistakes can be undone.
"""
import datetime
import os
import shutil
import urllib.parse

from . import media, util

TRASH = os.path.join(util.HOME, ".local", "share", "Trash")


def _check(path, must_exist=True):
    path = os.path.realpath(os.path.expanduser(path))
    if not media.allowed(path):
        raise PermissionError("That folder can't be managed here")
    if must_exist and not os.path.exists(path):
        raise FileNotFoundError(path)
    return path


def kind(name, is_dir):
    if is_dir:
        return "folder"
    ext = os.path.splitext(name)[1].lower()
    for k, exts in media.KINDS.items():
        if ext in exts:
            return k
    return "file"


def listdir(path=None, hidden=False):
    path = _check(path or util.HOME)
    out = []
    for e in os.scandir(path):
        if e.name.startswith(".") and not hidden:
            continue
        try:
            st = e.stat()
            is_dir = e.is_dir()
        except OSError:
            continue
        out.append({"name": e.name, "path": e.path, "dir": is_dir, "kind": kind(e.name, is_dir),
                    "size": 0 if is_dir else st.st_size, "mtime": st.st_mtime})
    out.sort(key=lambda f: (not f["dir"], f["name"].lower()))
    usage = shutil.disk_usage(path)
    return {"path": path, "parent": os.path.dirname(path) if media.allowed(os.path.dirname(path)) and path != "/" else None,
            "entries": out, "free": usage.free, "total": usage.total}


def places():
    out = [{"name": "Home", "path": util.HOME}]
    for name in ("Downloads", "Games", "Music", "Videos", "Pictures", "Documents"):
        p = os.path.join(util.HOME, name)
        if os.path.isdir(p):
            out.append({"name": name, "path": p})
    for base in (f"/run/media/{os.environ.get('USER', '')}", "/media", "/mnt/nas", "/mnt"):
        if os.path.isdir(base):
            for e in sorted(os.scandir(base), key=lambda e: e.name):
                if e.is_dir() and not (base == "/mnt" and e.name == "nas"):
                    out.append({"name": ("Network: " if base == "/mnt/nas" else "") + e.name, "path": e.path, "drive": True})
    return out


def _unique(dest):
    if not os.path.exists(dest):
        return dest
    base, ext = os.path.splitext(dest)
    n = 2
    while os.path.exists(f"{base} ({n}){ext}"):
        n += 1
    return f"{base} ({n}){ext}"


def _size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for dp, _, fns in os.walk(path):
        for fn in fns:
            try:
                total += os.path.getsize(os.path.join(dp, fn))
            except OSError:
                pass
    return total


def paste(job, sources, dest_dir, move=False):
    """Copy (or move) files/folders into dest_dir, with progress. Never overwrites."""
    dest_dir = _check(dest_dir)
    if not os.path.isdir(dest_dir):
        raise NotADirectoryError(dest_dir)
    sources = [_check(s) for s in sources]
    for s in sources:
        if os.path.isdir(s) and (dest_dir + os.sep).startswith(s + os.sep):
            raise ValueError("Can't put a folder inside itself")
    total = sum(_size(s) for s in sources) or 1
    done = [0]

    def copy_file(src, dst, *a, **k):
        shutil.copy2(src, dst)
        done[0] += os.path.getsize(dst)
        job.set(done[0] / total, f"{int(100 * done[0] / total)}%")
        return dst

    for s in sources:
        target = _unique(os.path.join(dest_dir, os.path.basename(s)))
        if move:
            try:
                os.rename(s, target)          # same drive: instant
                done[0] += _size(target)
                continue
            except OSError:
                pass                          # other drive: copy then delete
        if os.path.isdir(s):
            shutil.copytree(s, target, copy_function=copy_file, symlinks=True)
        else:
            copy_file(s, target)
        if move:
            shutil.rmtree(s) if os.path.isdir(s) else os.remove(s)


def trash(paths):
    """Move to the freedesktop Trash (restorable from a file manager)."""
    files, info = os.path.join(TRASH, "files"), os.path.join(TRASH, "info")
    os.makedirs(files, exist_ok=True)
    os.makedirs(info, exist_ok=True)
    for p in paths:
        p = _check(p)
        if p == os.path.realpath(util.HOME):
            raise PermissionError("Can't delete your home folder")
        name = os.path.basename(_unique(os.path.join(files, os.path.basename(p))))
        with open(os.path.join(info, name + ".trashinfo"), "w") as f:
            f.write(f"[Trash Info]\nPath={urllib.parse.quote(p)}\nDeletionDate={datetime.datetime.now():%Y-%m-%dT%H:%M:%S}\n")
        shutil.move(p, os.path.join(files, name))


def delete_forever(paths):
    for p in paths:
        p = _check(p)
        if p == os.path.realpath(util.HOME):
            raise PermissionError("Can't delete your home folder")
        shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)


def _valid_name(name):
    name = (name or "").strip()
    if not name or "/" in name or name in (".", "..") or "\0" in name:
        raise ValueError("Not a valid name")
    return name


def rename(path, new_name):
    path = _check(path)
    target = os.path.join(os.path.dirname(path), _valid_name(new_name))
    if os.path.exists(target):
        raise FileExistsError("Something with that name already exists")
    os.rename(path, target)
    return target


def mkdir(parent, name):
    parent = _check(parent)
    target = os.path.join(parent, _valid_name(name))
    os.makedirs(target, exist_ok=False)
    return target


def empty_trash():
    for sub in ("files", "info"):
        d = os.path.join(TRASH, sub)
        if os.path.isdir(d):
            shutil.rmtree(d)
