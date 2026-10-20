'use strict';
// The Xbox 360 dashboards, as alternatives to the cross-media bar. Settings › Theme ›
// Interface picks the look, Dashboard Era picks which of the three 360 dashboards.
//
// These are *renderers only*: they plug into the Shell seam in xmb.js and reuse its item
// model, folders (S.stack), Options panel, dialogs, input routing and polling untouched.
// Each keeps to the item node contract documented there — a .item root holding a .txt with
// a .sub and an optional .bar > i, and columnEls index-parallel to list().

// The dashboards paint their own backdrop. It's a fixed, full-viewport element rather than
// a #stage child so it still covers the letterbox bars on displays that aren't 16:9, and it
// goes between #theme-bg and #waves: a theme's picture sits under it (showing through where
// --x360-bg is translucent) and the waves canvas draws over it, which is what lets Blades
// keep a hint of motion. Layering is by DOM order on purpose — a negative z-index would put
// it behind body's opaque background (style.css: html, body { background: #000 }) and
// nothing would show. Colour comes from --x360-bg, so a theme's theme.css can replace it
// without needing JS.
const X360Base = {
  __proto__: XmbShell,                  // same item nodes, same renderColumn/hint/moveV/moveH
  setup() {
    if (!$('#x360-bg')) {
      const bg = document.createElement('div');
      bg.id = 'x360-bg'; bg.className = 'x-bg';
      document.body.insertBefore(bg, $('#waves'));
    }
  },
  teardown() {
    $('#x360-bg')?.remove();
    $('#cats').innerHTML = ''; $('#column').innerHTML = ''; $('#crumb').hidden = true;
  },
  resetCats() { $('#cats').innerHTML = ''; },
};

// ---------------------------------------------------------------- blades (2005)
// The original: a stack of slanted coloured blades, one per category. The selected blade
// opens to 760px and holds the item list; the rest stay as 112px spines either side of it.
const BladeShell = {
  __proto__: X360Base,

  X0: 80,                       // left edge of the stack
  SPINE: 112,                   // width of a closed blade
  OPEN: 760,                    // width of the open one
  ROW: 74,                      // item row pitch
  TOP: 250,                     // first row, inside the open blade
  BOT: 940,                     // last row that clears the button hints
  PAD: 70,                      // list inset from the blade's left edge

  setup() { X360Base.setup.call(this); Shell.artWindow = 10; },

  // x of blade i: the ones past the selection are pushed right by the open blade's extra width
  bladeX(i) { return this.X0 + i * this.SPINE + (i > S.ci ? this.OPEN - this.SPINE : 0); },

  renderCats() {
    const wrap = $('#cats');
    if (!wrap.children.length) {
      CATS.forEach((c) => {
        const el = document.createElement('div');
        el.className = 'x-blade';
        el.innerHTML = `<div class="x-face"></div>
          <div class="x-spine"><div class="x-ico">${icon(c.icon)}</div><div class="x-vlbl">${esc(c.label)}</div></div>
          <div class="x-head"><div class="x-ico">${icon(c.icon)}</div><div class="x-title"></div></div>`;
        wrap.appendChild(el);
      });
    }
    // inside a folder the blade stays open and its header becomes the breadcrumb
    const f = S.stack.at(-1);
    [...wrap.children].forEach((el, i) => {
      const on = i === S.ci;
      el.style.left = `${this.bladeX(i)}px`;
      el.style.width = `${on ? this.OPEN : this.SPINE}px`;
      el.style.zIndex = on ? 2 : 1;
      el.classList.toggle('on', on);
      if (!on) return;
      el.querySelector('.x-title').textContent = f ? f.title : CATS[i].label;
      el.querySelector('.x-head .x-ico').innerHTML = icon(f ? f.icon : CATS[i].icon);
    });
  },

  scroll: 0,                    // kept between moves, so rows below the cursor stay visible

  // A fresh column starts at the top; position() pulls the selection back into view.
  renderColumn(rebuild = true) {
    if (rebuild) this.scroll = 0;
    XmbShell.renderColumn.call(this, rebuild);
  },

  // Rows are a fixed-pitch list inside the open blade. The list only slides when the
  // selection would leave the window — the nudge-on-overflow rule the Options panel
  // uses (xmb.js Options.render), not a scroll recomputed from the index, which would
  // glue the cursor to the bottom edge and hide everything below it.
  position() {
    const items = list(), s = sel(), n = items.length;
    const view = this.BOT - this.TOP;
    const top = s * this.ROW, bot = top + this.ROW;
    if (top - this.scroll < 0) this.scroll = top;
    if (bot - this.scroll > view) this.scroll = bot - view;
    this.scroll = Math.max(0, Math.min(this.scroll, Math.max(0, n * this.ROW - view)));
    const x = this.bladeX(S.ci) + this.PAD;
    columnEls.forEach((el, i) => {
      const on = i === s;
      const y = this.TOP + i * this.ROW - this.scroll;
      el.style.transform = `translate(${x}px, ${y}px)`;
      el.classList.toggle('on', on);
      el.classList.toggle('dim', !on);
      el.style.opacity = y < this.TOP - this.ROW || y > this.BOT ? 0 : '';
      if (Math.abs(i - s) <= Shell.artWindow) ensureArt(el, items[i]);
    });
  },

  render() {
    document.body.classList.toggle('infolder', S.stack.length > 0);
    $('#crumb').hidden = true;          // the open blade's header shows it instead
    this.renderCats();
    this.renderColumn(true);
  },
};

// ---------------------------------------------------------------- tiles (NXE / Metro)
// NXE and Metro share a model — tiles on a surface that slides horizontally, the category
// on the other axis, and the selected item's text in a detail region — so they're one
// renderer with two geometries. What differs is `rows`, the chrome (a channel rail vs a
// pane header) and the cursor rules.
const ERAS = {
  nxe: {                        // 2008: one row of big tiles, channels down the left
    rows: 1, tileW: 260, tileH: 260, gap: 28, surfaceX: 470, surfaceY: 330,
    stripY: 700, railX: 90, railY: 480, railPitch: 96, cull: 5, artWindow: 10,
  },
  metro: {                      // 2011: a 3-row grid filled top-to-bottom, paged by column
    rows: 3, tileW: 220, tileH: 190, gap: 12, surfaceX: 520, surfaceY: 310,
    stripY: 225, headerY: 110, cull: 14, artWindow: 18,
  },
};

const TileShell = {
  __proto__: X360Base,

  get cfg() { return ERAS[Shell.era] || ERAS.nxe; },
  get metro() { return Shell.era === 'metro'; },

  setup() { X360Base.setup.call(this); Shell.artWindow = this.cfg.artWindow; },

  renderCats() {
    const wrap = $('#cats'), c = this.cfg, f = S.stack.at(-1);
    if (this.metro) {
      // a pane header: the current category, with its neighbours ghosted either side
      if (!wrap.children.length) {
        wrap.innerHTML = '<div class="x-pane"><span class="x-pane-prev"></span>'
          + '<span class="x-pane-cur"></span><span class="x-pane-next"></span></div>';
      }
      wrap.querySelector('.x-pane').style.top = `${c.headerY}px`;
      wrap.querySelector('.x-pane-prev').textContent = CATS[S.ci - 1]?.label || '';
      wrap.querySelector('.x-pane-cur').textContent = f ? f.title : (CATS[S.ci]?.label || '');
      wrap.querySelector('.x-pane-next').textContent = CATS[S.ci + 1]?.label || '';
      return;
    }
    // a vertical channel rail, the selected channel lit
    if (!wrap.children.length) {
      CATS.forEach((cat) => {
        const el = document.createElement('div');
        el.className = 'x-chan';
        el.innerHTML = `<div class="x-ico">${icon(cat.icon)}</div><div class="x-clbl">${esc(cat.label)}</div>`;
        wrap.appendChild(el);
      });
    }
    [...wrap.children].forEach((el, i) => {
      const on = i === S.ci;
      const y = c.railY + (i - S.ci) * c.railPitch;
      el.style.transform = `translate(${c.railX}px, ${y}px)`;
      el.classList.toggle('on', on);
      el.style.opacity = Math.abs(i - S.ci) > 4 ? 0 : '';
      if (on) el.querySelector('.x-clbl').textContent = f ? f.title : CATS[i].label;
      else el.querySelector('.x-clbl').textContent = CATS[i].label;
    });
  },

  position() {
    const items = list(), s = sel(), c = this.cfg;
    const selCol = this.metro ? Math.floor(s / c.rows) : s;
    columnEls.forEach((el, i) => {
      const on = i === s;
      const col = this.metro ? Math.floor(i / c.rows) : i;
      const row = this.metro ? i % c.rows : 0;
      const x = c.surfaceX + (col - selCol) * (c.tileW + c.gap);
      const y = c.surfaceY + row * (c.tileH + c.gap);
      el.style.transform = `translate(${x}px, ${y}px)`;
      el.classList.toggle('on', on);
      el.classList.toggle('dim', !on);
      el.style.opacity = Math.abs(col - selCol) > c.cull ? 0 : '';
      // the selected tile's own .txt is what CSS lifts out into the detail region; this
      // offset is what keeps that region pinned to the stage whatever row the tile is on
      el.style.setProperty('--detail-dy', `${c.stripY - y}px`);
      if (Math.abs(i - s) <= Shell.artWindow) ensureArt(el, items[i]);
    });
  },

  render() {
    document.body.classList.toggle('infolder', S.stack.length > 0);
    $('#crumb').hidden = true;          // the rail / pane header carries the title
    this.renderCats();
    this.renderColumn(true);
  },

  // NXE flips the axes: up/down walks channels, left/right walks the tile strip.
  // Metro keeps up/down inside a column and pages the whole view at the column edges.
  moveV(d) {
    if (this.metro) {
      const n = list().length, s = sel(), rows = this.cfg.rows;
      const row = s % rows, col = Math.floor(s / rows);
      if (row + d < 0 || row + d >= rows) return;
      const i = col * rows + row + d;
      if (i >= n) return;                            // ragged last column
      setSel(i); Sfx.move(); this.position(); this.hint();
      return;
    }
    this.goChannel(d);
  },

  moveH(d) {
    const n = list().length, s = sel();
    if (!this.metro) {
      if (S.stack.length && d < 0 && s === 0) return back();   // left out of a folder
      if (!n) return;
      const i = Math.max(0, Math.min(n - 1, s + d));
      if (i !== s) { setSel(i); Sfx.move(); this.position(); this.hint(); }
      return;
    }
    const rows = this.cfg.rows;
    const col = Math.floor(s / rows), row = s % rows;
    const lastCol = Math.floor(Math.max(0, n - 1) / rows);
    if (col + d < 0 || col + d > lastCol) {          // off the grid: page, or leave the folder
      if (S.stack.length) { if (d < 0) back(); return; }
      return this.goChannel(d);
    }
    const i = Math.min(n - 1, (col + d) * rows + row);
    if (i !== s) { setSel(i); Sfx.move(); this.position(); this.hint(); }
  },

  goChannel(d) {
    if (S.stack.length) return;
    const i = Math.max(0, Math.min(CATS.length - 1, S.ci + d));
    if (i === S.ci) return;
    S.ci = i; Sfx.move(); this.render();
    refresh(CATS[i].id);                 // without this the new channel shows the old tiles
  },
};

// One look, three eras; Settings only offers the ones registered here.
Shell.register('x360', { eras: { blades: BladeShell, nxe: TileShell, metro: TileShell } });
