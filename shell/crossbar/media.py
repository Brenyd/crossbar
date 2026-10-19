"""Local media library: folder browsing, tags, thumbnails, folder picker."""
import hashlib
import os
import subprocess
import threading

from . import util

AUDIO = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wav", ".wma", ".alac", ".ape", ".wv", ".mka"}
VIDEO = {".mkv", ".mp4", ".avi", ".mov", ".webm", ".m4v", ".wmv", ".ts", ".m2ts", ".mpg", ".mpeg", ".flv", ".ogv"}
PHOTO = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".tif", ".tiff"}
KINDS = {"music": AUDIO, "video": VIDEO, "photo": PHOTO}
DEFAULT_DIRS = {"music": "~/Music", "video": "~/Videos", "photo": "~/Pictures"}
THUMBS = os.path.join(util.HOME, ".cache", "crossbar", "thumbs")
# Paths the shell may read: the home folder and places removable/extra drives mount.
ALLOWED_ROOTS = [util.HOME, "/run/media", "/media", "/mnt"]

_tag_cache = {}
_thumb_lock = threading.Semaphore(3)


def allowed(path):
    real = os.path.realpath(path)
    return any(real == r or real.startswith(r.rstrip("/") + "/") for r in map(os.path.realpath, ALLOWED_ROOTS))


def root(kind):
    cfg = util.load_config()
    return os.path.expanduser(cfg["media"].get(kind) or DEFAULT_DIRS[kind])


def _tags(path):
    """Title/artist/album for a music file (mutagen if installed, else the file name)."""
    try:
        st = os.stat(path)
    except OSError:
        return {}
    key = (path, st.st_mtime)
    if key in _tag_cache:
        return _tag_cache[key]
    out = {}
    try:
        import mutagen
        f = mutagen.File(path, easy=True)
        if f and f.tags:
            for k in ("title", "artist", "album", "tracknumber"):
                v = f.tags.get(k)
                if v:
                    out[k] = str(v[0])
        if f and f.info and getattr(f.info, "length", None):
            out["length"] = int(f.info.length)
    except Exception:
        pass
    _tag_cache[key] = out
    return out


def listdir(kind, path=None):
    exts = KINDS[kind]
    base = root(kind)
    path = os.path.expanduser(path) if path else base
    if not allowed(path):
        raise PermissionError("Folder not allowed")
    dirs, files = [], []
    try:
        entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
    except FileNotFoundError:
        return {"path": path, "exists": False, "dirs": [], "files": []}
    for e in entries:
        if e.name.startswith("."):
            continue
        if e.is_dir():
            dirs.append({"name": e.name, "path": e.path})
        elif os.path.splitext(e.name)[1].lower() in exts:
            item = {"name": os.path.splitext(e.name)[0], "path": e.path}
            if kind == "music":
                t = _tags(e.path)
                item.update(t)
            files.append(item)
    if kind == "music":  # albums in track order when tags have numbers
        def tn(f):
            try:
                return int(str(f.get("tracknumber", "999")).split("/")[0])
            except ValueError:
                return 999
        files.sort(key=lambda f: (tn(f), f["name"].lower()))
    return {"path": path, "exists": True, "dirs": dirs, "files": files}


def scan(kind, limit=3000):
    """Every file of a kind under its library folder (for 'All Songs' / 'All Videos')."""
    exts, out = KINDS[kind], []
    for dp, dns, fns in os.walk(root(kind)):
        dns[:] = sorted(d for d in dns if not d.startswith("."))
        for fn in sorted(fns):
            if os.path.splitext(fn)[1].lower() in exts:
                p = os.path.join(dp, fn)
                item = {"name": os.path.splitext(fn)[0], "path": p}
                if kind == "music":
                    item.update(_tags(p))
                out.append(item)
                if len(out) >= limit:
                    return out
    return out


def browse_dirs(path=None, ext=None):
    """Folder picker: subfolders of path, or a list of starting places. ext (".zip"): also those files."""
    if not path:
        places = [{"name": "Home", "path": util.HOME}]
        for name in ("Music", "Videos", "Pictures", "Games", "Downloads"):
            p = os.path.join(util.HOME, name)
            if os.path.isdir(p):
                places.append({"name": name, "path": p})
        for base in ("/run/media/" + os.environ.get("USER", "player"), "/media", "/mnt"):
            if os.path.isdir(base):
                for e in sorted(os.scandir(base), key=lambda e: e.name):
                    if e.is_dir():
                        places.append({"name": f"Drive: {e.name}", "path": e.path})
        return {"path": None, "dirs": places}
    if not allowed(path):
        raise PermissionError("Folder not allowed")
    entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
    dirs = [{"name": e.name, "path": e.path} for e in entries if e.is_dir() and not e.name.startswith(".")]
    files = [{"name": e.name, "path": e.path} for e in entries
             if ext and e.is_file() and e.name.lower().endswith(ext.lower()) and not e.name.startswith(".")]
    return {"path": path, "dirs": dirs, "files": files}


# ---- artwork -------------------------------------------------------------
def _embedded_art(path):
    try:
        import mutagen
        f = mutagen.File(path)
        if f is None:
            return None
        if hasattr(f, "pictures") and f.pictures:            # FLAC / Ogg
            return f.pictures[0].data
        tags = f.tags or {}
        for k in list(getattr(tags, "keys", lambda: [])()):
            if str(k).startswith("APIC"):                       # MP3
                return tags[k].data
        if "covr" in tags:                                      # MP4/M4A
            return bytes(tags["covr"][0])
    except Exception:
        return None
    return None


def _folder_art(d):
    for n in ("cover.jpg", "cover.png", "folder.jpg", "folder.png", "front.jpg", "album.jpg", "Cover.jpg", "Folder.jpg"):
        p = os.path.join(d, n)
        if os.path.isfile(p):
            return p
    return None


def thumbnail(path, size=480):
    """Path to a cached JPEG thumbnail for a photo, video, music file or folder; None if unavailable."""
    if not allowed(path) or not os.path.exists(path):
        return None
    st = os.stat(path)
    key = hashlib.sha1(f"{path}:{st.st_mtime}:{size}".encode()).hexdigest()
    out = os.path.join(THUMBS, key + ".jpg")
    if os.path.exists(out):
        return out
    if os.path.exists(out + ".none"):
        return None
    os.makedirs(THUMBS, exist_ok=True)
    ext = os.path.splitext(path)[1].lower()
    with _thumb_lock:
        try:
            ok = False
            if ext in VIDEO:
                for ss in ("30", "3", "0"):
                    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", ss, "-i", path, "-frames:v", "1",
                                        "-vf", f"scale={size}:-2", out], capture_output=True, timeout=30)
                    if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out):
                        ok = True
                        break
            else:
                src = path
                data = None
                if os.path.isdir(path):
                    src = _folder_art(path)
                elif ext in AUDIO:
                    data = _embedded_art(path)
                    src = None if data else _folder_art(os.path.dirname(path))
                if src or data:
                    import io
                    from PIL import Image, ImageOps
                    im = Image.open(io.BytesIO(data) if data else src)
                    im = ImageOps.exif_transpose(im).convert("RGB")
                    im.thumbnail((size, size))
                    im.save(out, "JPEG", quality=85)
                    ok = True
            if not ok:
                open(out + ".none", "w").close()
                return None
            return out
        except Exception:
            open(out + ".none", "w").close()
            return None
