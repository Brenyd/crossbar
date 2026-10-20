'use strict';
// The smallest working look — a starting point for a new console skin (docs/LOOKS.md).
// Copy this folder to ~/.local/share/crossbar/looks/<your-id>/, set "id" in look.json to the
// folder's name, and register under the same id below. Everything the menu does (items,
// folders, actions, Options, dialogs, the Quick Menu's rows) is shared; a look only draws.
(() => {
  const ID = 'starter';                     // = the folder name = look.json "id"
  const ROW = 64, TOP = 200, VISIBLE = 11;

  Shell.register(ID, {
    id: ID,
    setup() {                               // your page: anything you add, remove in teardown()
      const r = document.createElement('div');
      r.id = 'st-root';
      r.innerHTML = '<div class="st-cats"></div><div class="st-title"></div>';
      $('#stage').insertBefore(r, $('#column'));
    },
    teardown() { $('#st-root')?.remove(); $('#column').innerHTML = ''; },
    resetCats() {},
    configure() {                           // your look.json settings, every state update
      const [a] = Looks.colors(ID, 'accent') || ['#2563eb'];
      document.body.style.setProperty('--st-accent', a);
    },

    // one node per item: class "item", a .txt holding .label and .sub (+ .bar > i for progress)
    itemEl(it) {
      const el = document.createElement('div');
      el.className = 'item';
      el.innerHTML = `<div class="ico">${icon(it.icon || 'folder')}</div><div class="txt"><div class="label">${esc(gl(it.label))}</div>
        <div class="sub">${esc(gl(it.sub || ''))}</div>${it.progress != null ? `<div class="bar"><i style="width:${it.progress * 100}%"></i></div>` : ''}</div>`;
      return el;
    },
    render() { this.renderCats(); this.renderColumn(true); },
    renderCats() {
      $('.st-cats').innerHTML = CATS.map((c, i) => `<div class="${i === S.ci ? 'on' : ''}">${esc(c.label)}</div>`).join('');
      $('.st-title').textContent = S.stack.length ? S.stack.map((f) => f.title).join(' › ') : CATS[S.ci].label;
    },
    renderColumn() {
      const col = $('#column');
      if (!S.stack.length && !S.items[CATS[S.ci].id]) S.items[CATS[S.ci].id] = [{ key: 'loading', label: 'Loading…', icon: 'refresh' }];
      col.innerHTML = '';
      columnEls = list().map((it) => { const el = this.itemEl(it); col.appendChild(el); return el; });   // index-parallel to list()
      this.position(); this.hint();
    },
    position() {
      const s = sel(), first = Math.max(0, Math.min(s - 4, list().length - VISIBLE));
      columnEls.forEach((el, i) => {
        el.style.transform = `translate(560px, ${TOP + (i - first) * ROW}px)`;
        el.style.opacity = i < first || i >= first + VISIBLE ? 0 : '';
        el.classList.toggle('on', i === s);
      });
    },
    hint() {
      const it = list()[sel()];
      $('#hint').innerHTML = [it && (it.action || it.children) ? `${glb('ok')} Open` : '', S.stack.length ? `${glb('back')} Back` : '',
        it?.options?.length ? `${glb('menu')} Options` : ''].filter(Boolean).join('   ');
    },
    moveV(d) {                               // up / down: the items
      const i = Math.max(0, Math.min(list().length - 1, sel() + d));
      if (i !== sel()) { setSel(i); Sfx.move(); this.position(); this.hint(); }
    },
    moveH(d) {                               // left / right: categories (left in a folder: back)
      if (S.stack.length) { if (d < 0) back(); return; }
      S.ci = (S.ci + d + CATS.length) % CATS.length; Sfx.move(); this.render(); refresh(CATS[S.ci].id);
    },
  });
})();
