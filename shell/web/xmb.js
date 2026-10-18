'use strict';
// Crossbar XMB shell. Categories run horizontally, items vertically; folders
// push a new column. Keyboard: arrows, Enter, Esc, Tab. Gamepad: d-pad/stick, A, B, Y.

const $ = (s) => document.querySelector(s);
const STAGE = $('#stage');
const CAT_X = 560, CAT_GAP = 230;

// ---------------------------------------------------------------- utilities
const api = {
  async get(p) { const r = await fetch(p); const j = await r.json(); if (!r.ok) throw new Error(j.error); return j; },
  async post(p, b) {
    const r = await fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) });
    const j = await r.json(); if (!r.ok) throw new Error(j.error); return j;
  },
};
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const STORE_NAMES = { steam: 'STEAM', gog: 'GOG', epic: 'EPIC' };
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

function fit() {
  const s = Math.min(innerWidth / 1920, innerHeight / 1080);
  STAGE.style.transform = `scale(${s}) translate(-50%, -50%)`;
}
addEventListener('resize', fit); fit();

function tick() {
  const d = new Date();
  $('#clock-date').textContent = `${d.getMonth() + 1}/${d.getDate()}`;
  $('#clock-time').textContent = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}
setInterval(tick, 5000); tick();

// ---------------------------------------------------------------- sound
const Sfx = (() => {
  let ac = null;
  function tone(f, dur, vol, delay = 0) {
    if (!S.state?.sounds) return;
    try {
      ac = ac || new AudioContext();
      const o = ac.createOscillator(), g = ac.createGain();
      o.type = 'sine'; o.frequency.value = f;
      const t0 = ac.currentTime + delay;
      g.gain.setValueAtTime(0, t0); g.gain.linearRampToValueAtTime(vol, t0 + 0.005);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
      o.connect(g).connect(ac.destination); o.start(t0); o.stop(t0 + dur + 0.02);
    } catch (e) { /* audio not available */ }
  }
  return {
    move: () => tone(1450, 0.05, 0.03),
    ok: () => { tone(880, 0.09, 0.05); tone(1320, 0.12, 0.04, 0.05); },
    back: () => tone(660, 0.1, 0.04),
    err: () => { tone(300, 0.15, 0.05); tone(220, 0.2, 0.05, 0.1); },
  };
})();

// ---------------------------------------------------------------- toasts
function toast(text, ico = 'info') {
  const el = document.createElement('div');
  el.className = 'toast';
  el.innerHTML = `<div class="ico">${icon(ico)}</div><div>${esc(text)}</div>`;
  $('#toasts').prepend(el);
  setTimeout(() => el.classList.add('out'), 4200);
  setTimeout(() => el.remove(), 5000);
}
async function call(fn, okMsg) {
  try { const r = await fn(); if (okMsg) toast(okMsg); return r; }
  catch (e) { Sfx.err(); toast(e.message || 'Something went wrong', 'info'); return null; }
}

// ---------------------------------------------------------------- dialog
const Dialog = {
  open: false, sel: 0, buttons: [], resolve: null,
  ask({ title = '', body = '', buttons = ['OK'], fields = [], def = 0 }) {
    this.open = true; this.sel = def; this.buttons = buttons;
    $('.dlg-title').textContent = title;
    $('.dlg-body').textContent = body;
    $('.dlg-fields').innerHTML = fields.map((f, i) =>
      `<label>${esc(f.label)}</label><input data-k="${esc(f.key)}" type="${f.secret ? 'password' : 'text'}" value="${esc(f.value || '')}" spellcheck="false">`).join('');
    this.renderButtons();
    $('#dialog').hidden = false;
    const first = $('.dlg-fields input');
    if (first) setTimeout(() => first.focus(), 50);
    return new Promise((res) => { this.resolve = res; });
  },
  renderButtons() {
    $('.dlg-buttons').innerHTML = this.buttons.map((b, i) => `<div class="dlg-btn ${i === this.sel ? 'on' : ''}">${esc(b)}</div>`).join('');
  },
  move(d) { this.sel = (this.sel + d + this.buttons.length) % this.buttons.length; this.renderButtons(); Sfx.move(); },
  close(idx) {
    const values = {};
    document.querySelectorAll('.dlg-fields input').forEach((i) => { values[i.dataset.k] = i.value; });
    $('#dialog').hidden = true; this.open = false;
    document.activeElement?.blur();
    (idx === null ? Sfx.back : Sfx.ok)();
    this.resolve({ button: idx, values });
  },
};
const confirmBox = async (body, title = '') => (await Dialog.ask({ title, body, buttons: ['Yes', 'No'] })).button === 0;
const message = (body, title = '') => Dialog.ask({ title, body });

// ---------------------------------------------------------------- options panel
const Options = {
  open: false, sel: 0, list: [],
  show(list) {
    if (!list?.length) return;
    this.list = list; this.sel = 0; this.open = true; this.render();
    $('#options').hidden = false; Sfx.ok();
  },
  render() {
    $('.opt-list').innerHTML = this.list.map((o, i) => `<div class="opt ${i === this.sel ? 'on' : ''}">${esc(o.label)}</div>`).join('');
  },
  move(d) { this.sel = (this.sel + d + this.list.length) % this.list.length; this.render(); Sfx.move(); },
  hide() { this.open = false; $('#options').hidden = true; },
  pick() { const o = this.list[this.sel]; this.hide(); Sfx.ok(); o.action(); },
};

// ---------------------------------------------------------------- state
const S = {
  state: null, jobs: [], ci: 2, catSel: {}, stack: [], items: {},
};

function prov(id) { return S.state.providers.find((p) => p.id === id); }

// ---------------------------------------------------------------- item builders
function gameItem(g, inStore) {
  const job = S.jobs.find((j) => j.kind === 'install' && j.provider === g.provider && j.game_id === g.id && j.status === 'running');
  const it = {
    key: `${g.provider}:${g.id}`, label: g.title, art: g.art || '', artTitle: g.title, badge: STORE_NAMES[g.provider],
    sub: job ? `Downloading… ${job.message}` : g.installed ? (inStore ? 'Installed' : 'Play') : (g.note || 'Download'),
    progress: job ? job.progress : null,
  };
  const options = [];
  if (g.installed) {
    it.action = () => launch(g);
    options.push({ label: 'Start', action: () => launch(g) });
    options.push({ label: 'Delete', action: () => uninstall(g) });
  } else if (!job) {
    it.action = () => install(g);
    options.push({ label: 'Download', action: () => install(g) });
  }
  options.push({ label: 'Information', action: () => message(`${g.title}\n${STORE_NAMES[g.provider]} · ${g.installed ? 'Installed' : 'Not installed'}${g.note ? '\n' + g.note : ''}`, 'Information') });
  it.options = options;
  return it;
}

async function launch(g) {
  Sfx.ok();
  const r = await call(() => api.post('/api/launch', { provider: g.provider, id: g.id }));
  if (r) toast(r.demo ? `${g.title}: demo mode, nothing to start` : `Starting ${g.title}…`, 'play');
  refresh('game');
}
async function install(g) {
  if (!(await confirmBox(`Download ${g.title}?`, STORE_NAMES[g.provider]))) return;
  const r = await call(() => api.post('/api/install', { provider: g.provider, id: g.id, title: g.title }));
  if (r) { toast(`Download started: ${g.title}`, 'download'); pollJobs(); }
}
async function uninstall(g) {
  if (!(await confirmBox(`Delete ${g.title}?\nSaved data stored by the game itself is kept.`))) return;
  await call(() => api.post('/api/uninstall', { provider: g.provider, id: g.id, title: g.title }));
  setTimeout(() => { refresh('game'); refresh('store'); }, 800);
}

async function signIn(p) {
  let fields = {};
  if (p.login_fields.length) {
    const r = await Dialog.ask({ title: `${p.name} account`, fields: p.login_fields, buttons: ['OK', 'Cancel'] });
    if (r.button !== 0) return;
    fields = r.values;
  } else {
    toast(`A ${p.name} sign-in window will open. Sign in there.`, 'link');
  }
  await call(() => api.post(`/api/login/${p.id}`, fields));
  pollJobs();
}

function storeFolder(p) {
  return {
    key: `store:${p.id}`, label: p.name, icon: 'folder', badge: p.linked ? '' : 'NOT SIGNED IN',
    sub: p.linked ? (p.account ? `Signed in · ${p.account}` : 'Signed in') : (p.note || 'Sign in to see your library'),
    options: [
      p.linked ? { label: 'Sign Out', action: async () => { if (await confirmBox(`Sign out of ${p.name}?`)) { await call(() => api.post(`/api/logout/${p.id}`)); await loadState(); refresh('store'); } } }
               : { label: 'Sign In', action: () => signIn(p) },
      { label: 'Refresh', action: () => refresh('store') },
    ],
    children: async () => {
      const fresh = prov(p.id);
      if (!fresh.linked) {
        return [
          { key: 'signin', label: `Sign In to ${p.name}`, icon: 'link', sub: p.id === 'steam' ? 'Uses your SteamID and a Web API key' : 'Opens the official sign-in page', action: () => signIn(fresh) },
        ];
      }
      const lib = await api.get(`/api/library?provider=${p.id}`);
      return lib.length ? lib.map((g) => gameItem(g, true)) : [{ key: 'empty', label: 'No games found', icon: 'info', sub: '' }];
    },
  };
}

// ---------------------------------------------------------------- categories
const CATS = [
  {
    id: 'users', label: 'Users', icon: 'users',
    async load() {
      return [
        { key: 'me', label: S.state.user, icon: 'user', sub: 'Signed in', options: [{ label: 'Rename', action: renameUser }], action: renameUser },
        { key: 'off', label: 'Turn Off System', icon: 'power', action: async () => { if (await confirmBox('Turn off the system?')) api.post('/api/power/poweroff'); } },
        { key: 'reboot', label: 'Restart System', icon: 'restart', action: async () => { if (await confirmBox('Restart the system?')) api.post('/api/power/reboot'); } },
      ];
    },
  },
  {
    id: 'settings', label: 'Settings', icon: 'settings',
    async load() {
      const st = S.state;
      const themeName = st.theme === 'auto' ? 'Automatic (changes monthly)' : MONTHS[st.theme];
      const themeOpts = [{ label: 'Automatic (changes monthly)', action: () => setSetting({ theme: 'auto' }) }]
        .concat(MONTHS.map((m, i) => ({ label: `${m} colour`, action: () => setSetting({ theme: i }) })));
      const audio = await api.get('/api/audio').catch(() => ({ output: {} }));
      const vol = audio.output.volume;
      return [
        { key: 'theme', label: 'Theme', icon: 'palette', sub: themeName, options: themeOpts, action: () => Options.show(themeOpts) },
        { key: 'vol', label: 'Sound Output', icon: 'sound', sub: vol == null ? 'Unavailable' : `${audio.output.name || 'Default'} · ${vol}%${audio.output.muted ? ' (muted)' : ''}`,
          options: volumeOptions('output'), action: () => Options.show(volumeOptions('output')) },
        { key: 'sfx', label: 'Menu Sounds', icon: 'music', sub: st.sounds ? 'On' : 'Off', action: () => setSetting({ sounds: !st.sounds }) },
        { key: 'demo', label: 'Demo Library', icon: 'demo', sub: st.demo ? 'On — showing sample games' : 'Off — using your real accounts',
          action: async () => {
            if (await confirmBox(st.demo ? 'Switch to your real Steam, GOG and Epic accounts?' : 'Show the demo library instead of your accounts?')) {
              await setSetting({ demo: !st.demo }); refresh('game'); refresh('store');
            }
          } },
        { key: 'sys', label: 'System Information', icon: 'info', action: async () => {
            const i = await api.get('/api/sysinfo');
            message(`${i.os}\nKernel ${i.kernel}\n${i.cpu}\nMemory ${i.memory}\nGames folder ${i.games_dir}`, 'System Information');
          } },
        ...(st.live ? [{ key: 'install', label: 'Install to Disk', icon: 'download', sub: 'Erases a disk and installs Crossbar permanently',
          action: async () => { if (await confirmBox('Open the installer?\nYou will pick the disk and confirm before anything is erased.')) call(() => api.post('/api/installer')); } }] : []),
        { key: 'about', label: 'About Crossbar', icon: 'info', sub: 'Prototype 0.1', action: () => message('Crossbar — an Arch-based console shell.\nPrototype 0.1', 'About') },
      ];
    },
  },
  {
    id: 'game', label: 'Game', icon: 'game',
    async load() {
      const items = [];
      for (const w of S.state.windows || []) {
        items.push({ key: `win:${w.con_id}`, label: `Return to ${w.title}`, icon: 'window', sub: 'Running',
          action: () => api.post('/api/window/focus', { con_id: w.con_id }),
          options: [{ label: 'Return', action: () => api.post('/api/window/focus', { con_id: w.con_id }) },
                    { label: 'Quit', action: async () => { await api.post('/api/window/close', { con_id: w.con_id }); setTimeout(loadState, 800); } }] });
      }
      for (const j of S.jobs.filter((j) => j.kind === 'install' && j.status === 'running')) {
        items.push({ key: `job:${j.id}`, label: j.title, icon: 'download', sub: `Downloading… ${j.message}`, progress: j.progress, badge: STORE_NAMES[j.provider] });
      }
      const games = await api.get('/api/installed');
      items.push(...games.map((g) => gameItem(g, false)));
      if (!games.length) items.push({ key: 'none', label: 'No games installed', icon: 'store', sub: 'Get some from the Store', action: () => goCat('store') });
      return items;
    },
  },
  {
    id: 'store', label: 'Store', icon: 'store',
    async load() {
      const items = [];
      if (S.state.demo) items.push({ key: 'demo', label: 'Demo library is on', icon: 'demo', sub: 'Settings › Demo Library to use your real accounts', action: () => goCat('settings') });
      items.push({ key: 'search', label: 'Search All Stores', icon: 'search', sub: 'Find a game across Steam, GOG and Epic', action: searchStores });
      items.push(...S.state.providers.map(storeFolder));
      return items;
    },
  },
  {
    id: 'party', label: 'Party', icon: 'party',
    async load() {
      const pty = S.state.party;
      const svc = pty.services.find((s) => s.id === pty.service) || pty.services[0];
      const running = (S.state.windows || []).filter((w) => new RegExp(svc.name.split(' ')[0], 'i').test(w.title + ' ' + w.app));
      const audio = await api.get('/api/audio').catch(() => ({ mic: {} }));
      const items = [
        { key: 'start', label: 'Start Party', icon: 'voice', sub: `Open ${svc.name}${svc.available ? '' : ' (not installed)'}`,
          action: () => call(() => api.post('/api/party/start'), `Opening ${svc.name}… press Home to come back`) },
      ];
      for (const w of running) {
        items.push({ key: `pw:${w.con_id}`, label: `Return to ${svc.name}`, icon: 'window', sub: w.title, action: () => api.post('/api/window/focus', { con_id: w.con_id }) });
      }
      items.push({
        key: 'quick', label: 'Quick Join', icon: 'folder', sub: `${pty.channels.length} saved channel${pty.channels.length === 1 ? '' : 's'}`,
        children: async () => [
          ...S.state.party.channels.map((c, i) => ({
            key: `ch:${i}`, label: c.name, icon: 'voice', sub: c.url,
            action: () => call(() => api.post('/api/party/start', { url: c.url }), `Joining ${c.name}…`),
            options: [{ label: 'Join', action: () => call(() => api.post('/api/party/start', { url: c.url }), `Joining ${c.name}…`) },
                      { label: 'Remove', action: async () => { S.state = await api.post('/api/party/remove', { index: i }); reloadFolder(); } }],
          })),
          { key: 'add', label: 'Add Channel…', icon: 'add', sub: 'Paste a Discord channel link, mumble:// or Matrix room URL', action: addChannel },
        ],
      });
      items.push({
        key: 'svc', label: 'Voice Service', icon: 'settings', sub: svc.name,
        children: async () => S.state.party.services.map((s) => ({
          key: `svc:${s.id}`, label: s.name, icon: 'voice',
          sub: (s.id === S.state.party.service ? '✓ Selected · ' : '') + (s.native ? 'App installed' : s.available ? 'Runs in a web window' : 'Not installed'),
          action: async () => { S.state = await api.post('/api/party/service', { service: s.id }); toast(`Party service: ${s.name}`, 'voice'); reloadFolder(); refresh('party'); },
        })),
      });
      const mic = audio.mic || {};
      items.push({ key: 'mic', label: 'Microphone', icon: 'mic', sub: mic.volume == null ? 'Unavailable' : `${mic.name || 'Default'} · ${mic.volume}%${mic.muted ? ' (muted)' : ''}`,
        options: volumeOptions('mic'), action: () => Options.show(volumeOptions('mic')) });
      return items;
    },
  },
];

function volumeOptions(target) {
  const go = (b) => async () => { await call(() => api.post('/api/audio', { target, ...b })); refresh(target === 'mic' ? 'party' : 'settings'); };
  return [{ label: 'Volume +10', action: go({ delta: 10 }) }, { label: 'Volume −10', action: go({ delta: -10 }) }, { label: 'Mute / Unmute', action: go({ mute: true }) }];
}
async function setSetting(b) { S.state = await api.post('/api/settings', b); applyState(); refresh('settings'); }
async function renameUser() {
  const r = await Dialog.ask({ title: 'User', fields: [{ key: 'user', label: 'Name', value: S.state.user }], buttons: ['OK', 'Cancel'] });
  if (r.button === 0 && r.values.user.trim()) { await setSetting({ user: r.values.user.trim() }); refresh('users'); }
}
async function addChannel() {
  const r = await Dialog.ask({ title: 'Add Channel', buttons: ['Save', 'Cancel'],
    fields: [{ key: 'name', label: 'Name (e.g. "Squad voice")' }, { key: 'url', label: 'Link (https://discord.com/channels/…, mumble://…)' }] });
  if (r.button !== 0 || !r.values.url.trim()) return;
  S.state = await api.post('/api/party/add', r.values);
  reloadFolder();
}
async function searchStores() {
  const r = await Dialog.ask({ title: 'Search All Stores', fields: [{ key: 'q', label: 'Game title' }], buttons: ['Search', 'Cancel'] });
  if (r.button !== 0) return;
  const q = r.values.q.trim();
  openFolder({ key: 'search', label: `“${q}”`, icon: 'search', children: async () => {
    const res = await api.get('/api/search?q=' + encodeURIComponent(q));
    return res.length ? res.map((g) => gameItem(g, true)) : [{ key: 'none', label: 'No matches', icon: 'info', sub: 'Only signed-in stores are searched' }];
  } });
}

// ---------------------------------------------------------------- navigation
function list() { return S.stack.length ? S.stack.at(-1).items : (S.items[CATS[S.ci].id] || []); }
function sel() { return S.stack.length ? S.stack.at(-1).sel : (S.catSel[CATS[S.ci].id] ?? 0); }
function setSel(i) { if (S.stack.length) S.stack.at(-1).sel = i; else S.catSel[CATS[S.ci].id] = i; }

async function refresh(catId) {
  const cat = CATS.find((c) => c.id === catId);
  if (!cat || !S.state) return;
  try {
    const items = await cat.load();
    const old = S.items[catId] || [];
    const prevKey = old[S.catSel[catId] ?? 0]?.key;
    S.items[catId] = items;
    const idx = items.findIndex((i) => i.key === prevKey);
    S.catSel[catId] = idx >= 0 ? idx : Math.min(S.catSel[catId] ?? 0, Math.max(0, items.length - 1));
  } catch (e) {
    S.items[catId] = [{ key: 'err', label: 'Couldn’t load', icon: 'info', sub: e.message }];
  }
  if (!S.stack.length && CATS[S.ci].id === catId) renderColumn(false);
}

function goCat(id) { S.stack = []; S.ci = CATS.findIndex((c) => c.id === id); render(); }

async function openFolder(item) {
  const frame = { title: item.label, icon: item.icon, items: [{ key: 'loading', label: 'Loading…', icon: 'refresh' }], sel: 0, source: item };
  S.stack.push(frame); Sfx.ok(); render();
  try { frame.items = await item.children(); }
  catch (e) { frame.items = [{ key: 'err', label: 'Couldn’t load', icon: 'info', sub: e.message }]; }
  if (S.stack.at(-1) === frame) renderColumn(true);
}
async function reloadFolder() {
  const frame = S.stack.at(-1);
  if (!frame) return;
  const prevKey = frame.items[frame.sel]?.key;
  frame.items = await frame.source.children();
  const idx = frame.items.findIndex((i) => i.key === prevKey);
  frame.sel = idx >= 0 ? idx : Math.min(frame.sel, frame.items.length - 1);
  renderColumn(false);
}

// ---------------------------------------------------------------- rendering
function hashHue(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h % 360; }

function itemEl(it) {
  const el = document.createElement('div');
  el.className = 'item';
  let slot;
  if (it.art !== undefined) {
    const h = hashHue(it.artTitle || it.label);
    slot = `<div class="art" style="background-image:linear-gradient(135deg,hsl(${h} 55% 38%),hsl(${(h + 40) % 360} 60% 18%))">${esc(it.artTitle)}</div>`;
  } else slot = `<div class="ico">${icon(it.icon)}</div>`;
  el.innerHTML = `${slot}<div class="txt"><div class="label">${esc(it.label)}${it.badge ? `<span class="badge">${esc(it.badge)}</span>` : ''}</div>
    <div class="sub">${esc(it.sub || '')}</div>${it.progress != null ? `<div class="bar"><i style="width:${(it.progress * 100).toFixed(1)}%"></i></div>` : ''}</div>`;
  if (it.art) {  // swap in real artwork once it loads; keep the generated tile if offline
    const img = new Image();
    img.onload = () => { const a = el.querySelector('.art'); a.style.backgroundImage = `url("${it.art}")`; a.textContent = ''; };
    img.src = it.art;
  }
  return el;
}

function renderCats() {
  const wrap = $('#cats');
  if (!wrap.children.length) {
    CATS.forEach((c, i) => {
      const el = document.createElement('div');
      el.className = 'cat';
      el.style.left = `${CAT_X + i * CAT_GAP}px`;
      el.innerHTML = `<div class="ico">${icon(c.icon)}</div><div class="lbl">${esc(c.label)}</div>`;
      wrap.appendChild(el);
    });
  }
  wrap.style.transform = `translateX(${-S.ci * CAT_GAP}px)`;
  [...wrap.children].forEach((el, i) => el.classList.toggle('on', i === S.ci));
}

let columnEls = [];
function renderColumn(rebuild = true) {
  const col = $('#column');
  if (!S.stack.length && !S.items[CATS[S.ci].id]) S.items[CATS[S.ci].id] = [{ key: 'loading', label: 'Loading…', icon: 'refresh' }];
  const items = list();
  if (rebuild) col.classList.add('swap');
  col.innerHTML = '';
  columnEls = items.map((it) => { const el = itemEl(it); col.appendChild(el); return el; });
  position();
  if (rebuild) requestAnimationFrame(() => requestAnimationFrame(() => col.classList.remove('swap')));
  hint();
}

function position() {
  const items = list(), s = sel();
  columnEls.forEach((el, i) => {
    const on = i === s;
    const isArt = items[i].art !== undefined;
    const slotW = isArt ? (on ? 300 : 150) : (on ? 104 : 72);
    let y;
    if (i < s) y = (S.stack.length ? 370 : 175) - (s - i - 1) * 100; // above the category bar
    else if (i === s) y = isArt ? 500 : 480;
    else y = (isArt ? 640 : 590) + (i - s - 1) * 100;
    const x = CAT_X - slotW / 2;
    el.style.transform = `translate(${x}px, ${y}px)`;
    el.classList.toggle('on', on);
    el.classList.toggle('dim', !on);
    el.style.opacity = y < -60 || y > 1140 ? 0 : '';
  });
}

function render() {
  const inFolder = S.stack.length > 0;
  document.body.classList.toggle('infolder', inFolder);
  $('#crumb').hidden = !inFolder;
  if (inFolder) {
    const f = S.stack.at(-1);
    $('#crumb .crumb-ico').innerHTML = icon(f.icon);
    $('#crumb .crumb-label').textContent = f.title;
  }
  renderCats();
  renderColumn(true);
}

function hint() {
  const it = list()[sel()];
  const parts = [];
  if (it && (it.action || it.children)) parts.push('<b>A</b>Enter');
  if (S.stack.length) parts.push('<b>B</b>Back');
  if (it?.options?.length) parts.push('<b>Y</b>Options');
  $('#hint').innerHTML = parts.join(' ');
}

// ---------------------------------------------------------------- input
function moveV(d) {
  const n = list().length; if (!n) return;
  const i = Math.max(0, Math.min(n - 1, sel() + d));
  if (i !== sel()) { setSel(i); Sfx.move(); position(); hint(); }
}
function moveH(d) {
  if (S.stack.length) { if (d < 0) back(); return; }
  const i = Math.max(0, Math.min(CATS.length - 1, S.ci + d));
  if (i === S.ci) return;
  S.ci = i; Sfx.move(); render();
  refresh(CATS[i].id);
}
function confirm() {
  const it = list()[sel()];
  if (!it) return;
  if (it.children) return openFolder(it);
  if (it.action) { Sfx.ok(); it.action(); }
}
function back() { if (S.stack.length) { S.stack.pop(); Sfx.back(); render(); } }
function options() { const it = list()[sel()]; if (it?.options) Options.show(it.options); }

function handle(action) {
  if (Dialog.open) {
    if (action === 'left') Dialog.move(-1);
    else if (action === 'right') Dialog.move(1);
    else if (action === 'ok') Dialog.close(Dialog.sel);
    else if (action === 'back') Dialog.close(null);
    return;
  }
  if (Options.open) {
    if (action === 'up') Options.move(-1);
    else if (action === 'down') Options.move(1);
    else if (action === 'ok') Options.pick();
    else if (action === 'back' || action === 'opt' || action === 'left') { Options.hide(); Sfx.back(); }
    return;
  }
  ({ up: () => moveV(-1), down: () => moveV(1), left: () => moveH(-1), right: () => moveH(1),
     ok: confirm, back, opt: options })[action]?.();
}

addEventListener('keydown', (e) => {
  const typing = e.target.tagName === 'INPUT';
  const map = { ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right', Enter: 'ok', Escape: 'back', Tab: 'opt' };
  if (!typing) Object.assign(map, { ' ': 'ok', Backspace: 'back', t: 'opt' });
  let a = map[e.key];
  if (typing && (a === 'left' || a === 'right' || a === 'opt')) return;  // let text fields work
  if (typing && (a === 'up' || a === 'down')) {                            // hop between fields
    const ins = [...document.querySelectorAll('.dlg-fields input')];
    ins[Math.max(0, Math.min(ins.length - 1, ins.indexOf(e.target) + (a === 'up' ? -1 : 1)))].focus();
    e.preventDefault(); return;
  }
  if (!a) return;
  e.preventDefault();
  handle(a);
});

// Gamepad (standard mapping): A=0 B=1 Y=3, d-pad 12-15, left stick.
const pad = { held: {}, next: {} };
function pollPads(now) {
  const pads = navigator.getGamepads ? [...navigator.getGamepads()].filter(Boolean) : [];
  const want = {};
  for (const p of pads) {
    const b = (i) => p.buttons[i]?.pressed;
    const ax = p.axes[0] || 0, ay = p.axes[1] || 0;
    if (b(12) || ay < -0.6) want.up = 1;
    if (b(13) || ay > 0.6) want.down = 1;
    if (b(14) || ax < -0.6) want.left = 1;
    if (b(15) || ax > 0.6) want.right = 1;
    if (b(0)) want.ok = 1;
    if (b(1)) want.back = 1;
    if (b(3)) want.opt = 1;
  }
  for (const a of ['up', 'down', 'left', 'right', 'ok', 'back', 'opt']) {
    if (!want[a]) { pad.held[a] = false; continue; }
    const repeatable = ['up', 'down', 'left', 'right'].includes(a);
    if (!pad.held[a]) { pad.held[a] = true; pad.next[a] = now + 380; fire(a); }
    else if (repeatable && now > pad.next[a]) { pad.next[a] = now + 85; fire(a); }
  }
  requestAnimationFrame(pollPads);
}
function fire(a) {
  if (Dialog.open && document.activeElement?.tagName === 'INPUT' && (a === 'up' || a === 'down')) {
    document.activeElement.blur(); return;
  }
  handle(a);
}
requestAnimationFrame(pollPads);
addEventListener('gamepadconnected', (e) => toast(`Controller connected`, 'game'));

// ---------------------------------------------------------------- polling
function applyState() {
  Waves.setTheme(S.state.theme);
  $('#demo-badge').hidden = !S.state.demo;
}
async function loadState() {
  S.state = await api.get('/api/state');
  S.jobs = S.state.jobs;
  applyState();
}

let lastJobSig = '';
const seenDone = new Set();
async function pollJobs() {
  let jobs;
  try { jobs = await api.get('/api/jobs'); } catch { return; }
  S.jobs = jobs;
  const sig = JSON.stringify(jobs.map((j) => [j.id, j.status, Math.round(j.progress * 200)]));
  if (sig === lastJobSig) return;
  lastJobSig = sig;
  let finished = false;
  for (const j of jobs) {
    if (j.status === 'running' || seenDone.has(j.id)) continue;
    seenDone.add(j.id); finished = true;
    if (j.status === 'error') { Sfx.err(); toast(`${j.title}: ${j.message}`, 'info'); }
    else if (j.kind === 'install') toast(`Download complete: ${j.title}`, 'download');
    else if (j.kind === 'login') toast(`Signed in to ${j.title}`, 'link');
  }
  if (finished) await loadState();
  const cur = CATS[S.ci].id;
  if (S.stack.length) {
    // update progress text inside an open store folder without losing place
    const f = S.stack.at(-1);
    if (finished || f.items.some((i) => i.progress != null || jobs.some((j) => `${j.provider}:${j.game_id}` === i.key))) reloadFolder();
  } else if (cur === 'game' || cur === 'store' || finished) refresh(cur);
  if (finished) CATS.forEach((c) => c.id !== cur && refresh(c.id));
}
setInterval(pollJobs, 1200);
setInterval(async () => {   // pick up windows opening/closing (games, Discord)
  const before = JSON.stringify(S.state?.windows || []);
  try { await loadState(); } catch { return; }
  if (JSON.stringify(S.state.windows) !== before && !S.stack.length && ['game', 'party'].includes(CATS[S.ci].id)) refresh(CATS[S.ci].id);
}, 4000);

// ---------------------------------------------------------------- boot
(async function boot() {
  render();
  for (let tries = 0; ; tries++) {
    try { await loadState(); break; } catch { await new Promise((r) => setTimeout(r, 500)); }
  }
  S.items = {};
  await Promise.all(CATS.map((c) => refresh(c.id)));
  render();
  setTimeout(() => { $('#boot').classList.add('done'); Sfx.ok(); }, 900);
})();
