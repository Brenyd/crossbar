'use strict';
// Crossbar shell. The XMB look: categories run horizontally, items vertically; folders
// push a new column. Keyboard: arrows, Enter, Esc, Tab. Gamepad: d-pad/stick, A, B, Y.
// Only the *drawing* half is swappable (see "shell seam" below); everything else —
// the item model, folders, Options, dialogs, input, polling — is shared by every look.

const $ = (s) => document.querySelector(s);
const STAGE = $('#stage');

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
  const themed = (n) => !!S.state?.sounds && typeof Theme !== 'undefined' && Theme.play(n);
  return {
    // a theme pack's sounds/ files replace these beeps
    move: () => themed('move') || tone(1450, 0.05, 0.03),
    ok: () => themed('ok') || (tone(880, 0.09, 0.05), tone(1320, 0.12, 0.04, 0.05)),
    back: () => themed('back') || tone(660, 0.1, 0.04),
    err: () => themed('err') || (tone(300, 0.15, 0.05), tone(220, 0.2, 0.05, 0.1)),
  };
})();

// ---------------------------------------------------------------- controller glyphs
// Hints are written with action tokens ("{ok} Select"); they're shown with the glyph of the
// button mapped to that action, in the style picked in Settings (Xbox / PlayStation / Nintendo).
const DIR_GLYPH = { up: '▲', down: '▼', left: '◀', right: '▶' };
function gl(text) {
  return String(text ?? '').replace(/\{(ok|back|menu|home|prev|next|toggle|up|down|left|right|kb_west|kb_north|kb_l1|kb_r1|kb_l2|kb_r2|kb_l3|kb_start)\}/g,
    (m, a) => S.state?.glyphs?.actions?.[a] || DIR_GLYPH[a] || ({ ok: 'A', back: 'B', menu: 'Y', prev: 'LB', next: 'RB', kb_west: 'X', kb_north: 'Y', kb_l1: 'LB', kb_r1: 'RB', kb_l2: 'LT', kb_r2: 'RT', kb_l3: 'LS', kb_start: 'Menu' })[a] || a);
}
// PlayStation symbols are drawn (font glyphs like △ sit off-centre); everything else is text
const PS_SVG = {
  '✕': '<path d="M7 7l10 10M17 7L7 17"/>',
  '○': '<circle cx="12" cy="12" r="5.6"/>',
  '□': '<rect x="7" y="7" width="10" height="10" rx="0.6"/>',
  '△': '<path d="M12 6.4l6 10.4H6z"/>',
};
const glb = (a) => {
  const g = gl(`{${a}}`);
  const svg = PS_SVG[g] ? `<svg viewBox="0 0 24 24" aria-label="${g}" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round">${PS_SVG[g]}</svg>` : esc(g);
  return `<b class="glyph g-${S.state?.glyphs?.style || 'xbox'}${PS_SVG[g] ? ' sym' : ''}" data-g="${esc(g)}" data-a="${esc(a)}">${svg}</b>`;
};
function applyGlyphs() {   // the few hints that live in the page itself
  $('#viewer .v-hint').innerHTML = `<b>◀ ▶</b>Browse ${glb('ok')}Slideshow ${glb('back')}Back ${glb('menu')}Hide info`;
  $('.q-foot').innerHTML = `${glb('ok')}Select <b>◀ ▶</b>Adjust ${glb('back')}Resume`;
  if (typeof hint === 'function' && S.state) hint();
}

// ---------------------------------------------------------------- toasts
function toast(text, ico = 'info') {
  const el = document.createElement('div');
  el.className = 'toast';
  el.innerHTML = `<div class="ico">${icon(ico)}</div><div>${esc(gl(text))}</div>`;
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
    $('.dlg-body').textContent = gl(body);
    $('.dlg-body').classList.toggle('long', String(body).split('\n').length > 5);
    $('.dlg-body').scrollTop = 0;
    $('.dlg-body').onscroll = () => this.scrolled();
    requestAnimationFrame(() => this.scrolled());
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
    $('.dlg-buttons').classList.remove('dim');      // left over from a dialog that had text fields
    $('#dialog').hidden = false;
    const first = $('.dlg-fields input');
    this.fi = first ? 0 : -1;               // controller focus: a field index, or -1 = the buttons
    if (first) setTimeout(() => {
      first.focus();
      this.padFocus();
      if (S.lastInput === 'pad') this.editField();     // on a controller: straight to the keyboard
    }, 60);
    return new Promise((res) => { this.resolve = res; });
  },
  renderButtons() {
    $('.dlg-buttons').innerHTML = this.buttons.map((b, i) => `<div class="dlg-btn ${i === this.sel ? 'on' : ''}">${esc(b)}</div>`).join('');
  },
  move(d) { this.sel = (this.sel + d + this.buttons.length) % this.buttons.length; this.renderButtons(); Sfx.move(); },
  // text taller than the box: up / down (or the wheel) scrolls it; fades show there's more
  scroll(d) {
    const b = $('.dlg-body');
    if (b.scrollHeight <= b.clientHeight + 2) return;
    b.scrollBy({ top: d * b.clientHeight * 0.6, behavior: 'smooth' });
    Sfx.move();
    setTimeout(() => this.scrolled(), 260);
  },
  scrolled() {
    const b = $('.dlg-body');
    b.classList.toggle('more-up', b.scrollTop > 2);
    b.classList.toggle('more-down', b.scrollTop + b.clientHeight < b.scrollHeight - 2);
  },
  fields() { return [...document.querySelectorAll('.dlg-fields input')]; },
  padFocus() {
    const fs = this.fields();
    fs.forEach((f, i) => f.classList.toggle('padfocus', i === this.fi));
    $('.dlg-buttons').classList.toggle('dim', this.fi >= 0 && fs.length > 0);
    if (this.fi >= 0 && fs[this.fi]) fs[this.fi].focus(); else document.activeElement?.blur();
  },
  editField() {
    const f = this.fields()[this.fi];
    if (!f) return;
    Osk.show(f, (done) => {
      if (!this.open) return;
      if (done) { this.fi = this.fi + 1 < this.fields().length ? this.fi + 1 : -1; }   // Done: on to the next field
      this.padFocus();
    });
  },
  pad(action) {   // controller in a dialog with text fields
    const n = this.fields().length;
    if (this.fi >= 0) {
      if (action === 'up') { this.fi = Math.max(0, this.fi - 1); this.padFocus(); Sfx.move(); }
      else if (action === 'down') { this.fi = this.fi + 1 < n ? this.fi + 1 : -1; this.padFocus(); Sfx.move(); }
      else if (action === 'ok') this.editField();
      else if (action === 'back') this.close(null);
      return;
    }
    const vert = Shell.active?.dialogVertical;
    if (action === 'up' && n && (!vert || this.sel === 0)) { this.fi = n - 1; this.padFocus(); Sfx.move(); }
    else if (action === (vert ? 'up' : 'left')) this.move(-1);
    else if (action === (vert ? 'down' : 'right')) this.move(1);
    else if (action === 'ok') this.close(this.sel);
    else if (action === 'back') this.close(null);
  },
  close(idx) {
    if (!this.open) return;
    clearInterval(this.timer);
    const values = {};
    document.querySelectorAll('.dlg-fields input').forEach((i) => { values[i.dataset.k] = i.value; });
    $('#dialog').hidden = true; this.open = false;
    if (Osk.open) Osk.hide(false);
    document.activeElement?.blur();
    (idx === null ? Sfx.back : Sfx.ok)();
    this.resolve({ button: idx, values });
  },
};
const confirmBox = async (body, title = '') => (await Dialog.ask({ title, body, buttons: ['Yes', 'No'] })).button === 0;
// For things that can't be undone (power): "No" is highlighted, so a stray A press does nothing.
const confirmSafe = async (body, title = '') => (await Dialog.ask({ title, body, buttons: ['Yes', 'No'], def: 1 })).button === 0;
const message = (body, title = '') => Dialog.ask({ title, body });

// ---------------------------------------------------------------- options panel
// Long Y menus are folded into a few groups, so the everyday choices stay on top
const OPTION_GROUPS = [
  ['Customize…', /^(Change Artwork…|Edit Tag…|Move to Folder…|Show In…|Hide|Rename…?|Change Icon…)$/],
  ['Windows & Proton…', /^(Compatibility Tool…|Launch Options…|Windows Components…)$/],
];
function groupOptions(list) {
  if (list.length <= 6) return list;
  let out = [...list];
  for (const [label, re] of OPTION_GROUPS) {
    const members = out.filter((o) => !o.group && re.test(o.label));
    if (members.length < 2) continue;
    const at = out.indexOf(members[0]);
    out = out.filter((o) => !members.includes(o));
    out.splice(at, 0, { label, group: members });
  }
  // the one you can't take back goes last, away from the thumb
  const risky = out.filter((o) => /^(Delete|Uninstall|Remove)/.test(o.label));
  return [...out.filter((o) => !risky.includes(o)), ...risky];
}
// what an Options panel opened from the menu is about (the highlighted row)
function list_title() { try { return list()[sel()]?.label || ''; } catch (e) { return ''; } }
const Options = {
  open: false, sel: 0, list: [],
  offset: 0,
  show(list, sel = 0, parent = null) {
    if (!list?.length) return;
    if (!parent) {
      list = groupOptions(list);
      $('#options').dataset.title = this.title || (QuickMenu.open ? '' : list_title());
      this.title = '';
    }
    this.parent = parent;
    this.list = list; this.sel = sel; this.offset = 0; this.open = true;
    $('#options').hidden = false; this.render(); Sfx.ok();
  },
  up() { const p = this.parent; this.show(p.list, p.sel, p.parent); },     // Back from a group: to its menu
  render() {
    const el = $('.opt-list');
    el.innerHTML = (this.parent ? `<div class="opt-head">${esc(this.parent.list[this.parent.sel].label.replace(/…$/, ''))}</div>` : '') +
      this.list.map((o, i) => `<div class="opt ${i === this.sel ? 'on' : ''}${o.group ? ' grp' : ''}">${esc(gl(o.label))}</div>`).join('');
    clearTimeout(this.mq);
    this.mq = setTimeout(() => Marquee.set(el.querySelector('.opt.on')), 400);
    // Keep the highlighted entry on screen: the list starts at y=380 on the
    // 1080px stage and slides up/down once the selection nears an edge.
    const { TOP, MIN, MAX } = Shell.active?.optionsGeom || { TOP: 380, MIN: 140, MAX: 960 };
    const row = el.children[this.sel + (this.parent ? 1 : 0)];
    const y = TOP + this.offset + row.offsetTop;
    if (y < MIN) this.offset += MIN - y;
    if (y + row.offsetHeight > MAX) this.offset -= y + row.offsetHeight - MAX;
    el.style.transform = `translateY(${this.offset}px)`;
    $('#options').classList.toggle('more-up', TOP + this.offset < MIN - 10);
    $('#options').classList.toggle('more-down', TOP + this.offset + el.scrollHeight > MAX + 10);
  },
  move(d) { this.sel = (this.sel + d + this.list.length) % this.list.length; this.render(); Sfx.move(); },
  hide() { this.open = false; $('#options').hidden = true; },
  pick() {
    const o = this.list[this.sel];
    if (o.group) { Sfx.ok(); this.show(o.group, 0, { list: this.list, sel: this.sel, parent: this.parent }); return; }
    this.hide(); Sfx.ok(); o.action();
  },
};

// ---------------------------------------------------------------- state
const S = {
  state: null, jobs: [], ci: 0, catSel: {}, stack: [], items: {},
};
const ORDER = ['users', 'settings', 'photo', 'music', 'video', 'tv', 'game', 'apps', 'store', 'party'];

function prov(id) { return S.state.providers.find((p) => p.id === id); }

// ---------------------------------------------------------------- item builders
// "Cancel Download" for a running download: stops it and deletes what was downloaded so far
async function cancelJob(j) {
  const steam = j.provider === 'steam';
  if (!(await confirmBox(`Cancel downloading ${j.title}?\nWhat's downloaded so far is deleted.${steam ? '\nSteam may ask you to confirm removing it.' : ''}`, 'Cancel Download'))) return;
  if (await call(() => api.post('/api/jobs/cancel', { id: j.id }))) { toast(`Cancelled ${j.title}`, 'download'); setTimeout(pollJobs, 600); }
}
function jobOptions(j) { return j && j.cancellable ? [{ label: 'Cancel Download', action: () => cancelJob(j) }] : []; }

function gameItem(g, inStore) {
  const job = S.jobs.find((j) => j.kind === 'install' && j.provider === g.provider && j.game_id === g.id && j.status === 'running');
  const it = {
    key: `${g.provider}:${g.id}`, label: g.title, art: g.art || '', artTitle: g.title, badge: STORE_NAMES[g.provider], recent: g.last_played || 0,
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
  } else {
    it.action = () => (job.cancellable ? cancelJob(job) : toast(`${g.title}: ${job.message}`, 'download'));
    options.push(...jobOptions(job));
  }
  if (typeof changeArtwork !== 'undefined' && g.provider !== 'demo') {
    options.push({ label: 'Change Artwork…', action: () => changeArtwork({ key: `${g.provider}:${g.id}`, title: g.title, custom: !!g.art_custom,
      steam: g.provider === 'steam' && /^\d+$/.test(g.id) ? g.id : null }) });
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
        { key: 'off', label: 'Turn Off System', icon: 'power', action: async () => { if (await confirmSafe('Turn off the system?')) api.post('/api/power/poweroff'); } },
        { key: 'reboot', label: 'Restart System', icon: 'restart', action: async () => { if (await confirmSafe('Restart the system?')) api.post('/api/power/reboot'); } },
      ];
    },
  },
  {
    id: 'game', label: 'Game', icon: 'game',
    async load() {
      const items = [];
      if (typeof TROPHIES_FOLDER !== 'undefined') items.push(TROPHIES_FOLDER);   // always first
      if (S.state.providers?.some((p) => p.id === 'steam')) {
        items.push({ key: 'bpm', label: 'Steam Big Picture', icon: 'game', sub: 'Steam\'s console mode: your whole Steam library, store and friends',
          action: async () => { const r = await call(() => api.post('/api/steam/bigpicture')); if (r?.demo) toast('Demo mode: Steam isn\'t started', 'info'); } });
      }
      // only games and emulators here; other apps (Discord, browsers) are in the Quick Menu's Switch App
      for (const w of (S.state.windows || []).filter((x) => x.game)) {
        items.push({ key: `win:${w.con_id}`, label: `Return to ${w.title}`, icon: 'window', sub: 'Running',
          action: () => api.post('/api/window/focus', { con_id: w.con_id }),
          options: [{ label: 'Return', action: () => api.post('/api/window/focus', { con_id: w.con_id }) },
                    { label: 'Quit', action: async () => { await api.post('/api/window/close', { con_id: w.con_id }); setTimeout(loadState, 800); } }] });
      }
      for (const j of S.jobs.filter((j) => j.kind === 'install' && j.status === 'running')) {
        items.push({ key: `job:${j.id}`, label: j.title, icon: 'download', sub: `Downloading… ${j.message}`, progress: j.progress, badge: STORE_NAMES[j.provider],
          ...(j.cancellable ? { action: () => cancelJob(j), options: jobOptions(j) } : {}) });
      }
      if (typeof EMULATION_FOLDER !== 'undefined') items.push(EMULATION_FOLDER);
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
      if (typeof INSTALL_APPS !== 'undefined') items.push({ ...INSTALL_APPS, key: 'install-apps', label: 'Install Apps' });
      const linked = S.state.providers.filter((p) => p.linked);
      items.push(...linked.map(storeFolder));
      if (!linked.length) {
        items.push({ key: 'signin', label: 'Sign In to a Store', icon: 'account', sub: 'Steam, GOG and Epic accounts are in Settings › Accounts',
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
// What you used last in each category (a look can lead with it: the Dashboard's big tile).
// Items can say when they were last used themselves (games: last played; Video: the last
// video); otherwise it's when you picked that top-level item here. Kept in this browser.
const Recent = {
  data: (() => { try { return JSON.parse(localStorage.getItem('crossbar.recent') || '{}'); } catch (e) { return {}; } })(),
  touch(cat, key) {
    if (!cat || !key || key === 'loading') return;
    const c = (this.data[cat] ||= {});
    c[key] = Date.now() / 1000;
    const keep = Object.entries(c).sort((a, b) => b[1] - a[1]).slice(0, 40);
    this.data[cat] = Object.fromEntries(keep);
    try { localStorage.setItem('crossbar.recent', JSON.stringify(this.data)); } catch (e) { /* private mode */ }
  },
  when(cat, it) { return Math.max(it.recent || 0, this.data[cat]?.[it.key] || 0); },
  top(cat, items) {
    let best = -1, t = 0;
    items.forEach((it, i) => { const w = this.when(cat, it); if (w > t) { t = w; best = i; } });
    return best;
  },
};

function list() { return S.stack.length ? S.stack.at(-1).items : (S.items[CATS[S.ci].id] || []); }
function sel() { return S.stack.length ? S.stack.at(-1).sel : (S.catSel[CATS[S.ci].id] ?? 0); }
function setSel(i) { if (S.stack.length) S.stack.at(-1).sel = i; else S.catSel[CATS[S.ci].id] = i; }

async function refresh(catId) {
  const cat = CATS.find((c) => c.id === catId);
  if (!cat || !S.state) return;
  try {
    let items = await cat.load();
    if (typeof applyExtras === 'function') items = applyExtras(catId, items);   // apps put here, your folders
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
  try { frame.items = await item.children(); if (typeof decorate === 'function') frame.items = decorate(frame.items); }
  catch (e) { frame.items = [{ key: 'err', label: 'Couldn’t load', icon: 'info', sub: e.message }]; }
  if (S.stack.at(-1) === frame) renderColumn(true);
}
async function reloadFolder() {
  const frame = S.stack.at(-1);
  if (!frame) return;
  const prevKey = frame.items[frame.sel]?.key;
  try { frame.items = await frame.source.children(); if (typeof decorate === 'function') frame.items = decorate(frame.items); } catch (e) { return; }
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

// ---------------------------------------------------------------- shell seam
// The front end is swappable: Settings › Theme › Interface picks a *look* — the XMB (looks/xmb),
// or another look from web/looks/ (docs/LOOKS.md). A look draws the menu and dresses the shared pieces;
// everything underneath — the item model, folders, actions, Options, dialogs, the Quick
// Menu's rows, input, polling — is one implementation, so both looks run the same commands.
//
// A look provides: setup teardown resetCats render renderCats renderColumn position itemEl
// hint moveV moveH, and may add:
//   configure(state)   apply its settings (called on every state update: keep it cheap)
//   bumper(d)          LB / RB on the menu; return true if used (else they skip tracks)
//   patched()          a running download changed some rows' text / progress
//   dialogVertical     dialog buttons stack vertically (up / down choose)
//   optionsGeom        {TOP, MIN, MAX}: where the Options list sits and may slide to
//   renderQuick(q)     draw the Quick Menu (q = QuickMenu: rows, sel, page, data); true if drawn
//   quickTabs          the Quick Menu has tabs (LB / RB, QuickMenu.bumper)
//
// It must also keep to the *item node contract*, because the shared code reaches into
// the nodes a look built:
//   · the root element has class "item"                    (ensureArt, patchJobRows)
//   · it holds a .txt wrapper containing a .sub, and a .bar > i when progress != null
//   · columnEls[i] is the node for list()[i] — index-parallel, whatever the visual order
// Break the last one and a running download's progress bar lands on the wrong game.
let columnEls = [];
const Shell = {
  id: 'xmb', impls: {},
  artWindow: 8,                             // rows either side of the cursor that load artwork
  register(id, impl) { this.impls[id] = impl; },
  get active() { return this.impls[this.id]; },
  // The look is chosen once, at start-up (Looks.load: the one built into the page). Settings ›
  // Interface saves another one, which takes over when the menu reloads.
  start(id) {
    this.id = this.impls[id] ? id : 'xmb';
    document.body.dataset.shell = this.id;
    columnEls = [];
    this.active?.setup?.();
    this.started = true;
  },
  // Called from applyState, so on every /api/state: configure() (background, accent…) runs every
  // time and must be cheap. A different Interface in the settings waits for the reload.
  apply(iface) {
    document.body.dataset.shell = this.id;   // a theme reload can never lose the CSS scope
    this.pending = iface && iface !== this.id ? iface : null;
    this.active?.configure?.(S.state);
  },
  resetCats() { this.active?.resetCats?.(); },
};



// Long text on the highlighted line (an Options entry, an item's name or description) that doesn't
// fit scrolls slowly across, pauses at the end and comes back, so all of it can be read.
const Marquee = {
  set(el) {
    if (!el) return;
    el.classList.remove('mq');
    const over = el.scrollWidth - el.clientWidth;
    if (over <= 4) return;
    const dist = over + 30;
    el.style.setProperty('--mq-dist', `-${dist}px`);
    el.style.setProperty('--mq-dur', `${Math.max(5, dist / 40 / 0.6).toFixed(1)}s`);    // ~40 px a second
    void el.offsetWidth;                                                              // restart from the start
    el.classList.add('mq');
  },
  clear(root) { (root || document).querySelectorAll('.mq').forEach((e) => e.classList.remove('mq')); },
  // the highlighted item in the menu (after it has settled into place)
  items() {
    clearTimeout(this.t);
    this.t = setTimeout(() => {
      this.clear($('#stage'));
      const on = document.querySelector('#column .item.on');
      if (on) on.querySelectorAll('.label, .sub').forEach((e) => this.set(e));
      if (Options.open) this.set(document.querySelector('#options .opt.on'));
    }, 450);
  },
};

// The rest of the shell (and every module) calls these by name; they follow whichever
// look is active. Declarations, not arrow consts, so they hoist like the functions they replace.
function itemEl(it)              { return Shell.active.itemEl(it); }
function renderCats()            { Shell.active?.renderCats(); }
function renderColumn(r = true)  { Shell.active?.renderColumn(r); }
function position()              { Shell.active?.position(); Marquee.items(); }
function render()                { Shell.active?.render(); }
function hint()                  { Shell.active?.hint(); }
function moveV(d)                { Shell.active?.moveV(d); }
function moveH(d)                { Shell.active?.moveH(d); }

// ---------------------------------------------------------------- acting on a row
function confirm() {
  const it = list()[sel()];
  if (!it) return;
  if (!S.stack.length) Recent.touch(CATS[S.ci].id, it.key);     // only top-level picks: deeper ones say so themselves
  if (it.children) return openFolder(it);
  if (it.action) { Sfx.ok(); it.action(); }
}
function back() { if (S.stack.length) { S.stack.pop(); Sfx.back(); render(); } }
function options() {
  const it = list()[sel()];
  if (!it?.options) return;
  Options.title = it.label || '';       // the Dashboard's options flyout is headed by what it's for
  Options.show(it.options);
}

function handle(action) {
  if (Osk.open) return Osk.handle(action);
  if (Term.open && !Dialog.open) return Term.handle(action);
  if (QuickMenu.open && !Dialog.open) return QuickMenu.handle(action);
  if (Viewer.open && !Dialog.open) return Viewer.handle(action);
  if (Dialog.open) {
    if (Dialog.fields().length) return Dialog.pad(action);
    const vert = Shell.active?.dialogVertical && Dialog.buttons.length > 1;   // the 360 stacks its buttons
    if (action === (vert ? 'up' : 'left')) Dialog.move(-1);
    else if (action === (vert ? 'down' : 'right')) Dialog.move(1);
    else if (action === 'up' || action === 'down') Dialog.scroll(action === 'down' ? 1 : -1);   // long text
    else if (action === 'ok') Dialog.close(Dialog.sel);
    else if (action === 'back') Dialog.close(null);
    return;
  }
  if (Options.open) {
    if (action === 'up') Options.move(-1);
    else if (action === 'down') Options.move(1);
    else if (action === 'ok') Options.pick();
    else if (action === 'right' && Options.list[Options.sel]?.group) Options.pick();
    else if ((action === 'back' || action === 'left') && Options.parent) { Options.up(); Sfx.back(); }
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
  if (Osk.open) return Osk.handle(action);            // the keyboard has the controller while it's up
  if (action === 'home') return QuickMenu.toggle();
  if ((action === 'prev' || action === 'next') && !Dialog.open && !Options.open && !Osk.open) {
    const d = action === 'next' ? 1 : -1;
    if (QuickMenu.open ? QuickMenu.bumper?.(d) : (!Viewer.open && !Term.open && Shell.active?.bumper?.(d))) return;
  }
  if ((action === 'prev' || action === 'next' || action === 'toggle') && !Dialog.open) return mediaKey(action);
  handle(ACTION[action] || action);
}

addEventListener('keydown', (e) => {
  if (e.isTrusted) S.lastInput = 'kbd';
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

// "Away": a game or app is in front, or a game is loading behind the launch screen. The menu
// then does next to nothing — animations pause, the backdrop stops drawing, polling slows right
// down — so every bit of CPU, GPU and memory bandwidth goes to the game.
function isAway() { return !S.xmbFocused || document.hidden || !$('#launch').hidden; }
function syncAway() {
  const a = isAway();
  if (a !== document.body.classList.contains('away')) document.body.classList.toggle('away', a);
  return a;
}
document.addEventListener('visibilitychange', syncAway);
setInterval(syncAway, 2000);

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
  // away from the menu the backend reads the controller; check far less often
  if (document.body.classList.contains('away') && !pad.capture) setTimeout(() => requestAnimationFrame(pollPads), 250);
  else requestAnimationFrame(pollPads);
}
function fire(a) {
  S.lastInput = 'pad';
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
// modules can handle their own events (Lutris installer questions…): a hook returns true when it did
const EventHooks = [];
function connectEvents() {
  const es = new EventSource('/api/events');
  es.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    for (const h of EventHooks) { try { if (h(ev)) return; } catch (e) { console.error(e); } }
    if (ev.type === 'launching') {
      $('#launch .l-title').textContent = ev.title; $('#launch .l-sub').textContent = ev.sub || 'Starting…'; $('#launch').hidden = false;
      clearTimeout(S.launchT); S.launchT = setTimeout(() => { $('#launch').hidden = true; syncAway(); }, 320000); syncAway(); return;
    }
    if (ev.type === 'art') { refresh('game'); return; }
    if (ev.type === 'notice') { toast(ev.text, ev.icon || 'info'); return; }        // backend notices (torrent finished…)
    if (ev.type === 'vpn') { const f = S.stack.at(-1); if (f && /^(vpn|network)/.test(f.source.key)) reloadFolder(); return; }
    if (ev.type === 'theme') { Theme.load(); return; }
    if (ev.type === 'interface') { loadState(); return; }   // Interface changed: used after a reload
    if (ev.type === 'apps') { loadApps().then(refreshAll); return; }
    if (ev.type === 'launched') { $('#launch').hidden = true; syncAway(); return; }
    if (ev.type === 'launch-timeout') { clearTimeout(S.launchT); $('#launch').hidden = true; syncAway(); toast(ev.error ? `Couldn't start ${ev.title}: ${ev.error}` : `${ev.title} didn't open a window — check Steam`, 'info'); return; }
    if (ev.type === 'term') { if (ev.id === Term.id) Term.output(ev.data); return; }
    if (ev.type === 'term-exit') { if (ev.id === Term.id) { Term.id = null; if (Term.open) Term.hide(); } return; }
    if (ev.type === 'open-terminal') { Term.show(ev.cmd); return; }
    if (ev.type === 'focus') { S.xmbFocused = ev.xmb; if (ev.xmb) pad.justFocused = true; syncAway(); return; }
    if (ev.type === 'open-cat') {          // from the Quick Menu overlay: a category, maybe a folder in it
      if (QuickMenu.open) QuickMenu.close(false);
      if (CATS.some((c) => c.id === ev.cat)) goCat(ev.cat);
      if (ev.folder === 'trophies' && typeof TROPHIES_FOLDER !== 'undefined') openFolder(TROPHIES_FOLDER);
      if (ev.folder === 'live-tv' && typeof iptvTopFolder === 'function' && S.state.iptv?.linked) openFolder(iptvTopFolder('live'));   // a remote's Live TV / Guide button
      return;
    }
    if (ev.type === 'open-settings') { QuickMenu.open && QuickMenu.close(false); if (ev.folder) openSettingsFolder(ev.folder); else goCat('settings'); return; }
    // meant for the overlay window or the system keyboard on top: the menu underneath must not act on it
    if (ev.type === 'input' && (ev.to === 'overlay' || ev.to === 'osk')) return;
    if (ev.type === 'osk-xmb') {                         // "Keyboard" asked for while the menu is in front
      const el = document.activeElement;
      if (el && el.tagName === 'INPUT' && !Osk.open) Osk.show(el);
      else if (!Osk.open) toast('Pick a text box first: the keyboard opens there', 'info');
      return;
    }
    if (ev.type === 'physical-input') { S.lastInput = 'kbd'; if (Osk.open) Osk.hide(false); return; }
    if (ev.type === 'input') {
      S.lastInput = 'pad';
      act(ev.action);
    } else if (ev.type === 'quick') {
      if (ev.open) { api.get('/api/quick/pending').catch(() => {}); QuickMenu.show(ev.shot); } else QuickMenu.toggle();
    }
  };
  es.onerror = () => { es.close(); setTimeout(connectEvents, 1500); };
}

// Play/Pause and skip work anywhere in the XMB, for local music or Spotify.
// "Now Playing · Song" / "Paused · Song" after a play/pause/skip
function nowToast(title, playing, artist = '') {
  if (!title) return;
  toast(`${playing ? 'Now Playing' : 'Paused'} · ${title}${artist ? ' — ' + artist : ''}`, 'music');
}

async function mediaKey(action) {
  const m = await api.get('/api/music/state').catch(() => null);
  if (m) {
    const r = await api.post('/api/music/control', { action: action === 'toggle' ? 'toggle' : action });
    Sfx.ok();
    nowToast(r?.title, r && !r.paused, r?.artist);
  } else if (S.state?.spotify?.linked) {
    const r = await call(() => api.post('/api/spotify/control', { action }));
    if (!r) return;
    Sfx.ok();
    nowToast(r.now?.name, r.now?.playing, r.now?.artist);
  }
}

// ---------------------------------------------------------------- polling
function applyState() {
  Shell.apply(S.state.interface);   // Settings › Theme › Interface; rebuilds only if it changed
  Waves.setTheme(S.state.theme);
  applyGlyphs();
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
  patchJobRows(jobs);                       // live progress text and bars, every poll
  const sig = JSON.stringify(jobs.map((j) => [j.id, j.status]));
  if (sig === lastJobSig) return;           // lists only reload when a download starts or ends
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
    else if (j.status === 'cancelled') continue;          // its own toast already said so
    else if (j.kind === 'install') toast(`Download complete: ${j.title}`, 'download');
    else if (j.kind === 'login') toast(`Signed in to ${j.title}`, 'link');
    else if (j.kind === 'wifi') toast(`Connected to ${j.title}`, 'wifi');
  }
  if (finished) { await loadState(); if (S.stack.at(-1)?.source?.key === 'accounts') reloadFolder(); }
  const cur = CATS[S.ci].id;
  if (S.stack.length) { if (finished || S.stack.at(-1).items.some((i) => jobFor(i, jobs))) reloadFolder(); }
  else refresh(cur);
  if (finished) CATS.forEach((c) => c.id !== cur && refresh(c.id));
}

// the running job a row stands for (a game's tile, a "Downloading…" row, a Flathub app)
function jobFor(it, jobs) {
  return jobs.find((j) => j.status === 'running' && (it.key === `job:${j.id}` || it.key === `${j.provider}:${j.game_id}`
    || (j.provider === 'flatpak' && it.key === `fh:${j.game_id}`)));
}
function patchJobRows(jobs) {
  const items = S.stack.length ? S.stack.at(-1).items : S.items[CATS[S.ci]?.id];
  if (!items || !jobs.some((j) => j.status === 'running')) return;
  let changed = false;
  for (const it of items) {
    const j = jobFor(it, jobs);
    if (!j) continue;
    const sub = `${j.kind === 'uninstall' ? 'Removing…' : 'Downloading…'} ${j.message || ''}`.trim();
    if (it.sub !== sub || it.progress !== j.progress) { it.sub = sub; it.progress = j.progress; changed = true; }
  }
  if (!changed) return;
  // update just the text and bar of those rows (no rebuild: selection and animation stay put)
  items.forEach((it, i) => {
    const el = columnEls[i];
    if (!el || !jobFor(it, jobs)) return;
    const sub = el.querySelector('.sub'); if (sub) sub.textContent = gl(it.sub);
    const bar = el.querySelector('.bar i'); if (bar) bar.style.width = `${(it.progress * 100).toFixed(1)}%`;
    else if (it.progress != null) { const t = el.querySelector('.txt'); if (t) t.insertAdjacentHTML('beforeend', `<div class="bar"><i style="width:${(it.progress * 100).toFixed(1)}%"></i></div>`); }
  });
  Shell.active?.patched?.();                // a look with a detail panel refreshes it
}
// Now Playing (music or Spotify), ticking smoothly in every look. The player and Spotify report the
// position every couple of seconds, rounded and a little late; showing each report made the seconds
// jump and the bar step. A report only resets this clock on a new track, play / pause, or when it's
// more than 2 s out; in between, the row's time and bar move on by themselves each second.
const NowClock = {
  c: null,
  sample(title, pos, dur, paused) {
    pos = Number(pos) || 0; paused = !!paused;
    const c = this.c;
    if (c && c.title === title && c.paused === paused && Math.abs(this.pos() - pos) < 2) { c.dur = dur || c.dur; return this.pos(); }
    this.c = { title, pos, dur: Number(dur) || 0, paused, at: Date.now() };
    return pos;
  },
  pos() {
    const c = this.c; if (!c) return 0;
    return Math.min(c.dur || Infinity, c.pos + (c.paused ? 0 : (Date.now() - c.at) / 1000));
  },
};
setInterval(() => {
  const c = NowClock.c;
  if (!c || c.paused || isAway() || Shell.active?.ownsNowClock) return;   // the Dashboard runs its own (same rules)
  const pos = NowClock.pos();
  list().forEach((it, i) => {
    if (!it.nowPlaying || it.label !== c.title) return;
    const el = columnEls[i]; if (!el) return;
    const sub = el.querySelector('.sub');
    if (sub) sub.textContent = sub.textContent.replace(/\d+:\d\d(:\d\d)? \/ /, `${fmtTime(pos)} / `);
    if (c.dur) {
      it.progress = Math.min(1, pos / c.dur);
      const bar = el.querySelector('.bar i'); if (bar) bar.style.width = `${(it.progress * 100).toFixed(1)}%`;
    }
  });
}, 1000);

let jobTicks = 0;
setInterval(() => { if (!syncAway() || ++jobTicks % 10 === 0) pollJobs(); }, 1000);   // every 10 s while away
// Now Playing items (music, Spotify, video) refresh themselves while visible.
setInterval(() => {
  if (Dialog.open || Options.open || Viewer.open || QuickMenu.open || !S.state || isAway()) return;
  const f = S.stack.at(-1);
  if (f) { if (f.source.live) reloadFolder(); }
  else if (CATS[S.ci].live) refresh(CATS[S.ci].id);
}, 2000);
let stateTicks = 0;
setInterval(async () => {   // pick up windows opening/closing (games, Discord)
  if (isAway() && ++stateTicks % 4) return;   // every 16 s while away
  const before = JSON.stringify(S.state?.windows || []);
  try { await loadState(); } catch { return; }
  if (JSON.stringify(S.state.windows) !== before && !S.stack.length && ['game', 'party'].includes(CATS[S.ci].id)) refresh(CATS[S.ci].id);
}, 4000);

// ---------------------------------------------------------------- boot
async function boot() {
  await Looks.load();                         // every look (console skin) is ready before the first draw
  connectEvents();
  CATS.sort((a, b) => ORDER.indexOf(a.id) - ORDER.indexOf(b.id));
  S.ci = CATS.findIndex((c) => c.id === 'game');
  render();
  // The splash goes as soon as the Game column is ready (other columns fill in behind it; some
  // wait on the network on a cold boot) and never stays more than 10 s.
  let booted = false;
  const reveal = () => { if (booted) return; booted = true; $('#boot').classList.add('done'); Sfx.ok(); };
  setTimeout(reveal, 10000);
  for (let tries = 0; ; tries++) {
    try { await loadState(); break; } catch { await new Promise((r) => setTimeout(r, 500)); }
  }
  await Promise.race([Theme.load(), new Promise((r) => setTimeout(r, 2000))]);
  // categories added by later scripts (Apps) take their place in the bar
  CATS.sort((a, b) => ORDER.indexOf(a.id) - ORDER.indexOf(b.id));
  S.ci = CATS.findIndex((c) => c.id === 'game');
  Shell.resetCats();
  if (typeof loadApps === 'function') await Promise.race([Promise.all([loadApps(), loadFolders()]), new Promise((r) => setTimeout(r, 3000))]);
  S.items = {};
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const others = Promise.all(CATS.filter((c) => c.id !== 'game').map((c) => refresh(c.id)));
  await Promise.race([refresh('game'), sleep(4000)]);
  render();
  setTimeout(reveal, 300);
  others.then(() => render());
  let reopen = null;                          // back where you were after Settings › Interface reloaded the menu
  try { reopen = sessionStorage.getItem('crossbar.reopen'); sessionStorage.removeItem('crossbar.reopen'); } catch { /* none */ }
  if (reopen && typeof openSettingsFolder === 'function') setTimeout(() => openSettingsFolder(reopen), 400);
  if (S.state.pads?.error) setTimeout(() => toast(S.state.pads.error, 'game'), 2500);
}
