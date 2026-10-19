'use strict';
// Settings, organised into folders like the original: Display, Sound, Theme,
// Media, Network, Accounts, System. Loaded last; starts the shell.

const check = (on) => (on ? '✓ ' : '');

// Open a Settings sub-folder directly (used by "Wi-Fi" in Network, missing-folder hints…).
function openSettingsFolder(id) {
  const f = SETTINGS_FOLDERS.find((x) => x.key === id);
  S.stack = [];
  S.ci = CATS.findIndex((c) => c.id === 'settings');
  render();
  openFolder(f);
}

const hz = (r) => (r > 0 ? `${(r / 1000).toFixed(2)} Hz` : 'Auto');

async function changeMode(o, m) {
  const prev = o.current;
  const r1 = await call(() => api.post('/api/display/mode', { name: o.name, ...m, save: false }));
  if (!r1) return;
  const r = await Dialog.ask({ title: 'Display Settings', body: `${m.width} × ${m.height}${m.refresh > 0 ? ` at ${hz(m.refresh)}` : ''}\nKeep this setting?`,
    buttons: ['Keep', 'Revert'], def: 1, timeout: 15000, timeoutButton: 1 });
  if (r.button === 0) await api.post('/api/display/mode', { name: o.name, ...m, save: true });
  else await api.post('/api/display/mode', { name: o.name, width: prev.width, height: prev.height, refresh: prev.refresh, custom: !o.listed, save: false });
  reloadFolder();
}

function pickFolder(kind) {
  const depth = S.stack.length;
  const node = (path, name) => ({
    key: `pick:${path || 'root'}`, label: name || `Choose ${KIND_NAME[kind]} Folder`, icon: 'folder',
    children: async () => {
      const r = await api.get(`/api/fs?${q({ path: path || '' })}`);
      const items = [];
      if (r.path) {
        items.push({ key: 'use', label: 'Use This Folder', icon: 'check', sub: r.path, action: async () => {
          S.state = await api.post('/api/media/folder', { kind, path: r.path });
          S.stack.length = depth;
          render();
          reloadFolder();
          ['music', 'video', 'photo'].forEach(refresh);
          toast(`${KIND_NAME[kind]} folder: ${r.path}`, 'folder');
        } });
      }
      items.push(...r.dirs.map((d) => node(d.path, d.name)));
      return items.length ? items : [{ key: 'none', label: 'No folders', icon: 'info' }];
    },
  });
  openFolder(node(null));
}

async function setVideo(patch) {
  S.state = await api.post('/api/settings', { video: patch });
  reloadFolder();
}

function deviceFolder(kind) {
  const label = kind === 'outputs' ? 'Output Device' : 'Input Device';
  return { key: `dev:${kind}`, label, icon: kind === 'outputs' ? 'sound' : 'mic',
    children: async () => {
      const d = await api.get('/api/audio/devices');
      const list = d[kind];
      if (!list.length) return [{ key: 'none', label: 'No devices found', icon: 'info', sub: 'Needs PipeWire' }];
      return list.map((x) => ({ key: `ad:${x.id}`, label: x.name, icon: x.default ? 'check' : (kind === 'outputs' ? 'sound' : 'mic'),
        sub: x.default ? 'In use' : '', action: async () => {
          await call(() => api.post('/api/audio-device', { id: x.id }), `${label}: ${x.name}`);
          reloadFolder();
        } }));
    } };
}

// ---- Controller & Keyboard -------------------------------------------------
const KEY_LABELS = { ArrowUp: '↑', ArrowDown: '↓', ArrowLeft: '←', ArrowRight: '→', Escape: 'Esc', Backspace: 'Backspace',
  PageUp: 'Page Up', PageDown: 'Page Down', Space: 'Space', Enter: 'Enter', Tab: 'Tab', Home: 'Home' };
const keyLabel = (k) => KEY_LABELS[k] || (k.length === 1 ? k.toUpperCase() : k);
async function savedControls(r, msg) {
  await loadState();           // the XMB's keyboard map comes from state
  if (msg) toast(msg, 'game');
  reloadFolder();
  return r;
}

async function capturePad(a, add, c, combo = false) {
  const viaBackend = c.pads.devices.length > 0;
  const browserSees = (navigator.getGamepads ? [...navigator.getGamepads()].filter(Boolean) : []).length > 0;
  if (!viaBackend && !browserSees) return message('No controller found. Connect one, press any button on it, and try again.', 'Controller');
  const what = combo ? `Hold two buttons together for “${a.name}”` : `Press the button for “${a.name}”`;
  const cap = viaBackend
    ? api.post('/api/controls/capture', { timeout: 10, combo }).then((x) => x.token)
    : browserCapture(combo);
  const dlg = Dialog.ask({ title: 'Controller Buttons', body: what, buttons: ['Cancel'], timeout: 10000, timeoutButton: null });
  const r = await Promise.race([cap.then((t) => ({ tok: t })), dlg.then((x) => ({ dlg: x }))]);
  if (r.dlg) { if (viaBackend) api.post('/api/controls/cancel'); else pad.capture = null; return; }
  Dialog.close(0);
  if (!r.tok) return toast('No button pressed', 'info');
  const tokens = add ? [...c.gamepad[a.id], r.tok] : [r.tok];
  const res = await call(() => api.post('/api/controls', { kind: 'gamepad', action: a.id, tokens }));
  if (res) savedControls(res, `${a.name}: ${res.labels[r.tok] || r.tok}`);
}

async function captureKey(a, add, c) {
  const got = new Promise((res) => { KeyCapture.active = (k) => { KeyCapture.active = null; res(k); }; });
  const dlg = Dialog.ask({ title: 'Keyboard Keys', body: `Press the key for “${a.name}”\n(wait to cancel)`, buttons: ['Cancel'],
    timeout: 8000, timeoutButton: null });
  const r = await Promise.race([got.then((k) => ({ key: k })), dlg.then((x) => ({ dlg: x }))]);
  KeyCapture.active = null;
  if (r.dlg) return;
  Dialog.close(0);
  const keys = add ? [...c.keyboard[a.id], r.key] : [r.key];
  const res = await call(() => api.post('/api/controls', { kind: 'keyboard', action: a.id, tokens: keys }));
  if (res) savedControls(res, `${a.name}: ${keyLabel(r.key)}`);
}

function bindingItems(kind) {
  return async () => {
    const c = await api.get('/api/controls');
    return c.actions.map((a) => {
      const toks = c[kind][a.id];
      const label = (t) => (kind === 'gamepad' ? c.labels[t] || t : keyLabel(t));
      const capture = (add, combo) => () => (kind === 'gamepad' ? capturePad(a, add, c, combo) : captureKey(a, add, c));
      return {
        key: `${kind}:${a.id}`, label: a.name, icon: kind === 'gamepad' ? 'game' : 'browser',
        sub: toks.length ? [...new Set(toks.map(label))].join(' · ') : 'Not set',
        action: capture(false),
        options: [
          { label: 'Change…', action: capture(false) },
          { label: `Add Another ${kind === 'gamepad' ? 'Button' : 'Key'}…`, action: capture(true) },
          ...(kind === 'gamepad' ? [{ label: 'Use a Button Combo…', action: capture(false, true) },
                                    { label: 'Add a Button Combo…', action: capture(true, true) }] : []),
          { label: 'Reset to Default', action: async () => savedControls(await api.post('/api/controls', { reset: kind, action: a.id }), `${a.name} reset`) },
        ],
      };
    });
  };
}

async function showDiagnostics() {
  const d = await api.get('/api/diagnostics');
  const p = d.pads;
  const when = (t) => `${Math.max(0, Math.round(Date.now() / 1000 - t))}s ago`;
  const lines = [
    `Controller service: ${p.mode === 'inputd' ? 'running' : p.mode === 'direct' ? 'NOT running — reading controllers directly' : p.mode}${p.inputd_error ? ' (' + p.inputd_error + ')' : ''}`,
    `Controllers Crossbar reads: ${p.devices.length ? p.devices.join(', ') : 'none'}`,
    p.virtual?.length ? `Steam virtual pads (held, not read): ${p.virtual.join(', ')}` : '',
    `Controllers the menu's browser sees: ${p.browser_pads?.length ? p.browser_pads.join(', ') : 'none'}`,
    p.unreadable.length ? `Found but NOT readable: ${p.unreadable.join(', ')}` : '',
    !p.available ? 'python-evdev missing — controllers only work in the menu' : '',
    `Web-app controls (/dev/uinput): ${d.uinput ? 'OK' : 'no access'}${p.uinput_error ? ' — ' + p.uinput_error : ''}`,
    `Window in front: ${d.focused ? (d.focused.app || '?') + ' — ' + (d.focused.title || '') : 'not in the Crossbar session'}`,
    `Menu window found: ${d.xmb_window ? 'yes' : 'no'} · Quick Menu screenshots: ${d.grim ? 'yes' : 'no (grim missing)'}`,
    `Groups: ${d.user_groups.join(' ')}`,
    '',
    'Last buttons (newest first):',
    ...(d.recent_input.length ? d.recent_input.slice(0, 6).map((e) => `  ${e.token} → ${e.action || '—'} → ${e.to}  (${when(e.t)})`) : ['  none yet — press something, then open this again']),
    '',
    'Full report: Ctrl+Alt+T, then run crossbar-doctor',
  ].filter((x) => x !== '');
  message(lines.join('\n'), 'Controller Diagnostics');
}

const CONTROLS_FOLDER = {
  key: 'controls', label: 'Controller & Keyboard', icon: 'game', sub: 'Button and key mapping',
  children: async () => {
    const c = await api.get('/api/controls');
    const pads = c.pads.devices;
    return [
      { key: 'devices', label: 'Connected Controllers', icon: 'game',
        sub: pads.length ? pads.join(', ') : (c.pads.browser_pads?.length ? `${c.pads.browser_pads.join(', ')} (menu only — see Diagnostics)` : 'None connected'),
        action: () => message(pads.length ? pads.join('\n') : 'No controller detected.\nUSB and Bluetooth pads appear here once connected.', 'Controllers') },
      ...(c.pads.error ? [{ key: 'warn', label: 'Controller Not Readable', icon: 'info', sub: c.pads.error, action: showDiagnostics }] : []),
      { key: 'glyphs', label: 'Button Glyphs', icon: 'game',
        sub: (() => { const g = S.state.glyphs || {}; const n = { xbox: 'Xbox', playstation: 'PlayStation', nintendo: 'Nintendo' };
          return g.setting === 'auto' || !g.setting ? `Automatic — ${n[g.style] || 'Xbox'} (from the connected controller)` : n[g.setting]; })(),
        action: () => {
          const cur = S.state.glyphs?.setting || 'auto';
          const opts = [['auto', 'Automatic (match the controller)'], ['xbox', 'Xbox — A B X Y'], ['playstation', 'PlayStation — ✕ ○ □ △'], ['nintendo', 'Nintendo — B A Y X']];
          Options.show(opts.map(([v, l]) => ({ label: `${check(cur === v)}${l}`, action: async () => { await setSetting({ glyphs: v }); await loadState(); reloadFolder(); } })),
            Math.max(0, opts.findIndex(([v]) => v === cur)));
        } },
      { key: 'pad', label: 'Controller Buttons', icon: 'game', sub: 'Choose what each button does', children: bindingItems('gamepad') },
      { key: 'diag', label: 'Controller Diagnostics', icon: 'info', sub: 'What Crossbar sees, and the last buttons pressed', action: showDiagnostics },
      { key: 'kbd', label: 'Keyboard Keys', icon: 'browser', sub: 'Choose what each key does', children: bindingItems('keyboard') },
      { key: 'guide', label: 'Guide / PS Button Opens Quick Menu', icon: 'game',
        sub: c.guide_home ? 'On — Steam\'s overlay won\'t get that button' : 'Off — left free for Steam (Quick Menu: Select + Start)',
        action: async () => savedControls(await api.post('/api/controls/guide', { on: !c.guide_home }),
          c.guide_home ? 'Guide/PS left to Steam' : 'Guide/PS opens the Quick Menu') },
      { key: 'swap', label: 'Swap Select and Back', icon: 'refresh', sub: 'Confirm with the right face button instead of the bottom one (or back again)',
        action: async () => savedControls(await api.post('/api/controls', { swap: true }), 'Select and Back swapped') },
      { key: 'reset', label: 'Reset All to Defaults', icon: 'refresh', sub: 'Controller and keyboard',
        action: async () => { if (await confirmBox('Reset all buttons and keys to the defaults?')) savedControls(await api.post('/api/controls', { reset: 'all' }), 'Controls reset'); } },
    ];
  },
};

async function wifiConnect(w) {
  let password = '';
  if (w.secure && !w.connected) {
    const r = await Dialog.ask({ title: w.ssid, fields: [{ key: 'pw', label: 'Password', secret: true }], buttons: ['Connect', 'Cancel'] });
    if (r.button !== 0) return;
    password = r.values.pw;
  }
  await call(() => api.post('/api/wifi', { ssid: w.ssid, password }), `Connecting to ${w.ssid}…`);
  pollJobs();
}

async function timezoneFolder() {
  const zones = await api.get('/api/timezones');
  const regions = {};
  for (const z of zones) (regions[z.split('/')[0]] ||= []).push(z);
  return Object.keys(regions).sort().map((r) => ({
    key: `tz:${r}`, label: r, icon: 'folder', sub: `${regions[r].length} zones`,
    children: async () => regions[r].map((z) => ({ key: z, label: z.split('/').slice(1).join(' / ').replace(/_/g, ' ') || z, icon: 'network',
      action: async () => { await call(() => api.post('/api/time/zone', { zone: z }), `Time zone: ${z}`); S.stack.length -= 1; reloadFolder(); } })),
  }));
}

async function runInTerminal(path, label) {
  const r = await call(() => api.post(path));
  if (r?.cmd) { toast(label, 'system'); Term.show(r.cmd); }
}

async function pickCompatTool(gameKey, title) {
  const c = await api.get(`/api/compat?game=${encodeURIComponent(gameKey || '')}`);
  if (!c.tools.length) return message('No way to run Windows games yet.\nInstall umu-launcher: Settings › System › Terminal, then\nsudo pacman -S umu-launcher', 'Windows Games');
  const current = gameKey ? (c.games[gameKey] || '') : c.default;
  const opts = (gameKey ? [{ id: '', name: `Use Default (${c.tools.find((t) => t.id === c.default)?.name || c.default})` }] : []).concat(c.tools);
  Options.show(opts.map((t) => ({
    label: `${t.id === current ? '✓ ' : ''}${t.name}`,
    action: async () => {
      await call(() => api.post(gameKey ? '/api/compat/game' : '/api/compat/default', gameKey ? { game: gameKey, tool: t.id } : { tool: t.id }),
        gameKey ? `${title}: ${t.id ? t.name : 'default'}` : `Default: ${t.name}`);
      if (S.stack.length) reloadFolder();
    },
  })), Math.max(0, opts.findIndex((t) => t.id === current)));
}

const COMPAT_FOLDER = {
  key: 'compat', label: 'Windows Games (Proton / Wine)', icon: 'game', sub: 'Default compatibility tool, Proton versions',
  children: async () => {
    const c = await api.get('/api/compat');
    const def = c.tools.find((t) => t.id === c.default);
    return [
      { key: 'default', label: 'Default Tool', icon: 'game', sub: def ? def.name : 'umu-launcher isn\'t installed', action: () => pickCompatTool(null) },
      { key: 'tools', label: 'Compatibility Tools', icon: 'download', sub: 'GE-Proton, Proton-CachyOS, Wine-GE, DXVK… (ProtonUp-Qt\'s list)',
        children: async () => {
          const cat = await api.get('/api/compat/catalogue');
          const items = cat.tools.map((t) => ({
            key: `tool:${t.id}`, label: t.name, icon: t.installed ? 'check' : 'download', badge: t.for.toUpperCase(),
            sub: t.available ? `${t.about}${t.installed ? ` · ${t.installed} installed` : ''}` : `${t.about} · needs ${t.for}`,
            children: async () => {
              if (!t.available) return [{ key: 'na', label: `Install ${t.for} first`, icon: 'info', sub: 'Store › Install Apps › Flatpak has it' }];
              const rel = await api.get(`/api/compat/tool?id=${t.id}`);
              if (!rel.length) return [{ key: 'none', label: 'No releases found', icon: 'info', sub: 'GitHub may be rate-limiting: try again in a while' }];
              return rel.map((r) => ({
                key: `compat:${t.id}:${r.id}`, label: r.id, icon: r.installed ? 'check' : 'download', badge: r.pre ? 'PREVIEW' : '',
                sub: `${r.installed ? 'Installed · {ok} remove · ' : ''}${r.date} · ${Math.round(r.size / 1048576)} MB`,
                action: r.installed
                  ? async () => { if (await confirmBox(`Remove ${t.name} ${r.id}?`)) { await call(() => api.post('/api/compat/tool-remove', { tool: t.id, tag: r.id }), `Removed ${r.id}`); reloadFolder(); } }
                  : async () => { await call(() => api.post('/api/compat/tool-install', { tool: t.id, tag: r.id }), `Downloading ${t.name} ${r.id}…`); pollJobs(); },
              }));
            },
          }));
          items.push(cat.app.installed
            ? { key: 'pupgui', label: 'Open ProtonUp-Qt', icon: 'window', sub: 'The full app (keyboard and mouse) — Quick Menu to come back',
                action: () => call(() => api.post('/api/apps/launch', { key: `flatpak:${cat.app.id}`, name: 'ProtonUp-Qt' })) }
            : { key: 'pupgui', label: 'Get ProtonUp-Qt', icon: 'add', sub: 'The desktop app, from Flathub (shows up in Apps)',
                action: async () => { if (await call(() => api.post('/api/apps/install-flatpak', { id: 'net.davidotek.pupgui2', name: 'ProtonUp-Qt', category: 'apps' }), 'Installing ProtonUp-Qt…')) pollJobs(); } });
          return items;
        } },
      { key: 'how', label: 'How This Works', icon: 'info', action: () => message('Windows games from GOG and Epic run through umu-launcher with Proton, like on a Steam Deck.\nEach game gets its own Wine prefix in Games/prefixes.\nPick a different tool for one game with Y › Compatibility Tool on that game.\nSteam games use Steam\'s own Proton settings: tools installed for Steam show up there after Steam restarts.\nTools for Lutris show up in Lutris\' runner options.', 'Windows Games') },
    ];
  },
};

const GAMES_FOLDER = {
  key: 'games', label: 'Game Settings', icon: 'game', sub: 'Launching, hidden games, demo library',
  children: async () => {
    const st = S.state;
    return [
      COMPAT_FOLDER,
      HIDDEN_FOLDER,
      { key: 'bpm', label: 'Launch Steam Games in Big Picture', icon: 'game',
        sub: st.steam_bigpicture ? 'On — Steam\'s console mode starts the game, then hides when you\'re done' : 'Off — launch directly',
        action: async () => { await setSetting({ steam_bigpicture: !st.steam_bigpicture }); reloadFolder(); } },
      { key: 'gs', label: 'Run GOG & Epic Games in Gamescope', icon: 'display',
        sub: !st.gamescope_available ? 'Gamescope isn\'t installed' : st.gamescope ? 'On — fixed resolution, better frame pacing' : 'Off — games run directly',
        action: async () => { if (st.gamescope_available) { await setSetting({ gamescope: !st.gamescope }); reloadFolder(); } } },
      { key: 'freemem', label: 'Free Memory While Gaming', icon: 'game',
        sub: st.free_memory_in_games !== false ? 'On — the menu closes while a game runs; Quick Menu, music and voice keep working' : 'Off — the menu stays open behind games',
        action: async () => { await setSetting({ free_memory_in_games: st.free_memory_in_games === false }); reloadFolder(); } },
      { key: 'fps', label: 'Frame Rate Overlay', icon: 'display',
        sub: !st.perf?.available ? 'Needs MangoHud (installed with Crossbar 0.11)' : `${({ off: 'Off', fps: 'FPS only', graph: 'FPS + frame time graph', full: 'Full: FPS, CPU, GPU, temperatures' })[st.perf.fps] || st.perf.fps} · ${st.perf.corner.replace('-', ' ')} — also in the Quick Menu`,
        children: async () => {
          const p = (await api.get('/api/quick')).perf || {};
          const pick = async (body) => { await call(() => api.post(body.mode ? '/api/perf/fps' : '/api/perf/corner', body)); S.state = await api.get('/api/state'); reloadFolder(); };
          return [
            ...[['off', 'Off'], ['fps', 'FPS Only'], ['graph', 'FPS + Frame Time Graph'], ['full', 'Full (CPU, GPU, Temperatures)']].map(([m, l]) => ({
              key: `m:${m}`, label: l, icon: p.fps === m ? 'check' : 'display', sub: p.fps === m ? 'Current' : '', action: () => pick({ mode: m }) })),
            ...['top-right', 'top-left', 'bottom-left', 'bottom-right'].map((c) => ({
              key: `c:${c}`, label: `Position: ${c.replace('-', ' ').replace(/\b\w/g, (x) => x.toUpperCase())}`, icon: p.corner === c ? 'check' : 'display',
              sub: p.corner === c ? 'Current' : '', action: () => pick({ corner: c }) })),
            { key: 'how', label: 'Which Games?', icon: 'info', sub: 'Vulkan games, incl. Windows games through Proton',
              action: () => message('The frame rate overlay is MangoHud. It works in Vulkan games, including Windows games running through Proton.\nSteam games get it when Crossbar starts Steam; if Steam was already open, restart Steam once.', 'Frame Rate Overlay') },
          ];
        } },
      { key: 'steamov', label: 'Steam Overlay', icon: 'info', sub: 'Works in Steam games: Steam button or Shift+Tab. Crossbar\'s Quick Menu: Select + Start',
        action: () => message('Steam games run through Steam, so Steam\'s overlay works as usual (Steam/Guide button or Shift+Tab).\nCrossbar\'s Quick Menu uses Select + Start so the two never fight over a button.\nChange either in Controller & Keyboard.', 'Steam Overlay') },
      { key: 'demo', label: 'Demo Library', icon: 'demo', sub: st.demo ? 'On — showing sample games' : 'Off — using your real accounts',
        action: async () => {
          if (await confirmBox(st.demo ? 'Switch to your real Steam, GOG and Epic accounts?' : 'Show the demo library instead of your accounts?')) {
            await setSetting({ demo: !st.demo }); refresh('game'); refresh('store'); reloadFolder();
          }
        } },
    ];
  },
};

async function addNas() {
  const r = await Dialog.ask({ title: 'Add Network Drive', buttons: ['SMB (Windows / Samba)', 'NFS', 'Cancel'],
    body: 'Most NAS boxes (Synology, QNAP, TrueNAS, Windows shares) use SMB.' });
  if (r.button === 2 || r.button === null) return;
  const smb = r.button === 0;
  const f = await Dialog.ask({ title: smb ? 'SMB Network Drive' : 'NFS Network Drive', buttons: ['Connect', 'Cancel'],
    fields: [
      { key: 'name', label: 'Name (shown in Crossbar, e.g. "NAS Movies")' },
      { key: 'server', label: 'Server (IP address or name, e.g. 192.168.1.20)' },
      { key: 'share', label: smb ? 'Share name (e.g. Media)' : 'Export path (e.g. /volume1/media)' },
      ...(smb ? [{ key: 'username', label: 'Username (leave empty for guest access)' },
                 { key: 'password', label: 'Password', secret: true },
                 { key: 'domain', label: 'Domain / workgroup (usually empty)' }] : []),
    ] });
  if (f.button !== 0) return;
  if (!f.values.name.trim() || !f.values.server.trim() || !f.values.share.trim()) return toast('Name, server and share are needed', 'info');
  await call(() => api.post('/api/nas/add', { ...f.values, type: smb ? 'smb' : 'nfs' }), `Connecting ${f.values.name}…`);
  pollJobs();
  setTimeout(() => S.stack.length && reloadFolder(), 4000);
}

const NAS_ITEM = {
  key: 'nas', label: 'Network Drives', icon: 'folder', sub: 'NAS and shared folders (SMB / NFS)',
  children: async () => {
    const drives = await api.get('/api/nas').catch(() => []);
    return [
      ...drives.map((d) => ({
        key: `nas:${d.name}`, label: d.label, icon: d.mounted ? 'check' : 'folder',
        sub: `${d.source} · ${d.mounted ? 'Connected' : 'Connects when opened'} · ${d.path}`,
        action: () => openFolder(folderNode(d.path, d.label)),
        options: [
          { label: 'Open in File Browser', action: () => openFolder(folderNode(d.path, d.label)) },
          { label: 'Use as Music / Video / Photo Folder…', action: () => Options.show(['music', 'video', 'photo'].map((k) => ({
            label: `${KIND_NAME[k]} Folder`, action: async () => { S.state = await api.post('/api/media/folder', { kind: k, path: d.path }); toast(`${KIND_NAME[k]} folder: ${d.label}`, 'folder'); refresh(k); } }))) },
          { label: 'Reconnect', action: async () => { await call(() => api.post('/api/nas/remount', { name: d.name }), 'Reconnected'); reloadFolder(); } },
          { label: 'Remove', action: async () => { if (await confirmBox(`Remove ${d.label}?\nFiles on the NAS aren\'t touched.`)) { await call(() => api.post('/api/nas/remove', { name: d.name }), `Removed ${d.label}`); reloadFolder(); } } },
        ],
      })),
      { key: 'add', label: 'Add Network Drive…', icon: 'add', sub: 'Saved permanently; connects automatically when used', action: addNas },
    ];
  },
};

// Per-app volume: every app playing sound right now. ◀ ▶ adjusts, A mutes, Y for set levels.
const APP_VOLUME_FOLDER = {
  key: 'appvol', label: 'App Volume', icon: 'sound', sub: 'Volume for each app playing sound (also in the Quick Menu)',
  children: async () => {
    const apps = await api.get('/api/audio/apps').catch(() => []);
    if (!apps.length) return [{ key: 'none', label: 'Nothing is playing sound', icon: 'info', sub: 'Apps show up here while they play audio' }];
    const set = async (a, body) => { await call(() => api.post('/api/audio/app', { ids: a.ids, ...body })); reloadFolder(); };
    return apps.map((a) => ({
      key: `app:${a.key}`, label: a.name, icon: 'sound',
      sub: `${a.muted ? 'Muted' : `${a.volume}%`}${a.sub ? ' · ' + a.sub : ''}`, progress: a.muted ? 0 : Math.min(1, a.volume / 100),
      action: () => set(a, { mute: !a.muted }),
      options: [
        { label: a.muted ? 'Unmute' : 'Mute', action: () => set(a, { mute: !a.muted }) },
        { label: 'Louder (+10%)', action: () => set(a, { delta: 10 }) },
        { label: 'Quieter (−10%)', action: () => set(a, { delta: -10 }) },
        ...[100, 75, 50, 25].map((v) => ({ label: `Set to ${v}%`, action: () => set(a, { delta: v - a.volume }) })),
      ],
    }));
  },
};

// Settings › Media › Browser: how big it draws, bookmarks on its start page
const BROWSER_SETTINGS = {
  key: 'browser', label: 'Browser', icon: 'browser', sub: 'Size on screen, bookmarks',
  children: async () => {
    const d = await api.get('/api/browser/bookmarks');
    const sizes = ['auto', 1, 1.25, 1.5, 1.75, 2, 2.25, 2.5, 2.75, 3, 3.5, 4];
    const pct = (v) => `${Math.round(v * 100)}%`;
    return [
      { key: 'size', label: 'Size', icon: 'display', sub: `${pct(d.size)} — bigger reads better from the couch`,
        children: async () => sizes.map((v) => ({ key: `s:${v}`, label: v === 'auto' ? 'Automatic (made for this screen)' : pct(v), icon: 'display',
          sub: v === 'auto' ? '125% at 1080p, 250% at 4K' : '',
          action: async () => { if (await call(() => api.post('/api/browser/size', { value: v }), 'Browser size saved')) reloadFolder(); } })) },
      { key: 'marks', label: 'Bookmarks', icon: 'folder', sub: `${d.bookmarks.length} on the start page · add more with Y › Bookmark This Page`,
        children: async () => {
          const r = await api.get('/api/browser/bookmarks');
          if (!r.bookmarks.length) return [{ key: 'none', label: 'No bookmarks', icon: 'info', sub: 'In the browser: Y › Bookmark This Page' }];
          return r.bookmarks.map((b) => ({ key: `b:${b.url}`, label: b.name, icon: 'browser', sub: `${b.url} · {ok} remove`,
            action: async () => { if (await confirmBox(`Remove ${b.name} from bookmarks?`)) { await api.post('/api/browser/unbookmark', { url: b.url }); reloadFolder(); } } }));
        } },
    ];
  },
};

// Settings › Theme › Install a Theme…: browse to a theme folder (has theme.json) or a .zip
async function themeBrowse(path) {
  const r = await api.get(`/api/fs?ext=.zip${path ? `&path=${encodeURIComponent(path)}` : ''}`);
  const install = async (p) => {
    const t = await call(() => api.post('/api/theme/install', { path: p }));
    if (!t) return;
    toast(`Installed ${t.name}`, 'palette');
    if (await confirmBox(`Use ${t.name} now?`, 'Theme')) { await call(() => api.post('/api/theme/set', { id: t.id })); await Theme.load(); }
    while (S.stack.length && S.stack.at(-1).source?.themeBrowse) S.stack.pop();
    reloadFolder();
  };
  const items = [];
  if (path) items.push({ key: 'here', label: 'Install This Folder', icon: 'check', sub: path, action: () => install(path) });
  for (const f of r.files || []) items.push({ key: `z:${f.path}`, label: f.name, icon: 'download', sub: 'Install this theme', action: () => install(f.path) });
  for (const d of r.dirs) items.push({ key: `d:${d.path}`, label: d.name, icon: 'folder', themeBrowse: true, children: () => themeBrowse(d.path) });
  if (!items.length) items.push({ key: 'none', label: 'Nothing here', icon: 'info', sub: 'No folders or .zip files' });
  return items;
}

const SETTINGS_FOLDERS = [
  {
    key: 'display', label: 'Display', icon: 'display', sub: 'Resolution, refresh rate, scale',
    children: async () => {
      const outs = await api.get('/api/display');
      if (!outs.length) return [{ key: 'na', label: 'Not available here', icon: 'info', sub: 'Display settings work in the Crossbar session' }];
      const items = [];
      for (const o of outs) {
        const c = o.current, multi = outs.length > 1 ? ` (${o.label})` : '';
        const sizes = [...new Map(o.modes.map((m) => [`${m.width}x${m.height}`, m])).values()];
        items.push({ key: `res:${o.name}`, label: `Resolution${multi}`, icon: 'display',
          sub: `${c.width} × ${c.height}${o.listed ? '' : ' · screen lists no modes, common sizes offered'}`,
          children: async () => (!sizes.length ? [{ key: 'none', label: 'No resolutions reported', icon: 'info', sub: 'The screen or driver didn\'t list any' }] : sizes.map((m) => {
            // keep the current refresh rate if this size supports it, else its best rate
            const same = o.modes.filter((x) => x.width === m.width && x.height === m.height);
            const pick = same.find((x) => Math.abs(x.refresh - c.refresh) < 500) || same[0];
            const cur = m.width === c.width && m.height === c.height;
            return { key: `m:${m.width}x${m.height}`, label: `${m.width} × ${m.height}`, icon: cur ? 'check' : 'display',
              sub: cur ? 'Current' : (m.custom ? 'Custom mode — may not work on every screen' : ''), action: () => changeMode(o, pick) };
          })) });
        const rates = o.modes.filter((m) => m.width === c.width && m.height === c.height && m.refresh > 0);
        items.push({ key: `hz:${o.name}`, label: `Refresh Rate${multi}`, icon: 'display', sub: hz(c.refresh),
          children: async () => (!rates.length ? [{ key: 'none', label: 'Only one rate available', icon: 'info', sub: 'The screen didn\'t report other refresh rates for this resolution' }] : rates.map((m) => {
            const cur = Math.abs(m.refresh - c.refresh) < 50;
            return { key: `r:${m.refresh}`, label: hz(m.refresh), icon: cur ? 'check' : 'display',
              sub: cur ? 'Current' : '', action: () => changeMode(o, m) };
          })) });
        const scales = [1, 1.25, 1.5, 2];
        items.push({ key: `sc:${o.name}`, label: `Display Scale${multi}`, icon: 'display', sub: `${Math.round(o.scale * 100)}%`,
          action: () => Options.show(scales.map((x) => ({ label: `${check(Math.abs(x - o.scale) < 0.01)}${x * 100}%`,
            action: async () => { await call(() => api.post('/api/display/scale', { name: o.name, scale: x })); reloadFolder(); } })),
            Math.max(0, scales.findIndex((x) => Math.abs(x - o.scale) < 0.01))) });
      }
      return items;
    },
  },
  {
    key: 'sound', label: 'Sound', icon: 'sound', sub: 'Output and input devices, volume',
    children: async () => {
      const a = await api.get('/api/audio').catch(() => ({ output: {}, mic: {} }));
      const vol = (x) => (x.volume == null ? 'Unavailable' : `${x.name || 'Default'} · ${x.volume}%${x.muted ? ' (muted)' : ''}`);
      return [
        deviceFolder('outputs'),
        deviceFolder('inputs'),
        { key: 'ovol', label: 'Output Volume', icon: 'sound', sub: vol(a.output), action: () => Options.show(volumeOptions('output')) },
        { key: 'mvol', label: 'Microphone Volume', icon: 'mic', sub: vol(a.mic), action: () => Options.show(volumeOptions('mic')) },
        APP_VOLUME_FOLDER,
        { key: 'sfx', label: 'Menu Sounds', icon: 'music', sub: S.state.sounds ? 'On' : 'Off',
          action: async () => { await setSetting({ sounds: !S.state.sounds }); reloadFolder(); } },
      ];
    },
  },
  CONTROLS_FOLDER,
  GAMES_FOLDER,
  {
    key: 'theme', label: 'Theme', icon: 'palette', sub: 'Theme packs, colour, adding your own',
    children: async () => {
      const st = S.state;
      const [list, cur] = await Promise.all([api.get('/api/themes'), api.get('/api/theme')]);
      const items = list.map((t) => ({
        key: `t:${t.id}`, label: t.name, badge: t.id === cur.id ? 'ON' : t.user ? 'YOURS' : '',
        sub: `${t.description}${t.author ? ' · by ' + t.author : ''}`,
        ...(t.preview ? { art: t.preview, artTitle: t.name } : { icon: t.id === cur.id ? 'check' : 'palette' }),
        action: async () => { if (await call(() => api.post('/api/theme/set', { id: t.id }), `Theme: ${t.name}`)) { await Theme.load(); reloadFolder(); } },
        options: [{ label: 'Use This Theme', action: async () => { await call(() => api.post('/api/theme/set', { id: t.id })); await Theme.load(); reloadFolder(); } },
          ...(t.user ? [{ label: 'Remove', action: async () => { if (await confirmBox(`Remove the theme ${t.name}?`)) { await call(() => api.post('/api/theme/remove', { id: t.id }), 'Theme removed'); await Theme.load(); reloadFolder(); } } }] : [])],
      }));
      if (cur.waves.mode === 'month') {
        const c = st.theme === 'auto' ? 0 : st.theme + 1;
        const opts = [{ label: `${check(c === 0)}Automatic (changes monthly)`, action: () => setSetting({ theme: 'auto' }).then(reloadFolder) }]
          .concat(MONTHS.map((m, i) => ({ label: `${check(c === i + 1)}${m} colour`, action: () => setSetting({ theme: i }).then(reloadFolder) })));
        items.push({ key: 'color', label: 'Wave Colour', icon: 'palette', sub: st.theme === 'auto' ? 'Automatic (changes monthly)' : `${MONTHS[st.theme]} colour`,
          action: () => Options.show(opts, c) });
      }
      items.push({ key: 'install', label: 'Install a Theme…', icon: 'add', sub: 'From a folder or .zip (USB stick, Downloads, network drive)', themeBrowse: true, children: () => themeBrowse(null) });
      items.push({ key: 'how', label: 'Make Your Own', icon: 'info', sub: 'A folder with theme.json — see docs/THEMES.md on GitHub',
        action: () => message('A theme is a folder with a theme.json file (colours, waves, background, font, keyboard),\nplus optional pictures: background.jpg, icons/<name>.svg, sounds/<name>.ogg, theme.css.\n\nPut it in ~/.local/share/crossbar/themes/ or install it from here.\nFull guide: github.com/Brenyd/crossbar/blob/main/docs/THEMES.md', 'Themes') });
      return items;
    },
  },
  {
    key: 'media', label: 'Media', icon: 'folder', sub: 'Library folders, video playback',
    children: async () => {
      const m = S.state.media, v = S.state.video;
      return [
        { key: 'music', label: 'Music Folder', icon: 'music', sub: m.music, action: () => pickFolder('music') },
        { key: 'video', label: 'Video Folder', icon: 'video', sub: m.video, action: () => pickFolder('video') },
        { key: 'photo', label: 'Photo Folder', icon: 'photo', sub: m.photo, action: () => pickFolder('photo') },
        BROWSER_SETTINGS,
        iptvSettingsFolder(),
        { key: 'resume', label: 'Resume Videos', icon: 'play', sub: v.resume ? 'On — continue where you left off' : 'Off — always start from the beginning',
          action: () => setVideo({ resume: !v.resume }) },
        { key: 'subs', label: 'Subtitles', icon: 'video', sub: v.subtitles === 'off' ? 'Off by default' : 'Automatic',
          action: () => setVideo({ subtitles: v.subtitles === 'off' ? 'auto' : 'off' }) },
      ];
    },
  },
  {
    key: 'network', label: 'Network', icon: 'network', sub: 'Wi-Fi, VPN, speed test, network drives',
    children: async () => {
      const n = await api.get('/api/network').catch(() => ({ available: false, devices: [] }));
      if (!n.available) return [{ key: 'na', label: 'Network settings need NetworkManager', icon: 'info' }];
      const radio = (await api.get('/api/wifi/radio').catch(() => ({ on: true }))).on;
      const wifi = n.devices.find((d) => d.type === 'wifi');
      const wired = n.devices.find((d) => d.type === 'ethernet');
      const items = [{ key: 'status', label: 'Connection Status', icon: 'network',
        sub: n.connectivity === 'full' ? `Connected${(wired?.state === 'connected' && wired.ip) ? ' · wired ' + wired.ip : wifi?.ip ? ' · Wi-Fi ' + wifi.ip : ''}` : (n.connectivity || 'Unknown'),
        action: showNetworkStatus }];
      if (wifi) {
        items.push({ key: 'radio', label: 'Wi-Fi', icon: 'wifi', sub: radio ? 'On' : 'Off',
          action: async () => { await call(() => api.post('/api/wifi-extra/radio', { on: !radio })); reloadFolder(); } });
        if (radio) {
          items.push({ key: 'nets', label: 'Wi-Fi Networks', icon: 'wifi', sub: wifi.connection ? `Connected to ${wifi.connection}` : 'Scan and connect',
            children: async () => {
              const nets = await api.get('/api/wifi');
              if (!nets.length) return [{ key: 'none', label: 'No networks found', icon: 'info' }];
              return nets.map((w) => ({ key: `w:${w.ssid}`, label: w.ssid, icon: w.connected ? 'check' : 'wifi',
                sub: `${w.connected ? 'Connected · ' : ''}${w.signal}%${w.secure ? ' · Secured' : ''}`,
                action: () => wifiConnect(w),
                options: [{ label: w.connected ? 'Disconnect' : 'Connect', action: w.connected
                  ? async () => { await call(() => api.post('/api/wifi-extra/disconnect')); reloadFolder(); } : () => wifiConnect(w) },
                          { label: 'Forget Network', action: async () => { if (await confirmBox(`Forget ${w.ssid}?`)) { await call(() => api.post('/api/wifi-extra/forget', { ssid: w.ssid })); reloadFolder(); } } }] }));
            } });
        }
      }
      items.push(VPN_ITEM);
      const last = await api.get('/api/speedtest').catch(() => ({}));
      items.push({ key: 'speed', label: 'Internet Speed Test', icon: 'download',
        sub: last && last.download != null ? `Last: ↓ ${last.download} Mbps · ↑ ${last.upload} Mbps · ${last.ping} ms` : 'Download, upload and latency',
        action: runSpeedTest });
      items.push(NAS_ITEM);
      return items;
    },
  },
  {
    key: 'bluetooth', label: 'Bluetooth', icon: 'bluetooth', sub: 'Controllers, headsets, keyboards',
    children: async () => {
      const bt = await api.get('/api/bluetooth').catch(() => ({ available: false }));
      if (!bt.available) return [{ key: 'na', label: bt.note || 'Bluetooth isn\'t available', icon: 'info', sub: 'No adapter found, or bluez isn\'t installed' }];
      const items = [{ key: 'power', label: 'Bluetooth', icon: 'settings', sub: bt.powered ? 'On' : 'Off',
        action: async () => { await call(() => api.post('/api/bluetooth/power', { on: !bt.powered })); reloadFolder(); } }];
      if (!bt.powered) return items;
      items.push({ key: 'scan', label: 'Find Devices', icon: 'search', sub: 'Put your controller or headset in pairing mode first',
        action: async () => { toast('Searching for 10 seconds…', 'search'); await call(() => api.post('/api/bluetooth/scan')); setTimeout(reloadFolder, 11000); } });
      for (const d of bt.devices) {
        const act = (a, ok) => async () => { await call(() => api.post(`/api/bluetooth/${a}`, { mac: d.mac }), ok); reloadFolder(); };
        items.push({ key: `bt:${d.mac}`, label: d.name, icon: d.connected ? 'check' : d.kind,
          sub: d.connected ? 'Connected' : d.paired ? 'Paired — {ok} to connect' : 'Not paired — {ok} to pair',
          action: d.connected ? act('disconnect', `Disconnected ${d.name}`) : d.paired ? act('connect', `Connected ${d.name}`)
            : async () => { toast(`Pairing ${d.name}…`, 'game'); await call(() => api.post('/api/bluetooth/pair', { mac: d.mac, name: d.name })); pollJobs(); setTimeout(reloadFolder, 3000); },
          options: [{ label: d.connected ? 'Disconnect' : 'Connect', action: d.connected ? act('disconnect') : act('connect') },
                    { label: 'Forget Device', action: async () => { if (await confirmBox(`Forget ${d.name}?`)) act('remove', `Forgot ${d.name}`)(); } }] });
      }
      return items;
    },
  },
  {
    key: 'time', label: 'Date & Time', icon: 'clock', sub: 'Time zone, clock',
    children: async () => {
      const t = await api.get('/api/time').catch(() => ({ available: false }));
      const items = [];
      if (t.available) {
        items.push({ key: 'zone', label: 'Time Zone', icon: 'network', sub: t.timezone, children: timezoneFolder });
        items.push({ key: 'ntp', label: 'Set Time Automatically', icon: 'refresh', sub: t.ntp ? `On${t.synced ? ' · synced' : ''}` : 'Off',
          action: async () => { await call(() => api.post('/api/time/ntp', { on: !t.ntp })); reloadFolder(); } });
      }
      items.push({ key: 'fmt', label: 'Clock Format', icon: 'settings', sub: S.state.clock24 ? '24-hour' : '12-hour',
        action: async () => { await setSetting({ clock24: !S.state.clock24 }); tick(); reloadFolder(); } });
      return items;
    },
  },
  {
    key: 'accounts', label: 'Accounts', icon: 'account', sub: 'Steam, GOG, Epic, Spotify, user name',
    children: async () => {
      const sp = S.state.spotify;
      return [
        { key: 'name', label: 'User Name', icon: 'user', sub: S.state.user, action: async () => { await renameUser(); reloadFolder(); } },
        ...S.state.providers.map((p) => ({
          key: `acct:${p.id}`, label: p.name, icon: 'store',
          sub: p.linked ? `Signed in${p.account ? ' · ' + p.account : ''} — library in Store` : (p.note && !p.ready ? p.note : 'Not signed in'),
          action: () => (p.linked ? Options.show([{ label: 'Sign Out', action: () => signOut(p) }, { label: 'Sign In Again', action: () => signIn(p) }]) : signIn(p)),
          options: p.linked ? [{ label: 'Sign Out', action: () => signOut(p) }] : [{ label: 'Sign In', action: () => signIn(p) }],
        })),
        ...(sp.linked ? [{ key: 'sp-restart', label: 'Restart Spotify Speaker', icon: 'refresh',
          sub: sp.speaker_running ? 'Speaker running' : 'Speaker not running',
          action: async () => { await call(() => api.post('/api/spotify/restart'), 'Spotify speaker restarted'); setTimeout(async () => { await loadState(); reloadFolder(); }, 1500); } }] : []),
        { key: 'spotify', label: 'Spotify', icon: 'spotify', sub: sp.linked ? `Signed in${sp.speaker ? ' · speaker ready' : ''}` : 'Not set up',
          action: async () => {
            if (!sp.linked) return spotifySetup();
            if (await confirmBox('Sign out of Spotify on this console?')) { S.state = await api.post('/api/spotify/logout'); reloadFolder(); }
          } },
        ...(typeof DISCORD_ACCOUNT_FOLDER !== 'undefined' ? [DISCORD_ACCOUNT_FOLDER] : []),
      ];
    },
  },
  {
    key: 'system', label: 'System Settings', icon: 'system', sub: 'Terminal, updates, information, install',
    children: async () => {
      const st = S.state;
      return [
        { key: 'sys', label: 'System Information', icon: 'info', action: async () => {
          const i = await api.get('/api/sysinfo');
          message(`Crossbar ${i.version}\n${i.os}\nKernel ${i.kernel}\n${i.cpu}\nMemory ${i.memory}\nGames folder ${i.games_dir}`, 'System Information');
        } },
        { key: 'term', label: 'Terminal', icon: 'browser', sub: 'A command line, right here (keyboard needed)', action: () => Term.show() },
        ...(st.live ? [{ key: 'install', label: 'Install to Disk', icon: 'download', sub: 'Erases a disk and installs Crossbar permanently',
          action: async () => { if (await confirmBox('Start the installer?\nYou will pick the disk and confirm before anything is erased.')) runInTerminal('/api/installer', 'Installer started'); } }] : []),
        { key: 'report', label: 'Share Support Report', icon: 'info', sub: 'Upload a diagnostic report and get a short link to share',
          action: async () => {
            if (!(await confirmBox('Upload a support report?\nIt includes controller and window names, Crossbar settings status and recent logs.\nLines mentioning passwords, tokens or keys are removed.'))) return;
            toast('Uploading report…', 'info');
            const r = await call(() => api.post('/api/report'));
            if (r?.url) message(`Your report link:\n\n${r.url}\n\nType or paste this link into your message.`, 'Support Report');
          } },
        { key: 'restart-cb', label: 'Restart Crossbar', icon: 'restart', sub: 'Stop and restart every Crossbar piece (menu, Quick Menu, backend)',
          action: async () => { if (await confirmBox('Restart Crossbar?\nOpen games and apps keep running.')) { toast('Restarting Crossbar…', 'info'); api.post('/api/session/restart'); } } },
        ...(st.boot_mode === 'ps5' ? [
          { key: 'gaming', label: 'Switch to Gaming Mode', icon: 'game', sub: 'Steam\'s gaming mode. Its "Switch to Desktop", then "Return to Crossbar", comes back',
            action: async () => { if (await confirmBox('Switch to Gaming Mode?\nOpen games and apps will be closed.')) call(() => api.post('/api/session/gaming'), 'Switching…'); } },
          { key: 'desktop', label: 'Switch to Desktop', icon: 'browser', sub: 'Plasma. "Return to Crossbar" in its app menu comes back',
            action: async () => { if (await confirmBox('Switch to the desktop?\nOpen games and apps will be closed.')) call(() => api.post('/api/session/desktop'), 'Switching…'); } }] :
        st.desktop_available ? [{ key: 'desktop', label: st.boot_mode === 'tty' ? 'Switch to Your Usual Session' : 'Switch to Desktop', icon: 'browser',
          sub: st.boot_mode === 'tty' ? 'Back to your own startup (Plasma / gaming mode). From Plasma, "Return to Crossbar" comes back'
                                       : 'Log in to the Plasma desktop instead. On the desktop, open "Return to Crossbar" to come back',
          action: async () => { if (await confirmBox('Leave Crossbar?\nOpen games and apps will be closed.')) call(() => api.post('/api/session/desktop'), 'Switching…'); } }] : []),
        { key: 'exit-cb', label: 'Exit Crossbar', icon: 'power', sub: 'Close everything and go back to the login screen / TTY',
          action: async () => { if (await confirmSafe('Exit Crossbar?\nOpen games and apps will be closed.')) api.post('/api/session/exit'); } },
        { key: 'update', label: 'Update Crossbar', icon: 'download', sub: 'Download the latest version and apply it (no ISO rebuild)',
          action: async () => { if (await confirmBox('Update Crossbar now?\nYou\'ll see the progress here; Crossbar restarts when it finishes.')) runInTerminal('/api/update', 'Updating Crossbar…'); } },
        { key: 'about', label: 'About Crossbar', icon: 'info', sub: '1.1 Alpha', action: () => message('Crossbar — an Arch-based console shell.\n1.1 Alpha', 'About') },
      ];
    },
  },
];

// Order in the Settings column.
// PS5 running Linux: temperatures, fan, front LED (only shown when the PS5 drivers are there)
const ledName = (n) => (n === 'off' ? 'Off' : n.replace(/^zoneb_/, 'zone B ').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()));
const tempText = (t) => [['CPU', t.cpu], ['GPU', t.gpu], ['NVMe', t.nvme]].filter(([, v]) => v != null).map(([k, v]) => `${k} ${v} °C`).join(' · ') || 'No sensors found';
const PS5_FOLDER = {
  key: 'ps5', label: 'PS5 Hardware', icon: 'game', sub: 'Temperatures, fan, front light',
  children: async () => {
    const p = await api.get('/api/ps5');
    if (!p.available) return [{ key: 'na', label: 'PS5 drivers not found', icon: 'info', sub: 'Needs the PS5 fan and LED kernel drivers' }];
    const post = async (path, body, msg) => { const r = await call(() => api.post(path, body), msg); if (r) reloadFolder(); };
    const [lo, hi] = p.target_range;
    const items = [
      { key: 'temps', label: 'Temperatures', icon: 'info', sub: tempText(p.temps),
        action: () => message(`${tempText(p.temps).replace(/ · /g, '\n')}\n\nFan target: ${p.fan_target ?? '?'} °C`, 'Temperatures') },
      { key: 'hud', label: 'Temperature Overlay', icon: 'display',
        sub: p.hud ? `On — ${p.hud_corner.replace('-', ' ')} of the screen, also over games` : 'Off — show CPU/GPU/NVMe temperatures on screen',
        action: () => Options.show([
          { label: `${check(!p.hud)}Off`, action: () => post('/api/ps5/hud', { on: false }) },
          ...['top-right', 'top-left', 'bottom-right', 'bottom-left'].map((c) => ({
            label: `${check(p.hud && p.hud_corner === c)}On — ${c.replace('-', ' ')}`, action: () => post('/api/ps5/hud', { on: true, corner: c }) })),
        ]) },
    ];
    if (p.fan_target != null) {
      const vals = []; for (let v = lo; v <= hi; v += 5) vals.push(v);
      items.push({ key: 'fan', label: 'Fan Target Temperature', icon: 'settings',
        sub: `${p.fan_target} °C — the fan speeds up to keep the chip below this. Lower = cooler but louder`,
        action: () => Options.show(vals.map((v) => ({ label: `${check(v === p.fan_target)}${v} °C${v <= 60 ? ' (coolest, loudest)' : v >= 90 ? ' (quietest, warmest)' : ''}`,
          action: () => post('/api/ps5/fan-target', { value: v }, `Fan target ${v} °C`) })), Math.max(0, vals.indexOf(p.fan_target))) });
    }
    if (p.ps5_control) {
      const modes = [['auto', 'Automatic (follow the target)'], ['on', 'On'], ['off', 'Off'], ['max', 'Max']];
      items.push({ key: 'fanmode', label: 'Fan Mode', icon: 'settings', sub: (modes.find(([m]) => m === p.fan_mode) || modes[0])[1],
        action: () => Options.show(modes.map(([m, l]) => ({ label: `${check(m === p.fan_mode)}${l}`,
          action: async () => { if (m !== 'off' || await confirmSafe('Turn the fan off?\nOnly for a moment: the PS5 can overheat without it.')) post('/api/ps5/fan-mode', { mode: m }); } }))) });
      items.push({ key: 'boost', label: 'Boost', icon: 'settings', sub: p.boost ? 'On' : 'Off',
        action: () => post('/api/ps5/boost', { on: !p.boost }) });
    }
    if (!p.ps5_control) {
      items.push({ key: 'ps5c', label: 'Fan Mode & Boost', icon: 'info', sub: 'Needs ps5_control: Settings › System › Update Crossbar installs it',
        action: () => message('Fan modes and boost use ps5_control from the ps5-linux project.\nCrossbar downloads and builds it when you update (Settings › System › Update Crossbar) or run ps5-tools.sh.\nIts own fan / boost services stay off unless you turn them on.', 'PS5 Hardware') });
    }
    if (p.leds.length) {
      const names = ['off', ...p.leds];
      items.push({ key: 'led', label: 'Front Light', icon: 'theme', sub: ledName(p.led || 'off'),
        action: () => Options.show(names.map((n) => ({ label: `${check((p.led || 'off') === n)}${ledName(n)}`,
          action: () => post('/api/ps5/led', { name: n }) })), Math.max(0, names.indexOf(p.led || 'off'))) });
    }
    return items;
  },
};
SETTINGS_FOLDERS.push(PS5_FOLDER);

const SETTINGS_ORDER = ['display', 'sound', 'network', 'bluetooth', 'controls', 'games', 'ps5', 'theme', 'media', 'time', 'accounts', 'system'];
SETTINGS_FOLDERS.sort((a, b) => SETTINGS_ORDER.indexOf(a.key) - SETTINGS_ORDER.indexOf(b.key));

// The Settings column: related folders grouped, so the list stays short.
const SETTINGS_GROUPS = [
  { key: 'g-av', label: 'Display & Sound', icon: 'display', sub: 'Resolution, refresh rate, outputs, volume', keys: ['display', 'sound'] },
  { key: 'g-net', label: 'Network & Bluetooth', icon: 'network', sub: 'Wi-Fi, network drives, pairing', keys: ['network', 'bluetooth'] },
  { key: 'controls' },
  { key: 'g-games', label: 'Games & Emulation', icon: 'game', sub: 'Launching, Proton, artwork, emulators, achievements', keys: ['games', 'artwork', 'emulation'] },
  { key: 'media' },
  { key: 'accounts' },
  { key: 'g-look', label: 'Theme & Time', icon: 'palette', sub: 'Themes, clock, time zone', keys: ['theme', 'time'] },
  { key: 'g-system', label: 'System', icon: 'system', sub: 'Updates, power, terminal, information', keys: ['ps5', 'system'], flatten: 'system' },
];
const settingsFolder = (k) => SETTINGS_FOLDERS.find((f) => f.key === k);
const settingsVisible = (f) => f && (f.key !== 'ps5' || S.state?.ps5hw);

function settingsColumn() {
  return SETTINGS_GROUPS.map((g) => {
    if (!g.keys) return settingsFolder(g.key);
    return { key: g.key, label: g.label, icon: g.icon, sub: g.sub,
      children: async () => {
        const out = [];
        for (const k of g.keys) {
          const f = settingsFolder(k);
          if (!settingsVisible(f)) continue;
          if (g.flatten === k) out.push(...await f.children());   // System's own items sit right here
          else out.push(f);
        }
        return out;
      } };
  }).filter(Boolean);
}
CATS.push({ id: 'settings', label: 'Settings', icon: 'settings', async load() { return settingsColumn(); } });

// After boot: if this is the Crossbar session but parts are missing (e.g. code
// updated without rebuilding the ISO), say so plainly instead of half-working.
async function checkComponents() {
  const d = await api.get('/api/diagnostics').catch(() => null);
  if (!d || !d.sway) return;
  const missing = [];
  if (!d.inputd) missing.push('controller service');
  if (!d.overlay_window) missing.push('Quick Menu overlay');
  if (missing.length) {
    toast(`Not installed: ${missing.join(' and ')}. Settings › System › Update Crossbar`, 'info');
  }
}

boot();
setTimeout(checkComponents, 12000);


// ---- Settings › Network › Internet Speed Test: live numbers while it runs ----------------------------
async function runSpeedTest() {
  const j = await call(() => api.post('/api/speedtest'));
  if (!j) return;
  let open = true;
  Dialog.ask({ title: 'Internet Speed Test', body: 'Finding the nearest server…', buttons: ['Close'] }).then(() => { open = false; });
  const v = (x, unit) => (x == null ? '…' : `${x.toFixed ? x.toFixed(1) : x} ${unit}`);
  while (open) {
    await new Promise((r) => setTimeout(r, 400));
    const cur = (await api.get('/api/jobs').catch(() => [])).find((x) => x.id === j.id);
    if (!cur || !open) break;
    const r = cur.result || {};
    const lines = [
      `Download   ${v(r.download ?? r.download_live, 'Mbps')}`,
      `Upload   ${v(r.upload ?? r.upload_live, 'Mbps')}`,
      `Latency   ${v(r.ping, 'ms')}${r.jitter != null ? `   (jitter ${r.jitter} ms)` : ''}`,
      r.server ? `Server: Cloudflare ${r.server}${r.ip ? ` · seen as ${r.ip}` : ''}` : '',
      cur.status === 'running' ? `\n${cur.message}` : cur.status === 'error' ? `\n${cur.message}` : '\nDone',
    ];
    $('.dlg-body').textContent = lines.filter((x) => x !== '').join('\n');
    if (cur.status !== 'running') break;
  }
  if (S.stack.length) reloadFolder();
}
