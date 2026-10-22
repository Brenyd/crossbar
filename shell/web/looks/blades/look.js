'use strict';
// The Blades look — modelled on the Xbox 360's first dashboard (2005–2008): every category is a
// coloured blade. The open one fills the screen; the blades before it stand in a stack on the
// left and the ones after it on the right, each showing just its edge with its name running up
// it. Left / right (or LB / RB) flips to the next blade like turning a page. On each blade a list
// runs down the left and a showcase on the right shows what's highlighted: its picture (with a
// reflection), name and description. Folders open as a new page on the same blade. The Guide
// (Quick Menu) is a blade of its own that slides in from the left over anything.
//
// Same menu model as every look (xmb.js): A / B / Y and every command behave as in the XMB; the
// item node contract (.item > .txt > .label/.sub, .bar > i; columnEls parallel to list()) keeps
// live download progress working. No console maker's logo or marks are drawn anywhere.

const BLADE_COLORS = {          // [light, deep] per category, "Classic"
  store: ['#f7a531', '#c45a06'],     // the shop: orange
  party: ['#78c043', '#2f7f18'],     // friends and voice: green
  game: ['#b8d43a', '#5d8a0e'],      // games: lime
  apps: ['#3ec1b4', '#11766f'],
  music: ['#5aa2ff', '#1c4fae'],
  video: ['#9a7bff', '#4a2fae'],
  tv: ['#40c3ef', '#0f6f9a'],
  photo: ['#f06aa8', '#a8205e'],
  users: ['#8fb3d6', '#3f6488'],
  settings: ['#aeb6be', '#56606a'],  // the system blade: silver
};
const BLADE_ONE = { silver: ['#aeb6be', '#56606a'], green: ['#86cf3c', '#2f7f18'], blue: ['#5aa2ff', '#1c4fae'], black: ['#55595f', '#17181a'] };
const BLADE_NAMES = { users: 'Profile', game: 'Games', party: 'Social', settings: 'System', photo: 'Pictures', tv: 'TV' };
const bladeName = (c) => BLADE_NAMES[c.id] || c.label;
function mixHex(a, b, t) {            // a → b by t (0..1), for SVG gradient stops
  const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return '#' + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, '0')).join('');
}

const Blades = {
  id: 'blades',
  // ---- geometry (1920×1080 stage)
  X0: 64, X1: 1856, TOP: 92, BOT: 1004, STRIP: 50,
  PAD: 58,                       // inside the open blade
  LIST_TOP: 304, ROW: 70, LIST_W: 640,
  dialogVertical: true,
  optionsGeom: { TOP: 210, MIN: 190, MAX: 960 },
  scroll: 0,

  // ---------------------------------------------------------------- lifecycle
  ownsNowClock: true,
  setup() {
    if (!$('#b-bg')) {
      const bg = document.createElement('div');
      bg.id = 'b-bg';
      bg.innerHTML = '<div class="b-wash"></div><div class="b-orb"><i></i></div><div class="b-floor"></div>';
      document.body.insertBefore(bg, $('#stage'));
    }
    if (!$('#b-root')) {
      const r = document.createElement('div');
      r.id = 'b-root';
      r.innerHTML = `
        <div class="b-blades"></div>
        <div class="b-head"><div class="b-crumb"></div><div class="b-title"></div>
          <svg class="b-rule" viewBox="0 0 1000 24" preserveAspectRatio="none" aria-hidden="true"><defs>
            <linearGradient id="brg" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity=".95"/><stop offset=".55" stop-color="#fff" stop-opacity=".55"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient></defs>
            <path d="M0,17 C220,5 620,1 1000,7 C620,5 230,10 0,22 Z" fill="url(#brg)"/></svg></div>
        <div class="b-card"><div class="b-pic"></div><div class="b-who"><div class="b-tag"></div><div class="b-status"></div></div></div>
        <div class="b-now" hidden><span class="b-now-t"></span><div class="b-now-bar"><i></i></div></div>
        <div class="b-show"><div class="b-frame"><div class="b-art"><div class="b-art-ic"></div></div></div>
          <div class="b-s-label"></div><div class="b-s-badge"></div><div class="b-s-sub"></div><div class="b-s-bar"><i></i></div></div>
        <div class="b-more up">▲</div><div class="b-more down">▼</div>
        <div class="b-empty" hidden>Nothing here yet</div>`;
      $('#stage').insertBefore(r, $('#column'));
    }
    $('#cats').innerHTML = ''; $('#crumb').hidden = true;
    clearInterval(this.tick);
    const tick = () => { const t = $('.b-status'); if (t) t.textContent = $('#clock-time')?.textContent || ''; };
    tick(); this.tick = setInterval(tick, 5000);
    clearInterval(this.nowPoll); clearInterval(this.nowTick);
    const here = () => !document.body.classList.contains('away');
    this.nowPoll = setInterval(() => { if (here()) this.pollNow(); }, 3000); this.pollNow();
    this.nowTick = setInterval(() => { if (here()) this.drawNow(); }, 1000);
  },
  teardown() {
    clearInterval(this.tick); clearInterval(this.nowPoll); clearInterval(this.nowTick);
    $('#b-root')?.remove(); $('#b-bg')?.remove(); $('#quick .b-guide')?.remove();
    $('#column').innerHTML = '';
    ['data-bbg', 'data-bmode'].forEach((a) => document.body.removeAttribute(a));
    ['--b-c', '--b-c2', '--g-c', '--g-c2'].forEach((p) => document.body.style.removeProperty(p));
  },
  resetCats() { const b = $('.b-blades'); if (b) b.innerHTML = ''; },

  configure(st) {
    const set = Looks.settings('blades');
    const bg = set.bg || 'light';
    const pic = bg === 'picture' && Theme.cur?.background?.image;
    document.body.dataset.bbg = pic ? 'picture' : bg === 'picture' ? 'dark' : bg;
    const g = Looks.colors('blades', 'guide') || ['#3f9b2a', '#86cf3c'];
    document.body.style.setProperty('--g-c', g[0]); document.body.style.setProperty('--g-c2', g[1]);
    const mode = set.blades || 'classic';
    if (mode !== this.colorMode) { this.colorMode = mode; this.resetCats(); if (Shell.started) this.renderCats(); }
    if ($('.b-tag')) {
      $('.b-tag').textContent = st.user || 'Player';
      $('.b-pic').textContent = (st.user || 'P').trim().charAt(0).toUpperCase();
    }
  },
  color(cat) {
    if (this.colorMode && this.colorMode !== 'classic') return BLADE_ONE[this.colorMode] || BLADE_ONE.silver;
    return BLADE_COLORS[cat.id] || BLADE_COLORS.settings;
  },

  // ---------------------------------------------------------------- what's playing (gamercard corner)
  async pollNow() {
    let n = null;
    try {
      const m = await api.get('/api/music/state');
      if (m?.title) n = { title: m.title, by: m.artist, pos: m.position, dur: m.duration, paused: m.paused };
    } catch (e) { /* no player */ }
    if (!n && S.state?.spotify?.linked && Date.now() - (this.spAt || 0) > 5000) {
      this.spAt = Date.now();
      try {
        const s = await api.get('/api/spotify/now');
        this.sp = s && (s.playing || s.here) ? { title: s.name, by: s.artist, pos: s.position, dur: s.duration, paused: !s.playing, at: Date.now() } : null;
      } catch (e) { this.sp = null; }
    }
    if (!n && this.sp) n = { ...this.sp, pos: this.sp.pos + (this.sp.paused ? 0 : (Date.now() - this.sp.at) / 1000) };
    const c = this.now;
    if (!n) this.now = null;
    else if (!(c && c.title === n.title && c.paused === !!n.paused && Math.abs(this.pos() - n.pos) < 2)) this.now = { ...n, paused: !!n.paused, at: Date.now() };
    this.drawNow();
  },
  pos() {
    const n = this.now; if (!n) return 0;
    return Math.min(n.dur || Infinity, n.pos + (n.paused ? 0 : (Date.now() - n.at) / 1000));
  },
  drawNow() {
    const el = $('.b-now'); if (!el) return;
    el.hidden = !this.now;
    if (!this.now) return;
    const n = this.now, p = this.pos();
    $('.b-now-t').textContent = `${n.paused ? '❚❚' : '♪'}  ${n.title}${n.by ? ` — ${n.by}` : ''}`;
    $('.b-now-bar i').style.width = n.dur ? `${Math.min(100, p / n.dur * 100).toFixed(1)}%` : '0';
  },

  // ---------------------------------------------------------------- the blades
  // where blade j sits when blade i is open: the open one fills the space between the stacks
  geom(j, i = S.ci) {
    const n = CATS.length, { X0, X1, STRIP } = this;
    if (j < i) return { x: X0 + j * STRIP, w: STRIP, side: 'l' };
    if (j > i) return { x: X1 - (n - j) * STRIP, w: STRIP, side: 'r' };
    const x = X0 + i * STRIP;
    return { x, w: X1 - (n - 1 - i) * STRIP - x, side: 'on' };
  },
  open() { return this.geom(S.ci); },

  // A blade, painted: a curved top edge that sweeps up toward the open blade, glass shine with a
  // curved lower edge, a bloom of light, shading at the foot, a bright rim, and on the open blade
  // faint swooshes and a ring. Drawn at the blade's final size (the box animates to it).
  paint(j, w, h, side, [c, c2]) {
    const id = `bp${j}`, open = side === 'on';
    const t = open ? 44 : 30, r = open ? 20 : 12;
    const shape = `M0,${t + r} Q0,${t} ${r},${t - 1} C${(w * 0.36).toFixed(1)},${t - 3} ${(w * 0.56).toFixed(1)},0 ${w - r},0 `
      + `Q${w},0 ${w},${r} L${w},${h - r} Q${w},${h} ${w - r},${h} L${r},${h} Q0,${h} 0,${h - r} Z`;
    const flip = side === 'r' ? ` transform="translate(${w},0) scale(-1,1)"` : '';
    const gloss = open
      ? `M0,0 H${w} V${(h * 0.09).toFixed(1)} C${(w * 0.64).toFixed(1)},${(h * 0.15).toFixed(1)} ${(w * 0.3).toFixed(1)},${(h * 0.29).toFixed(1)} 0,${(h * 0.4).toFixed(1)} Z`
      : `M0,0 H${w} V${(h * 0.16).toFixed(1)} C${(w * 0.7).toFixed(1)},${(h * 0.2).toFixed(1)} ${(w * 0.3).toFixed(1)},${(h * 0.34).toFixed(1)} 0,${(h * 0.42).toFixed(1)} Z`;
    const deco = open ? `
      <g clip-path="url(#${id}k)" fill="none" stroke="#fff">
        <path d="M${-60},${(h * 0.74).toFixed(0)} C${(w * 0.28).toFixed(0)},${(h * 0.56).toFixed(0)} ${(w * 0.62).toFixed(0)},${(h * 0.98).toFixed(0)} ${w + 60},${(h * 0.6).toFixed(0)}" stroke-width="70" stroke-opacity=".07"/>
        <path d="M${-60},${(h * 0.83).toFixed(0)} C${(w * 0.3).toFixed(0)},${(h * 0.68).toFixed(0)} ${(w * 0.6).toFixed(0)},${(h * 1.02).toFixed(0)} ${w + 60},${(h * 0.72).toFixed(0)}" stroke-width="3" stroke-opacity=".22"/>
        <circle cx="${(w * 0.9).toFixed(0)}" cy="${(h * 0.88).toFixed(0)}" r="${(h * 0.36).toFixed(0)}" stroke-width="30" stroke-opacity=".06"/>
        <circle cx="${(w * 0.9).toFixed(0)}" cy="${(h * 0.88).toFixed(0)}" r="${(h * 0.46).toFixed(0)}" stroke-width="2" stroke-opacity=".16"/>
      </g>` : '';
    return `<svg class="b-paint" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id="${id}b" x1="0" y1="0" x2="0.25" y2="1">
          <stop offset="0" stop-color="${c}"/><stop offset=".5" stop-color="${mixHex(c, c2, 0.45)}"/><stop offset="1" stop-color="${c2}"/></linearGradient>
        <radialGradient id="${id}l" cx=".22" cy=".12" r=".75"><stop offset="0" stop-color="#fff" stop-opacity=".42"/><stop offset=".55" stop-color="#fff" stop-opacity=".06"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>
        <linearGradient id="${id}g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".62"/><stop offset="1" stop-color="#fff" stop-opacity=".07"/></linearGradient>
        <linearGradient id="${id}f" x1="0" y1="0" x2="0" y2="1"><stop offset=".55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".32"/></linearGradient>
        <linearGradient id="${id}e" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity=".35"/><stop offset=".6" stop-color="#fff" stop-opacity=".95"/><stop offset="1" stop-color="#fff" stop-opacity=".5"/></linearGradient>
        <clipPath id="${id}k"><path d="${shape}"${flip}/></clipPath>
      </defs>
      <g${flip}>
        <path d="${shape}" fill="url(#${id}b)"/>
        <path d="${shape}" fill="url(#${id}l)"/>
        <path d="${shape}" fill="url(#${id}f)"/>
      </g>
      <g clip-path="url(#${id}k)"><path d="${gloss}" fill="url(#${id}g)"${flip}/></g>${deco}
      <g${flip} fill="none">
        <path d="${shape}" stroke="#fff" stroke-opacity=".28" stroke-width="5" clip-path="url(#${id}k)"/>
        <path d="M${r},${t - 1} C${(w * 0.36).toFixed(1)},${t - 3} ${(w * 0.56).toFixed(1)},1 ${w - r},1" stroke="url(#${id}e)" stroke-width="2.5"/>
        <path d="${shape}" stroke="#000" stroke-opacity=".25" stroke-width="1"/>
      </g>
    </svg>`;
  },

  renderCats() {
    const wrap = $('.b-blades'); if (!wrap) return;
    if (wrap.children.length !== CATS.length) {
      wrap.innerHTML = CATS.map((c) => `<div class="b-blade"><div class="b-shape"></div>
          <div class="b-spine"><div class="b-sico">${icon(c.icon)}</div><div class="b-sl">${esc(bladeName(c))}</div></div></div>`).join('');
    }
    const H = this.BOT - this.TOP;
    [...wrap.children].forEach((el, j) => {
      const g = this.geom(j), col = this.color(CATS[j]);
      el.style.left = `${g.x}px`; el.style.width = `${g.w}px`;
      el.style.zIndex = g.side === 'on' ? 50 : g.side === 'l' ? 10 + j : 40 - j;
      const was = el.dataset.side;
      el.className = `b-blade ${g.side}`;
      if (was && was !== 'on' && g.side === 'on') {        // the blade you flipped to swings into place
        el.classList.add(document.body.dataset.bflip === 'l' ? 'swing-l' : 'swing-r');
      }
      el.dataset.side = g.side;
      const key = `${g.w}|${g.side}|${col}`;
      if (el.dataset.paint !== key) { el.dataset.paint = key; el.querySelector('.b-shape').innerHTML = this.paint(j, g.w, H, g.side, col); }
    });
    const [a, b] = this.color(CATS[S.ci]);
    document.body.style.setProperty('--b-c', a); document.body.style.setProperty('--b-c2', b);
    // the header on the open blade: its name, or the page you're on in it
    const o = this.open(), head = $('.b-head');
    head.style.left = `${o.x + this.PAD}px`; head.style.width = `${o.w - this.PAD * 2 - 420}px`;
    const crumb = $('.b-crumb'), title = $('.b-title');
    if (S.stack.length) {
      crumb.textContent = [bladeName(CATS[S.ci]), ...S.stack.slice(0, -1).map((f) => f.title)].join('  ›  ');
      title.textContent = S.stack.at(-1).title || '';
    } else { crumb.textContent = ''; title.textContent = bladeName(CATS[S.ci]); }
    title.classList.remove('in'); void title.offsetWidth; title.classList.add('in');
    const card = $('.b-card'), now = $('.b-now');
    card.style.right = `${1920 - (o.x + o.w) + this.PAD}px`;
    now.style.right = card.style.right;
  },

  // ---------------------------------------------------------------- items
  itemEl(it) {
    const el = document.createElement('div');
    el.className = 'item';
    let slot;
    if (it.art !== undefined) {
      const h = hashHue(it.artTitle || it.label);
      slot = `<div class="art${it.artShape === 'poster' ? ' poster' : it.artShape === 'square' ? ' square' : ''}" style="background-image:linear-gradient(135deg,hsl(${h} 45% 45%),hsl(${(h + 40) % 360} 50% 25%))"></div>`;
    } else slot = `<div class="ico b-orbi">${icon(it.icon)}</div>`;
    el.innerHTML = `${slot}<div class="txt"><div class="label">${esc(gl(it.label))}</div><div class="sub">${esc(gl(it.sub || ''))}</div>${
      it.progress != null ? `<div class="bar"><i style="width:${(it.progress * 100).toFixed(1)}%"></i></div>` : ''}</div>${
      it.badge ? `<div class="b-badge">${esc(it.badge)}</div>` : ''}`;
    if (it.art && artLoaded.has(it.art)) showArt(el, it.art);
    return el;
  },

  render() {
    document.body.classList.toggle('infolder', S.stack.length > 0);
    this.renderCats();
    this.renderColumn(true);
  },

  renderColumn(rebuild = true) {
    const col = $('#column');
    if (!S.stack.length && !S.items[CATS[S.ci].id]) S.items[CATS[S.ci].id] = [{ key: 'loading', label: 'Loading…', icon: 'refresh' }];
    const items = list();
    if (rebuild) { col.classList.add('swap'); this.scroll = 0; }
    col.innerHTML = '';
    columnEls = items.map((it) => { const el = this.itemEl(it); col.appendChild(el); return el; });
    $('.b-empty').hidden = items.length > 0;
    this.position();
    if (rebuild) requestAnimationFrame(() => requestAnimationFrame(() => col.classList.remove('swap')));
    this.hint();
  },

  // the list down the left of the open blade, scrolled to keep the highlight in view
  position() {
    const items = list(), s = sel(), o = this.open();
    const x = o.x + this.PAD, top = this.LIST_TOP, rows = Math.floor((this.BOT - 120 - top) / this.ROW);
    this.listW = Math.min(this.LIST_W, Math.round((o.w - this.PAD * 2) * 0.5));
    if (s < this.scroll) this.scroll = s;
    if (s >= this.scroll + rows) this.scroll = s - rows + 1;
    this.scroll = Math.max(0, Math.min(this.scroll, Math.max(0, items.length - rows)));
    columnEls.forEach((el, i) => {
      const k = i - this.scroll, vis = k >= 0 && k < rows;
      el.style.transform = `translate(${x}px, ${top + k * this.ROW}px)`;
      el.style.width = `${this.listW}px`;
      el.classList.toggle('on', i === s);
      el.style.opacity = vis ? '' : 0;
      el.style.visibility = vis ? '' : 'hidden';
      if (Math.abs(i - s) <= Shell.artWindow) ensureArt(el, items[i]);
    });
    const up = $('.b-more.up'), down = $('.b-more.down');
    up.hidden = this.scroll <= 0; down.hidden = this.scroll + rows >= items.length;
    up.style.left = down.style.left = `${x + this.listW / 2 - 12}px`;
    up.style.top = `${top - 40}px`; down.style.top = `${top + rows * this.ROW}px`;
    this.showcase();
  },

  // the right-hand side of the blade: what the highlighted thing is
  showcase() {
    const it = list()[sel()], sh = $('.b-show'), o = this.open();
    if (!sh) return;
    const x = o.x + this.PAD + this.listW + 70, w = o.x + o.w - this.PAD - x;
    sh.style.left = `${x}px`; sh.style.width = `${w}px`;
    sh.hidden = !it || it.key === 'loading' || w < 260;
    if (sh.hidden) return;
    const art = $('.b-art');
    art.className = `b-art${it.art ? ' pic' : ' ic'}${it.artShape ? ' ' + it.artShape : ''}`;
    art.style.backgroundImage = it.art ? `url("${it.art}")` : '';
    $('.b-art-ic').innerHTML = it.art ? '' : icon(it.icon || 'info');
    $('.b-s-label').textContent = gl(it.label || '');
    $('.b-s-badge').textContent = it.badge || ''; $('.b-s-badge').hidden = !it.badge;
    $('.b-s-sub').textContent = gl(it.sub || '');
    const bar = $('.b-s-bar');
    bar.hidden = it.progress == null;
    if (it.progress != null) bar.firstElementChild.style.width = `${(it.progress * 100).toFixed(1)}%`;
    if (this.lastShow !== it.key) { this.lastShow = it.key; sh.classList.remove('in'); void sh.offsetWidth; sh.classList.add('in'); }
  },
  patched() { this.showcase(); },

  hint() {
    const it = list()[sel()];
    const parts = [];
    if (it && (it.action || it.children)) parts.push(`${glb('ok')}<span>Select</span>`);
    if (S.stack.length) parts.push(`${glb('back')}<span>Back</span>`);
    if (it?.options?.length) parts.push(`${glb('menu')}<span>Options</span>`);
    if (!S.stack.length) parts.push(`${glb('prev')}${glb('next')}<span>Blades</span>`);
    const h = $('#hint');
    h.innerHTML = parts.join('');
    h.style.left = `${this.open().x + this.PAD}px`;
  },

  // ---------------------------------------------------------------- moving
  moveV(d) {
    const n = list().length; if (!n) return;
    const i = Math.max(0, Math.min(n - 1, sel() + d));
    if (i === sel()) return;
    setSel(i); Sfx.move(); this.position(); this.hint();
  },
  moveH(d) {
    if (S.stack.length) { if (d < 0) back(); return; }
    this.flip(d);
  },
  flip(d) {
    const i = Math.max(0, Math.min(CATS.length - 1, S.ci + d));
    if (i === S.ci) return false;
    S.ci = i; Sfx.move();
    document.body.dataset.bflip = d > 0 ? 'r' : 'l';
    this.render();
    refresh(CATS[i].id);
    return true;
  },
  bumper(d) {
    if (!S.stack.length) return this.flip(d) || true;
    const n = list().length, rows = Math.floor((this.BOT - 120 - this.LIST_TOP) / this.ROW);
    const i = Math.max(0, Math.min(n - 1, sel() + d * rows));
    if (i !== sel()) { setSel(i); Sfx.move(); this.position(); this.hint(); }
    return true;
  },

  // ---------------------------------------------------------------- the Guide blade (Quick Menu)
  renderQuick(q) {
    const root = $('#quick');
    let g = root.querySelector('.b-guide');
    if (!g) {
      g = document.createElement('div');
      g.className = 'b-guide';
      g.innerHTML = `<div class="b-shape"></div><div class="bg-card"><div class="bg-pic"></div><div class="bg-who"><div class="bg-tag"></div><div class="bg-now"></div></div><div class="bg-time"></div></div>
        <div class="bg-title"></div><svg class="b-rule bg-rule" viewBox="0 0 1000 24" preserveAspectRatio="none" aria-hidden="true">
          <path d="M0,17 C220,5 620,1 1000,7 C620,5 230,10 0,22 Z" fill="url(#brg)"/></svg><div class="bg-rows"></div><div class="bg-foot"></div>`;
      root.appendChild(g);
    }
    const gc = Looks.colors('blades', 'guide') || ['#3f9b2a', '#86cf3c'];
    const gkey = gc.join('|');
    if (g.dataset.paint !== gkey) { g.dataset.paint = gkey; g.querySelector('.b-shape').innerHTML = this.paint('g', 760, 912, 'on', [gc[1], gc[0]]); }
    const d = q.data || {}, st = S.state || {};
    g.querySelector('.bg-pic').textContent = (st.user || 'P').charAt(0).toUpperCase();
    g.querySelector('.bg-tag').textContent = st.user || 'Player';
    g.querySelector('.bg-now').textContent = d.app ? `Playing ${d.app.title}` : 'In the dashboard';
    g.querySelector('.bg-time').textContent = $('#clock-time')?.textContent || '';
    g.querySelector('.bg-title').textContent = ({ sound: 'Sound', perf: 'Performance', trophies: 'Trophies', social: 'Friends & Party', party: 'Party', friends: 'Friends' })[q.page] || 'Guide';
    g.querySelector('.bg-rows').innerHTML = q.rows.map((r, i) => `
      <div class="bg-row ${i === q.sel ? 'on' : ''}${r.danger ? ' danger' : ''}">
        <div class="bg-ico${r.art ? '' : ' b-orbi'}">${r.art ? `<div class="bg-art" style="background-image:url('${esc(r.art)}')"></div>` : icon(r.icon)}</div>
        <div class="bg-txt"><div class="bg-label">${esc(r.label.replace(/ ▸$/, ''))}</div><div class="bg-sub">${esc(gl(r.sub || ''))}</div>
          ${r.bar != null ? `<div class="bg-bar"><i style="width:${(r.bar * 100).toFixed(1)}%"></i></div>` : ''}</div>
        ${/ ▸$/.test(r.label) ? '<div class="bg-more">›</div>' : ''}
      </div>`).join('');
    const r = q.rows[q.sel];
    g.querySelector('.bg-foot').innerHTML = `${r?.ok ? `${glb('ok')}<span>Select</span>` : ''}${r?.adjust ? '<b class="glyph bg-dpad">◀ ▶</b><span>Adjust</span>' : ''}${glb('back')}<span>${q.page === 'main' ? 'Close' : 'Back'}</span>`;
    g.querySelector('.bg-row.on')?.scrollIntoView({ block: 'nearest' });
    clearTimeout(this.gmq);
    this.gmq = setTimeout(() => g.querySelector('.bg-row.on')?.querySelectorAll('.bg-label, .bg-sub').forEach((e) => Marquee.set(e)), 450);
    return true;
  },
};

Shell.register('blades', Blades);
