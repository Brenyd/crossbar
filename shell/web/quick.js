'use strict';
// Quick Menu — Guide/PS button (or the Home key) from anywhere.
// Sits over a dimmed screenshot of the game or movie you came from.
//   Up/Down choose · Left/Right adjust or skip · A select · B resume

const QuickMenu = {
  open: false, sel: 0, rows: [], data: null, timer: null,

  async show(shot) {
    this.open = true;
    this.sel = 0;
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

  build(d) {
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
        bar: m.duration ? m.position / m.duration : null, hint: '◀ ▶ skip · A play/pause',
        ok: ctl('toggle'), adjust: (dir) => ctl(dir > 0 ? 'next' : 'prev')() });
    } else if (sp) {
      const ctl = (action) => async () => { await call(() => api.post('/api/spotify/control', { action })); after(); };
      rows.push({ key: 'media', icon: 'spotify', art: sp.art, label: sp.name,
        sub: `Spotify · ${sp.artist}${sp.here ? '' : ` · on ${sp.device}`} · ${sp.playing ? 'Playing' : 'Paused'}`,
        bar: sp.duration ? sp.position / sp.duration : null, hint: '◀ ▶ skip · A play/pause',
        ok: ctl('toggle'), adjust: (dir) => ctl(dir > 0 ? 'next' : 'prev')() });
    }

    const out = d.audio?.output || {};
    if (out.volume != null) {
      rows.push({ key: 'vol', icon: 'sound', label: 'Volume', sub: out.muted ? 'Muted' : `${out.volume}%`,
        bar: out.muted ? 0 : Math.min(1, out.volume / 100), hint: '◀ ▶ adjust · A mute',
        ok: async () => { await api.post('/api/audio', { target: 'output', mute: true }); after(); },
        adjust: async (dir) => { await api.post('/api/audio', { target: 'output', delta: dir * 5 }); after(); } });
    }
    if (d.outputs?.length > 1) {
      rows.push({ key: 'out', icon: 'sound', label: 'Sound Output', sub: d.output?.name || 'Default', hint: 'A switch',
        ok: async () => { const r = await call(() => api.post('/api/quick/output')); if (r?.name) toast(`Sound output: ${r.name}`, 'sound'); after(); } });
    }
    const mic = d.audio?.mic || {};
    if (mic.volume != null) {
      rows.push({ key: 'mic', icon: 'mic', label: 'Microphone', sub: mic.muted ? 'Muted' : `${mic.volume}%`, hint: 'A mute',
        ok: async () => { await api.post('/api/audio', { target: 'mic', mute: true }); after(); } });
    }
    rows.push({ key: 'pad', icon: 'game', label: 'Controller & Keyboard', sub: 'Button mapping', ok: () => this.goSettings('controls') });
    rows.push({ key: 'net', icon: 'wifi', label: 'Network', sub: 'Wi-Fi and connection', ok: () => this.goSettings('network') });
    rows.push({ key: 'power', icon: 'power', label: 'Power', sub: 'Turn off or restart', ok: () => Options.show([
      { label: 'Turn Off System', action: async () => { if (await confirmBox('Turn off the system?')) api.post('/api/power/poweroff'); } },
      { label: 'Restart System', action: async () => { if (await confirmBox('Restart the system?')) api.post('/api/power/reboot'); } },
    ]) });
    return rows;
  },

  goSettings(id) { this.close(false); openSettingsFolder(id); },

  render() {
    const d = this.data || {};
    $('#quick .q-title').textContent = d.app ? d.app.title : 'Crossbar';
    $('#quick .q-rows').innerHTML = this.rows.map((r, i) => `
      <div class="q-row ${i === this.sel ? 'on' : ''}">
        <div class="q-ico">${r.art ? `<div class="q-art" style="background-image:url('${esc(r.art)}')"></div>` : icon(r.icon)}</div>
        <div class="q-txt">
          <div class="q-label">${esc(r.label)}</div>
          <div class="q-sub">${esc(r.sub || '')}</div>
          ${r.bar != null ? `<div class="q-bar"><i style="width:${(r.bar * 100).toFixed(1)}%"></i></div>` : ''}
        </div>
        ${r.hint && i === this.sel ? `<div class="q-hint">${esc(r.hint)}</div>` : ''}
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
    } else if (a === 'back' || a === 'opt') {
      this.close(true);
    }
  },
};
