'use strict';
// The Dashboard look — modelled on the Xbox 360's last dashboard (2011 onwards): lowercase
// pivots across the top, a horizontally scrolling surface of tiles under them, flat colour,
// lists with a solid highlight bar, a Guide with tabs, stacked dialog buttons, toasts along
// the bottom. Settings › Theme › Interface switches between it and the XMB on the fly.
//
// It's a whole front end, not a re-skin: it builds its own page (#x-root), its own item
// nodes and layouts, and draws the Quick Menu as a Guide — but every row is still the same
// item from the same menu model (xmb.js), so A / B / Y and every command behave exactly as
// they do in the XMB. It keeps xmb.js's item node contract (.item > .txt > .sub, .bar > i;
// columnEls index-parallel to list()) so live download progress works here too.
//
// Three layouts, picked per page:
//   home  — the top level: pivots + tiles; the big "hero" tile is what you used last there
//           (the game you played, the video you watched, the setting you opened)
//   grid  — a folder of mostly pictures (games, films, photos): tiles, no hero
//   list  — any other folder (settings…): rows with a highlight bar + a details pane

const X360 = {
  id: 'x360',
  // ---- geometry: a 1920×1080 stage with TV-safe margins
  L: 150, R: 1770,              // left / right edges of the content
  TOP: 262,                     // first tile row
  U: 344, H: 162, G: 16,        // tile unit (≈ a Steam header's 2.15:1), gap
  ROWS: 3,
  LIST_TOP: 262, ROW: 78, LIST_W: 860, LIST_BOT: 900,
  dialogVertical: true,
  quickTabs: true,
  optionsGeom: { TOP: 214, MIN: 200, MAX: 980 },

  mode: 'home', slots: [], scroll: 0,

  // ---------------------------------------------------------------- lifecycle
  setup() {
    if (!$('#x-bg')) {                       // the backdrop covers the whole screen, letterbox included
      const bg = document.createElement('div');
      bg.id = 'x-bg';
      bg.innerHTML = '<div class="x-bg-glow"></div><div class="x-bg-band b1"></div><div class="x-bg-band b2"></div>';
      document.body.insertBefore(bg, $('#stage'));
    }
    if (!$('#x-root')) {
      const r = document.createElement('div');
      r.id = 'x-root';
      r.innerHTML = `
        <div class="x-top"><div class="x-crumb"></div>
          <div class="x-me"><div class="x-pic"></div><div class="x-who"><div class="x-tag"></div><div class="x-status"></div></div></div></div>
        <div class="x-now" hidden><div class="x-now-t"><span class="x-now-title"></span><span class="x-now-by"></span></div>
          <div class="x-now-row"><span class="x-now-pos"></span><div class="x-now-bar"><i></i></div><span class="x-now-dur"></span></div></div>
        <div class="x-pivots"></div>
        <div class="x-title"></div>
        <div class="x-detail"><div class="x-d-art"></div><div class="x-d-txt"><div class="x-d-label"></div><div class="x-d-badge"></div>
          <div class="x-d-sub"></div><div class="x-d-bar"><i></i></div></div></div>
        <div class="x-empty" hidden>Nothing here yet</div>`;
      $('#stage').insertBefore(r, $('#column'));
    }
    $('#cats').innerHTML = ''; $('#crumb').hidden = true;
    clearInterval(this.tick);                // the time sits under your name, like the 360's profile corner
    const tick = () => { const t = $('.x-status'); if (t) t.textContent = $('#clock-time')?.textContent || ''; };
    tick(); this.tick = setInterval(tick, 5000);
    // what's playing, centred along the top (music or Spotify)
    clearInterval(this.nowTick); clearInterval(this.nowPoll);
    this.nowPoll = setInterval(() => this.pollNow(), 3000); this.pollNow();
    this.nowTick = setInterval(() => this.drawNow(), 1000);
  },

  async pollNow() {
    let n = null;
    try {
      const m = await api.get('/api/music/state');
      if (m?.title) n = { title: m.title, by: m.artist, pos: m.position, dur: m.duration, paused: m.paused };
    } catch (e) { /* no player */ }
    if (!n && S.state?.spotify?.linked) {
      if (Date.now() - (this.spAt || 0) > 5000) {           // Spotify's API is rate limited: every 5 s at most
        this.spAt = Date.now();
        try {
          const s = await api.get('/api/spotify/now');
          this.sp = s && (s.playing || s.here) ? { title: s.name, by: s.artist, pos: s.position, dur: s.duration, paused: !s.playing } : null;
          if (this.sp) this.sp.at = Date.now();
        } catch (e) { this.sp = null; }
      }
      n = this.sp ? { ...this.sp, pos: this.sp.pos + (this.sp.paused ? 0 : (Date.now() - this.sp.at) / 1000) } : null;
    }
    this.now = n ? { ...n, at: Date.now() } : null;
    this.drawNow();
  },
  drawNow() {
    const el = $('.x-now'); if (!el) return;
    const n = this.now;
    el.hidden = !n;
    if (!n) return;
    const pos = Math.min(n.dur || 0, n.pos + (n.paused ? 0 : (Date.now() - n.at) / 1000));
    $('.x-now-title').textContent = `${n.paused ? '❚❚  ' : '♪  '}${n.title}`;
    $('.x-now-by').textContent = n.by ? `  —  ${n.by}` : '';
    $('.x-now-pos').textContent = fmtTime(pos);
    $('.x-now-dur').textContent = n.dur ? fmtTime(n.dur) : '';
    $('.x-now-bar i').style.width = n.dur ? `${(pos / n.dur * 100).toFixed(1)}%` : '0';
  },
  teardown() {
    clearInterval(this.tick); clearInterval(this.nowTick); clearInterval(this.nowPoll);
    $('#x-root')?.remove(); $('#x-bg')?.remove(); $('#quick .x-guide')?.remove();
    $('#column').innerHTML = ''; $('#column').style.transform = '';
    document.body.removeAttribute('data-xbg'); document.body.removeAttribute('data-xmode');
    document.body.style.removeProperty('--x-accent'); document.body.style.removeProperty('--x-accent-2');
  },
  resetCats() { const p = $('.x-pivots'); if (p) p.innerHTML = ''; },

  // look.json's settings: Background and Accent Colour
  configure(st) {
    const set = Looks.settings('x360');
    const bg = set.bg || 'light';
    const pic = bg === 'picture' && Theme.cur?.background?.image;
    document.body.dataset.xbg = pic ? 'picture' : bg === 'picture' ? 'dark' : bg;
    const [a, b] = Looks.colors('x360', 'accent') || ['#107c10', '#5dc21e'];
    const r = document.body.style;            // on body: look.css's defaults live there too
    r.setProperty('--x-accent', a); r.setProperty('--x-accent-2', b);
    const me = $('.x-me');
    if (me) {
      $('.x-tag').textContent = st.user || 'Player';
      $('.x-pic').textContent = (st.user || 'P').trim().charAt(0).toUpperCase();
    }
  },

  // ---------------------------------------------------------------- item nodes
  itemEl(it) {
    const el = document.createElement('div');
    el.className = 'item';
    let slot;
    if (it.art !== undefined) {
      const h = hashHue(it.artTitle || it.label);
      const shape = it.artShape === 'poster' ? ' poster' : it.artShape === 'square' ? ' square' : '';
      slot = `<div class="art${shape}" style="background-image:linear-gradient(135deg,hsl(${h} 45% 42%),hsl(${(h + 40) % 360} 50% 22%))"><span>${esc(it.artTitle || it.label)}</span></div>`;
      el.classList.add(shape ? `x-${shape.trim()}` : 'x-pic');
    } else {
      slot = `<div class="ico">${icon(it.icon)}</div>`;
      el.classList.add('x-ic');
    }
    el.innerHTML = `${slot}<div class="txt"><div class="label">${esc(gl(it.label))}</div><div class="sub">${esc(gl(it.sub || ''))}</div>${
      it.progress != null ? `<div class="bar"><i style="width:${(it.progress * 100).toFixed(1)}%"></i></div>` : ''}</div>${
      it.badge ? `<div class="x-badge">${esc(it.badge)}</div>` : ''}`;
    if (it.art && artLoaded.has(it.art)) showArt(el, it.art);
    return el;
  },

  // ---------------------------------------------------------------- pages
  pickMode() {
    if (!S.stack.length) return 'home';
    const items = list();
    const pics = items.filter((i) => i.art !== undefined).length;
    return items.length && pics >= items.length * 0.6 ? 'grid' : 'list';
  },

  render() {
    document.body.classList.toggle('infolder', S.stack.length > 0);
    this.renderCats();
    this.renderColumn(true);
  },

  // pivots on the top level; a page title (and where you came from) in a folder
  renderCats() {
    const piv = $('.x-pivots'), title = $('.x-title'), crumb = $('.x-crumb');
    if (!piv) return;
    if (!S.stack.length) {
      // the current pivot leads; the rest follow in order and wrap round, like the real thing
      piv.innerHTML = CATS.map((_, k) => {
        const i = (S.ci + k) % CATS.length;
        return `<span class="${k === 0 ? 'on' : ''}">${esc(pivotName(CATS[i]))}</span>`;
      }).join('');
      piv.classList.remove('slide'); void piv.offsetWidth; piv.classList.add('slide');
      piv.hidden = false; title.hidden = true;
      crumb.textContent = '';
    } else {
      const path = [pivotName(CATS[S.ci]), ...S.stack.slice(0, -1).map((f) => f.title)];
      crumb.textContent = path.join('  ›  ').toLowerCase();
      title.textContent = (S.stack.at(-1).title || '').toLowerCase();
      piv.hidden = true; title.hidden = false;
    }
  },

  renderColumn(rebuild = true) {
    const col = $('#column');
    if (!S.stack.length && !S.items[CATS[S.ci].id]) S.items[CATS[S.ci].id] = [{ key: 'loading', label: 'Loading…', icon: 'refresh' }];
    const items = list();
    const mode = this.pickMode();
    // the hero is what you used last here; the first time you come to a pivot, you start on it
    this.hero = mode === 'home' && items.length > 2 ? Math.max(0, Recent.top(CATS[S.ci].id, items)) : -1;
    if (mode === 'home' && this.hero >= 0 && S.catSel[CATS[S.ci].id] === undefined) S.catSel[CATS[S.ci].id] = this.hero;
    if (rebuild || mode !== this.mode) this.scroll = 0;
    this.mode = mode;
    document.body.dataset.xmode = mode;
    if (rebuild) col.classList.add('swap');
    col.innerHTML = '';
    columnEls = items.map((it) => { const el = this.itemEl(it); col.appendChild(el); return el; });
    this.layout(items);
    $('.x-empty').hidden = items.length > 0;
    this.position();
    if (rebuild) requestAnimationFrame(() => requestAnimationFrame(() => col.classList.remove('swap')));
    this.hint();
  },

  // where every tile / row goes, in stage pixels (before scrolling)
  layout(items) {
    const { U, H, G, ROWS, L, TOP } = this;
    if (this.mode === 'list') {
      this.slots = items.map((_, i) => ({ x: L, y: this.LIST_TOP + i * this.ROW, w: this.LIST_W, h: this.ROW - 6 }));
      return;
    }
    const taken = new Set(), slots = [];
    const free = (c, r) => !taken.has(`${c},${r}`);
    const take = (c, r, w, h) => { for (let a = 0; a < w; a++) for (let b = 0; b < h; b++) taken.add(`${c + a},${r + b}`); };
    let c = 0, r = 0;
    if (this.mode === 'home' && this.hero >= 0) {                       // the hero: big, first
      take(0, 0, 2, 2); slots[this.hero] = { c: 0, r: 0, w: 2, h: 2 };
    }
    items.forEach((it, i) => {
      if (slots[i]) return;
      while (!free(c, r)) { r++; if (r >= ROWS) { r = 0; c++; } }       // column by column, top to bottom
      take(c, r, 1, 1); slots[i] = { c, r, w: 1, h: 1 };
    });
    this.slots = slots.map((s) => ({ x: L + s.c * (U + G), y: TOP + s.r * (H + G), w: s.w * U + (s.w - 1) * G, h: s.h * H + (s.h - 1) * G }));
  },

  position() {
    const items = list(), s = sel(), cur = this.slots[s];
    if (cur) {
      if (this.mode === 'list') {
        const top = this.LIST_TOP, bot = this.LIST_BOT;
        if (cur.y - this.scroll < top) this.scroll = cur.y - top;
        if (cur.y + this.ROW - this.scroll > bot) this.scroll = cur.y + this.ROW - bot;
        this.scroll = Math.max(0, this.scroll);
      } else {
        if (cur.x - this.scroll < this.L) this.scroll = cur.x - this.L;
        if (cur.x + cur.w - this.scroll > this.R) this.scroll = cur.x + cur.w - this.R;
        this.scroll = Math.max(0, this.scroll);
      }
    }
    const list_ = this.mode === 'list';
    columnEls.forEach((el, i) => {
      const p = this.slots[i]; if (!p) return;
      const x = list_ ? p.x : p.x - this.scroll, y = list_ ? p.y - this.scroll : p.y;
      el.style.transform = `translate(${x}px, ${y}px)`;
      el.style.width = `${p.w}px`; el.style.height = `${p.h}px`;
      el.classList.toggle('on', i === s);
      el.classList.toggle('dim', false);
      el.classList.toggle('hero', !list_ && p.w > this.U);
      const off = list_ ? (y < this.LIST_TOP - this.ROW || y > this.LIST_BOT) : (x + p.w < 0 || x > 1920);
      el.style.opacity = off ? 0 : '';
      el.style.visibility = off ? 'hidden' : '';
      if (!off || Math.abs(i - s) <= Shell.artWindow) ensureArt(el, items[i]);
    });
    this.detail();
  },

  // what the selected thing is: under the tiles, or in a pane beside the list
  detail() {
    const it = list()[sel()], d = $('.x-detail');
    if (!d) return;
    d.hidden = !it || it.key === 'loading';
    if (d.hidden) return;
    $('.x-d-label').textContent = gl(it.label || '');
    $('.x-d-sub').textContent = gl(it.sub || '');
    $('.x-d-badge').textContent = it.badge || '';
    $('.x-d-badge').hidden = !it.badge;
    const bar = $('.x-d-bar');
    bar.hidden = it.progress == null;
    if (it.progress != null) bar.firstElementChild.style.width = `${(it.progress * 100).toFixed(1)}%`;
    const art = $('.x-d-art');
    if (this.mode === 'list') {
      art.hidden = false;
      if (it.art) { art.className = `x-d-art pic${it.artShape ? ' ' + it.artShape : ''}`; art.style.backgroundImage = `url("${it.art}")`; art.innerHTML = ''; }
      else { art.className = 'x-d-art ic'; art.style.backgroundImage = ''; art.innerHTML = icon(it.icon || 'info'); }
    } else art.hidden = true;
  },
  patched() { this.detail(); },

  hint() {
    const it = list()[sel()];
    const parts = [];
    if (it && (it.action || it.children)) parts.push(`${glb('ok')}<span>select</span>`);
    if (S.stack.length) parts.push(`${glb('back')}<span>back</span>`);
    if (it?.options?.length) parts.push(`${glb('menu')}<span>options</span>`);
    if (!S.stack.length) parts.push(`${glb('prev')}${glb('next')}<span>change pivot</span>`);
    $('#hint').innerHTML = parts.join('');
  },

  // ---------------------------------------------------------------- moving
  moveV(d) {
    if (this.mode === 'list') return this.step(sel() + d);
    this.spatial(0, d);
  },
  moveH(d) {
    if (this.mode === 'list') { if (d < 0 && S.stack.length) back(); return; }
    if (!this.spatial(d, 0)) {
      if (!S.stack.length) this.pivot(d);              // off the end of the tiles: the next pivot
      else if (d < 0) back();
    }
  },
  step(i) {
    const n = list().length; if (!n) return false;
    i = Math.max(0, Math.min(n - 1, i));
    if (i === sel()) return false;
    setSel(i); Sfx.move(); this.position(); this.hint();
    return true;
  },
  // the nearest tile that way, preferring ones in line with this one
  spatial(dx, dy) {
    const s = sel(), a = this.slots[s]; if (!a) return false;
    const ac = { x: a.x + a.w / 2, y: a.y + a.h / 2 };
    let best = -1, score = Infinity;
    this.slots.forEach((b, j) => {
      if (j === s) return;
      const bc = { x: b.x + b.w / 2, y: b.y + b.h / 2 };
      const along = dx ? (bc.x - ac.x) * dx : (bc.y - ac.y) * dy;
      if (along <= 4) return;
      const overlap = dx ? Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y) : Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
      const across = overlap > 0 ? 0 : Math.abs(dx ? bc.y - ac.y : bc.x - ac.x);
      const sc = along + across * 3;
      if (sc < score) { score = sc; best = j; }
    });
    return best >= 0 && this.step(best);
  },
  pivot(d) {
    if (S.stack.length) return false;
    S.ci = (S.ci + d + CATS.length) % CATS.length;
    Sfx.move(); this.render();
    refresh(CATS[S.ci].id);
    return true;
  },
  // LB / RB: pivots on the top level, a page at a time in a folder
  bumper(d) {
    if (!S.stack.length) return this.pivot(d);
    if (this.mode === 'list') return this.step(sel() + d * 8) || true;
    const s = sel(), a = this.slots[s];
    const target = a.x + d * (this.R - this.L);
    let best = s, dist = Infinity;
    this.slots.forEach((b, j) => { const v = Math.abs(b.x - target) + Math.abs(b.y - a.y) * 2; if (v < dist) { dist = v; best = j; } });
    this.step(best);
    return true;
  },

  // ---------------------------------------------------------------- the Guide (Quick Menu)
  renderQuick(q) {
    const root = $('#quick');
    let g = root.querySelector('.x-guide');
    if (!g) {
      g = document.createElement('div');
      g.className = 'x-guide';
      g.innerHTML = `<div class="xg-top"><div class="xg-pic"></div><div class="xg-who"><div class="xg-tag"></div><div class="xg-now"></div></div><div class="xg-time"></div></div>
        <div class="xg-tabs"></div><div class="xg-head"></div><div class="xg-rows"></div><div class="xg-foot"></div>`;
      root.appendChild(g);
    }
    const d = q.data || {}, st = S.state || {};
    g.querySelector('.xg-pic').textContent = (st.user || 'P').charAt(0).toUpperCase();
    g.querySelector('.xg-tag').textContent = st.user || 'Player';
    g.querySelector('.xg-now').textContent = d.app ? `Playing ${d.app.title}` : 'In the dashboard';
    g.querySelector('.xg-time').textContent = $('#clock-time')?.textContent || '';
    const tab = q.isTab(q.page) ? q.page : (q.parent || 'main');
    g.querySelector('.xg-tabs').innerHTML = q.tabs().map(([p, ic, label]) =>
      `<div class="xg-tab ${p === tab ? 'on' : ''}${p === 'main' ? ' home' : ''}"><div class="xg-ti">${icon(ic)}</div><div class="xg-tl">${esc(label.toLowerCase())}</div></div>`).join('');
    // a page opened from a tab (Sound, Performance, Trophies) says where you are
    const sub = { sound: 'sound', perf: 'performance', trophies: d.app ? `trophies · ${d.app.title}` : 'trophies' }[q.page];
    const head = g.querySelector('.xg-head');
    head.hidden = !sub; head.textContent = sub || '';
    g.querySelector('.xg-rows').innerHTML = q.rows.map((r, i) => `
      <div class="xg-row ${i === q.sel ? 'on' : ''}">
        <div class="xg-ico">${r.art ? `<div class="xg-art" style="background-image:url('${esc(r.art)}')"></div>` : icon(r.icon)}</div>
        <div class="xg-txt"><div class="xg-label">${esc(r.label.replace(/ ▸$/, ''))}</div><div class="xg-sub">${esc(gl(r.sub || ''))}</div>
          ${r.bar != null ? `<div class="xg-bar"><i style="width:${(r.bar * 100).toFixed(1)}%"></i></div>` : ''}</div>
        ${/ ▸$/.test(r.label) ? '<div class="xg-more">›</div>' : ''}
      </div>`).join('');
    const r = q.rows[q.sel];
    g.querySelector('.xg-foot').innerHTML = `${r?.ok ? `${glb('ok')}<span>select</span>` : ''}${r?.adjust ? '<b class="glyph xg-dpad">◀ ▶</b><span>adjust</span>' : ''}${glb('back')}<span>${q.isTab(q.page) ? 'close' : 'back'}</span>${glb('prev')}${glb('next')}<span>tabs</span>`;
    g.querySelector('.xg-row.on')?.scrollIntoView({ block: 'nearest' });
    return true;
  },
};

// the dashboard's own words for some categories (lowercase, short, like its pivots)
const PIVOT_NAMES = { users: 'profile', game: 'games', photo: 'pictures', tv: 'tv' };
const pivotName = (c) => (PIVOT_NAMES[c.id] || c.label).toLowerCase();


Shell.register('x360', X360);
