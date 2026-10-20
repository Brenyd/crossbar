'use strict';
// Looks (console skins) — the loader. Each look is a folder (web/looks/<id>/, or your own in
// ~/.local/share/crossbar/looks/<id>/) with look.json, look.js and look.css; the backend lists
// them (/api/looks) and this loads every one at start-up, before the menu first draws. A look's
// script registers its drawing code with Shell.register(id, {...}) (xmb.js documents the
// contract); its manifest — name, settings, colours — is attached as `.manifest`.
// docs/LOOKS.md walks through making one.

const Looks = {
  list: [], byId: {},

  async load() {
    try { this.list = await api.get('/api/looks'); } catch (e) { this.list = []; }
    if (!this.list.some((m) => m.id === 'xmb')) {      // the base look can't go missing
      this.list.unshift({ id: 'xmb', name: 'Cross-media bar (PS3 style)', short: 'PS3', settings: [], colors: {},
        script: '/looks/xmb/look.js', css: '/looks/xmb/look.css' });
    }
    for (const m of this.list) {
      this.byId[m.id] = m;
      if (m.css && !document.querySelector(`link[data-look="${m.id}"]`)) {
        const l = document.createElement('link');
        l.rel = 'stylesheet'; l.href = m.css; l.dataset.look = m.id;
        // before theme.css (a theme pack's CSS must still win)
        document.head.insertBefore(l, document.getElementById('theme-css'));
      }
      if (m.script && !Shell.impls[m.id]) {
        await new Promise((res) => {
          const s = document.createElement('script');
          s.src = m.script; s.onload = res;
          s.onerror = () => { console.error(`look ${m.id}: ${m.script} didn't load`); res(); };
          document.head.appendChild(s);
        });
      }
      if (Shell.impls[m.id]) Shell.impls[m.id].manifest = m;
    }
  },

  // [[id, name]] of the looks that loaded, for pickers
  names() { return this.list.filter((m) => Shell.impls[m.id]).map((m) => [m.id, m.name]); },
  // a look's settings as stored (each one filled in by the backend from look.json's defaults)
  settings(id) { return S.state?.look_settings?.[id] || {}; },
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
