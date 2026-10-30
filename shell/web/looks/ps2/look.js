'use strict';
// The Browser look — the PlayStation 2's own menu, kept as close as a menu with a games library
// in it can be. Nothing is drawn in a box and nothing runs down the side: there is the backdrop
// (a burst of glowing rods turning slowly in space, dark cubes tumbling past, in a colour the PS2
// took from its own clock — "Automatic" does the same, a hue a month), the black bands top and
// bottom with the clock and the buttons on them, and the words. Where you are is spelled out in
// gold, what the cursor is on in pale blue, and its value in white, the way System Configuration
// had it.
//
// It's a whole front end, not a re-skin: it builds its own page (#p2-root) and its own layouts,
// and it swaps the cross-media bar's axes — left / right walks the row, up / down changes
// category. Every icon is still the same item from the same menu model (xmb.js), so A / B / Y and
// every command behave exactly as they do in the other looks, and it keeps xmb.js's item node
// contract (.item > .txt > .sub, .bar > i; columnEls index-parallel to list()) so a running
// download's text and progress land here too.
//
// Three screens, picked per page — the two the PS2 itself had, and a grid for the libraries it
// never had to show:
//   browser — the top level: icons in a row across the middle, only the one under the cursor
//             named, the way the PS2's own Browser named the memory card you were on
//   grid    — a folder of mostly artwork (games, films, photos): the same icons six across
//   list    — any other folder (settings…): System Configuration — one entry at a time, its
//             value under it, ▲▼ beside it, and the rest waiting above and below

// The PS2 read its backdrop's colour off the clock, so the browser looked different through the
// year: deep blue in the winter, green by the summer, rust in the autumn. A hue a month.
const P2_MONTH_HUE = [222, 206, 188, 162, 128, 96, 58, 40, 24, 8, 334, 268];
const P2_NAMED = { blue: [222, 46], teal: [188, 44], violet: [268, 42], amber: [40, 52], crimson: [356, 46], graphite: [215, 9] };
// The backdrop is the PS2's own: a burst of glowing rods turning slowly in space, with dark
// cubes tumbling past it. All of it is CSS 3D — the compositor animates transforms and nothing
// repaints — and Background Motion › Still stops the lot where a machine would rather it didn't.
const P2_RODS = 13;                       // spokes of the burst, sprayed by the golden angle
// the cubes: [left %, top %, size, seconds, delay, drift x, drift y]
const P2_CUBES = [[2, 20, 88, 104, 0, '130px', '-70px'], [74, 56, 108, 128, -46, '-140px', '70px'],
  [29, 74, 64, 92, -70, '90px', '90px']];

const PS2 = {
  id: 'ps2',
  // ---- geometry: a 1920×1080 stage, between the bands (66px down to 1010px)
  MID: 960, PITCH: 230, ITEM_W: 200, ROW_Y: 430,       // the row: centred on the cursor, as the PS2's was
  COLS: 6, CELL_W: 270, CELL_H: 196, GRID_W: 230, GRID_TOP: 252, GRID_BOT: 812,
  // a page of settings: the entries stand in a column that steps past the middle one, and the
  // words sit right of the burst, where System Configuration's did
  TEXT_X: 520, TEXT_W: 1200, STEP: 96, WHEEL_Y: 486,
  optionsGeom: { TOP: 346, MIN: 336, MAX: 690 },

  mode: 'browser', slots: [], scroll: 0,

  // ---------------------------------------------------------------- lifecycle
  setup() {
    if (!$('#p2-bg')) {                       // the backdrop covers the whole screen, bands included
      const bg = document.createElement('div');
      bg.id = 'p2-bg';
      const rods = Array.from({ length: P2_RODS }, (_, i) => {
        const yaw = Math.round(i * 137.5) % 360, pitch = (i % 5) * 34 - 68;
        return `<i class="p2-rod" style="--yaw:${yaw}deg;--pitch:${pitch}deg;--len:${170 + (i % 4) * 85}px;--o:${(0.4 + (i % 3) * 0.2).toFixed(2)}"></i>`;
      }).join('');
      const cubes = P2_CUBES.map(([x, y, s, t, d, fx, fy]) =>
        `<div class="p2-cube" style="left:${x}%;top:${y}%;--s:${s}px;--t:${t}s;--d:${d}s;--fx:${fx};--fy:${fy}">
           <div class="p2-spin">${'<i></i>'.repeat(6)}</div></div>`).join('');
      bg.innerHTML = `<div class="p2-sky"></div><div class="p2-space">
        <div class="p2-burst"><div class="p2-core"></div>${rods}</div>${cubes}</div>`;
      document.body.insertBefore(bg, $('#stage'));
    }
    if (!$('#p2-root')) {
      const r = document.createElement('div');
      r.id = 'p2-root';
      // the head names the page; the block under it is what the cursor is on (a settings page
      // draws that itself, in its own column, so it hides this one)
      r.innerHTML = `
        <div class="p2-band top"></div><div class="p2-band bot"></div>
        <div class="p2-head"><span><i class="p2-txt"></i></span></div>
        <div class="p2-sel"><div class="p2-name"></div><div class="p2-badge" hidden></div>
          <div class="p2-value"></div><div class="p2-bar" hidden><i></i></div></div>
        <div class="p2-shelf"></div>
        <div class="p2-empty" hidden>Nothing here yet</div>`;
      $('#stage').insertBefore(r, $('#column'));
    }
    $('#cats').innerHTML = ''; $('#crumb').hidden = true;
  },
  teardown() {
    $('#p2-root')?.remove(); $('#p2-bg')?.remove();
    $('#column').innerHTML = '';
    for (const a of ['p2mode', 'p2bg', 'p2motion', 'p2more']) document.body.removeAttribute(`data-${a}`);
    document.body.style.removeProperty('--p2-h'); document.body.style.removeProperty('--p2-s');
  },
  resetCats() {},                             // the categories aren't drawn: the head names the one you're in

  // look.json's settings: Background and Background Motion
  configure() {
    const set = Looks.settings('ps2');
    const pic = set.bg === 'picture' && Theme.cur?.background?.image;
    const [h, s] = set.bg === 'date' || !P2_NAMED[set.bg] ? [P2_MONTH_HUE[new Date().getMonth()], 44] : P2_NAMED[set.bg];
    document.body.style.setProperty('--p2-h', h);
    document.body.style.setProperty('--p2-s', `${s}%`);
    document.body.dataset.p2bg = pic ? 'picture' : 'field';
    document.body.dataset.p2motion = set.motion === 'off' ? 'off' : 'on';
  },

  // ---------------------------------------------------------------- item nodes
  // an icon and its words. The row and the grid show the icon alone — only the one under the
  // cursor is named, over in .p2-sel; a settings page shows the words and no icon at all.
  itemEl(it) {
    const el = document.createElement('div');
    el.className = 'item';
    let face;
    if (it.art !== undefined) {
      const hue = hashHue(it.artTitle || it.label);
      const shape = it.artShape === 'poster' ? ' poster' : it.artShape === 'square' ? ' square' : '';
      face = `<div class="art${shape}" style="background-image:linear-gradient(150deg,hsl(${hue} 48% 44%),hsl(${(hue + 40) % 360} 54% 20%))"><span>${esc(it.artTitle || it.label)}</span></div>`;
    } else face = `<div class="ico">${icon(it.icon)}</div>`;
    el.innerHTML = `<div class="p2-obj">${face}</div>
      <div class="txt"><div class="label"><i class="p2-txt">${esc(gl(it.label))}</i>${it.badge ? `<b class="p2-tag">${esc(it.badge)}</b>` : ''}</div>
      <div class="sub">${esc(gl(it.sub || ''))}</div>${
      it.progress != null ? `<div class="bar"><i style="width:${(it.progress * 100).toFixed(1)}%"></i></div>` : ''}</div>`;
    if (it.art && artLoaded.has(it.art)) showArt(el, it.art);
    return el;
  },

  // ---------------------------------------------------------------- pages
  // the same rule the Dashboard uses, so a folder looks like a wall of pictures in both looks
  pickMode() {
    if (!S.stack.length) return 'browser';
    const items = list();
    const pics = items.filter((i) => i.art !== undefined).length;
    return items.length && pics >= items.length * 0.6 ? 'grid' : 'list';
  },

  render() {
    document.body.classList.toggle('infolder', S.stack.length > 0);
    this.renderCats();
    this.renderColumn(true);
  },

  // the head: the page you're on — the folder's name, or the category's at the top level, where
  // ▲ ▼ walks them (look.css puts the arrows beside it)
  renderCats() {
    const head = $('#p2-root .p2-head .p2-txt');
    if (head) head.textContent = S.stack.length ? (S.stack.at(-1).title || '') : CATS[S.ci].label;
  },

  renderColumn(rebuild = true) {
    const col = $('#column');
    if (!S.stack.length && !S.items[CATS[S.ci].id]) S.items[CATS[S.ci].id] = [{ key: 'loading', label: 'Loading…', icon: 'refresh' }];
    const items = list(), mode = this.pickMode();
    if (rebuild || mode !== this.mode) this.scroll = 0;
    this.mode = mode;
    document.body.dataset.p2mode = mode;
    document.body.dataset.p2more = items.length > 1 ? '1' : '';      // ▲ ▼ beside the entry
    if (rebuild) col.classList.add('swap');
    col.innerHTML = '';
    columnEls = items.map((it) => { const el = this.itemEl(it); col.appendChild(el); return el; });
    this.layout(items);
    $('.p2-empty').hidden = items.length > 0;
    this.position();
    if (rebuild) requestAnimationFrame(() => requestAnimationFrame(() => col.classList.remove('swap')));
    this.hint();
  },

  // where every icon / entry goes, in stage pixels. The row and the settings column are laid out
  // from zero and slid under the cursor by position(); the grid scrolls.
  layout(items) {
    if (this.mode === 'browser') {
      this.slots = items.map((_, i) => ({ x: i * this.PITCH, y: this.ROW_Y, w: this.ITEM_W }));
    } else if (this.mode === 'grid') {
      // centred on the screen, however many columns it actually fills
      const cols = Math.min(this.COLS, items.length);
      const left = Math.round((1920 - (cols * this.CELL_W - (this.CELL_W - this.GRID_W))) / 2);
      this.slots = items.map((_, i) => ({ x: left + (i % this.COLS) * this.CELL_W,
        y: this.GRID_TOP + Math.floor(i / this.COLS) * this.CELL_H, w: this.GRID_W }));
    } else {
      this.slots = items.map((_, i) => ({ x: this.TEXT_X, y: i * this.STEP, w: this.TEXT_W }));
    }
  },

  position() {
    const items = list(), s = sel(), cur = this.slots[s];
    if (this.mode === 'grid' && cur) {                    // keep the selection inside the window
      if (cur.y - this.scroll < this.GRID_TOP) this.scroll = cur.y - this.GRID_TOP;
      if (cur.y + this.CELL_H - this.scroll > this.GRID_BOT) this.scroll = cur.y + this.CELL_H - this.GRID_BOT;
      this.scroll = Math.max(0, this.scroll);
    }
    // the cursor holds the middle and the page moves under it, as the PS2's did
    const dx = this.mode === 'browser' ? this.MID - this.ITEM_W / 2 - s * this.PITCH : 0;
    const dy = this.mode === 'list' ? this.WHEEL_Y - s * this.STEP : -this.scroll;
    columnEls.forEach((el, i) => {
      const p = this.slots[i]; if (!p) return;
      const x = p.x + dx, y = p.y + dy;
      el.style.transform = `translate(${x}px, ${y}px)`;
      el.style.width = `${p.w}px`;
      el.classList.toggle('on', i === s);
      // a settings page shows one entry: its neighbours are kept near enough to slide in from
      const off = this.mode === 'list' ? i !== s : (this.mode === 'browser' ? x + p.w < 60 || x > 1900 : y < -this.CELL_H || y > 1010);
      el.style.opacity = off ? 0 : '';
      el.style.visibility = off && (this.mode !== 'list' || Math.abs(i - s) > 2) ? 'hidden' : '';
      if (!off || Math.abs(i - s) <= Shell.artWindow) ensureArt(el, items[i]);
    });
    this.detail();
  },

  // what the cursor is on, under the row: its name in pale blue, then its value. A settings page
  // draws its own entries, so it leaves this hidden.
  detail() {
    const it = list()[sel()], sel_ = $('#p2-root .p2-sel');
    if (!sel_) return;
    const loading = !it || it.key === 'loading';
    sel_.hidden = this.mode === 'list';
    if (sel_.hidden) return;
    $('.p2-name').textContent = gl(it?.label || '');
    $('.p2-value').textContent = loading ? '' : gl(it.sub || '');
    const badge = $('#p2-root .p2-badge');
    badge.textContent = it?.badge || ''; badge.hidden = !it?.badge;
    const bar = $('#p2-root .p2-bar');
    bar.hidden = !it || it.progress == null;
    if (it?.progress != null) bar.firstElementChild.style.width = `${(it.progress * 100).toFixed(1)}%`;
  },
  patched() { this.detail(); },

  hint() {
    const it = list()[sel()], parts = [];
    if (it && (it.action || it.children)) parts.push(`${glb('ok')}<span>Enter</span>`);
    if (S.stack.length) parts.push(`${glb('back')}<span>Back</span>`);
    if (it?.options?.length) parts.push(`${glb('menu')}<span>Options</span>`);
    if (!S.stack.length && CATS.length > 1) parts.push('<b class="glyph p2-dpad">▲ ▼</b><span>Category</span>');
    $('#hint').innerHTML = parts.join('');
  },

  // ---------------------------------------------------------------- moving
  // the row and the grid run left to right; up / down changes category at the top level, and
  // walks the entries inside a folder. Left off the front of a folder goes back, as in the XMB.
  moveV(d) {
    if (this.mode === 'browser') return void this.cat(d);
    this.step(sel() + (this.mode === 'grid' ? d * this.COLS : d));
  },
  moveH(d) {
    if (this.mode === 'list') { if (d < 0) back(); return; }
    if (this.mode === 'grid' && d < 0 && sel() === 0) return back();
    this.step(sel() + d);
  },
  step(i) {
    const n = list().length; if (!n) return false;
    i = Math.max(0, Math.min(n - 1, i));
    if (i === sel()) return false;
    setSel(i); Sfx.move(); this.position(); this.hint();
    return true;
  },
  cat(d) {
    if (S.stack.length || CATS.length < 2) return false;
    S.ci = (S.ci + d + CATS.length) % CATS.length;
    Sfx.move(); this.render();
    refresh(CATS[S.ci].id);
    return true;
  },
  // LB / RB: a screenful at a time, so a long row or a big library isn't walked one by one
  bumper(d) {
    const by = this.mode === 'browser' ? 6 : this.mode === 'grid' ? this.COLS * 3 : 8;
    this.step(sel() + d * by);
    return true;
  },
};

Shell.register('ps2', PS2);
