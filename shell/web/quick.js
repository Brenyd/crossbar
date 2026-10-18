'use strict';
// Quick Menu — Guide/PS button (or the Home key) from anywhere.
// Sits over a dimmed screenshot of the game or movie you came from.
//   Up/Down choose · Left/Right adjust or skip · A select · B resume

const QuickMenu = {
  open: false, sel: 0, rows: [], data: null, timer: null, page: 'main', backTo: null,

  async show(shot) {
    this.open = true;
    this.sel = 0; this.page = 'main';
    Options.hide();
    const bg = $('#quick .q-bg');
    bg.style.backgroundImage = shot ? `url("/api/overlay.jpg?t=${Date.now()}")` : 'none';
    $('#quick').classList.toggle('has-shot', !!shot);
    $('#quick').hidden = false;
    Sfx.ok();
    await this.refresh();
    clearInterval(this.timer);
    this.timer = setInterval(() => this.refresh(), 1000);
  },

  toggle() { if (this.open) this.close(true); else this.show(false); },

  async close(resume) {
    if (!this.open) return;
    this.open = false;
    clearInterval(this.timer);
    $('#quick').hidden = true;
    Sfx.back();
    if (resume && this.data?.app) await api.post('/api/quick/resume');
  },

  async refresh() {
    try { this.data = await api.get('/api/quick'); } catch { return; }
    if (!this.open) return;
    const key = this.rows[this.sel]?.key;
    this.rows = this.build(this.data);
    const i = this.rows.findIndex((r) => r.key === key);
    this.sel = i >= 0 ? i : Math.min(this.sel, this.rows.length - 1);
    this.render();
  },

  // Pages keep the list short: Sound and Performance open their own page (B comes back).
  go(page) {
    if (page !== 'main') this.backTo = this.rows[this.sel]?.key;      // B returns to the row you came from
    this.page = page; Sfx.ok();
    this.rows = this.build(this.data);
    this.sel = page === 'main' ? Math.max(0, this.rows.findIndex((r) => r.key === this.backTo)) : 0;
    this.render();
  },

  build(d) {
    if (this.page === 'sound') return this.buildSound(d);
    if (this.page === 'perf') return this.buildPerf(d);
    const rows = [];
    const after = () => setTimeout(() => this.refresh(), 300);
    if (d.app) {
      const what = d.app.video ? 'Video' : 'Game';
      rows.push({ key: 'resume', icon: 'play', label: `Resume ${what}`, sub: d.app.title, ok: () => this.close(true) });
      rows.push({ key: 'close', icon: 'power', label: `Close ${what}`, sub: d.app.title, ok: async () => {
        this.open = false;          // let the confirm dialog take input
        const yes = await confirmBox(`Close ${d.app.title}?${d.app.video ? '' : '\nUnsaved game progress may be lost.'}`);
        this.open = true;
        if (!yes) return this.render();
        await call(() => api.post('/api/quick/close'));
        toast(`Closed ${d.app.title}`, 'power');
        this.close(false);
        setTimeout(loadState, 500);
      } });
    }
    rows.push({ key: 'home', icon: 'users', label: 'Go to Home', sub: d.app ? `${d.app.title} stays open` : 'Back to the menu',
      ok: () => this.close(false) });

    // Now playing: local music first, then Spotify
    const m = d.music, sp = d.spotify;
    if (m) {
      const ctl = (action) => async () => { await api.post('/api/music/control', { action }); after(); };
      rows.push({ key: 'media', icon: 'music', art: thumb(m.path), label: m.title,
        sub: `${m.artist ? m.artist + ' · ' : ''}${m.paused ? 'Paused' : 'Playing'} · ${fmtTime(m.position)} / ${fmtTime(m.duration)}`,
        bar: m.duration ? m.position / m.duration : null, hint: '◀ ▶ skip · {ok} play/pause',
        ok: ctl('toggle'), adjust: (dir) => ctl(dir > 0 ? 'next' : 'prev')() });
    } else if (sp) {
      const ctl = (action) => async () => { await call(() => api.post('/api/spotify/control', { action })); after(); };
      rows.push({ key: 'media', icon: 'spotify', art: sp.art, label: sp.name,
        sub: `Spotify · ${sp.artist}${sp.here ? '' : ` · on ${sp.device}`} · ${sp.playing ? 'Playing' : 'Paused'}`,
        bar: sp.duration ? sp.position / sp.duration : null, hint: '◀ ▶ skip · {ok} play/pause',
        ok: ctl('toggle'), adjust: (dir) => ctl(dir > 0 ? 'next' : 'prev')() });
    }

    const out = d.audio?.output || {};
    if (out.volume != null) {
      rows.push({ key: 'vol', icon: 'sound', label: 'Volume', sub: out.muted ? 'Muted' : `${out.volume}%`,
        bar: out.muted ? 0 : Math.min(1, out.volume / 100), hint: '◀ ▶ adjust · {ok} mute',
        ok: async () => { await api.post('/api/audio', { target: 'output', mute: true }); after(); },
        adjust: async (dir) => { await api.post('/api/audio', { target: 'output', delta: dir * 5 }); after(); } });
    }
    const nApps = (d.apps_audio || []).length;
    rows.push({ key: 'sound', icon: 'sound', label: 'Sound ▸', sub: [d.output?.name, d.audio?.mic?.muted ? 'mic muted' : '', nApps ? `${nApps} app${nApps === 1 ? '' : 's'} playing` : ''].filter(Boolean).join(' · ') || 'Output, microphone, app volume',
      ok: () => this.go('sound') });
    if (d.perf?.available || d.ps5?.available) {
      rows.push({ key: 'perf', icon: 'display', label: 'Performance ▸', sub: 'Frame rate and temperature overlays', ok: () => this.go('perf') });
    }
    rows.push({ key: 'settings', icon: 'settings', label: 'Settings', sub: 'Controller, network, everything else', ok: () => { this.close(false); goCat('settings'); } });
    rows.push({ key: 'power', icon: 'power', label: 'Power', sub: 'Turn off or restart', ok: () => Options.show([
      { label: 'Turn Off System', action: async () => { if (await confirmSafe('Turn off the system?')) api.post('/api/power/poweroff'); } },
      { label: 'Restart System', action: async () => { if (await confirmSafe('Restart the system?')) api.post('/api/power/reboot'); } },
    ]) });
    return rows;
  },

  buildSound(d) {
    const rows = [];
    const after = () => setTimeout(() => this.refresh(), 300);
    if (d.outputs?.length > 1) {
      rows.push({ key: 'out', icon: 'sound', label: 'Sound Output', sub: d.output?.name || 'Default', hint: '{ok} switch',
        ok: async () => { const r = await call(() => api.post('/api/quick/output')); if (r?.name) toast(`Sound output: ${r.name}`, 'sound'); after(); } });
    }
    const mic = d.audio?.mic || {};
    if (mic.volume != null) {
      rows.push({ key: 'mic', icon: 'mic', label: 'Microphone', sub: mic.muted ? 'Muted' : `${mic.volume}%`, hint: '{ok} mute',
        ok: async () => { await api.post('/api/audio', { target: 'mic', mute: true }); after(); } });
    }
    // per-app volume: one row per app playing sound (◀ ▶ volume, A mute)
    for (const ap of d.apps_audio || []) {
      const change = async (body) => { await api.post('/api/audio/app', { ids: ap.ids, ...body }); after(); };
      rows.push({ key: `app:${ap.key}`, icon: 'sound', label: ap.name,
        sub: `${ap.muted ? 'Muted' : `${ap.volume}%`}${ap.sub ? ' · ' + ap.sub : ''}`,
        bar: ap.muted ? 0 : Math.min(1, ap.volume / 100), hint: '◀ ▶ volume · {ok} mute',
        ok: () => change({ mute: !ap.muted }), adjust: (dir) => change({ delta: dir > 0 ? 5 : -5 }) });
    }
    if (!rows.length) rows.push({ key: 'none', icon: 'info', label: 'No sound devices', sub: '' });
    return rows;
  },

  buildPerf(d) {
    const rows = [], p = d.perf || {}, after = () => setTimeout(() => this.refresh(), 300);
    const NAMES = { off: 'Off', fps: 'FPS only', graph: 'FPS + frame time', full: 'Full' }, MODES = Object.keys(NAMES);
    if (p.available) {
      const set = async (mode) => { await call(() => api.post('/api/perf/fps', { mode })); after(); };
      rows.push({ key: 'fps', icon: 'display', label: 'Frame Rate Overlay', sub: `${NAMES[p.fps] || p.fps} · ${p.corner.replace('-', ' ')}`, hint: '◀ ▶ change · {ok} on/off',
        ok: () => set(p.fps === 'off' ? (p.last || 'fps') : 'off'),
        adjust: (dir) => set(MODES[(MODES.indexOf(p.fps) + dir + MODES.length) % MODES.length]) });
    }
    if (d.ps5?.available) {
      rows.push({ key: 'hud', icon: 'display', label: 'Temperature Overlay', sub: d.ps5.hud ? 'On' : 'Off', hint: '{ok} on/off',
        ok: async () => { await call(() => api.post('/api/ps5/hud', { on: !d.ps5.hud })); after(); } });
    }
    return rows;
  },

  goSettings(id) { this.close(false); openSettingsFolder(id); },

  render() {
    const d = this.data || {};
    $('#quick .q-title').textContent = ({ sound: 'Sound', perf: 'Performance' })[this.page] || (d.app ? d.app.title : 'Crossbar');
    $('#quick .q-rows').innerHTML = this.rows.map((r, i) => `
      <div class="q-row ${i === this.sel ? 'on' : ''}">
        <div class="q-ico">${r.art ? `<div class="q-art" style="background-image:url('${esc(r.art)}')"></div>` : icon(r.icon)}</div>
        <div class="q-txt">
          <div class="q-label">${esc(r.label)}</div>
          <div class="q-sub">${esc(r.sub || '')}</div>
          ${r.bar != null ? `<div class="q-bar"><i style="width:${(r.bar * 100).toFixed(1)}%"></i></div>` : ''}
        </div>
        ${r.hint && i === this.sel ? `<div class="q-hint">${esc(gl(r.hint))}</div>` : ''}
      </div>`).join('');
    $('#quick .q-row.on')?.scrollIntoView({ block: 'nearest' });
  },

  handle(a) {
    if (Options.open) {        // the Power sub-menu
      if (a === 'up') Options.move(-1);
      else if (a === 'down') Options.move(1);
      else if (a === 'ok') Options.pick();
      else if (a === 'back' || a === 'opt') { Options.hide(); Sfx.back(); }
      return;
    }
    const r = this.rows[this.sel];
    if (a === 'up' || a === 'down') {
      const n = Math.max(0, Math.min(this.rows.length - 1, this.sel + (a === 'up' ? -1 : 1)));
      if (n !== this.sel) { this.sel = n; Sfx.move(); this.render(); }
    } else if ((a === 'left' || a === 'right') && r?.adjust) {
      Sfx.move(); r.adjust(a === 'right' ? 1 : -1);
    } else if (a === 'ok' && r?.ok) {
      Sfx.ok(); r.ok();
    } else if (a === 'back' && this.page !== 'main') {
      Sfx.back(); this.go('main');
    } else if (a === 'back' || a === 'opt') {
      this.close(true);
    }
  },
};
