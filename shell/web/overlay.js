'use strict';
// Quick Menu overlay page (shown by crossbar-overlay above the running app).
// Input arrives from crossbard ("to": "overlay") or from the keyboard.

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const api = {
  async get(p) { const r = await fetch(p); const j = await r.json(); if (!r.ok) throw new Error(j.error); return j; },
  async post(p, b) {
    const r = await fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) });
    const j = await r.json(); if (!r.ok) throw new Error(j.error); return j;
  },
};
const fmt = (t) => { t = Math.max(0, Math.floor(t || 0)); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`; };
const thumb = (path) => `/api/thumb?path=${encodeURIComponent(path)}`;

const O = { visible: false, rows: [], sel: 0, data: null, timer: null, armed: null, keymap: null };

function toast(text) {
  const t = $('#toast');
  t.textContent = text;
  t.classList.remove('hidden');
  clearTimeout(toast.h);
  toast.h = setTimeout(() => t.classList.add('hidden'), 2500);
}
async function call(fn, ok) {
  try { const r = await fn(); if (ok) toast(ok); return r; } catch (e) { toast(e.message || 'Something went wrong'); return null; }
}

function build(d) {
  const rows = [];
  const after = () => setTimeout(refresh, 300);
  const what = d.app ? (d.app.video ? 'Video' : (/chrom/i.test(d.app.app) ? 'App' : 'Game')) : null;
  if (d.app) {
    rows.push({ key: 'resume', icon: 'play', label: `Resume ${what}`, sub: d.app.title, ok: () => close(true) });
    rows.push({ key: 'close', icon: 'power', danger: true,
      label: O.armed === 'close' ? `Press A again to close` : `Close ${what}`,
      sub: O.armed === 'close' ? `${d.app.title}${d.app.video ? '' : ' — unsaved progress may be lost'}` : d.app.title,
      ok: async () => {
        if (O.armed !== 'close') { O.armed = 'close'; render(); return; }
        O.armed = null;
        await call(() => api.post('/api/overlay/close-app'), `Closed ${d.app.title}`);
      } });
  }
  rows.push({ key: 'home', icon: 'users', label: 'Go to Home', sub: d.app ? `${d.app.title} stays open` : 'The Crossbar menu',
    ok: () => api.post('/api/overlay/home') });

  const m = d.music, sp = d.spotify;
  if (m) {
    const ctl = (action) => async () => { await api.post('/api/music/control', { action }); after(); };
    rows.push({ key: 'media', art: thumb(m.path), icon: 'music', label: m.title,
      sub: `${m.artist ? m.artist + ' · ' : ''}${m.paused ? 'Paused' : 'Playing'} · ${fmt(m.position)} / ${fmt(m.duration)}`,
      bar: m.duration ? m.position / m.duration : null, hint: '◀ ▶ skip · A play/pause',
      ok: ctl('toggle'), adjust: (dir) => ctl(dir > 0 ? 'next' : 'prev')() });
  } else if (sp) {
    const ctl = (action) => async () => { await call(() => api.post('/api/spotify/control', { action })); after(); };
    rows.push({ key: 'media', art: sp.art, icon: 'spotify', label: sp.name,
      sub: `Spotify · ${sp.artist}${sp.here ? '' : ` · on ${sp.device}`} · ${sp.playing ? 'Playing' : 'Paused'}`,
      bar: sp.duration ? sp.position / sp.duration : null, hint: '◀ ▶ skip · A play/pause',
      ok: ctl('toggle'), adjust: (dir) => ctl(dir > 0 ? 'next' : 'prev')() });
  }
  const out = d.audio?.output || {};
  if (out.volume != null) {
    rows.push({ key: 'vol', icon: 'sound', label: 'Volume', sub: out.muted ? 'Muted' : `${out.volume}%`,
      bar: out.muted ? 0 : Math.min(1, out.volume / 100), hint: '◀ ▶ adjust · A mute',
      ok: async () => { await api.post('/api/audio', { target: 'output', mute: true }); after(); },
      adjust: async (dir) => { await api.post('/api/audio', { target: 'output', delta: dir * 5 }); after(); } });
  }
  if (d.outputs?.length > 1) {
    rows.push({ key: 'out', icon: 'sound', label: 'Sound Output', sub: d.output?.name || 'Default', hint: 'A switch',
      ok: async () => { const r = await call(() => api.post('/api/quick/output')); if (r?.name) toast(`Sound output: ${r.name}`); after(); } });
  }
  const mic = d.audio?.mic || {};
  if (mic.volume != null) {
    rows.push({ key: 'mic', icon: 'mic', label: 'Microphone', sub: mic.muted ? 'Muted' : `${mic.volume}%`, hint: 'A mute',
      ok: async () => { await api.post('/api/audio', { target: 'mic', mute: true }); after(); } });
  }
  rows.push({ key: 'pad', icon: 'game', label: 'Controller & Keyboard', sub: 'Button mapping',
    ok: () => api.post('/api/overlay/settings', { folder: 'controls' }) });
  rows.push({ key: 'net', icon: 'wifi', label: 'Network', sub: 'Wi-Fi and connection',
    ok: () => api.post('/api/overlay/settings', { folder: 'network' }) });
  rows.push({ key: 'power', icon: 'power', danger: true,
    label: O.armed === 'power' ? 'Press A again to turn off' : 'Turn Off System', sub: '',
    ok: () => { if (O.armed !== 'power') { O.armed = 'power'; render(); return; } api.post('/api/power/poweroff'); } });
  return rows;
}

function render() {
  const d = O.data || {};
  $('#title').textContent = d.app ? d.app.title : 'Crossbar';
  $('#back-to').textContent = d.app ? (d.app.video ? 'video' : 'game') : 'menu';
  $('#rows').innerHTML = O.rows.map((r, i) => `
    <div class="row ${i === O.sel ? 'on' : ''} ${r.danger ? 'danger' : ''}">
      <div class="ico">${r.art ? `<div class="art" style="background-image:url('${esc(r.art)}')"></div>` : icon(r.icon)}</div>
      <div class="txt"><div class="label">${esc(r.label)}</div>${r.sub ? `<div class="sub">${esc(r.sub)}</div>` : ''}
        ${r.bar != null ? `<div class="bar"><i style="width:${(r.bar * 100).toFixed(1)}%"></i></div>` : ''}</div>
      ${r.hint && i === O.sel ? `<div class="hint">${esc(r.hint)}</div>` : ''}
    </div>`).join('');
  document.querySelector('.row.on')?.scrollIntoView({ block: 'nearest' });
  $('#clock').textContent = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

async function refresh() {
  try { O.data = await api.get('/api/quick'); } catch { return; }
  const key = O.rows[O.sel]?.key;
  O.rows = build(O.data);
  const i = O.rows.findIndex((r) => r.key === key);
  O.sel = i >= 0 ? i : Math.min(O.sel, O.rows.length - 1);
  render();
}

function show(on) {
  O.visible = on;
  O.armed = null;
  $('#ov').classList.toggle('hidden', !on);
  clearInterval(O.timer);
  if (on) {
    O.sel = 0;
    refresh();
    O.timer = setInterval(refresh, 1000);
  }
}

function close(resume) { api.post('/api/overlay/close', { resume }); }

function handle(a) {
  if (!O.visible) return;
  const r = O.rows[O.sel];
  if (a === 'up' || a === 'down') {
    const n = Math.max(0, Math.min(O.rows.length - 1, O.sel + (a === 'up' ? -1 : 1)));
    if (n !== O.sel) { O.sel = n; O.armed = null; O.rows = build(O.data || {}); render(); }
  } else if ((a === 'left' || a === 'right') && r?.adjust) {
    r.adjust(a === 'right' ? 1 : -1);
  } else if (a === 'ok' && r?.ok) {
    r.ok();
  } else if (a === 'back' || a === 'menu') {
    if (O.armed) { O.armed = null; O.rows = build(O.data || {}); render(); } else close(true);
  } else if (a === 'home') {
    close(true);
  } else if (a === 'toggle' || a === 'prev' || a === 'next') {
    const media = O.rows.find((x) => x.key === 'media');
    if (media) (a === 'toggle' ? media.ok() : media.adjust(a === 'next' ? 1 : -1));
  }
}

// keyboard (the overlay has the keyboard while it's open)
const keyName = (e) => (e.key === ' ' ? 'Space' : e.key.length === 1 ? e.key.toLowerCase() : e.key);
addEventListener('keydown', (e) => {
  const map = O.keymap || { up: ['ArrowUp'], down: ['ArrowDown'], left: ['ArrowLeft'], right: ['ArrowRight'],
    ok: ['Enter', 'Space'], back: ['Escape', 'Backspace'], menu: ['Tab'], home: ['Home'] };
  const name = keyName(e);
  for (const [a, keys] of Object.entries(map)) {
    if (keys.includes(name)) { e.preventDefault(); handle(a); return; }
  }
});

function connect() {
  const es = new EventSource('/api/events?role=overlay');
  es.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    if (ev.type === 'overlay') show(ev.visible);
    else if (ev.type === 'input' && ev.to === 'overlay') handle(ev.action);
  };
  es.onerror = () => { es.close(); setTimeout(connect, 1500); };
}
connect();
api.get('/api/controls').then((c) => { O.keymap = c.keyboard; }).catch(() => {});
api.get('/api/quick/overlay-state').then((s) => show(!!s.open)).catch(() => {});
