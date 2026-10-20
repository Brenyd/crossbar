'use strict';
// The cross-media bar (PS3 style): Crossbar's original look and the default.
// Categories across, items down; a folder pushes a new column. See docs/LOOKS.md for what a
// look provides — this one is the reference implementation of the Shell contract (xmb.js).
// Its styles are the base style.css (look.css only holds what's XMB-only and new).

const XmbShell = {
  id: 'xmb',
  CAT_X: 560, CAT_GAP: 230,
  setup() {},                               // #cats/#column/#crumb are already in index.html
  teardown() { $('#cats').innerHTML = ''; $('#column').innerHTML = ''; $('#crumb').hidden = true; },
  resetCats() { $('#cats').innerHTML = ''; },

  itemEl(it) {
    const el = document.createElement('div');
    el.className = 'item';
    let slot;
    if (it.art !== undefined) {
      const h = hashHue(it.artTitle || it.label);
      slot = `<div class="art${it.artShape === 'poster' ? ' poster' : it.artShape === 'square' ? ' square' : ''}" style="background-image:linear-gradient(135deg,hsl(${h} 55% 38%),hsl(${(h + 40) % 360} 60% 18%))">${esc(it.artTitle)}</div>`;
    } else slot = `<div class="ico">${icon(it.icon)}</div>`;
    el.innerHTML = `${slot}<div class="txt"><div class="label">${esc(gl(it.label))}${it.badge ? `<span class="badge">${esc(it.badge)}</span>` : ''}</div>
      <div class="sub">${esc(gl(it.sub || ''))}</div>${it.progress != null ? `<div class="bar"><i style="width:${(it.progress * 100).toFixed(1)}%"></i></div>` : ''}</div>`;
    if (it.art && artLoaded.has(it.art)) showArt(el, it.art);
    return el;
  },

  renderCats() {
    const wrap = $('#cats');
    if (!wrap.children.length) {
      CATS.forEach((c, i) => {
        const el = document.createElement('div');
        el.className = 'cat';
        el.style.left = `${this.CAT_X + i * this.CAT_GAP}px`;
        el.innerHTML = `<div class="ico">${icon(c.icon)}</div><div class="lbl">${esc(c.label)}</div>`;
        wrap.appendChild(el);
      });
    }
    wrap.style.transform = `translateX(${-S.ci * this.CAT_GAP}px)`;
    [...wrap.children].forEach((el, i) => el.classList.toggle('on', i === S.ci));
  },

  renderColumn(rebuild = true) {
    const col = $('#column');
    if (!S.stack.length && !S.items[CATS[S.ci].id]) S.items[CATS[S.ci].id] = [{ key: 'loading', label: 'Loading…', icon: 'refresh' }];
    const items = list();
    if (rebuild) col.classList.add('swap');
    col.innerHTML = '';
    columnEls = items.map((it) => { const el = this.itemEl(it); col.appendChild(el); return el; });
    this.position();
    if (rebuild) requestAnimationFrame(() => requestAnimationFrame(() => col.classList.remove('swap')));
    this.hint();
  },

  position() {
    const items = list(), s = sel();
    // the rows below make room for the *highlighted* row's size (a 140px artwork tile, a progress
    // bar), not their own: otherwise an icon row tucks under a big tile
    const selArt = items[s]?.art !== undefined;
    const selExtra = items[s]?.progress != null ? 18 : 0;
    columnEls.forEach((el, i) => {
      const on = i === s;
      const isArt = items[i].art !== undefined;
      const square = isArt && items[i].artShape === 'square';       // app icons: centred like icons
      const slotW = square ? (on ? 120 : 72) : isArt ? (on ? 300 : 150) : (on ? 104 : 72);
      let y;
      if (i < s) y = (S.stack.length ? 370 : 175) - (s - i - 1) * 100; // above the category bar
      else if (i === s) y = selArt ? 500 : 480;
      else y = (selArt ? 648 : 596) + selExtra + (i - s - 1) * 100;
      const x = this.CAT_X - slotW / 2;
      el.style.transform = `translate(${x}px, ${y}px)`;
      el.classList.toggle('on', on);
      el.classList.toggle('dim', !on);
      el.style.opacity = y < -60 || y > 900 ? 0 : '';     // > 900 would run under the button hints
      if (Math.abs(i - s) <= Shell.artWindow) ensureArt(el, items[i]);
    });
  },

  render() {
    const inFolder = S.stack.length > 0;
    document.body.classList.toggle('infolder', inFolder);
    $('#crumb').hidden = !inFolder;
    if (inFolder) {
      const f = S.stack.at(-1);
      $('#crumb .crumb-ico').innerHTML = icon(f.icon);
      $('#crumb .crumb-label').textContent = f.title;
    }
    this.renderCats();
    this.renderColumn(true);
  },

  hint() {
    const it = list()[sel()];
    const parts = [];
    if (it && (it.action || it.children)) parts.push(`${glb('ok')}Enter`);
    if (S.stack.length) parts.push(`${glb('back')}Back`);
    if (it?.options?.length) parts.push(`${glb('menu')}Options`);
    $('#hint').innerHTML = parts.join(' ');
  },

  moveV(d) {
    const n = list().length; if (!n) return;
    const i = Math.max(0, Math.min(n - 1, sel() + d));
    if (i !== sel()) { setSel(i); Sfx.move(); this.position(); this.hint(); }
  },
  moveH(d) {
    if (S.stack.length) { if (d < 0) back(); return; }
    const i = Math.max(0, Math.min(CATS.length - 1, S.ci + d));
    if (i === S.ci) return;
    S.ci = i; Sfx.move(); this.render();
    refresh(CATS[i].id);
  },

  // Settings › Theme: the XMB's own row besides its look.json settings — Wave Colour, for theme
  // packs whose waves follow the month
  settingsRows(st, cur) {
    if (cur.waves?.mode !== 'month') return [];
    const c = st.theme === 'auto' ? 0 : st.theme + 1;
    const opts = [{ label: `${check(c === 0)}Automatic (changes monthly)`, action: () => setSetting({ theme: 'auto' }).then(reloadFolder) }]
      .concat(MONTHS.map((m, i) => ({ label: `${check(c === i + 1)}${m} colour`, action: () => setSetting({ theme: i }).then(reloadFolder) })));
    return [{ key: 'color', label: 'Wave Colour', icon: 'palette', sub: st.theme === 'auto' ? 'Automatic (changes monthly)' : `${MONTHS[st.theme]} colour`,
      action: () => Options.show(opts, c) }];
  },
};
Shell.register('xmb', XmbShell);
