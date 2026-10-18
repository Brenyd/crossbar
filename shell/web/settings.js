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
      { key: 'pad', label: 'Controller Buttons', icon: 'game', sub: 'Choose what each button does', children: bindingItems('gamepad') },
      { key: 'diag', label: 'Controller Diagnostics', icon: 'info', sub: 'What Crossbar sees, and the last buttons pressed', action: showDiagnostics },
      { key: 'kbd', label: 'Keyboard Keys', icon: 'browser', sub: 'Choose what each key does', children: bindingItems('keyboard') },
      { key: 'guide', label: 'Guide / PS Button Opens Quick Menu', icon: 'game',
        sub: c.guide_home ? 'On — Steam\'s overlay won\'t get that button' : 'Off — left free for Steam (Quick Menu: Select + Start)',
        action: async () => savedControls(await api.post('/api/controls/guide', { on: !c.guide_home }),
          c.guide_home ? 'Guide/PS left to Steam' : 'Guide/PS opens the Quick Menu') },
      { key: 'swap', label: 'Swap Select and Back', icon: 'refresh', sub: 'Confirm with B / ○ instead of A / ✕ (or back again)',
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

const GAMES_FOLDER = {
  key: 'games', label: 'Game Settings', icon: 'game', sub: 'Launching, demo library',
  children: async () => {
    const st = S.state;
    return [
      { key: 'gs', label: 'Run GOG & Epic Games in Gamescope', icon: 'display',
        sub: !st.gamescope_available ? 'Gamescope isn\'t installed' : st.gamescope ? 'On — fixed resolution, better frame pacing' : 'Off — games run directly',
        action: async () => { if (st.gamescope_available) { await setSetting({ gamescope: !st.gamescope }); reloadFolder(); } } },
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
  GAMES_FOLDER,
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
    key: 'network', label: 'Network Settings', icon: 'network', sub: 'Wi-Fi, connection status',
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
          sub: d.connected ? 'Connected' : d.paired ? 'Paired — A to connect' : 'Not paired — A to pair',
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
        { key: 'update', label: 'Update Crossbar', icon: 'download', sub: 'Download the latest version and apply it (no ISO rebuild)',
          action: async () => { if (await confirmBox('Update Crossbar now?\nYou\'ll see the progress here; Crossbar restarts when it finishes.')) runInTerminal('/api/update', 'Updating Crossbar…'); } },
        { key: 'about', label: 'About Crossbar', icon: 'info', sub: 'Prototype 0.7', action: () => message('Crossbar — an Arch-based console shell.\nPrototype 0.7', 'About') },
      ];
    },
  },
];

// Order in the Settings column.
const SETTINGS_ORDER = ['display', 'sound', 'network', 'bluetooth', 'controls', 'games', 'theme', 'media', 'time', 'accounts', 'system'];
SETTINGS_FOLDERS.sort((a, b) => SETTINGS_ORDER.indexOf(a.key) - SETTINGS_ORDER.indexOf(b.key));

CATS.push({ id: 'settings', label: 'Settings', icon: 'settings', async load() { return SETTINGS_FOLDERS; } });

// After boot: if this is the Crossbar session but parts are missing (e.g. code
// updated without rebuilding the ISO), say so plainly instead of half-working.
async function checkComponents() {
  const d = await api.get('/api/diagnostics').catch(() => null);
  if (!d || !d.sway) return;
  const missing = [];
  if (!d.inputd) missing.push('controller service');
  if (!d.overlay_window) missing.push('Quick Menu overlay');
  if (missing.length) {
    toast(`Not installed: ${missing.join(' and ')}. Settings › System Settings › Update Crossbar`, 'info');
  }
}

boot();
setTimeout(checkComponents, 12000);
