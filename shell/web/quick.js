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
    if (['social', 'party', 'friends'].includes(this.page) && Date.now() - (this.soc?.at || 0) > 4000) this.loadSocial();
    if (!this.open) return;
    const key = this.rows[this.sel]?.key;
    this.rows = this.build(this.data);
    const i = this.rows.findIndex((r) => r.key === key);
    this.sel = i >= 0 ? i : Math.min(this.sel, this.rows.length - 1);
    this.render();
  },

  // Pages: the XMB's Quick Menu is one list ('main') with Sound / Performance / Trophies pages;
  // a look with quickTabs (the Dashboard's Guide) splits it into tabs walked with LB / RB —
  // the same rows and commands, grouped like the 360's Guide. B on a sub-page goes back to
  // where you opened it from.
  go(page) {
    if (!this.isTab(page)) { this.parent = this.page; this.backTo = this.rows[this.sel]?.key; }
    else this.parent = null;
    this.page = page; Sfx.ok();
    if (page === 'trophies') this.loadTrophies();
    if (['social', 'party', 'friends'].includes(page)) this.loadSocial();
    this.rows = this.build(this.data);
    this.sel = this.isTab(page) ? Math.max(0, this.rows.findIndex((r) => r.key === this.backTo)) : 0;
    this.render();
  },
  isTab(page) { return page === 'main' || (!!Shell.active?.quickTabs && this.tabs().some(([p]) => p === page)); },
  back() {
    const to = this.parent || 'main';
    this.parent = null;
    this.page = to; Sfx.back();
    this.rows = this.build(this.data);
    this.sel = Math.max(0, this.rows.findIndex((r) => r.key === this.backTo));
    this.render();
  },

  build(d) {
    const tabs = !!Shell.active?.quickTabs;
    switch (this.page) {
      case 'sound': return this.buildSound(d);
      case 'perf': return this.buildPerf(d);
      case 'trophies': return this.buildTrophies();
      case 'games': return [...this.rowsApp(d), this.rowTrophies(d), this.rowAllTrophies(), this.rowGo('game', 'Games', 'game', 'Your library')];
      case 'media': return [...this.rowsMedia(d), this.rowSound(d), this.rowGo('music', 'Music', 'music', 'Songs, Spotify'), this.rowGo('video', 'Video', 'video', 'Films, shows, IPTV')];
      case 'social': return this.buildSocial();
      case 'party': return this.buildParty();
      case 'friends': return this.buildFriends();
      case 'settings': return [this.rowPerf(d), this.rowSettings(), this.rowPower()].filter(Boolean);
      default:
        if (tabs) return [...this.rowsApp(d), this.rowHome(d), ...this.rowsMedia(d).slice(0, 1), this.rowPower()].filter(Boolean);
        return [...this.rowsApp(d), this.rowHome(d), d.app ? this.rowTrophies(d) : null, ...this.rowsMedia(d), this.rowSound(d), this.rowSocial(d),
          this.rowPerf(d), this.rowTrophies(d, true), this.rowSettings(), this.rowPower()].filter(Boolean);
    }
  },
  after() { setTimeout(() => this.refresh(), 300); },

  // ---- rows, shared by every layout
  rowsApp(d) {
    if (!d.app) return [];
    const what = d.app.video ? 'Video' : 'Game';
    return [
      { key: 'resume', icon: 'play', label: `Resume ${what}`, sub: d.app.title, ok: () => this.close(true) },
      { key: 'close', icon: 'power', label: `Close ${what}`, sub: d.app.title, ok: async () => {
        this.open = false;          // let the confirm dialog take input
        const yes = await confirmBox(`Close ${d.app.title}?${d.app.video ? '' : '\nUnsaved game progress may be lost.'}`);
        this.open = true;
        if (!yes) return this.render();
        await call(() => api.post('/api/quick/close'));
        toast(`Closed ${d.app.title}`, 'power');
        this.close(false);
        setTimeout(loadState, 500);
      } }];
  },
  rowHome(d) {
    return { key: 'home', icon: 'users', label: 'Go to Home', sub: d.app ? `${d.app.title} stays open` : 'Back to the menu', ok: () => this.close(false) };
  },
  // the running game's trophies (Steam achievements), or where to find them
  rowTrophies(d, onlyWithoutGame = false) {
    if (onlyWithoutGame && d.app) return null;
    return d.app && !d.app.video
      ? { key: 'trophies', icon: 'trophy', label: 'Trophies ▸', sub: `${d.app.title}: what you've unlocked`, ok: () => this.go('trophies') }
      : { key: 'trophies', icon: 'trophy', label: 'Trophies', sub: 'RetroAchievements and Steam', ok: () => this.openTrophiesFolder() };
  },
  rowAllTrophies() { return { key: 'all-trophies', icon: 'trophy', label: 'All Trophies', sub: 'Every game, RetroAchievements and Steam', ok: () => this.openTrophiesFolder() }; },
  openTrophiesFolder() {
    this.close(false); goCat('game');
    if (typeof TROPHIES_FOLDER !== 'undefined') openFolder(TROPHIES_FOLDER);
  },
  rowGo(cat, label, ico, sub) { return { key: `go:${cat}`, icon: ico, label, sub, ok: () => { this.close(false); goCat(cat); } }; },
  rowsMedia(d) {
    const rows = [], m = d.music, sp = d.spotify;
    if (m) {
      const ctl = (action) => async () => { await api.post('/api/music/control', { action }); this.after(); };
      rows.push({ key: 'media', icon: 'music', art: thumb(m.path), label: m.title,
        sub: `${m.artist ? m.artist + ' · ' : ''}${m.paused ? 'Paused' : 'Playing'} · ${fmtTime(m.position)} / ${fmtTime(m.duration)}`,
        bar: m.duration ? m.position / m.duration : null, hint: '◀ ▶ skip · {ok} play/pause',
        ok: ctl('toggle'), adjust: (dir) => ctl(dir > 0 ? 'next' : 'prev')() });
    } else if (sp) {
      const ctl = (action) => async () => { await call(() => api.post('/api/spotify/control', { action })); this.after(); };
      rows.push({ key: 'media', icon: 'spotify', art: sp.art, label: sp.name,
        sub: `Spotify · ${sp.artist}${sp.here ? '' : ` · on ${sp.device}`} · ${sp.playing ? 'Playing' : 'Paused'}`,
        bar: sp.duration ? sp.position / sp.duration : null, hint: '◀ ▶ skip · {ok} play/pause',
        ok: ctl('toggle'), adjust: (dir) => ctl(dir > 0 ? 'next' : 'prev')() });
    }
    const out = d.audio?.output || {};
    if (out.volume != null) {
      rows.push({ key: 'vol', icon: 'sound', label: 'Volume', sub: out.muted ? 'Muted' : `${out.volume}%`,
        bar: out.muted ? 0 : Math.min(1, out.volume / 100), hint: '◀ ▶ adjust · {ok} mute',
        ok: async () => { await api.post('/api/audio', { target: 'output', mute: true }); this.after(); },
        adjust: async (dir) => { await api.post('/api/audio', { target: 'output', delta: dir * 5 }); this.after(); } });
    }
    return rows;
  },
  rowSound(d) {
    const nApps = (d.apps_audio || []).length;
    return { key: 'sound', icon: 'sound', label: 'Sound ▸', sub: [d.output?.name, d.audio?.mic?.muted ? 'mic muted' : '', nApps ? `${nApps} app${nApps === 1 ? '' : 's'} playing` : ''].filter(Boolean).join(' · ') || 'Output, microphone, app volume',
      ok: () => this.go('sound') };
  },
  // ---- Social: who's online, calls, your Discord voice channels, screen share
  rowSocial(d) {
    const v = d.voice?.channel;
    return { key: 'social', icon: 'party', label: 'Friends & Party ▸', sub: v ? `In voice: ${v.name}` : 'Who\'s online, calls, voice channels', ok: () => this.go('social') };
  },
  async loadSocial() {
    this.soc = { ...(this.soc || {}), at: Date.now() };
    const [st, df, sf] = await Promise.all([
      api.get('/api/discord/state').catch(() => ({})),
      api.get('/api/discord/friends').catch(() => null),
      api.get('/api/steam/friends').catch(() => null)]);
    this.soc = { st, discord: df, steam: sf, at: Date.now(), loaded: true };
    if (this.open && ['social', 'party', 'friends'].includes(this.page)) { this.rows = this.build(this.data); this.render(); }
  },
  socialAct(path, body, msg) {
    return async () => {
      if (msg) toast(msg, 'voice');
      const r = await call(() => api.post(`/api/discord/${path}`, body || {}));
      setTimeout(() => this.loadSocial(), 400);
      return r;
    };
  },
  buildSocial() {
    const s = this.soc, st = s?.st || {}, v = st.voice;
    if (!s?.loaded) return [{ key: 'loading', icon: 'refresh', label: 'Loading…', sub: '' }];
    const rows = [];
    if (v) {
      rows.push({ key: 'in-voice', icon: 'voice', label: `In Voice: ${v.channel}`, sub: `${v.guild || 'Discord'} · ${st.deaf ? 'Deafened' : st.mute ? 'Muted' : 'Mic on'} · {ok} leave`,
        ok: this.socialAct('leave', {}, `Leaving ${v.channel}…`) });
      rows.push({ key: 'mute', icon: 'mic', label: st.mute ? 'Unmute Microphone' : 'Mute Microphone', sub: '', ok: this.socialAct('mute') });
      rows.push({ key: 'deaf', icon: 'sound', label: st.deaf ? 'Undeafen' : 'Deafen', sub: '', ok: this.socialAct('deaf') });
      rows.push({ key: 'share', icon: 'display', label: st.sharing ? 'Stop Sharing Screen' : 'Share Screen', sub: st.sharing ? 'Live on Discord' : 'Your friends see what\'s on the TV',
        ok: this.socialAct('share', { on: !st.sharing }, st.sharing ? 'Stopping…' : 'Starting screen share…') });
    }
    if (!st.signed_in) {
      rows.push({ key: 'dc-signin', icon: 'voice', label: 'Sign In to Discord', sub: 'Settings › Accounts › Discord', ok: () => { this.close(false); openSettingsFolder('accounts'); } });
    } else {
      const n = (st.saved || []).length;
      rows.push({ key: 'party', icon: 'voice', label: 'Party ▸', sub: n ? `${n} voice channel${n === 1 ? '' : 's'}` : 'Choose voice channels in Social', ok: () => this.go('party') });
    }
    const on = (s.discord || []).length + (s.steam || []).length;
    rows.push({ key: 'friends', icon: 'users', label: 'Friends ▸', sub: on ? `${on} online` : 'Steam and Discord friends online', ok: () => this.go('friends') });
    rows.push(this.rowGo('party', 'Open Social', 'party', 'Everything else, in the menu'));
    return rows;
  },
  buildParty() {
    const s = this.soc, st = s?.st || {}, cur = st.voice;
    if (!s?.loaded) return [{ key: 'loading', icon: 'refresh', label: 'Loading…', sub: '' }];
    const rows = (st.saved || []).map((c) => {
      const here = cur && cur.channel_id === c.id;
      return { key: `ch:${c.id}`, icon: 'voice', label: c.name, sub: [c.guild, here ? 'Joined · {ok} leave' : '{ok} join'].filter(Boolean).join(' · '),
        ok: here ? this.socialAct('leave', {}, `Leaving ${c.name}…`) : this.socialAct('join', { guild_id: c.guild_id, channel_id: c.id }, `Joining ${c.name}…`) };
    });
    if (!rows.length) rows.push({ key: 'none', icon: 'info', label: 'No voice channels chosen', sub: 'Pick them in Settings › Accounts › Discord' });
    return rows;
  },
  buildFriends() {
    const s = this.soc;
    if (!s?.loaded) return [{ key: 'loading', icon: 'refresh', label: 'Loading…', sub: '' }];
    const rows = (s.discord || []).map((f) => ({ key: `df:${f.id}`, icon: 'voice', art: f.avatar || undefined, label: f.name,
      sub: `Discord · ${f.status || 'Online'} · {ok} call`, ok: this.socialAct('call', { id: f.id }, `Calling ${f.name}…`) }));
    for (const f of s.steam || []) {
      rows.push({ key: `sf:${f.id}`, icon: 'game', art: f.avatar || undefined, label: f.name, sub: `Steam · ${f.game ? `Playing ${f.game}` : f.status || 'Online'}` });
    }
    if (!rows.length) rows.push({ key: 'none', icon: 'info', label: 'No friends online', sub: s.discord === null && s.steam === null ? 'Sign in to Discord or set up Steam friends' : 'Nobody\'s online right now' });
    return rows;
  },
  rowsVoice(d) {
    const v = d.voice;
    if (!v?.channel) return [];
    return [{ key: 'voice', icon: 'voice', label: `Voice: ${v.channel.name}`, sub: `${v.channel.guild || 'Discord'} · ${v.deaf ? 'Deafened' : v.mute ? 'Muted' : 'Mic on'}`,
      hint: '{ok} mute', ok: async () => { await call(() => api.post('/api/discord/mute', {})); this.after(); } }];
  },
  rowPerf(d) {
    if (!(d.perf?.available || d.ps5?.available)) return null;
    return { key: 'perf', icon: 'display', label: 'Performance ▸', sub: 'Frame rate and temperature overlays', ok: () => this.go('perf') };
  },
  rowSettings() { return { key: 'settings', icon: 'settings', label: 'Settings', sub: 'Controller, network, everything else', ok: () => { this.close(false); goCat('settings'); } }; },
  rowPower() {
    return { key: 'power', icon: 'power', label: 'Power', sub: 'Turn off or restart', ok: () => Options.show([
      { label: 'Turn Off System', action: async () => { if (await confirmSafe('Turn off the system?')) api.post('/api/power/poweroff'); } },
      { label: 'Restart System', action: async () => { if (await confirmSafe('Restart the system?')) api.post('/api/power/reboot'); } },
    ]) };
  },

  // ---- Trophies: the running game's list
  async loadTrophies() {
    this.troph = null;
    try { this.troph = await api.get('/api/quick/trophies'); } catch (e) { this.troph = { note: e.message }; }
    if (this.open && this.page === 'trophies') { this.rows = this.build(this.data); this.render(); }
  },
  buildTrophies() {
    const t = this.troph;
    if (!t) return [{ key: 'loading', icon: 'refresh', label: 'Loading…', sub: '' }];
    const rows = [];
    if (t.total) {
      rows.push({ key: 'sum', icon: 'trophy', label: `${t.earned} of ${t.total} unlocked`, sub: [t.game, t.console, t.points ? `${t.points} points` : ''].filter(Boolean).join(' · '), bar: t.earned / t.total });
      for (const [i, a] of (t.achievements || []).entries()) {
        rows.push({ key: `a:${i}`, icon: a.earned ? 'trophy' : 'info', art: a.icon || undefined, label: a.title,
          sub: [a.earned ? `Unlocked ${a.when}${a.hardcore ? ' · hardcore' : ''}` : 'Locked', a.points ? `${a.points} pts` : '', a.desc].filter(Boolean).join(' · '),
          ok: () => message(`${a.title}\n\n${a.desc || ''}\n\n${a.earned ? `Unlocked ${a.when}` : 'Not unlocked yet'}`, t.game) });
      }
    } else rows.push({ key: 'none', icon: 'info', label: t.game ? `${t.game}` : 'No game running', sub: t.note || 'No trophies to show' });
    rows.push(this.rowAllTrophies());
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
    const CORNERS = ['top-right', 'top-left', 'bottom-left', 'bottom-right'], SIZES = ['auto', 'small', 'medium', 'large', 'huge'];
    const SIZE_NAMES = { auto: 'Automatic (fits the screen)', small: 'Small', medium: 'Medium', large: 'Large', huge: 'Huge' };
    const cyc = (list, cur, dir) => list[(Math.max(0, list.indexOf(cur)) + dir + list.length) % list.length];
    const where = (c) => c.replace('-', ' ').replace(/^./, (x) => x.toUpperCase());
    if (p.available) {
      rows.push({ key: 'corner', icon: 'display', label: 'Frame Rate Position', sub: where(p.corner), hint: '◀ ▶ move',
        adjust: async (dir) => { await call(() => api.post('/api/perf/corner', { corner: cyc(CORNERS, p.corner, dir) })); after(); } });
      rows.push({ key: 'size', icon: 'display', label: 'Frame Rate Size', sub: `${SIZE_NAMES[p.size] || p.size}${p.font_size ? ` · ${p.font_size} px` : ''}`, hint: '◀ ▶ size',
        adjust: async (dir) => { await call(() => api.post('/api/perf/size', { size: cyc(SIZES, p.size, dir) })); after(); } });
    }
    if (d.ps5?.available) {
      const hc = d.ps5.hud_corner || 'top-left', hs = d.ps5.hud_size || 'auto';
      rows.push({ key: 'hud', icon: 'display', label: 'Temperature Overlay', sub: d.ps5.hud ? 'On' : 'Off', hint: '{ok} on/off',
        ok: async () => { await call(() => api.post('/api/ps5/hud', { on: !d.ps5.hud })); after(); } });
      rows.push({ key: 'hud-corner', icon: 'display', label: 'Temperature Position', sub: where(hc), hint: '◀ ▶ move',
        adjust: async (dir) => { await call(() => api.post('/api/ps5/hud', { corner: cyc(CORNERS, hc, dir) })); after(); } });
      rows.push({ key: 'hud-size', icon: 'display', label: 'Temperature Size', sub: SIZE_NAMES[hs] || hs, hint: '◀ ▶ size',
        adjust: async (dir) => { await call(() => api.post('/api/ps5/hud', { size: cyc(SIZES, hs, dir) })); after(); } });
    }
    return rows;
  },

  goSettings(id) { this.close(false); openSettingsFolder(id); },

  // The Guide's tabs (a look with quickTabs): LB / RB walk them; Home is where it opens
  tabs() {
    return [['games', 'game', 'Games & Apps'], ['media', 'music', 'Media'], ['main', 'users', 'Home'],
      ['social', 'party', 'Social'], ['settings', 'settings', 'Settings']];
  },
  bumper(dir) {
    if (!Shell.active?.quickTabs || Options.open) return false;
    const t = this.tabs();
    const cur = this.isTab(this.page) ? this.page : (this.parent || 'main');
    const i = Math.max(0, t.findIndex(([p]) => p === cur));
    this.backTo = null;
    this.go(t[(i + dir + t.length) % t.length][0]);
    return true;
  },

  render() {
    if (Shell.active?.renderQuick?.(this)) return;     // a look that draws its own (the 360 Guide)
    const d = this.data || {};
    $('#quick .q-title').textContent = ({ sound: 'Sound', perf: 'Performance', trophies: 'Trophies', social: 'Friends & Party', party: 'Party', friends: 'Friends' })[this.page] || (d.app ? d.app.title : 'Crossbar');
    $('#quick .q-rows').innerHTML = this.rows.map((r, i) => `
      <div class="q-row ${i === this.sel ? 'on' : ''}">
        <div class="q-ico">${r.art ? `<div class="q-art" style="background-image:url('${esc(r.art)}')"></div>` : icon(r.icon)}</div>
        <div class="q-txt">
          <div class="q-label">${esc(r.label)}</div>
          <div class="q-sub">${esc(gl(r.sub || ''))}</div>
          ${r.bar != null ? `<div class="q-bar"><i style="width:${(r.bar * 100).toFixed(1)}%"></i></div>` : ''}
        </div>
        ${r.hint && i === this.sel ? `<div class="q-hint">${esc(gl(r.hint))}</div>` : ''}
      </div>`).join('');
    $('#quick .q-row.on')?.scrollIntoView({ block: 'nearest' });
    clearTimeout(this.mq);
    this.mq = setTimeout(() => $('#quick .q-row.on')?.querySelectorAll('.q-label, .q-sub').forEach((e) => Marquee.set(e)), 450);
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
    } else if (a === 'back' && !this.isTab(this.page)) {
      this.back();
    } else if (a === 'back' || a === 'opt') {
      this.close(true);
    }
  },
};
