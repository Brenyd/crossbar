'use strict';
// The Browser look — modelled on the PlayStation 2's own menu: upright blocks standing in a row
// on a thin shelf, over the PS2's backdrop of a burst of glowing rods turning slowly in space
// with dark cubes tumbling past, in a colour the PS2 took from its own clock ("Automatic" here
// does the same, a hue a month). The clock and the buttons sit on black bands top and bottom;
// where you are is spelled out in gold and what the cursor is on in pale blue, the way System
// Configuration had it. A folder of artwork opens as a grid of blocks, the way a memory card
// showed its saves, and a folder of settings as System Configuration's list of rows.
//
// It's a whole front end, not a re-skin: it builds its own page (#p2-root), its own blocks and
// layouts, and it swaps the cross-media bar's axes — left / right walks the row, up / down
// changes category (the index down the left edge). Every block is still the same item from the
// same menu model (xmb.js), so A / B / Y and every command behave exactly as they do in the
// other looks. It keeps xmb.js's item node contract (.item > .txt > .sub, .bar > i; columnEls
// index-parallel to list()) so a running download's text and progress land here too.
//
// Three layouts, picked per page:
//   browser — the top level: the row of blocks, the category index, the name above the shelf
//   grid    — a folder of mostly artwork (games, films, photos): blocks six across
//   list    — any other folder (settings…): rows, the value on the right, help underneath

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
  // ---- geometry: a 1920×1080 stage with TV-safe margins
  MID: 1110, PITCH: 200, ITEM_W: 210, ROW_Y: 420,          // the row: centre, block pitch, slot, top
  WIN_L: 480, WIN_R: 1740,                                 // and the window it runs in (look.css fades both ends)
  COLS: 6, CELL_W: 270, CELL_H: 210, GRID_W: 230, GRID_TOP: 336, GRID_BOT: 966,
  L: 150, LIST_TOP: 268, ROW: 76, LIST_W: 1320, LIST_BOT: 876,
  optionsGeom: { TOP: 300, MIN: 220, MAX: 980 },

  mode: 'browser', slots: [], scroll: 0,

  // ---------------------------------------------------------------- lifecycle
  setup() {
    if (!$('#p2-bg')) {                       // the field covers the whole screen, letterbox included
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
      r.innerHTML = `
        <div class="p2-band top"></div><div class="p2-band bot"></div>
        <div class="p2-cats"></div>
        <div class="p2-head"><div class="p2-path"></div>
          <div class="p2-title"></div><div class="p2-badge" hidden></div>
          <div class="p2-sub"></div><div class="p2-bar" hidden><i></i></div></div>
        <div class="p2-shelf"></div>
        <div class="p2-empty" hidden>Nothing here yet</div>`;
      $('#stage').insertBefore(r, $('#column'));
    }
    $('#cats').innerHTML = ''; $('#crumb').hidden = true;
  },
  teardown() {
    $('#p2-root')?.remove(); $('#p2-bg')?.remove();
    $('#column').innerHTML = '';
    for (const a of ['p2mode', 'p2bg', 'p2motion']) document.body.removeAttribute(`data-${a}`);
    document.body.style.removeProperty('--p2-h'); document.body.style.removeProperty('--p2-s');
  },
  resetCats() { const c = $('.p2-cats'); if (c) c.innerHTML = ''; },

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
  // a block: artwork or an icon on its front face, the name underneath (the row and the grid);
  // in a list it flattens into a row — one node shape, three sets of styles
  itemEl(it) {
    const el = document.createElement('div');
    el.className = 'item';
    let face;
    if (it.art !== undefined) {
      const hue = hashHue(it.artTitle || it.label);
      const shape = it.artShape === 'poster' ? ' poster' : it.artShape === 'square' ? ' square' : '';
      face = `<div class="art${shape}" style="background-image:linear-gradient(150deg,hsl(${hue} 48% 44%),hsl(${(hue + 40) % 360} 54% 20%))"><span>${esc(it.artTitle || it.label)}</span></div>`;
    } else face = `<div class="ico">${icon(it.icon)}</div>`;
    el.innerHTML = `<div class="p2-box">${face}<i class="p2-gl"></i></div>
      <div class="txt"><div class="label">${esc(gl(it.label))}</div><div class="sub">${esc(gl(it.sub || ''))}</div>${
      it.progress != null ? `<div class="bar"><i style="width:${(it.progress * 100).toFixed(1)}%"></i></div>` : ''}</div>${
      it.badge ? `<div class="p2-tag">${esc(it.badge)}</div>` : ''}`;
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

  // the category index down the left edge (the top level), and where you are above the title
  renderCats() {
    const idx = $('.p2-cats');
    if (!idx) return;
    if (!idx.children.length) {
      idx.innerHTML = CATS.map((c) => `<div class="p2-cat"><div class="p2-ci">${icon(c.icon)}</div><div class="p2-cl">${esc(c.label)}</div></div>`).join('');
    }
    [...idx.children].forEach((el, i) => el.classList.toggle('on', i === S.ci));
    idx.hidden = S.stack.length > 0;
    const trail = [CATS[S.ci].label, ...S.stack.map((f) => f.title)];
    if (this.pickMode() === 'list') trail.pop();          // a list is headed by the folder's own name
    $('.p2-path').textContent = trail.join('  ›  ');
  },

  renderColumn(rebuild = true) {
    const col = $('#column');
    if (!S.stack.length && !S.items[CATS[S.ci].id]) S.items[CATS[S.ci].id] = [{ key: 'loading', label: 'Loading…', icon: 'refresh' }];
    const items = list(), mode = this.pickMode();
    if (rebuild || mode !== this.mode) this.scroll = 0;
    this.mode = mode;
    document.body.dataset.p2mode = mode;
    if (rebuild) col.classList.add('swap');
    col.innerHTML = '';
    columnEls = items.map((it) => { const el = this.itemEl(it); col.appendChild(el); return el; });
    this.layout(items);
    $('.p2-empty').hidden = items.length > 0;
    this.position();
    if (rebuild) requestAnimationFrame(() => requestAnimationFrame(() => col.classList.remove('swap')));
    this.hint();
  },

  // where every block / row goes, in stage pixels (the row is laid out from zero and slid into
  // place by rowShift; the grid and the list scroll instead)
  layout(items) {
    if (this.mode === 'browser') {
      this.slots = items.map((_, i) => ({ x: i * this.PITCH, y: this.ROW_Y, w: this.ITEM_W }));
    } else if (this.mode === 'grid') {
      this.slots = items.map((_, i) => ({ x: this.L + (i % this.COLS) * this.CELL_W,
        y: this.GRID_TOP + Math.floor(i / this.COLS) * this.CELL_H, w: this.GRID_W }));
    } else {
      this.slots = items.map((_, i) => ({ x: this.L, y: this.LIST_TOP + i * this.ROW, w: this.LIST_W }));
    }
  },

  position() {
    const items = list(), s = sel(), cur = this.slots[s];
    const row = this.mode === 'browser';
    if (cur && !row) {                                    // keep the selection inside the window
      const top = this.mode === 'grid' ? this.GRID_TOP : this.LIST_TOP;
      const bot = this.mode === 'grid' ? this.GRID_BOT : this.LIST_BOT;
      const h = this.mode === 'grid' ? this.CELL_H : this.ROW;
      if (cur.y - this.scroll < top) this.scroll = cur.y - top;
      if (cur.y + h - this.scroll > bot) this.scroll = cur.y + h - bot;
      this.scroll = Math.max(0, this.scroll);
    }
    const shift = row ? this.rowShift(items.length, s) : 0;
    columnEls.forEach((el, i) => {
      const p = this.slots[i]; if (!p) return;
      const x = p.x + shift, y = row ? p.y : p.y - this.scroll;
      el.style.transform = `translate(${x}px, ${y}px)`;
      el.style.width = `${p.w}px`;
      el.classList.toggle('on', i === s);
      const off = row ? x + p.w < 300 || x > 1920 : y < -this.CELL_H || y > 1010;
      el.style.opacity = off ? 0 : '';
      el.style.visibility = off ? 'hidden' : '';
      if (!off || Math.abs(i - s) <= Shell.artWindow) ensureArt(el, items[i]);
    });
    this.detail();
  },

  // A short row stands centred in its window; a long one runs under the cursor, but never far
  // enough to leave a gap at either end — so the shelf is never half empty.
  rowShift(n, s) {
    const span = (n - 1) * this.PITCH + this.ITEM_W, win = this.WIN_R - this.WIN_L;
    if (span <= win) return this.WIN_L + (win - span) / 2;
    return Math.min(this.WIN_L, Math.max(this.WIN_R - span, this.MID - this.ITEM_W / 2 - s * this.PITCH));
  },

  // what the cursor is on: above the shelf in the row and the grid, a help line under a list
  detail() {
    const it = list()[sel()], title = $('.p2-title');
    if (!title) return;
    const loading = !it || it.key === 'loading';
    title.textContent = this.mode === 'list' ? (S.stack.at(-1)?.title || '') : gl(it?.label || '');
    $('.p2-sub').textContent = loading ? '' : gl(it.sub || '');
    const badge = $('.p2-badge');
    badge.textContent = it?.badge || ''; badge.hidden = !it?.badge;
    const bar = $('.p2-bar');
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
  // walks rows inside a folder. Left off the front of a folder goes back, as it does in the XMB.
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
