'use strict';
// On-screen keyboard for Crossbar's own text fields (QWERTY, XMB look).
// Opens when you're on a controller; closes the moment a real keyboard or mouse is used.
//   ◀ ▶ ▲ ▼ move · A type · B delete (on an empty field: close) · Y/△ shift · L1/R1 move the cursor
//   Start: done

const OSK_LAYERS = {
  abc: [
    ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '⌫'],
    ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p', "'"],
    ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', ':', '⏎'],
    ['⇧', 'z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.', '/', '@'],
    ['?123', '◀', 'space', '▶', '.com', 'Done'],
  ],
  sym: [
    ['!', '@', '#', '$', '%', '^', '&', '*', '(', ')', '_', '⌫'],
    ['~', '`', '=', '+', '[', ']', '{', '}', '\\', '|', ';'],
    ['"', "'", '<', '>', '?', '€', '£', '¥', '°', '·', '⏎'],
    ['⇧', '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', ':'],
    ['abc', '◀', 'space', '▶', 'https://', 'Done'],
  ],
};
const OSK_WIDE = { space: 5, Done: 2, '?123': 1.5, abc: 1.5, '.com': 1.5, 'https://': 2, '⏎': 1.5, '⇧': 1.5, '⌫': 1.5 };

const Osk = {
  open: false, input: null, layer: 'abc', shift: false, caps: false, r: 1, c: 0, onDone: null, lastPress: 0,

  show(input, onDone = null) {
    if (!input) return;
    this.input = input; this.onDone = onDone; this.open = true;
    this.layer = 'abc'; this.shift = false; this.caps = false; this.r = 1; this.c = 0;
    input.focus();
    try { input.setSelectionRange(input.value.length, input.value.length); } catch (e) { /* password fields */ }
    $('#osk').hidden = false;
    document.body.classList.add('osk-open');
    this.render();
  },
  hide(done = false) {
    if (!this.open) return;
    this.open = false;
    $('#osk').hidden = true;
    document.body.classList.remove('osk-open');
    const cb = this.onDone; this.onDone = null;
    if (cb) cb(done);
  },

  keys() { return OSK_LAYERS[this.layer]; },
  label(k) {
    if (k.length === 1 && /[a-z]/.test(k) && (this.shift || this.caps)) return k.toUpperCase();
    if (k === 'space') return '';
    if (k === '⇧') return this.caps ? '⇪' : '⇧';
    return k;
  },
  render() {
    const rows = this.keys();
    const html = rows.map((row, r) => `<div class="osk-row">${row.map((k, c) =>
      `<div class="osk-key${r === this.r && c === this.c ? ' on' : ''}${k === '⇧' && (this.shift || this.caps) ? ' lit' : ''}${k.length > 1 && k !== 'space' ? ' fn' : ''}"
            style="flex:${OSK_WIDE[k] || 1}" data-r="${r}" data-c="${c}">${esc(this.label(k))}</div>`).join('')}</div>`).join('');
    $('#osk .osk-keys').innerHTML = html;
    $('#osk .osk-hint').innerHTML = `${glb('ok')}Type ${glb('back')}Delete ${glb('menu')}Shift ${glb('prev')}${glb('next')}Cursor ${glb('toggle')}Done`;
  },

  // moving between rows keeps the column under the same spot (rows have different key widths)
  moveRow(d) {
    const rows = this.keys();
    const nr = Math.max(0, Math.min(rows.length - 1, this.r + d));
    if (nr === this.r) return;
    const from = $(`#osk .osk-key[data-r="${this.r}"][data-c="${this.c}"]`)?.getBoundingClientRect();
    const x = from ? from.left + from.width / 2 : 0;
    let best = 0, bestDist = Infinity;
    document.querySelectorAll(`#osk .osk-key[data-r="${nr}"]`).forEach((el) => {
      const b = el.getBoundingClientRect(), dist = Math.abs(b.left + b.width / 2 - x);
      if (dist < bestDist) { bestDist = dist; best = +el.dataset.c; }
    });
    this.r = nr; this.c = best;
  },

  insert(text) {
    const i = this.input;
    const s = i.selectionStart ?? i.value.length, e = i.selectionEnd ?? i.value.length;
    i.value = i.value.slice(0, s) + text + i.value.slice(e);
    try { i.setSelectionRange(s + text.length, s + text.length); } catch (err) { /* password */ }
    i.dispatchEvent(new Event('input', { bubbles: true }));
  },
  backspace() {
    const i = this.input;
    if (!i.value) { this.hide(false); return; }
    const s = i.selectionStart ?? i.value.length, e = i.selectionEnd ?? i.value.length;
    const from = s === e ? Math.max(0, s - 1) : s;
    i.value = i.value.slice(0, from) + i.value.slice(e);
    try { i.setSelectionRange(from, from); } catch (err) { /* password */ }
    i.dispatchEvent(new Event('input', { bubbles: true }));
  },
  cursor(d) {
    const i = this.input;
    const p = Math.max(0, Math.min(i.value.length, (i.selectionStart ?? i.value.length) + d));
    try { i.setSelectionRange(p, p); } catch (err) { /* password */ }
  },
  press() {
    const k = this.keys()[this.r][this.c];
    if (k === '⌫') this.backspace();
    else if (k === '⇧') { if (this.shift && !this.caps) { this.caps = true; this.shift = false; } else if (this.caps) this.caps = false; else this.shift = true; }
    else if (k === '?123') { this.layer = 'sym'; this.c = Math.min(this.c, this.keys()[this.r].length - 1); }
    else if (k === 'abc') { this.layer = 'abc'; this.c = Math.min(this.c, this.keys()[this.r].length - 1); }
    else if (k === '◀') this.cursor(-1);
    else if (k === '▶') this.cursor(1);
    else if (k === 'space') this.insert(' ');
    else if (k === 'Done' || k === '⏎') { this.hide(true); return; }
    else {
      this.insert(this.label(k));
      if (this.shift) this.shift = false;          // one capital, like a phone keyboard
    }
    Sfx.move();
    this.render();
  },

  handle(action) {
    if (action === 'up' || action === 'down') this.moveRow(action === 'up' ? -1 : 1);
    else if (action === 'left' || action === 'right') {
      const n = this.keys()[this.r].length;
      this.c = (this.c + (action === 'left' ? -1 : 1) + n) % n;
    } else if (action === 'ok') return this.press();
    else if (action === 'back') this.backspace();
    else if (action === 'menu' || action === 'opt') { this.shift = !this.shift; this.caps = false; }
    else if (action === 'prev') this.cursor(-1);
    else if (action === 'next') this.cursor(1);
    else if (action === 'toggle' || action === 'home') { this.hide(true); return; }
    if (this.open) { Sfx.move(); this.render(); }
  },
};

// A real keyboard or mouse takes over: the on-screen keyboard steps aside.
addEventListener('keydown', (e) => { if (Osk.open && e.isTrusted && !e.repeat) Osk.hide(false); }, true);
addEventListener('mousedown', () => { if (Osk.open) Osk.hide(false); }, true);
