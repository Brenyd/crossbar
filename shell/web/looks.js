'use strict';
// Looks (console skins) — the loader. Each look is a folder (web/looks/<id>/, or your own in
// ~/.local/share/crossbar/looks/<id>/) with look.json, look.js and look.css. Only the chosen
// look runs: the backend builds it into the page (window.CROSSBAR_BOOT, plus its <script> and
// <link>), so the first frame is already drawn in it. Settings › Theme › Interface picks another;
// it takes over when the menu reloads (nothing else is kept loaded, so nothing else uses memory).
// A look's script registers its drawing code with Shell.register(id, {...}) (xmb.js documents the
// contract); its manifest — name, settings, colours — is attached as `.manifest`.
// docs/LOOKS.md walks through making one.

const Looks = {
  list: [], byId: {}, all: null,

  async load() {
    // every <script> of the page (the chosen look's comes last) has run once the DOM is ready
    if (document.readyState === 'loading') await new Promise((r) => addEventListener('DOMContentLoaded', r, { once: true }));
    const boot = window.CROSSBAR_BOOT;
    let m = boot?.look;
    if (!m || !Shell.impls[m.id]) {
      // no built-in choice (an old page), or its script failed: ask the backend, else the cross-media bar
      const want = boot?.interface || 'xmb';
      const all = await this.fetchAll();
      m = all.find((x) => x.id === want && x.script) || all.find((x) => x.id === 'xmb')
        || { id: 'xmb', name: 'Cross-media bar (PS3 style)', short: 'PS3', settings: [], colors: {}, script: '/looks/xmb/look.js', css: '/looks/xmb/look.css' };
      if (m.id !== want) console.error(`look ${want} didn't load: using ${m.id}`);
      await this.inject(m);
      if (!Shell.impls[m.id] && m.id !== 'xmb') {
        m = all.find((x) => x.id === 'xmb') || { ...m, id: 'xmb', script: '/looks/xmb/look.js', css: '/looks/xmb/look.css' };
        await this.inject(m);
      }
    }
    this.list = [m];
    this.byId = { [m.id]: m };
    if (Shell.impls[m.id]) Shell.impls[m.id].manifest = m;
    Shell.start(m.id);
  },

  // every installed look (for Settings › Theme › Interface), fetched when it's needed
  async fetchAll() {
    if (this.all) return this.all;
    for (let i = 0; i < 6; i++) {
      try { this.all = await api.get('/api/looks'); return this.all; } catch { await new Promise((r) => setTimeout(r, 500)); }
    }
    return [];
  },

  inject(m) {
    if (m.css && !document.querySelector(`link[data-look="${m.id}"]`)) {
      const l = document.createElement('link');
      l.rel = 'stylesheet'; l.href = m.css; l.dataset.look = m.id;
      document.head.insertBefore(l, document.getElementById('theme-css'));   // a theme pack's CSS still wins
    }
    if (!m.script || Shell.impls[m.id]) return Promise.resolve();
    return new Promise((res) => {
      const s = document.createElement('script');
      s.src = m.script; s.onload = res;
      s.onerror = () => { console.error(`look ${m.id}: ${m.script} didn't load`); res(); };
      document.head.appendChild(s);
    });
  },

  // [[id, name]] of every installed look, for the Interface picker
  async names() { return (await this.fetchAll()).filter((m) => m.script).map((m) => [m.id, m.name]); },
  // a look's settings as stored (each one filled in by the backend from look.json's defaults)
  settings(id) { return S.state?.look_settings?.[id] || window.CROSSBAR_BOOT?.look_settings?.[id] || {}; },
  // look.json "colors": {setting: {value: [dark, light]}} -> the pair for the current value
  colors(id, key) {
    const m = this.byId[id], v = this.settings(id)[key];
    return m?.colors?.[key]?.[v] || null;
  },
  // can a choice be offered? ("needs": "theme_picture" — only with a pack that has a picture)
  choiceOk(choice, theme) {
    const need = choice[2]?.needs;
    return !need || (need === 'theme_picture' && !!theme?.background?.image);
  },
};
