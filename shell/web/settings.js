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

async function changeMode(o, m) {
  const prev = o.current;
  const r1 = await call(() => api.post('/api/display/mode', { name: o.name, ...m, save: false }));
  if (!r1) return;
  const r = await Dialog.ask({ title: 'Display Settings', body: `${m.width} × ${m.height} at ${(m.refresh / 1000).toFixed(2)} Hz\nKeep this setting?`,
    buttons: ['Keep', 'Revert'], def: 1, timeout: 15000, timeoutButton: 1 });
  if (r.button === 0) await api.post('/api/display/mode', { name: o.name, ...m, save: true });
  else await api.post('/api/display/mode', { name: o.name, width: prev.width, height: prev.height, refresh: prev.refresh, save: false });
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

async function capturePad(a, add, c) {
  if (!c.pads.available) return message('Remapping controller buttons needs python-evdev (included in the Crossbar ISO).', 'Controller');
  if (!c.pads.devices.length) return message('No controller found. Connect one and try again.', 'Controller');
  const cap = api.post('/api/controls/capture', { timeout: 10 });
  const dlg = Dialog.ask({ title: 'Controller Buttons', body: `Press the button for “${a.name}”`, buttons: ['Cancel'],
    timeout: 10000, timeoutButton: null });
  const r = await Promise.race([cap.then((x) => ({ cap: x })), dlg.then((x) => ({ dlg: x }))]);
  if (r.dlg) { api.post('/api/controls/cancel'); return; }
  Dialog.close(0);
  if (!r.cap?.token) return toast('No button pressed', 'info');
  const tokens = add ? [...c.gamepad[a.id], r.cap.token] : [r.cap.token];
  const res = await call(() => api.post('/api/controls', { kind: 'gamepad', action: a.id, tokens }));
  if (res) savedControls(res, `${a.name}: ${res.labels[r.cap.token] || r.cap.token}`);
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
      const capture = (add) => () => (kind === 'gamepad' ? capturePad(a, add, c) : captureKey(a, add, c));
      return {
        key: `${kind}:${a.id}`, label: a.name, icon: kind === 'gamepad' ? 'game' : 'browser',
        sub: toks.length ? [...new Set(toks.map(label))].join(' · ') : 'Not set',
        action: capture(false),
        options: [
          { label: 'Change…', action: capture(false) },
          { label: `Add Another ${kind === 'gamepad' ? 'Button' : 'Key'}…`, action: capture(true) },
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
    `Controllers in use: ${p.devices.length ? p.devices.join(', ') : 'none'}`,
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
        sub: pads.length ? pads.join(', ') : (c.pads.available ? 'None connected' : 'Read by the browser'),
        action: () => message(pads.length ? pads.join('\n') : 'No controller detected.\nUSB and Bluetooth pads appear here once connected.', 'Controllers') },
      ...(c.pads.error ? [{ key: 'warn', label: 'Controller Not Readable', icon: 'info', sub: c.pads.error, action: showDiagnostics }] : []),
      { key: 'pad', label: 'Controller Buttons', icon: 'game', sub: 'Choose what each button does', children: bindingItems('gamepad') },
      { key: 'diag', label: 'Controller Diagnostics', icon: 'info', sub: 'What Crossbar sees, and the last buttons pressed', action: showDiagnostics },
      { key: 'kbd', label: 'Keyboard Keys', icon: 'browser', sub: 'Choose what each key does', children: bindingItems('keyboard') },
      { key: 'swap', label: 'Swap Select and Back', icon: 'refresh', sub: 'Confirm with B / ○ instead of A / ✕ (or back again)',
        action: async () => savedControls(await api.post('/api/controls', { swap: true }), 'Select and Back swapped') },
      { key: 'reset', label: 'Reset All to Defaults', icon: 'refresh', sub: 'Controller and keyboard',
        action: async () => { if (await confirmBox('Reset all buttons and keys to the defaults?')) savedControls(await api.post('/api/controls', { reset: 'all' }), 'Controls reset'); } },
    ];
  },
};

const SETTINGS_FOLDERS = [
  {
    key: 'display', label: 'Display Settings', icon: 'display', sub: 'Resolution, refresh rate, scale',
    children: async () => {
      const outs = await api.get('/api/display');
      if (!outs.length) return [{ key: 'na', label: 'Not available here', icon: 'info', sub: 'Display settings work in the Crossbar session' }];
      const items = [];
      for (const o of outs) {
        const c = o.current, multi = outs.length > 1 ? ` (${o.label})` : '';
        const sizes = [...new Map(o.modes.map((m) => [`${m.width}x${m.height}`, m])).values()];
        items.push({ key: `res:${o.name}`, label: `Resolution${multi}`, icon: 'display', sub: `${c.width} × ${c.height}`,
          children: async () => sizes.map((m) => {
            // keep the current refresh rate if this size supports it, else its best rate
            const same = o.modes.filter((x) => x.width === m.width && x.height === m.height);
            const pick = same.find((x) => Math.abs(x.refresh - c.refresh) < 500) || same[0];
            const cur = m.width === c.width && m.height === c.height;
            return { key: `m:${m.width}x${m.height}`, label: `${m.width} × ${m.height}`, icon: cur ? 'check' : 'display',
              sub: cur ? 'Current' : '', action: () => changeMode(o, pick) };
          }) });
        const rates = o.modes.filter((m) => m.width === c.width && m.height === c.height);
        items.push({ key: `hz:${o.name}`, label: `Refresh Rate${multi}`, icon: 'display', sub: `${(c.refresh / 1000).toFixed(2)} Hz`,
          children: async () => rates.map((m) => {
            const cur = Math.abs(m.refresh - c.refresh) < 50;
            return { key: `r:${m.refresh}`, label: `${(m.refresh / 1000).toFixed(2)} Hz`, icon: cur ? 'check' : 'display',
              sub: cur ? 'Current' : '', action: () => changeMode(o, m) };
          }) });
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
    key: 'sound', label: 'Sound Settings', icon: 'sound', sub: 'Output and input devices, volume',
    children: async () => {
      const a = await api.get('/api/audio').catch(() => ({ output: {}, mic: {} }));
      const vol = (x) => (x.volume == null ? 'Unavailable' : `${x.name || 'Default'} · ${x.volume}%${x.muted ? ' (muted)' : ''}`);
      return [
        deviceFolder('outputs'),
        deviceFolder('inputs'),
        { key: 'ovol', label: 'Output Volume', icon: 'sound', sub: vol(a.output), action: () => Options.show(volumeOptions('output')) },
        { key: 'mvol', label: 'Microphone Volume', icon: 'mic', sub: vol(a.mic), action: () => Options.show(volumeOptions('mic')) },
        { key: 'sfx', label: 'Menu Sounds', icon: 'music', sub: S.state.sounds ? 'On' : 'Off',
          action: async () => { await setSetting({ sounds: !S.state.sounds }); reloadFolder(); } },
      ];
    },
  },
  CONTROLS_FOLDER,
  {
    key: 'theme', label: 'Theme Settings', icon: 'palette', sub: 'Background colour',
    children: async () => {
      const st = S.state;
      const cur = st.theme === 'auto' ? 0 : st.theme + 1;
      const opts = [{ label: `${check(cur === 0)}Automatic (changes monthly)`, action: () => setSetting({ theme: 'auto' }).then(reloadFolder) }]
        .concat(MONTHS.map((m, i) => ({ label: `${check(cur === i + 1)}${m} colour`, action: () => setSetting({ theme: i }).then(reloadFolder) })));
      return [{ key: 'color', label: 'Theme Colour', icon: 'palette', sub: st.theme === 'auto' ? 'Automatic (changes monthly)' : `${MONTHS[st.theme]} colour`,
        action: () => Options.show(opts, cur) }];
    },
  },
  {
    key: 'media', label: 'Media Settings', icon: 'folder', sub: 'Library folders, video playback',
    children: async () => {
      const m = S.state.media, v = S.state.video;
      return [
        { key: 'music', label: 'Music Folder', icon: 'music', sub: m.music, action: () => pickFolder('music') },
        { key: 'video', label: 'Video Folder', icon: 'video', sub: m.video, action: () => pickFolder('video') },
        { key: 'photo', label: 'Photo Folder', icon: 'photo', sub: m.photo, action: () => pickFolder('photo') },
        { key: 'resume', label: 'Resume Videos', icon: 'play', sub: v.resume ? 'On — continue where you left off' : 'Off — always start from the beginning',
          action: () => setVideo({ resume: !v.resume }) },
        { key: 'subs', label: 'Subtitles', icon: 'video', sub: v.subtitles === 'off' ? 'Off by default' : 'Automatic',
          action: () => setVideo({ subtitles: v.subtitles === 'off' ? 'auto' : 'off' }) },
      ];
    },
  },
  {
    key: 'network', label: 'Network Settings', icon: 'network', sub: 'Wi-Fi and connection status',
    children: async () => [
      { key: 'status', label: 'Connection Status', icon: 'network', action: showNetworkStatus },
      { key: 'wifi', label: 'Wi-Fi Networks', icon: 'wifi', sub: 'Scan and connect',
        children: async () => {
          const nets = await api.get('/api/wifi');
          if (!nets.length) return [{ key: 'none', label: 'No networks found', icon: 'info', sub: 'Wired connections work automatically' }];
          return nets.map((n) => ({ key: `w:${n.ssid}`, label: n.ssid, icon: n.connected ? 'check' : 'wifi',
            sub: `${n.connected ? 'Connected · ' : ''}${n.signal}%${n.secure ? ' · Secured' : ''}`,
            action: async () => {
              let password = '';
              if (n.secure && !n.connected) {
                const r = await Dialog.ask({ title: n.ssid, fields: [{ key: 'pw', label: 'Password', secret: true }], buttons: ['Connect', 'Cancel'] });
                if (r.button !== 0) return;
                password = r.values.pw;
              }
              await call(() => api.post('/api/wifi', { ssid: n.ssid, password }), `Connecting to ${n.ssid}…`);
              pollJobs();
            } }));
        } },
    ],
  },
  {
    key: 'accounts', label: 'Account Settings', icon: 'account', sub: 'User name, Spotify',
    children: async () => {
      const sp = S.state.spotify;
      return [
        { key: 'name', label: 'User Name', icon: 'user', sub: S.state.user, action: async () => { await renameUser(); reloadFolder(); } },
        ...(sp.linked ? [{ key: 'sp-restart', label: 'Restart Spotify Speaker', icon: 'refresh',
          sub: sp.speaker_running ? 'Speaker running' : 'Speaker not running',
          action: async () => { await call(() => api.post('/api/spotify/restart'), 'Spotify speaker restarted'); setTimeout(async () => { await loadState(); reloadFolder(); }, 1500); } }] : []),
        { key: 'spotify', label: 'Spotify', icon: 'spotify', sub: sp.linked ? `Signed in${sp.speaker ? ' · speaker ready' : ''}` : 'Not set up',
          action: async () => {
            if (!sp.linked) return spotifySetup();
            if (await confirmBox('Sign out of Spotify on this console?')) { S.state = await api.post('/api/spotify/logout'); reloadFolder(); }
          } },
      ];
    },
  },
  {
    key: 'system', label: 'System Settings', icon: 'system', sub: 'Demo library, information, install',
    children: async () => {
      const st = S.state;
      return [
        { key: 'demo', label: 'Demo Library', icon: 'demo', sub: st.demo ? 'On — showing sample games' : 'Off — using your real accounts',
          action: async () => {
            if (await confirmBox(st.demo ? 'Switch to your real Steam, GOG and Epic accounts?' : 'Show the demo library instead of your accounts?')) {
              await setSetting({ demo: !st.demo }); refresh('game'); refresh('store'); reloadFolder();
            }
          } },
        { key: 'sys', label: 'System Information', icon: 'info', action: async () => {
          const i = await api.get('/api/sysinfo');
          message(`${i.os}\nKernel ${i.kernel}\n${i.cpu}\nMemory ${i.memory}\nGames folder ${i.games_dir}`, 'System Information');
        } },
        ...(st.live ? [{ key: 'install', label: 'Install to Disk', icon: 'download', sub: 'Erases a disk and installs Crossbar permanently',
          action: async () => { if (await confirmBox('Open the installer?\nYou will pick the disk and confirm before anything is erased.')) call(() => api.post('/api/installer')); } }] : []),
        { key: 'about', label: 'About Crossbar', icon: 'info', sub: 'Prototype 0.4', action: () => message('Crossbar — an Arch-based console shell.\nPrototype 0.4', 'About') },
      ];
    },
  },
];

CATS.push({ id: 'settings', label: 'Settings', icon: 'settings', async load() { return SETTINGS_FOLDERS; } });

boot();
