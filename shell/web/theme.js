'use strict';
// Theme packs (crossbar/themes.py, docs/THEMES.md): colours, waves, background picture or video,
// font, icon replacements, sounds, keyboard colours and an optional theme.css, applied live.

const Theme = {
  cur: null, icons: {}, sounds: {}, id: null,

  async load() {
    try { await this.apply(await api.get('/api/theme')); } catch (e) { /* keep the built-in look */ }
  },

  async apply(t) {
    this.cur = t; this.id = t.id;
    const r = document.documentElement.style, c = t.colors, k = t.keyboard;
    const vars = {
      '--text': c.text, '--dim': c.dim, '--hl': c.highlight, '--panel': c.panel, '--glyph': c.glyph,
      '--kb-bg': k.background, '--kb-key': k.key, '--kb-text': k.key_text, '--kb-hl': k.highlight, '--kb-hl-text': k.highlight_text,
      '--kb-radius': `${k.radius}px`, '--font-weight': t.font.weight,
      '--icon-color': t.icons.color || 'currentColor',
      '--icon-glow': t.icons.glow ? 'drop-shadow(0 0 6px rgba(255,255,255,.35))' : 'none',
    };
    for (const [n, v] of Object.entries(vars)) r.setProperty(n, v);

    // font: a file in the theme, or a font installed on the system
    let face = document.getElementById('theme-font');
    if (t.font.file) {
      if (!face) { face = document.createElement('style'); face.id = 'theme-font'; document.head.appendChild(face); }
      face.textContent = `@font-face { font-family: "CrossbarTheme"; src: url("${t.font.file}"); font-display: swap; }`;
      r.setProperty('--font', `"CrossbarTheme", "${t.font.family}", "Noto Sans", sans-serif`);
    } else {
      if (face) face.remove();
      r.setProperty('--font', `"${t.font.family}", "Noto Sans", "Helvetica Neue", Arial, sans-serif`);
    }

    // background picture / video under the waves
    const bg = document.getElementById('theme-bg');
    const b = t.background;
    bg.innerHTML = '';
    if (b.image) {
      const el = document.createElement(b.video ? 'video' : 'img');
      el.src = b.image;
      if (b.video) { el.autoplay = true; el.loop = true; el.muted = true; el.playsInline = true; }
      el.style.filter = `blur(${b.blur}px) brightness(${1 - b.dim})`;
      bg.appendChild(el);
    }
    bg.hidden = !b.image;
    document.getElementById('waves').style.opacity = b.image && !b.waves_on_top ? '0' : '';
    Waves.configure(t.waves, !!b.image, c.accent);

    // icons: the theme's SVGs are drawn like the built-in ones (in the text colour); PNGs as pictures
    this.icons = {};
    await Promise.all(Object.entries(t.icons.overrides || {}).map(async ([name, url]) => {
      if (!/\.svg$/i.test(url)) { this.icons[name] = `<img class="i ti" src="${url}" alt="">`; return; }
      try { this.icons[name] = cleanSvg(await (await fetch(url)).text()); } catch (e) { /* keep the built-in one */ }
    }));

    // sounds: files in the theme replace the built-in beeps
    this.sounds = {};
    for (const [name, url] of Object.entries(t.sounds || {})) { const a = new Audio(url); a.preload = 'auto'; this.sounds[name] = a; }

    // advanced: the theme's own CSS, loaded last
    let link = document.getElementById('theme-css');
    if (t.css) {
      if (!link) { link = document.createElement('link'); link.id = 'theme-css'; link.rel = 'stylesheet'; document.head.appendChild(link); }
      link.href = `${t.css}?v=${Date.now()}`;
    } else if (link) link.remove();

    document.body.dataset.theme = t.id;
    // the category row is built once: let the active look rebuild it with the new icons
    if (typeof Shell !== 'undefined') { Shell.resetCats(); if (S.state) Shell.active?.configure?.(S.state); }
    if (typeof render === 'function' && S.state) render();
  },

  icon(name) { return this.icons[name] || null; },

  play(name) {
    const a = this.sounds[name];
    if (!a) return false;
    try { const p = a.cloneNode(); p.volume = 0.6; p.play().catch(() => {}); } catch (e) { /* no audio */ }
    return true;
  },
};

// Only drawing: no scripts, event handlers, links or embedded documents from a theme's SVG.
function cleanSvg(text) {
  const doc = new DOMParser().parseFromString(text, 'image/svg+xml');
  const svg = doc.documentElement;
  if (!svg || svg.nodeName.toLowerCase() !== 'svg') return null;
  svg.querySelectorAll('script, foreignObject, iframe, object, embed, a, use[href^="http"]').forEach((n) => n.remove());
  for (const el of [svg, ...svg.querySelectorAll('*')]) {
    for (const at of [...el.attributes]) {
      if (/^on/i.test(at.name) || (/href$/i.test(at.name) && !/^#/.test(at.value))) el.removeAttribute(at.name);
    }
  }
  svg.setAttribute('class', 'i ti');
  svg.removeAttribute('width'); svg.removeAttribute('height');
  if (!svg.getAttribute('viewBox')) svg.setAttribute('viewBox', '0 0 64 64');
  return svg.outerHTML;
}
