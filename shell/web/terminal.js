'use strict';
// Built-in terminal: a full-screen panel inside Crossbar (no separate window).
// Uses xterm.js when it's installed (vendor/xterm, fetched when the ISO is built
// or Crossbar is updated); otherwise a simple built-in text view.
// Esc twice quickly (or the Back button) closes it; the shell keeps running.

const Term = {
  open: false, id: null, xterm: null, fit: null, plain: null, lastEsc: 0,

  async show(cmd) {
    const el = $('#term');
    el.hidden = false;
    this.open = true;
    Options.hide();
    if (!this.id || cmd) await this.start(cmd);
    this.focus();
    Sfx.ok();
  },

  async start(cmd) {
    if (this.id) { api.post('/api/term/close', { token: S.state.term_token, id: this.id }).catch(() => {}); this.id = null; }
    const host = $('#term .t-screen');
    host.innerHTML = '';
    const size = this.measure();
    if (window.Terminal) {
      this.xterm = new window.Terminal({ fontFamily: '"DejaVu Sans Mono", "Noto Sans Mono", monospace', fontSize: 18, cursorBlink: true,
        theme: { background: '#0b0b0e', foreground: '#e8e8e8' }, scrollback: 5000 });
      if (window.FitAddon) { this.fit = new window.FitAddon.FitAddon(); this.xterm.loadAddon(this.fit); }
      this.xterm.open(host);
      this.fit?.fit();
      this.xterm.onData((d) => this.send(d));
      this.xterm.attachCustomKeyEventHandler((e) => this.escCheck(e));
    } else {
      this.xterm = null;
      this.plain = document.createElement('pre');
      this.plain.className = 't-plain';
      this.plain.tabIndex = 0;
      host.appendChild(this.plain);
      this.plain.addEventListener('keydown', (e) => this.plainKey(e));
    }
    const cols = this.xterm ? this.xterm.cols : size.cols, rows = this.xterm ? this.xterm.rows : size.rows;
    const r = await call(() => api.post('/api/term/open', { token: S.state.term_token, cmd: cmd || null, cols, rows }));
    this.id = r?.id || null;
  },

  measure() {
    const host = $('#term .t-screen');
    return { cols: Math.max(40, Math.floor(host.clientWidth / 11)), rows: Math.max(10, Math.floor(host.clientHeight / 24)) };
  },

  focus() { (this.xterm || this.plain)?.focus(); },

  hide() {
    this.open = false;
    $('#term').hidden = true;
    document.activeElement?.blur();
    Sfx.back();
  },

  // Keystrokes are queued and sent one request at a time, in order (parallel
  // requests can arrive out of order and scramble what you typed).
  queue: '', sending: false,
  send(data) { this.queue += data; this.flush(); },
  async flush() {
    if (this.sending || !this.queue || !this.id) return;
    this.sending = true;
    const data = this.queue;
    this.queue = '';
    try { await api.post('/api/term/input', { token: S.state.term_token, id: this.id, data }); } catch { /* session gone */ }
    this.sending = false;
    if (this.queue) this.flush();
  },

  output(b64) {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    if (this.xterm) { this.xterm.write(bytes); return; }
    // plain view: decode, drop escape sequences, handle backspace/carriage return simply
    let t = new TextDecoder().decode(bytes).replace(/\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][A-Z0-9]/g, '');
    let cur = this.plain.textContent;
    for (const ch of t) {
      if (ch === '\b') cur = cur.slice(0, -1);
      else if (ch === '\r') continue;
      else if (ch === '\x07') continue;
      else cur += ch;
    }
    this.plain.textContent = cur.slice(-60000);
    this.plain.scrollTop = this.plain.scrollHeight;
  },

  escCheck(e) {             // double Esc closes; single Esc goes to the shell
    if (e.type === 'keydown' && e.key === 'Escape') {
      const now = Date.now();
      if (now - this.lastEsc < 400) { this.hide(); return false; }
      this.lastEsc = now;
    }
    return true;
  },

  plainKey(e) {
    if (!this.escCheck(e)) { e.preventDefault(); return; }
    const map = { Enter: '\r', Backspace: '\x7f', Tab: '\t', Escape: '\x1b', ArrowUp: '\x1b[A', ArrowDown: '\x1b[B', ArrowRight: '\x1b[C', ArrowLeft: '\x1b[D' };
    let d = map[e.key];
    if (!d && e.ctrlKey && e.key.length === 1) d = String.fromCharCode(e.key.toUpperCase().charCodeAt(0) - 64);
    if (!d && e.key.length === 1) d = e.key;
    if (d) { e.preventDefault(); e.stopPropagation(); this.send(d); }
  },

  handle(action) {          // controller in the terminal: B closes, arrows/A send keys
    if (action === 'back') return this.hide();
    const keys = { up: '\x1b[A', down: '\x1b[B', left: '\x1b[D', right: '\x1b[C', ok: '\r' };
    if (keys[action]) this.send(keys[action]);
  },
};

addEventListener('resize', () => {
  if (!Term.open || !Term.id) return;
  Term.fit?.fit();
  const s = Term.xterm ? { cols: Term.xterm.cols, rows: Term.xterm.rows } : Term.measure();
  api.post('/api/term/resize', { token: S.state.term_token, id: Term.id, ...s }).catch(() => {});
});
