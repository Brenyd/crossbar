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

function clock24() {          // tick() first runs before S exists
  try { return !!S.state?.clock24; } catch { return false; }
}
function tick() {
  const d = new Date();
  $('#clock-date').textContent = `${d.getMonth() + 1}/${d.getDate()}`;
  $('#clock-time').textContent = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: !clock24() });
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
  ask({ title = '', body = '', buttons = ['OK'], fields = [], def = 0, timeout = 0, timeoutButton = null }) {
    this.open = true; this.sel = def; this.buttons = buttons;
    $('.dlg-title').textContent = title;
    $('.dlg-body').textContent = body;
    $('.dlg-body').classList.toggle('long', String(body).split('\n').length > 5);
    clearInterval(this.timer);
    if (timeout) {  // e.g. "Keep this resolution?" reverts by itself
      let left = Math.round(timeout / 1000);
      const tickDown = () => {
        $('.dlg-body').textContent = `${body}\n(${left} s)`;
        if (left-- <= 0) this.close(timeoutButton);
      };
      tickDown();
      this.timer = setInterval(tickDown, 1000);
    }
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
    if (!this.open) return;
    clearInterval(this.timer);
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
  offset: 0,
  show(list, sel = 0) {
    if (!list?.length) return;
    this.list = list; this.sel = sel; this.offset = 0; this.open = true;
    $('#options').hidden = false; this.render(); Sfx.ok();
  },
  render() {
    const el = $('.opt-list');
    el.innerHTML = this.list.map((o, i) => `<div class="opt ${i === this.sel ? 'on' : ''}">${esc(o.label)}</div>`).join('');
    // Keep the highlighted entry on screen: the list starts at y=380 on the
    // 1080px stage and slides up/down once the selection nears an edge.
    const TOP = 380, MIN = 140, MAX = 960;
    const row = el.children[this.sel];
    const y = TOP + this.offset + row.offsetTop;
    if (y < MIN) this.offset += MIN - y;
    if (y + row.offsetHeight > MAX) this.offset -= y + row.offsetHeight - MAX;
    el.style.transform = `translateY(${this.offset}px)`;
    $('#options').classList.toggle('more-up', TOP + this.offset < MIN - 10);
    $('#options').classList.toggle('more-down', TOP + this.offset + el.scrollHeight > MAX + 10);
  },
  move(d) { this.sel = (this.sel + d + this.list.length) % this.list.length; this.render(); Sfx.move(); },
  hide() { this.open = false; $('#options').hidden = true; },
  pick() { const o = this.list[this.sel]; this.hide(); Sfx.ok(); o.action(); },
};

// ---------------------------------------------------------------- state
const S = {
  state: null, jobs: [], ci: 0, catSel: {}, stack: [], items: {},
};
const ORDER = ['users', 'settings', 'photo', 'music', 'video', 'tv', 'game', 'store', 'party'];

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
  if (g.windows) options.push({ label: 'Compatibility Tool…', action: () => pickCompatTool(`${g.provider}:${g.id}`, g.title) });
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

async function signOut(p) {
  if (!(await confirmBox(`Sign out of ${p.name}?`))) return;
  await call(() => api.post(`/api/logout/${p.id}`));
  await loadState();
  refresh('store');
  if (S.stack.length) reloadFolder();
}

// Store shows only the stores you're signed in to (sign in under Settings › Accounts).
function storeFolder(p) {
  return {
    key: `store:${p.id}`, label: p.name, icon: 'folder',
    sub: p.account ? `Your library · ${p.account}` : 'Your library',
    options: [{ label: 'Refresh', action: () => refresh('store') },
              { label: 'Account Settings', action: () => openSettingsFolder('accounts') }],
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
const CATS = [   // more categories are added by media.js and settings.js
  {
    id: 'users', label: 'Users', icon: 'users',
    async load() {
      return [
        { key: 'me', label: S.state.user, icon: 'user', sub: 'Signed in', options: [{ label: 'Rename', action: renameUser }], action: renameUser },
        fileBrowserItem(),
        { key: 'off', label: 'Turn Off System', icon: 'power', action: async () => { if (await confirmBox('Turn off the system?')) api.post('/api/power/poweroff'); } },
        { key: 'reboot', label: 'Restart System', icon: 'restart', action: async () => { if (await confirmBox('Restart the system?')) api.post('/api/power/reboot'); } },
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
      const linked = S.state.providers.filter((p) => p.linked);
      items.push(...linked.map(storeFolder));
      if (!linked.length) {
        items.push({ key: 'signin', label: 'Sign In to a Store', icon: 'account', sub: 'Steam, GOG and Epic accounts are in Settings › Account Settings',
          action: () => openSettingsFolder('accounts') });
      }
      return items;
    },
  },
  {
    id: 'party', label: 'Social', icon: 'party', live: true,
    async load() { return socialItems(); },
  },
];

function volumeOptions(target) {
  const go = (b) => async () => {
    await call(() => api.post('/api/audio', { target, ...b }));
    if (S.stack.length) reloadFolder(); else refresh(target === 'mic' ? 'party' : 'settings');
  };
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
  try { frame.items = await frame.source.children(); } catch (e) { return; }
  if (S.stack.at(-1) !== frame) return;
  const idx = frame.items.findIndex((i) => i.key === prevKey);
  frame.sel = idx >= 0 ? idx : Math.min(frame.sel, frame.items.length - 1);
  renderColumn(false);
}

// ---------------------------------------------------------------- rendering
function hashHue(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h % 360; }

// Artwork loads lazily (only items near the selection) and is remembered, so
// big photo/video folders and periodic refreshes don't flicker or stall.
const artLoaded = new Set(), artFailed = new Set();
function showArt(el, url) {
  const a = el.querySelector('.art');
  if (a) { a.style.backgroundImage = `url("${url}")`; a.textContent = ''; }
}
function ensureArt(el, it) {
  if (!it.art || artLoaded.has(it.art) || artFailed.has(it.art) || el.dataset.loading) return;
  el.dataset.loading = 1;
  const img = new Image();
  img.onload = () => { artLoaded.add(it.art); if (el.isConnected) showArt(el, it.art); };
  img.onerror = () => artFailed.add(it.art);
  img.src = it.art;
}

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
  if (it.art && artLoaded.has(it.art)) showArt(el, it.art);
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
    if (Math.abs(i - s) <= 8) ensureArt(el, items[i]);
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
  if (Term.open && !Dialog.open) return Term.handle(action);
  if (QuickMenu.open && !Dialog.open) return QuickMenu.handle(action);
  if (Viewer.open && !Dialog.open) return Viewer.handle(action);
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

// ---------------------------------------------------------------- input
// Keyboard: mapping from Settings › Controller & Keyboard (backend-stored).
const KEY_DEFAULTS = { up: ['ArrowUp'], down: ['ArrowDown'], left: ['ArrowLeft'], right: ['ArrowRight'], ok: ['Enter', 'Space'],
  back: ['Escape', 'Backspace'], menu: ['Tab', 't'], home: ['Home'], prev: ['PageUp'], next: ['PageDown'], toggle: ['p'] };
const keyName = (e) => (e.key === ' ' ? 'Space' : e.key.length === 1 ? e.key.toLowerCase() : e.key);
function keyAction(name) {
  const map = S.state?.controls?.keyboard || KEY_DEFAULTS;
  for (const [a, keys] of Object.entries(map)) if (keys.includes(name)) return a;
  return null;
}
const KeyCapture = { active: null };   // set by Settings while waiting for "press a key"

// Actions from the controller/keyboard -> what the XMB does with them.
const ACTION = { menu: 'opt' };
function act(action) {
  if (action === 'home') return QuickMenu.toggle();
  if ((action === 'prev' || action === 'next' || action === 'toggle') && !Dialog.open) return mediaKey(action);
  handle(ACTION[action] || action);
}

addEventListener('keydown', (e) => {
  if (KeyCapture.active) { e.preventDefault(); KeyCapture.active(keyName(e)); return; }
  if (Term.open && !Dialog.open) return;
  const typing = e.target.tagName === 'INPUT';
  const name = keyName(e);
  if (typing) {
    // text fields keep their keys; Enter/Escape/arrows-up-down still drive the dialog
    if (name === 'Enter') { e.preventDefault(); return handle('ok'); }
    if (name === 'Escape') { e.preventDefault(); return handle('back'); }
    if (name === 'ArrowUp' || name === 'ArrowDown') {
      const ins = [...document.querySelectorAll('.dlg-fields input')];
      ins[Math.max(0, Math.min(ins.length - 1, ins.indexOf(e.target) + (name === 'ArrowUp' ? -1 : 1)))].focus();
      e.preventDefault();
    }
    return;
  }
  const a = keyAction(name);
  if (!a) return;
  e.preventDefault();
  act(a);
});

// Controllers are normally read by the backend and arrive over the event stream.
// The browser's own Gamepad API is only a fallback: used when the backend sees no
// controller AND the backend says the XMB is the window in front (so a controller
// can never drive the menu from behind a video, game or web app).
const PAD_INDEX = ['BTN_SOUTH', 'BTN_EAST', 'BTN_WEST', 'BTN_NORTH', 'BTN_TL', 'BTN_TR', 'BTN_TL2', 'BTN_TR2',
  'BTN_SELECT', 'BTN_START', 'BTN_THUMBL', 'BTN_THUMBR', 'BTN_DPAD_UP', 'BTN_DPAD_DOWN', 'BTN_DPAD_LEFT', 'BTN_DPAD_RIGHT', 'BTN_MODE'];
const AXIS_INDEX = ['ABS_X', 'ABS_Y', 'ABS_RX', 'ABS_RY'];
const pad = { prev: new Set(), next: {}, consumed: new Set(), capture: null, lastReport: '' };
S.xmbFocused = true;

function backendHasPads() { return !!(S.state?.pads?.devices?.length); }
function browserPadsWanted() { return !backendHasPads() && S.xmbFocused && document.hasFocus(); }

// The tokens currently held on all browser-visible pads (same names as the backend uses).
function heldTokens() {
  const held = new Set();
  for (const p of (navigator.getGamepads ? [...navigator.getGamepads()].filter(Boolean) : [])) {
    p.buttons.forEach((b, i) => { if (b.pressed && PAD_INDEX[i]) held.add(PAD_INDEX[i]); });
    p.axes.slice(0, 4).forEach((v, i) => { if (Math.abs(v) > 0.6) held.add(`${AXIS_INDEX[i]}${v > 0 ? '+' : '-'}`); });
  }
  return held;
}
function padMap() {
  const g = S.state?.controls?.gamepad || {};
  const single = {}, combos = [];
  for (const [action, toks] of Object.entries(g)) {
    for (const t of toks) {
      if (t.includes('&')) combos.push([t.split('&'), action]);
      else single[t] = action;
    }
  }
  return { single, combos, comboKeys: new Set(combos.flatMap(([k]) => k)) };
}

function pollPads(now) {
  const pads = navigator.getGamepads ? [...navigator.getGamepads()].filter(Boolean) : [];
  const names = pads.map((p) => p.id).join('|');
  if (names !== pad.lastReport) {          // let diagnostics know what the browser sees
    pad.lastReport = names;
    api.post('/api/controls/browser-pads', { pads: pads.map((p) => p.id) }).catch(() => {});
  }
  const held = browserPadsWanted() || pad.capture ? heldTokens() : new Set();
  if (pad.justFocused) { pad.prev = held; pad.justFocused = false; }
  const pressed = [...held].filter((t) => !pad.prev.has(t));
  const released = [...pad.prev].filter((t) => !held.has(t));

  if (pad.capture) {                      // Settings › remap, when the backend can't see the pad
    if (pad.capture.combo) {
      if (held.size >= 2) { const t = [...held].filter((x) => x.startsWith('BTN_')).slice(0, 2); if (t.length === 2) pad.capture.done(t.join('&')); }
    } else if (pressed.length) pad.capture.done(pressed[0]);
  } else {
    const m = padMap();
    for (const t of pressed) {
      const combo = m.combos.find(([keys]) => keys.includes(t) && keys.every((k) => held.has(k)));
      if (combo) { combo[0].forEach((k) => pad.consumed.add(k)); fire(combo[1]); continue; }
      if (m.comboKeys.has(t)) continue;   // acts on release unless it became a combo
      const a = m.single[t];
      if (a) { fire(a); pad.next[t] = now + 380; }
    }
    for (const t of released) {
      delete pad.next[t];
      if (m.comboKeys.has(t)) {
        if (pad.consumed.has(t)) pad.consumed.delete(t);
        else if (m.single[t]) fire(m.single[t]);
      }
    }
    for (const t of held) {               // repeat held directions
      const a = m.single[t];
      if (pad.next[t] && now > pad.next[t] && ['up', 'down', 'left', 'right'].includes(a)) { pad.next[t] = now + 85; fire(a); }
    }
  }
  pad.prev = held;
  requestAnimationFrame(pollPads);
}
function fire(a) {
  if (Dialog.open && document.activeElement?.tagName === 'INPUT' && (a === 'up' || a === 'down')) {
    document.activeElement.blur(); return;
  }
  act(a);
}
function browserCapture(combo, timeout = 10000) {
  return new Promise((resolve) => {
    const t = setTimeout(() => { pad.capture = null; resolve(null); }, timeout);
    pad.capture = { combo, done: (tok) => { clearTimeout(t); pad.capture = null; resolve(tok); } };
  });
}
requestAnimationFrame(pollPads);
// Coming back from a game: buttons still held must not "click" in the XMB.
addEventListener('focus', async () => {
  pad.justFocused = true;   // buttons still held from a game must not "click" here
  // Backup path: if the Quick Menu was requested while the event stream was down.
  const p = await api.get('/api/quick/pending').catch(() => null);
  if (p?.open && !QuickMenu.open) QuickMenu.show(true);
});

// Event stream from the backend: controller input and Quick Menu requests.
function connectEvents() {
  const es = new EventSource('/api/events');
  es.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    if (ev.type === 'launching') { $('#launch .l-title').textContent = ev.title; $('#launch').hidden = false; clearTimeout(S.launchT); S.launchT = setTimeout(() => { $('#launch').hidden = true; }, 95000); return; }
    if (ev.type === 'launched') { $('#launch').hidden = true; return; }
    if (ev.type === 'launch-timeout') { $('#launch').hidden = true; toast(`${ev.title} didn't open a window — check Steam`, 'info'); return; }
    if (ev.type === 'term') { if (ev.id === Term.id) Term.output(ev.data); return; }
    if (ev.type === 'term-exit') { if (ev.id === Term.id) { Term.id = null; if (Term.open) Term.hide(); } return; }
    if (ev.type === 'open-terminal') { Term.show(ev.cmd); return; }
    if (ev.type === 'focus') { S.xmbFocused = ev.xmb; if (ev.xmb) pad.justFocused = true; return; }
    if (ev.type === 'open-settings') { QuickMenu.open && QuickMenu.close(false); if (ev.folder) openSettingsFolder(ev.folder); else goCat('settings'); return; }
    if (ev.type === 'input' && ev.to === 'overlay') return;      // meant for the overlay window
    if (ev.type === 'input') {
      if (Dialog.open && document.activeElement?.tagName === 'INPUT' && (ev.action === 'up' || ev.action === 'down')) {
        document.activeElement.blur(); return;
      }
      act(ev.action);
    } else if (ev.type === 'quick') {
      if (ev.open) { api.get('/api/quick/pending').catch(() => {}); QuickMenu.show(ev.shot); } else QuickMenu.toggle();
    }
  };
  es.onerror = () => { es.close(); setTimeout(connectEvents, 1500); };
}

// Play/Pause and skip work anywhere in the XMB, for local music or Spotify.
async function mediaKey(action) {
  const m = await api.get('/api/music/state').catch(() => null);
  if (m) {
    await api.post('/api/music/control', { action: action === 'toggle' ? 'toggle' : action });
  } else if (S.state?.spotify?.linked) {
    await call(() => api.post('/api/spotify/control', { action }));
  } else return;
  Sfx.ok();
  toast(action === 'toggle' ? 'Play / Pause' : action === 'next' ? 'Next track' : 'Previous track', 'music');
}

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
  for (const j of jobs) {   // show sign-in / pairing steps as they happen
    if (j.status === 'running' && ['login', 'pair', 'wifi'].includes(j.kind) && j.message && pollJobs.seen?.[j.id] !== j.message) {
      (pollJobs.seen ||= {})[j.id] = j.message;
      toast(`${j.title}: ${j.message}`, 'info');
    }
  }
  for (const j of jobs) {
    if (j.status === 'running' || seenDone.has(j.id)) continue;
    seenDone.add(j.id); finished = true;
    if (j.status === 'error') { Sfx.err(); toast(`${j.title}: ${j.message}`, 'info'); }
    else if (j.kind === 'install') toast(`Download complete: ${j.title}`, 'download');
    else if (j.kind === 'login') toast(`Signed in to ${j.title}`, 'link');
    else if (j.kind === 'wifi') toast(`Connected to ${j.title}`, 'wifi');
  }
  if (finished) { await loadState(); if (S.stack.at(-1)?.source?.key === 'accounts') reloadFolder(); }
  const cur = CATS[S.ci].id;
  if (S.stack.length) {
    // update progress text inside an open store folder without losing place
    const f = S.stack.at(-1);
    if (finished || f.items.some((i) => i.progress != null || jobs.some((j) => `${j.provider}:${j.game_id}` === i.key))) reloadFolder();
  } else if (cur === 'game' || cur === 'store' || finished) refresh(cur);
  if (finished) CATS.forEach((c) => c.id !== cur && refresh(c.id));
}
setInterval(pollJobs, 1200);
// Now Playing items (music, Spotify, video) refresh themselves while visible.
setInterval(() => {
  if (Dialog.open || Options.open || Viewer.open || QuickMenu.open || !S.state) return;
  const f = S.stack.at(-1);
  if (f) { if (f.source.live) reloadFolder(); }
  else if (CATS[S.ci].live) refresh(CATS[S.ci].id);
}, 2000);
setInterval(async () => {   // pick up windows opening/closing (games, Discord)
  const before = JSON.stringify(S.state?.windows || []);
  try { await loadState(); } catch { return; }
  if (JSON.stringify(S.state.windows) !== before && !S.stack.length && ['game', 'party'].includes(CATS[S.ci].id)) refresh(CATS[S.ci].id);
}, 4000);

// ---------------------------------------------------------------- boot
async function boot() {
  connectEvents();
  CATS.sort((a, b) => ORDER.indexOf(a.id) - ORDER.indexOf(b.id));
  S.ci = CATS.findIndex((c) => c.id === 'game');
  render();
  for (let tries = 0; ; tries++) {
    try { await loadState(); break; } catch { await new Promise((r) => setTimeout(r, 500)); }
  }
  S.items = {};
  await Promise.all(CATS.map((c) => refresh(c.id)));
  render();
  setTimeout(() => { $('#boot').classList.add('done'); Sfx.ok(); }, 900);
  if (S.state.pads?.error) setTimeout(() => toast(S.state.pads.error, 'game'), 2500);
}
