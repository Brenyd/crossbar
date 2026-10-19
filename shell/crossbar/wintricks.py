"""Windows Components for a game (Y › Windows & Proton › Windows Components…): Visual C++
runtimes, .NET, DirectX pieces, fonts, Windows version… installed into that game's own Wine /
Proton prefix with winetricks, the way protontricks does it.

Which prefix and which Wine:
  Steam / non-Steam  steamapps/compatdata/<appid>/pfx; through protontricks when it's installed
                     (it sets up Steam's runtime), else winetricks with the game's Proton.
  GOG / Epic         Crossbar's prefix for the game (Games/prefixes/…); through umu-run (its
                     Proton) or the system's Wine, whichever the game uses.
  Lutris             the prefix and Wine version in the game's Lutris settings.
What's installed comes from the prefix's winetricks.log, which winetricks keeps up to date.
"""
import glob
import os
import re
import signal
import subprocess

from . import util

# The components people actually need, grouped (the rest: Search All Components…)
CATALOGUE = [
    ("Runtimes", [
        ("vcrun2022", "Visual C++ 2015–2022", "Most games from the last 10 years"),
        ("vcrun2013", "Visual C++ 2013", ""),
        ("vcrun2012", "Visual C++ 2012", ""),
        ("vcrun2010", "Visual C++ 2010", ""),
        ("vcrun2008", "Visual C++ 2008", ""),
        ("vcrun2005", "Visual C++ 2005", "Older games"),
        ("dotnet48", ".NET Framework 4.8", "Launchers and tools; takes a while"),
        ("dotnet40", ".NET Framework 4.0", ""),
        ("dotnetdesktop8", ".NET Desktop Runtime 8", "Newer launchers and mod managers"),
        ("xna40", "XNA Framework 4.0", "Indie games built on XNA"),
        ("physx", "PhysX", "Older NVIDIA physics games"),
        ("openal", "OpenAL", "3D sound in older games"),
        ("vcrun6", "Visual Basic / C++ 6", "Very old games"),
        ("mfc140", "MFC 14", ""),
    ]),
    ("DirectX & Video", [
        ("d3dx9", "DirectX 9 (d3dx9)", "Fixes many DX9-era games"),
        ("d3dx10", "DirectX 10 (d3dx10)", ""),
        ("d3dx11_43", "DirectX 11 (d3dx11_43)", ""),
        ("d3dcompiler_47", "D3D Compiler 47", "Shader errors in newer games"),
        ("d3dcompiler_43", "D3D Compiler 43", ""),
        ("xact", "XACT audio (32-bit)", "No sound in older games"),
        ("xact_x64", "XACT audio (64-bit)", ""),
        ("xinput", "XInput", "Controller not detected in old games"),
        ("dxvk", "DXVK", "Direct3D 9–11 on Vulkan (Proton already has it)"),
        ("vkd3d", "VKD3D-Proton", "Direct3D 12 on Vulkan (Proton already has it)"),
        ("mf", "Media Foundation", "Cutscenes that don't play"),
        ("quartz", "DirectShow (quartz)", "Old video playback"),
        ("lavfilters", "LAV video filters", "Cutscene codecs"),
        ("wmp11", "Windows Media Player 11", "Some older video cutscenes"),
    ]),
    ("Fonts", [
        ("corefonts", "Microsoft Core Fonts", "Arial, Times New Roman… (missing text)"),
        ("tahoma", "Tahoma", ""),
        ("cjkfonts", "Chinese / Japanese / Korean fonts", "Boxes instead of text"),
        ("consolas", "Consolas", ""),
        ("lucida", "Lucida Console", ""),
        ("meiryo", "Meiryo (Japanese)", ""),
    ]),
    ("Windows Version", [
        ("win10", "Windows 10", "The usual"),
        ("win81", "Windows 8.1", ""),
        ("win7", "Windows 7", "Older launchers"),
        ("winxp", "Windows XP", "Very old games"),
    ]),
    ("Other", [
        ("gdiplus", "GDI+", "Launcher windows that look broken"),
        ("msxml3", "MSXML 3", ""),
        ("msxml6", "MSXML 6", ""),
        ("faudio", "FAudio", "XAudio sound"),
        ("dinput8", "DirectInput 8", "Mod loaders (e.g. dinput8.dll mods)"),
    ]),
]
SETTINGS = {"win10", "win81", "win7", "winxp"}            # not "installed": the current one is shown
PROTONTRICKS_FLATPAK = "com.github.Matoking.protontricks"
_VERB = re.compile(r"^[a-z0-9_][a-z0-9_.=+-]{0,60}$")


def _steam_libs():
    from .providers.steam import Steam
    return Steam()._library_dirs()


def _protontricks():
    if util.which("protontricks"):
        return ["protontricks"]
    for base in (os.path.join(util.HOME, ".local/share/flatpak"), "/var/lib/flatpak"):
        if os.path.isdir(os.path.join(base, "app", PROTONTRICKS_FLATPAK)):
            return ["flatpak", "run", PROTONTRICKS_FLATPAK]
    return None


def _proton_wine(appid):
    """The wine binary of the Proton a Steam game uses (its choice in Steam, else the newest)."""
    from . import launchopts, compat
    want = launchopts._steam_tool(appid)
    cands = []
    for root in launchopts._steam_roots():
        for vdf in glob.glob(os.path.join(root, "compatibilitytools.d", "*", "compatibilitytool.vdf")):
            tools = launchopts._sub(launchopts._read_vdf(vdf), "compatibilitytools", "compat_tools") or {}
            for internal in tools:
                cands.append((internal, os.path.dirname(vdf)))
    for p in compat.installed_protons():
        cands.append((launchopts._valve_proton_name(p["name"].replace(" (Steam)", "")) or p["id"], p["path"]))
    chosen = next((d for n, d in cands if want and n == want), None) or (cands[0][1] if cands else None)
    for sub in ("files/bin/wine", "dist/bin/wine"):
        if chosen and os.path.isfile(os.path.join(chosen, sub)):
            return os.path.join(chosen, sub)
    return None


def target(key):
    """{"prefix", "argv" (what goes before the verbs), "env", "how"} for one game."""
    kind, _, gid = str(key or "").partition(":")
    if kind in ("steam", "shortcut"):
        if not gid.isdigit():
            raise ValueError("game")
        pfx = next((os.path.join(lib, "compatdata", gid, "pfx") for lib in _steam_libs()
                    if os.path.isdir(os.path.join(lib, "compatdata", gid, "pfx"))), None)
        if not pfx:
            raise RuntimeError("Start the game once first: Proton makes its Windows folder the first time it runs")
        pt = _protontricks()
        if pt:
            return {"prefix": pfx, "argv": [*pt, gid, "-q"], "env": {}, "how": "protontricks"}
        wine = _proton_wine(gid)
        if not wine:
            raise RuntimeError("Couldn't find this game's Proton: install protontricks (Settings › System › Update Crossbar)")
        return {"prefix": pfx, "argv": ["winetricks", "-q"], "how": "winetricks with Proton",
                "env": {"WINEPREFIX": pfx, "WINE": wine, "WINESERVER": os.path.join(os.path.dirname(wine), "wineserver")}}
    if kind in ("gog", "epic"):
        from . import compat
        tool = compat.tool_for(key)
        pfx = compat.prefix_for(key)
        if tool and tool != "wine" and util.which("umu-run"):
            env = {"WINEPREFIX": pfx, "GAMEID": "umu-default", "PROTON_VERB": "run"}
            if tool != "umu":
                proton = next((p for p in compat.installed_protons() if p["id"] == tool), None)
                env["PROTONPATH"] = proton["path"] if proton else tool
            return {"prefix": pfx, "argv": ["umu-run", "winetricks", "-q"], "env": env, "how": "umu-run (Proton)"}
        return {"prefix": pfx, "argv": ["winetricks", "-q"], "env": {"WINEPREFIX": pfx}, "how": "winetricks (Wine)"}
    if kind == "lutris":
        from . import launchopts
        g = launchopts._lutris_game(gid)
        c = launchopts._lutris_cfg(g)
        game = c.get("game") or {}
        pfx = os.path.expanduser(str(game.get("prefix") or (c.get("wine") or {}).get("prefix") or ""))
        if not pfx or not os.path.isdir(pfx):
            raise RuntimeError("This Lutris game has no Wine prefix yet: run it once from Lutris")
        env = {"WINEPREFIX": pfx}
        ver = str((c.get("wine") or {}).get("version") or "")
        wine = os.path.join(g["base"], "runners", "wine", ver, "bin", "wine") if ver and ver != "system" else ""
        if wine and os.path.isfile(wine):
            env["WINE"] = wine
            env["WINESERVER"] = os.path.join(os.path.dirname(wine), "wineserver")
        return {"prefix": pfx, "argv": ["winetricks", "-q"], "env": env, "how": "winetricks (Lutris' Wine)"}
    raise ValueError("Windows Components are for Windows games")


def installed(prefix):
    try:
        with open(os.path.join(prefix, "winetricks.log"), errors="replace") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except OSError:
        return []


def status(key):
    t = target(key)
    have = installed(t["prefix"])
    ver = next((v for v in reversed(have) if v in SETTINGS), None)
    groups = [{"name": g, "items": [{"id": v, "name": n, "about": a, "installed": (v == ver) if v in SETTINGS else v in have}
                                    for v, n, a in items]} for g, items in CATALOGUE]
    ok = bool(util.which("winetricks")) or t["how"] == "protontricks"
    return {"key": key, "how": t["how"], "prefix": t["prefix"], "installed": have, "groups": groups, "available": ok}


_all = []


def all_components():
    """Everything winetricks knows: [{"id","name","group"}] (for Search All Components…)."""
    if _all:
        return _all
    if not util.which("winetricks"):
        raise RuntimeError("winetricks isn't installed (Settings › System › Update Crossbar installs it)")
    for group in ("dlls", "fonts", "settings", "apps"):
        r = subprocess.run(["winetricks", group, "list"], capture_output=True, text=True, timeout=60,
                           env={**os.environ, "WINEPREFIX": os.path.join(util.HOME, ".cache/crossbar/wt-list")})
        for ln in r.stdout.splitlines():
            m = re.match(r"^([a-z0-9_][\w.=+-]*)\s+(.+)$", ln.strip())
            if m and _VERB.match(m.group(1)):
                _all.append({"id": m.group(1), "name": m.group(2).strip(), "group": group})
    return _all


def install(job, key, verbs):
    verbs = [v for v in (verbs or []) if isinstance(v, str)]
    if not verbs or not all(_VERB.match(v) for v in verbs):
        raise ValueError("components")
    t = target(key)
    if t["how"] != "protontricks" and not util.which("winetricks"):
        raise RuntimeError("winetricks isn't installed (Settings › System › Update Crossbar installs it)")
    job.set(0.03, f"Installing {', '.join(verbs)} ({t['how']})…")
    p = subprocess.Popen([*t["argv"], *verbs], env={**os.environ, **t["env"]}, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True)

    def stop():
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    job.cancel_with(stop)
    tail, done = [], 0
    for line in p.stdout:
        line = line.strip()
        if not line:
            continue
        tail = (tail + [line])[-6:]
        m = re.match(r"Executing (?:w_do_call|load_)\s*(\S+)", line)
        if m:
            done += 1
            job.set(min(0.95, 0.05 + 0.9 * done / (len(verbs) + 1)), f"Installing {m.group(1)}…")
        elif re.search(r"Downloading|Extracting", line):
            job.set(None, line[:90])
    if p.wait():
        if job.cancelled():
            return
        err = next((x for x in reversed(tail) if re.search(r"error|failed|not found|couldn't", x, re.I)), tail[-1] if tail else "")
        raise RuntimeError(f"winetricks failed: {err[:200]}")
    job.set(1.0, "Installed")
