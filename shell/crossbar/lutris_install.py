"""Run a Lutris install script with Lutris's own installer engine, without its window — Crossbar asks
every question on the TV instead. Run with the Python that has Lutris installed (the system one, or
the Lutris Flatpak's: flatpak run --command=python3 net.lutris.Lutris this-file …).

    lutris_install.py '<json job>'
        job: {"slug": game slug, "version": installer version (or "script_file": a local .yml script),
              "target": install folder, "files": {file id: path the user picked}}

Talks JSON lines: events on stdout ({"event": …}), answers to questions on stdin ({"answer": …}).
Standard library + Lutris + PyGObject only (it runs inside Lutris's Python).
"""
import inspect
import json
import os
import sys

# This file lives next to Crossbar's own modules (one of them is called lutris.py): never let those
# shadow the real Lutris package.
_here = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != _here]
import threading
import time
import traceback
import urllib.request

_out_lock = threading.Lock()


def emit(event, **kw):
    with _out_lock:
        sys.stdout.write(json.dumps({"event": event, **kw}, default=str) + "\n")
        sys.stdout.flush()


def ask(event, **kw):
    """A question for the person: blocks until Crossbar answers (the install waits meanwhile)."""
    emit(event, **kw)
    line = sys.stdin.readline()
    if not line:
        raise SystemExit("Crossbar went away")
    return json.loads(line)


def _point_at_wrapper():
    """Lutris finds its lutris-wrapper script (which every install command runs through) next to the
    program that started it: sys.argv[0]/../share/lutris/bin. Started as this helper — and in the Flatpak,
    where Lutris lives under /app — that misses, so find the real prefix and say Lutris was started from there."""
    import shutil
    rel = os.path.join("share", "lutris", "bin", "lutris-wrapper")
    prefixes = []
    exe = shutil.which("lutris")
    if exe:
        prefixes.append(os.path.dirname(os.path.dirname(os.path.realpath(exe))))
    prefixes += [sys.prefix, sys.base_prefix, "/app", "/usr", "/usr/local", os.path.expanduser("~/.local")]
    try:
        import lutris
        d = os.path.dirname(os.path.abspath(lutris.__file__))
        while d != os.path.dirname(d):                      # …/lib/python3.x/site-packages/lutris → walk up
            d = os.path.dirname(d)
            prefixes.append(d)
    except Exception:
        pass
    for pre in prefixes:
        if os.path.isfile(os.path.join(pre, rel)):
            sys.argv[0] = os.path.join(pre, "bin", "lutris")
            return os.path.join(pre, rel)
    return None


def main():
    job = json.loads(sys.argv[1])
    if not _point_at_wrapper():
        emit("error", text="Lutris's lutris-wrapper script is missing, so it can't run install commands. "
                           "Reinstall Lutris (Install Apps › Lutris), then try again.")
        return 2
    os.environ.setdefault("LUTRIS_SKIP_INIT", "1")
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib

    try:
        from lutris.startup import init_lutris
        init_lutris()
    except Exception as e:                                        # older Lutris: the dirs exist already
        emit("log", line=f"init: {e}")
    from lutris.installer import interpreter as interp_mod
    from lutris.gui.dialogs.delegates import InstallUIDelegate

    loop = GLib.MainLoop()
    state = {"done": False}

    class Delegate(interp_mod.ScriptInterpreter.InterpreterUIDelegate, InstallUIDelegate):
        def __init__(self):
            interp_mod.ScriptInterpreter.InterpreterUIDelegate.__init__(self)

        def report_error(self, error):
            emit("error", text=str(error) or error.__class__.__name__,
                 detail=str(getattr(error, "faulty_data", "") or "")[:600])
            state["done"] = True
            loop.quit()

        def report_status(self, status):
            emit("status", text=str(status))

        def report_progress(self, fraction, text=""):
            emit("progress", fraction=fraction, text=text or "")

        def attach_log(self, command):
            emit("status", text="Running the installer's commands…")

        def begin_disc_prompt(self, message, requires, installer, callback):
            a = ask("ask_disc", message=_plain(message), requires=requires)
            path = a.get("path")
            if path:
                callback(None, requires, path)
            else:
                callback(None, requires)                          # autodetect

        def begin_input_menu(self, alias, options, preselect, callback):
            opts = []
            for o in options:
                (k, label), = dict(o).items()
                opts.append([str(k), str(label)])
            a = ask("ask_menu", alias=alias, options=opts, preselect=preselect)

            class Choice:                                          # what Lutris reads from its combo box
                def get_active_id(self_inner):
                    return a.get("answer") or preselect or (opts[0][0] if opts else "")
            callback(alias, Choice())

        def report_finished(self, game_id, status):
            emit("finished", game_id=game_id, text=_plain(status))
            state["done"] = True
            loop.quit()

        # runner installs (Wine and others) ask these
        def show_install_yesno_inquiry(self, question, title):
            return bool(ask("ask_yesno", question=_plain(question), title=title).get("answer"))

        def show_install_file_inquiry(self, question, title, message):
            return ask("ask_file", question=_plain(question), title=title, message=_plain(message)).get("path")

        def download_install_file(self, url, destination):
            return _download(url, destination, "Downloading a runner…")

    delegate = Delegate()
    if job.get("script_file"):                       # a local script: Lutris's own loader ("Install from a local script")
        from lutris.installer import get_installers
        installers = get_installers(installer_file=job["script_file"])
        if not installers:
            emit("error", text="Lutris couldn't read that script")
            return 2
        script = next((i for i in installers if str(i.get("version")) == str(job.get("version"))), installers[0])
    else:
        from lutris.api import get_game_installers
        installers = get_game_installers(job["slug"])
        script = next((i for i in installers if str(i.get("version")) == str(job.get("version"))), None)
        if not script:
            emit("error", text=f"Lutris has no installer called {job.get('version')} for {job['slug']} any more")
            return 2
    try:
        interp = interp_mod.ScriptInterpreter(script, delegate)
    except Exception as e:
        emit("error", text=str(e), detail=str(getattr(e, "faulty_data", "") or "")[:600], kind=e.__class__.__name__,
             slug=getattr(e, "slug", None))
        return 2
    if job.get("target") and interp.installer.creates_game_folder:
        interp.target_path = os.path.expanduser(job["target"])
    emit("started", game=interp.installer.game_name, target=interp.target_path, runner=interp.installer.runner)

    def on_files_prepared(_result=None, error=None):
        if error:
            delegate.report_error(error)
            return
        threading.Thread(target=get_files, daemon=True).start()

    def get_files():
        try:
            files = list(interp.installer.files or [])
            user = job.get("files") or {}
            for n, f in enumerate(files):
                url = f.url
                if url.startswith("N/A"):
                    path = user.get(f.id)
                    if not path or not os.path.exists(path):
                        raise RuntimeError(f"Choose the file for “{f.get_label() if hasattr(f, 'get_label') else f.id}” first")
                    f.override_dest_file(path)
                    emit("status", text=f"Using your file: {os.path.basename(path)}")
                elif url.startswith("$STEAM"):
                    raise RuntimeError("This installer needs files from Steam: install it in Lutris itself")
                elif getattr(f, "is_cached", False) and os.path.exists(f.dest_file):
                    emit("status", text=f"Already downloaded: {os.path.basename(f.dest_file)}")
                else:
                    f.prepare()
                    if not os.path.exists(f.dest_file):
                        if not _download(url, f.dest_file, f"Downloading {f.filename or f.id} ({n + 1} of {len(files)})",
                                         referer=getattr(f, "referer", None)):
                            raise RuntimeError(f"Couldn't download {url}")
                    f.check_hash()
            interp.game_files = {k: v for f in files for k, v in f.get_dest_files_by_id().items()}
            GLib.idle_add(start_commands)
        except Exception as e:
            GLib.idle_add(delegate.report_error, e)

    def start_commands():
        try:
            emit("status", text="Installing…")
            if hasattr(interp.installer, "install_extras"):
                interp.installer.install_extras()
            interp.launch_installer_commands()
        except Exception as e:
            delegate.report_error(e)
        return False

    def on_runners_ready(*_a):
        emit("status", text="Preparing the game's files…")
        from lutris.util.jobs import AsyncCall
        prep = interp.installer.prepare_game_files
        args = [[]] + ([None] if len(inspect.signature(prep).parameters) >= 2 else [])
        AsyncCall(prep, on_files_prepared, *args)

    interp.connect("runners-installed", on_runners_ready)

    def go():
        try:
            emit("status", text="Checking the runner (Wine, emulator…)…")
            interp.launch_install(delegate)
        except Exception as e:
            delegate.report_error(e)
        return False
    GLib.idle_add(go)
    loop.run()
    return 0 if state["done"] else 1


def _plain(text):
    import re
    return re.sub(r"<[^>]+>", "", str(text or "")).strip()


def _download(url, dest, label, referer=None):
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = dest + ".tmp"
    if url.startswith("file://"):
        import shutil
        shutil.copyfile(url[7:], dest)
        return True
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Lutris"}
    if referer:
        headers["Referer"] = referer
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, 0
        while True:
            chunk = r.read(1 << 17)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if time.time() - last > 0.5:
                last = time.time()
                emit("progress", fraction=(done / total) if total else None, text=label, done=done, total=total)
    os.replace(tmp, dest)
    return True


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except SystemExit:
        raise
    except BaseException as e:
        emit("error", text=str(e) or e.__class__.__name__, detail=traceback.format_exc()[-1500:])
        sys.exit(1)
