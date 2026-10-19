"""Per-game launch options: environment variables, a launch command and the Proton / Wine
version, edited from the XMB (Y › Launch Options…) for Steam, Lutris, GOG and Epic games.

The launch command uses Steam's convention, everywhere:
    DXVK_HUD=fps gamemoderun %command% -dx11
i.e. variables first, then what goes in front of the game, %command% for the game itself,
then the game's own arguments. Variables are kept in their own list in the XMB, so you
rarely need to type them.

Where each thing is kept (so the launcher's own UI shows the same settings):
  Steam      LaunchOptions in userdata/<you>/config/localconfig.vdf, and the Proton version in
             config/config.vdf (CompatToolMapping). Steam reads those when it starts and writes
             them back when it quits, so a change is saved for later and put in place the next
             time Crossbar starts that game (closing and reopening Steam first if it's running),
             or straight away with "Apply Now".
  Non-Steam  (games you added to Steam) the Proton version, the same way.
  Lutris     the game's own .yml (system › env, system › prefix_command, game › args, wine › version).
  GOG, Epic  Crossbar's own settings (they run through umu-launcher / Proton, chosen per game).
"""
import glob
import os
import re
import shlex
import sqlite3
import time
import urllib.parse

from . import util

# ---- "%command%" strings --------------------------------------------------------------------
_ENV = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def split_options(s):
    """'A=1 B="x y" gamemoderun %command% -dx11' -> ({'A': '1', 'B': 'x y'}, ['gamemoderun'], ['-dx11'])"""
    try:
        toks = shlex.split(s or "")
    except ValueError:
        toks = (s or "").split()
    env = {}
    while toks and _ENV.match(toks[0]):
        k, _, v = toks.pop(0).partition("=")
        env[k] = v
    if "%command%" in toks:
        i = toks.index("%command%")
        return env, toks[:i], toks[i + 1:]
    return env, [], toks                      # no %command%: it's all arguments for the game (Steam's rule)


def join_options(env, pre, post):
    parts = [f"{k}={shlex.quote(str(v))}" for k, v in (env or {}).items()] + [shlex.quote(x) for x in pre or []]
    if parts or post:
        parts.append("%command%")
    parts += [shlex.quote(x) for x in post or []]
    return " ".join(parts) if (env or pre or post) else ""


def command_only(s):
    """The command part of a full string (without the leading variables): '%command%' when empty."""
    _, pre, post = split_options(s)
    return join_options({}, pre, post) or "%command%"


def _clean_env(env):
    out = {}
    for k, v in (env or {}).items():
        k = str(k).strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
            raise ValueError(f"“{k}” isn't a valid variable name (letters, digits and _ only)")
        out[k] = str(v)
    return out


def _clean_command(cmd):
    cmd = (cmd or "").strip()
    if len(cmd) > 1000:
        raise ValueError("That command is too long")
    if cmd and "%command%" not in cmd:
        cmd = "%command% " + cmd                  # plain text = arguments for the game
    env, pre, post = split_options(cmd)
    if env:
        raise ValueError("Put variables in Environment Variables, not in the command")
    return pre, post


# ---- Valve text KeyValues that round-trips (escapes and order kept as they are) -------------------
_TOK = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])|//[^\n]*')


def vdf_load(text):
    root, key = {}, None
    stack = [root]
    for m in _TOK.finditer(text):
        s, brace = m.group(1), m.group(2)
        if brace == "{":
            d = {}
            stack[-1][key if key is not None else ""] = d
            stack.append(d)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif s is None:
            continue                               # a // comment
        elif key is None:
            key = s
        else:
            stack[-1][key] = s                     # kept escaped, exactly as Steam wrote it
            key = None
    return root


def vdf_dump(d, depth=0):
    out = []
    tab = "\t" * depth
    for k, v in d.items():
        if isinstance(v, dict):
            out.append(f'{tab}"{k}"\n{tab}{{\n{vdf_dump(v, depth + 1)}{tab}}}\n')
        else:
            out.append(f'{tab}"{k}"\t\t"{v}"\n')
    return "".join(out)


def _esc(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def _unesc(s):
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s or "")


def _sub(d, *path, create=False):
    """Walk nested keys case-insensitively (Steam isn't consistent: "apps" / "Apps")."""
    for p in path:
        if not isinstance(d, dict):
            return None
        k = next((x for x in d if x.lower() == p.lower()), None)
        if k is None:
            if not create:
                return None
            d[p] = {}
            k = p
        d = d[k]
    return d


def _read_vdf(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return vdf_load(f.read())


def _write_vdf(path, data):
    tmp = path + ".crossbar-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(vdf_dump(data))
    if os.path.exists(path) and not os.path.exists(path + ".crossbar-backup"):
        import shutil
        shutil.copy2(path, path + ".crossbar-backup")    # the first time only: Steam's original
    os.replace(tmp, path)


# ---- Steam -------------------------------------------------------------------------------------
def _steam_roots():
    from .providers.steam import steam_roots
    return steam_roots()


def _localconfigs():
    """Every signed-in Steam user's localconfig.vdf, the most recently used first."""
    out = []
    for root in _steam_roots():
        out += glob.glob(os.path.join(root, "userdata", "*", "config", "localconfig.vdf"))
    return sorted(out, key=lambda p: os.path.getmtime(p), reverse=True)


def _steam_launch_options(appid):
    for p in _localconfigs():
        try:
            apps = _sub(_read_vdf(p), "UserLocalConfigStore", "Software", "Valve", "Steam", "apps")
        except OSError:
            continue
        app = _sub(apps or {}, str(appid))
        if isinstance(app, dict):
            lo = next((v for k, v in app.items() if k.lower() == "launchoptions"), None)
            if lo is not None:
                return _unesc(lo)
        return ""
    return ""


def _steam_tool(appid):
    for root in _steam_roots():
        try:
            m = _sub(_read_vdf(os.path.join(root, "config", "config.vdf")),
                     "InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping", str(appid))
        except OSError:
            continue
        if isinstance(m, dict):
            return _unesc(next((v for k, v in m.items() if k.lower() == "name"), "")) or ""
    return ""


def _valve_proton_name(dirname):
    """'Proton 9.0' -> 'proton_9', 'Proton 6.3' -> 'proton_63', 'Proton - Experimental' -> 'proton_experimental'."""
    low = dirname.lower()
    if "experimental" in low:
        return "proton_experimental"
    if "hotfix" in low:
        return "proton_hotfix"
    m = re.search(r"proton (\d+)\.(\d+)", low)
    if not m:
        return None
    major, minor = int(m.group(1)), m.group(2)
    return f"proton_{major}" if major >= 7 or minor == "0" else f"proton_{major}{minor}"


def steam_tools():
    out = [{"id": "", "name": "Steam's Default", "note": "Whatever Steam › Compatibility is set to"}]
    seen = set()
    for root in _steam_roots():
        for vdf in sorted(glob.glob(os.path.join(root, "compatibilitytools.d", "*", "compatibilitytool.vdf")), reverse=True):
            try:
                tools = _sub(_read_vdf(vdf), "compatibilitytools", "compat_tools") or {}
            except OSError:
                continue
            for internal, info in tools.items():
                if internal not in seen and isinstance(info, dict):
                    seen.add(internal)
                    out.append({"id": internal, "name": _unesc(info.get("display_name") or internal), "note": "Installed"})
        from .compat import _steam_libraries
        libs = [root] + _steam_libraries()
        for lib in libs:
            for d in sorted(glob.glob(os.path.join(lib, "steamapps", "common", "Proton*")), reverse=True):
                name = _valve_proton_name(os.path.basename(d))
                if name and name not in seen and os.path.isfile(os.path.join(d, "proton")):
                    seen.add(name)
                    out.append({"id": name, "name": os.path.basename(d), "note": "Valve"})
    return out


def _pending():
    p = util.load_config().get("launchopts_pending")
    return p if isinstance(p, dict) else {}


def _apply_steam(appid, options=None, tool=None):
    """Write straight into Steam's files (Steam must not be running)."""
    if options is not None:
        for p in _localconfigs():
            data = _read_vdf(p)
            app = _sub(data, "UserLocalConfigStore", "Software", "Valve", "Steam", "apps", str(appid), create=True)
            k = next((x for x in app if x.lower() == "launchoptions"), "LaunchOptions")
            app[k] = _esc(options)
            _write_vdf(p, data)
    if tool is not None:
        for root in _steam_roots():
            path = os.path.join(root, "config", "config.vdf")
            if not os.path.exists(path):
                continue
            data = _read_vdf(path)
            mapping = _sub(data, "InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping", create=True)
            if tool:
                mapping[str(appid)] = {"name": _esc(tool), "config": "", "priority": "250"}
            else:
                for k in [k for k in mapping if k == str(appid)]:
                    del mapping[k]
            _write_vdf(path, data)


def steam_needs_apply(appid=None):
    p = _pending()
    return bool(p.get(str(appid))) if appid is not None else bool(p)


def apply_pending(progress=None, appid=None):
    """Put saved Steam changes in place: closes Steam first if it's running (it would overwrite
    them), and starts it again afterwards. Returns True if Steam was restarted."""
    from .providers import steam as st
    pend = _pending()
    if appid is not None:
        pend = {k: v for k, v in pend.items() if k == str(appid)}
    if not pend:
        return False
    progress = progress or (lambda m: None)
    was = st.steam_running()
    if was:
        progress("Closing Steam to save your launch options…")
        close_steam()
    for a, ch in pend.items():
        _apply_steam(a, ch.get("options"), ch.get("tool"))
    util.update_config(lambda c: [c.setdefault("launchopts_pending", {}).pop(a, None) for a in pend])
    return was


def close_steam(timeout=90):
    from .providers import steam as st
    util.spawn(["steam", "-shutdown"])
    end = time.time() + timeout
    while time.time() < end:
        if not st.steam_running():
            time.sleep(1.5)                  # let it finish writing its files
            return
        time.sleep(1)
    raise RuntimeError("Steam didn't close, so the launch options couldn't be saved: try again")


# ---- Lutris -------------------------------------------------------------------------------------
def _lutris_game(gid):
    from .extgames import LUTRIS_DIRS
    for base in LUTRIS_DIRS:
        db = os.path.join(base, "pga.db")
        if not os.path.isfile(db):
            continue
        try:
            con = sqlite3.connect(f"file:{urllib.parse.quote(db)}?mode=ro", uri=True, timeout=2)
            row = con.execute("SELECT configpath, runner, name FROM games WHERE id = ?", (int(gid),)).fetchone()
            con.close()
        except sqlite3.Error:
            continue
        if row and row[0]:
            for d in (os.path.join(base, "games"), os.path.join(util.HOME, ".config/lutris/games")):
                y = os.path.join(d, f"{row[0]}.yml")
                if os.path.isfile(y):
                    return {"yml": y, "runner": row[1] or "", "name": row[2], "base": base}
    raise RuntimeError("Couldn't find that game's Lutris settings")


def _yaml():
    try:
        import yaml
        return yaml
    except ImportError:
        raise RuntimeError("Editing Lutris games needs python-yaml (Settings › System › Update Crossbar installs it)") from None


def _lutris_cfg(g):
    with open(g["yml"]) as f:
        return _yaml().safe_load(f) or {}


def lutris_tools(g):
    out = [{"id": "", "name": "Lutris' Default", "note": "Whatever Lutris › Wine is set to"}]
    d = os.path.join(g["base"], "runners", "wine")
    if os.path.isdir(d):
        out += [{"id": n, "name": n, "note": "Installed"} for n in sorted(os.listdir(d), reverse=True) if not n.startswith(".")]
    out.append({"id": "system", "name": "System Wine", "note": "The Wine installed on this system"})
    return out


# ---- reading and saving -----------------------------------------------------------------------------
def _parse_key(key):
    kind, _, rest = str(key or "").partition(":")
    if kind not in ("steam", "shortcut", "lutris", "gog", "epic") or not re.fullmatch(r"[\w.-]{1,120}", rest):
        raise ValueError("Launch options aren't available for this")
    return kind, rest


def get(key):
    kind, gid = _parse_key(key)
    if kind in ("steam", "shortcut"):
        appid = gid
        pend = _pending().get(appid) or {}
        opts = pend["options"] if pend.get("options") is not None else (_steam_launch_options(appid) if kind == "steam" else "")
        tool = pend["tool"] if pend.get("tool") is not None else _steam_tool(appid)
        env, pre, post = split_options(opts)
        tools = steam_tools()
        return {"key": key, "kind": "steam", "env": env, "command": join_options({}, pre, post) or "%command%",
                "can_command": kind == "steam", "tool": tool, "tools": tools,
                "tool_name": next((t["name"] for t in tools if t["id"] == tool), tool or "Steam's Default"),
                "pending": bool(pend)}
    if kind == "lutris":
        g = _lutris_game(gid)
        c = _lutris_cfg(g)
        system = c.get("system") or {}
        env = {str(k): str(v) for k, v in (system.get("env") or {}).items()}
        pre = shlex.split(system.get("prefix_command") or "")
        post = shlex.split(str((c.get("game") or {}).get("args") or ""))
        wine = g["runner"] == "wine"
        tools = lutris_tools(g) if wine else []
        tool = str((c.get("wine") or {}).get("version") or "") if wine else ""
        return {"key": key, "kind": "lutris", "env": env, "command": join_options({}, pre, post) or "%command%",
                "can_command": True, "tool": tool, "tools": tools, "runner": g["runner"],
                "tool_name": next((t["name"] for t in tools if t["id"] == tool), tool or "Lutris' Default"), "pending": False}
    # GOG / Epic: run by Crossbar
    from . import compat
    o = (util.load_config().get("launchopts") or {}).get(key) or {}
    tools = compat.tools()
    tool = (compat.cfg().get("games") or {}).get(key) or ""
    return {"key": key, "kind": "native", "env": dict(o.get("env") or {}), "command": o.get("command") or "%command%",
            "can_command": True, "tool": tool, "tools": [{"id": "", "name": "Default", "note": "Game Settings › Windows Games"}] + tools,
            "tool_name": next((t["name"] for t in tools if t["id"] == tool), "Default"), "pending": False}


def save(key, env=None, command=None, tool=None):
    """Change any of env (dict), command (string with %command%), tool (id, "" = default)."""
    kind, gid = _parse_key(key)
    cur = get(key)
    env = _clean_env(cur["env"] if env is None else env)
    pre, post = _clean_command(cur["command"] if command is None else command)
    if tool is not None and tool != "" and tool not in [t["id"] for t in cur["tools"]]:
        raise ValueError("That Proton / Wine version isn't installed")
    if kind in ("steam", "shortcut"):
        change = {}
        if kind == "steam":
            change["options"] = join_options(env, pre, post)
        if tool is not None:
            change["tool"] = tool
        util.update_config(lambda c: c.setdefault("launchopts_pending", {}).setdefault(gid, {}).update(change))
        from .providers import steam as st
        if not st.steam_running():                # nothing to fight with: put it in place now
            apply_pending(appid=gid)
    elif kind == "lutris":
        g = _lutris_game(gid)
        c = _lutris_cfg(g)
        system = c.setdefault("system", {}) or {}
        c["system"] = system
        if env:
            system["env"] = env
        else:
            system.pop("env", None)
        if pre:
            system["prefix_command"] = shlex.join(pre)
        else:
            system.pop("prefix_command", None)
        game = c.setdefault("game", {}) or {}
        c["game"] = game
        if post:
            game["args"] = shlex.join(post)
        else:
            game.pop("args", None)
        if tool is not None and g["runner"] == "wine":
            wine = c.setdefault("wine", {}) or {}
            c["wine"] = wine
            if tool:
                wine["version"] = tool
            else:
                wine.pop("version", None)
        tmp = g["yml"] + ".crossbar-tmp"
        with open(tmp, "w") as f:
            _yaml().safe_dump(c, f, default_flow_style=False, sort_keys=False)
        os.replace(tmp, g["yml"])
    else:
        def upd(c):
            lo = c.setdefault("launchopts", {})
            if env or pre or post:
                lo[key] = {"env": env, "command": join_options({}, pre, post) or "%command%"}
            else:
                lo.pop(key, None)
        util.update_config(upd)
        if tool is not None:
            from . import compat
            compat.set_game(key, tool or None)
    return get(key)


def reset(key):
    kind, _ = _parse_key(key)
    return save(key, env={}, command="", tool="")


def native(key):
    """For games Crossbar runs itself: (env, things to put before the game, extra arguments)."""
    o = (util.load_config().get("launchopts") or {}).get(key) or {}
    _, pre, post = split_options(o.get("command") or "")
    return dict(o.get("env") or {}), pre, post
