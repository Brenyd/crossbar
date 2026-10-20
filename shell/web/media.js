'use strict';
// Photo, Music (+ Spotify), Video, TV and Network categories, and the photo viewer.

const q = (o) => Object.entries(o).map(([k, v]) => `${k}=${encodeURIComponent(v ?? '')}`).join('&');
const thumb = (path) => `/api/thumb?${q({ path })}`;
const fmtTime = (t) => {
  t = Math.max(0, Math.floor(t || 0));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = String(t % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
};
const KIND_NAME = { music: 'Music', video: 'Video', photo: 'Photo' };

// ---------------------------------------------------------------- photo viewer
const Viewer = {
  open: false, list: [], i: 0, show: null,
  start(list, i, slideshow = false) {
    this.list = list; this.i = i; this.open = true;
    $('#viewer').hidden = false;
    this.draw();
    if (slideshow) this.toggleShow(); else this.stopShow();
    Sfx.ok();
  },
  draw() {
    const f = this.list[this.i];
    const img = $('#viewer img');
    img.classList.add('fade');
    const next = new Image();
    next.onload = () => { img.src = next.src; img.classList.remove('fade'); };
    next.src = `/api/file?${q({ path: f.path })}`;
    const pre = this.list[this.i + 1];
    if (pre) new Image().src = `/api/file?${q({ path: pre.path })}`;
    $('#viewer .v-cap').textContent = f.name;
    $('#viewer .v-count').textContent = `${this.i + 1} / ${this.list.length}${this.show ? ' · Slideshow' : ''}`;
  },
  go(d) { this.i = (this.i + d + this.list.length) % this.list.length; this.draw(); Sfx.move(); },
  toggleShow() {
    if (this.show) return this.stopShow();
    this.show = setInterval(() => this.go(1), 5000);
    this.draw();
  },
  stopShow() { clearInterval(this.show); this.show = null; if (this.open) this.draw(); },
  close() { this.stopShow(); this.open = false; $('#viewer').hidden = true; Sfx.back(); },
  handle(a) {
    if (a === 'left' || a === 'up') this.go(-1);
    else if (a === 'right' || a === 'down') this.go(1);
    else if (a === 'ok') { this.toggleShow(); Sfx.ok(); }
    else if (a === 'back') this.close();
    else if (a === 'opt') $('#viewer').classList.toggle('bare');
  },
};

// ---------------------------------------------------------------- local media
function fileItem(kind, f, i, files) {
  const base = { key: `f:${f.path}`, label: f.title || f.name };
  if (kind === 'music') {
    const play = (shuffle) => async () => {
      await call(() => api.post('/api/music/play', { paths: files.map((x) => x.path), index: i }));
      if (shuffle) await api.post('/api/music/control', { action: 'shuffle' });
      refresh('music');
    };
    return { ...base, icon: 'music', sub: [f.artist, f.album].filter(Boolean).join(' · ') || (f.length ? fmtTime(f.length) : ''),
      action: play(false),
      options: [{ label: 'Play', action: play(false) }, { label: 'Shuffle Play', action: play(true) },
                { label: 'Information', action: () => message([f.title || f.name, f.artist, f.album, f.length && fmtTime(f.length), f.path].filter(Boolean).join('\n'), 'Information') }] };
  }
  if (kind === 'video') {
    const play = async () => { const r = await call(() => api.post('/api/video/play', { paths: files.map((x) => x.path), index: i })); if (r) toast(`Playing ${f.name}`, 'play'); };
    return { ...base, art: thumb(f.path), artTitle: f.name, sub: 'Play', action: play,
      options: [{ label: 'Play', action: play }, { label: 'Information', action: () => message(`${f.name}\n${f.path}`, 'Information') }] };
  }
  return { ...base, art: thumb(f.path), artTitle: f.name, sub: '', action: () => Viewer.start(files, i),
    options: [{ label: 'View', action: () => Viewer.start(files, i) }, { label: 'Slideshow', action: () => Viewer.start(files, i, true) },
              { label: 'Information', action: () => message(`${f.name}\n${f.path}`, 'Information') }] };
}

function dirItem(kind, d) {
  return { key: `d:${d.path}`, label: d.name, icon: 'folder',
    children: () => mediaItems(kind, d.path) };
}

async function mediaItems(kind, path) {
  const r = await api.get(`/api/media/list?${q({ kind, path: path || '' })}`);
  if (!r.exists) {
    return [{ key: 'missing', label: `${KIND_NAME[kind]} folder not found`, icon: 'info', sub: `${r.path} — choose another in Settings`,
              action: () => openSettingsFolder('media') }];
  }
  const items = [...r.dirs.map((d) => dirItem(kind, d)), ...r.files.map((f, i) => fileItem(kind, f, i, r.files))];
  if (kind === 'photo' && r.files.length > 1) {
    items.unshift({ key: 'slideshow', label: 'Slideshow', icon: 'play', sub: `${r.files.length} photos in this folder`, action: () => Viewer.start(r.files, 0, true) });
  }
  return items.length ? items : [{ key: 'empty', label: 'No files', icon: 'info', sub: r.path }];
}

function allItem(kind, label) {
  return { key: `all:${kind}`, label, icon: kind === 'music' ? 'shuffle' : 'folder', sub: 'Everything in your library',
    children: async () => {
      const files = await api.get(`/api/media/scan?${q({ kind })}`);
      return files.length ? files.map((f, i) => fileItem(kind, f, i, files)) : [{ key: 'empty', label: 'Nothing here yet', icon: 'info' }];
    } };
}

// ---------------------------------------------------------------- music now playing
function musicNowItem(m) {
  const ctl = (action) => async () => {
    const r = await api.post('/api/music/control', { action });
    if (['toggle', 'next', 'prev'].includes(action)) nowToast(r?.title, r && !r.paused, r?.artist);
    refresh('music');
  };
  return {
    key: 'now', label: m.title, art: thumb(m.path), artTitle: m.title, badge: m.paused ? 'PAUSED' : 'NOW PLAYING', recent: Date.now() / 1000,
    sub: `${m.artist ? m.artist + ' · ' : ''}${fmtTime(m.position)} / ${fmtTime(m.duration)}  ·  ${m.index + 1} of ${m.count}`,
    progress: m.duration ? m.position / m.duration : null,
    action: ctl('toggle'),
    options: [
      { label: m.paused ? 'Play' : 'Pause', action: ctl('toggle') },
      { label: 'Next Track', action: ctl('next') },
      { label: 'Previous Track', action: ctl('prev') },
      { label: `Shuffle: ${m.shuffle ? 'On' : 'Off'}`, action: ctl('shuffle') },
      { label: `Repeat: ${m.repeat ? 'On' : 'Off'}`, action: ctl('repeat') },
      { label: 'Stop', action: ctl('stop') },
    ],
  };
}

// ---------------------------------------------------------------- Spotify
function spotifyNowItem(n, key = 'sp-now') {
  const ctl = (action) => async () => {
    const r = await call(() => api.post('/api/spotify/control', { action }));
    if (r && ['toggle', 'next', 'prev'].includes(action)) nowToast(r.now?.name, r.now?.playing, r.now?.artist);
    setTimeout(reloadOrRefresh, 400);
  };
  const opts = [
    { label: n.playing ? 'Pause' : 'Play', action: ctl('toggle') },
    { label: 'Next Track', action: ctl('next') },
    { label: 'Previous Track', action: ctl('prev') },
    { label: `Shuffle: ${n.shuffle ? 'On' : 'Off'}`, action: ctl('shuffle') },
    { label: `Repeat: ${n.repeat !== 'off' ? 'On' : 'Off'}`, action: ctl('repeat') },
  ];
  if (!n.here) opts.unshift({ label: 'Play on Crossbar', action: spotifyTransfer });
  if (n.lost) opts.splice(0, opts.length, { label: 'Stop', action: ctl('toggle') }, { label: 'Reconnect (keeps playing)', action: spotifyTransfer });
  return { key, label: n.name, art: n.art || '', artTitle: n.name, badge: 'SPOTIFY',
    sub: `${n.artist} · ${fmtTime(n.position)} / ${fmtTime(n.duration)}${n.here ? '' : ` · on ${n.device}`}${n.lost ? ' · Spotify lost the speaker: {menu} to reconnect' : n.playing ? '' : ' · Paused'}`,
    progress: n.duration ? n.position / n.duration : null, action: ctl('toggle'), options: opts };
}
function reloadOrRefresh() { if (S.stack.length) reloadFolder(); else refresh('music'); }
async function spotifyTransfer() { if (await call(() => api.post('/api/spotify/transfer'))) toast('Playing on Crossbar', 'spotify'); }
async function spotifyPlay(body, label) {
  const r = await call(() => api.post('/api/spotify/play', body));
  if (r) { toast(`Spotify: ${label}`, 'spotify'); setTimeout(reloadOrRefresh, 800); }
}

async function spotifySetup() {
  const st = S.state.spotify;
  if (!st.installed) return message('Spotify needs librespot, which is included in the Crossbar ISO.\nInstall it with: sudo pacman -S librespot', 'Spotify');
  const intro = 'One-time setup (Spotify requires it, and Premium):\n' +
    '1. On any device, open developer.spotify.com/dashboard and create an app.\n' +
    '2. Redirect URI: http://127.0.0.1:7777/spotify/callback — tick "Web API".\n' +
    '3. Copy the Client ID into the box below.';
  const r = await Dialog.ask({ title: 'Set Up Spotify', body: intro, buttons: ['Sign In', 'Cancel'],
    fields: [{ key: 'client_id', label: 'Client ID', value: '' }] });
  if (r.button !== 0) return;
  if (r.values.client_id.trim()) S.state = await api.post('/api/spotify/config', { client_id: r.values.client_id });
  if (!S.state.spotify.client_id) return toast('A Client ID is needed', 'info');
  toast('A Spotify sign-in window will open. Press Home when you\'re done.', 'spotify');
  await call(() => api.post('/api/spotify/login'));
  pollJobs();
}

function trackItems(tracks, playBody) {
  return tracks.map((t, i) => ({ key: `t:${t.uri}:${i}`, label: t.name, art: t.art || '', artTitle: t.name,
    sub: [t.artist, t.album].filter(Boolean).join(' · '), action: () => spotifyPlay(playBody(i), t.name) }));
}

function spotifyFolder() {
  return {
    key: 'spotify', label: 'Spotify', icon: 'spotify', live: true,
    sub: S.state.spotify.linked ? 'Your playlists and Liked Songs' : 'Set up to play Spotify here',
    options: S.state.spotify.linked ? [{ label: 'Restart Speaker', action: () => call(() => api.post('/api/spotify/restart'), 'Spotify speaker restarted') },
      { label: 'Sign Out', action: async () => {
      if (await confirmBox('Sign out of Spotify on this console?')) { S.state = await api.post('/api/spotify/logout'); refresh('music'); }
    } }] : [{ label: 'Set Up', action: spotifySetup }],
    children: async () => {
      const st = S.state.spotify;
      if (!st.linked) {
        return [{ key: 'setup', label: 'Set Up Spotify', icon: 'spotify', sub: 'Needs Premium and a free developer Client ID', action: spotifySetup }];
      }
      const items = [];
      const now = await api.get('/api/spotify/now').catch(() => null);
      if (now) items.push(spotifyNowItem(now));
      if (!now || !now.here) items.push({ key: 'transfer', label: 'Play on Crossbar', icon: 'sound', sub: 'Move what you were playing to this console', action: spotifyTransfer });
      items.push({ key: 'liked', label: 'Liked Songs', icon: 'music', children: async () => {
        const tracks = await api.get('/api/spotify/liked');
        return trackItems(tracks, (i) => ({ uris: tracks.map((t) => t.uri), offset: i }));
      } });
      items.push({ key: 'playlists', label: 'Playlists', icon: 'folder', children: async () => {
        const pls = await api.get('/api/spotify/playlists');
        return pls.map((p) => ({ key: `pl:${p.id}`, label: p.name, art: p.art || '', artTitle: p.name,
          sub: `${p.total ? p.total + ' tracks · ' : ''}${p.owner}`,
          action: () => spotifyPlay({ context_uri: p.uri }, p.name),
          options: [{ label: 'Play', action: () => spotifyPlay({ context_uri: p.uri }, p.name) },
                    { label: 'Shuffle Play', action: () => spotifyPlay({ context_uri: p.uri, shuffle: true }, p.name) },
                    { label: 'Show Tracks', action: () => openFolder({ key: `plt:${p.id}`, label: p.name, icon: 'spotify', children: async () => {
                      const tracks = await api.get(`/api/spotify/playlist?${q({ id: p.id })}`);
                      return trackItems(tracks, (i) => ({ context_uri: p.uri, offset: i }));
                    } }) }] }));
      } });
      items.push({ key: 'search', label: 'Search', icon: 'search', sub: 'Songs, albums and playlists', action: async () => {
        const r = await Dialog.ask({ title: 'Search Spotify', fields: [{ key: 'q', label: 'Search' }], buttons: ['Search', 'Cancel'] });
        if (r.button !== 0 || !r.values.q.trim()) return;
        openFolder({ key: 'sp-search', label: r.values.q, icon: 'search', children: async () => {
          const res = await api.get(`/api/spotify/search?${q({ q: r.values.q })}`);
          return res.map((x, i) => ({ key: `s:${x.uri}`, label: x.name, art: x.art || '', artTitle: x.name, badge: x.kind.toUpperCase(),
            sub: x.artist, action: () => spotifyPlay(x.kind === 'track' ? { uris: [x.uri] } : { context_uri: x.uri }, x.name) }));
        } });
      } });
      return items;
    },
  };
}

// ---------------------------------------------------------------- categories
CATS.push(
  {
    id: 'photo', label: 'Photo', icon: 'photo',
    async load() { return mediaItems('photo'); },
  },
  {
    id: 'music', label: 'Music', icon: 'music', live: true,
    async load() {
      const items = [];
      const m = await api.get('/api/music/state').catch(() => null);
      if (m) items.push(musicNowItem(m));
      if (S.state.spotify.linked) {
        const n = await api.get('/api/spotify/now').catch(() => null);
        if (n && (n.playing || n.here)) items.push(spotifyNowItem(n, 'sp-now-root'));
      }
      items.push(spotifyFolder());
      items.push(allItem('music', 'All Songs'));
      return items.concat(await mediaItems('music'));
    },
  },
  {
    id: 'video', label: 'Video', icon: 'video', live: true,
    async load() {
      const items = [];
      for (const w of (S.state.windows || []).filter((w) => w.app === 'crossbar-player')) {
        items.push({ key: `vw:${w.con_id}`, label: `Return to ${w.title}`, icon: 'play', sub: 'Now playing',
          action: () => api.post('/api/window/focus', { con_id: w.con_id }) });
      }
      // the last video you played, to carry on with (the Dashboard's big tile)
      const rv = S.state.recent_video;
      if (rv) {
        const play = async () => { if (await call(() => api.post('/api/video/play', { paths: [rv.path], index: 0 }))) toast(`Playing ${rv.title}`, 'play'); };
        items.push({ key: 'recent-video', label: rv.title, art: thumb(rv.path), artTitle: rv.title, recent: rv.at, badge: 'CONTINUE',
          sub: 'Continue watching', action: play, options: [{ label: 'Play', action: play }, { label: 'Information', action: () => message(`${rv.title}\n${rv.path}`, 'Information') }] });
      }
      if (S.state.iptv?.linked) items.push(iptvTopFolder('vod'), iptvTopFolder('series'));
      items.push(allItem('video', 'All Videos'));
      return items.concat(await mediaItems('video'));
    },
  },
  {
    id: 'tv', label: 'TV & Video Services', icon: 'tv',
    async load() {
      const items = S.state.tv.map((t, i) => ({
        key: `tv:${t.url}`, label: t.name, icon: 'tv', sub: t.tv_ui ? 'TV interface — controller ready' : t.url.replace(/^https?:\/\//, ''),
        action: () => call(() => api.post('/api/tv/open', { index: i }), `Opening ${t.name} full screen — Guide/PS or Home for the Quick Menu`),
        options: [{ label: 'Open', action: () => call(() => api.post('/api/tv/open', { index: i })) },
                  { label: 'Remove', action: async () => { if (await confirmBox(`Remove ${t.name}?`)) { S.state = await api.post('/api/tv/remove', { index: i }); refresh('tv'); } } }],
      }));
      if (S.state.iptv?.linked) items.unshift(iptvTopFolder('live'));
      else items.push({ key: 'iptv-in', label: 'IPTV', icon: 'tv', sub: 'Sign in with Xtream Codes to watch live TV here', action: () => openIptvSettings('live') });
      items.push({ key: 'browser', label: 'Internet Browser', icon: 'browser', sub: 'Made for the controller · Y in the browser for its menu',
        action: () => call(() => api.post('/api/browser/open', {}), 'Opening the browser — Y for its menu, Select + Start for the Quick Menu') });
      items.push({ key: 'add', label: 'Add Service…', icon: 'add', sub: 'Jellyfin, Plex, Crunchyroll — any web app', action: async () => {
        const r = await Dialog.ask({ title: 'Add Service', buttons: ['Add', 'Cancel'],
          fields: [{ key: 'name', label: 'Name' }, { key: 'url', label: 'Address (e.g. http://192.168.1.10:8096 for Jellyfin)' }] });
        if (r.button === 0 && r.values.url.trim()) { S.state = await api.post('/api/tv/add', r.values); refresh('tv'); }
      } });
      return items;
    },
  },
);

async function showNetworkStatus() {
  const n = await api.get('/api/network');
  if (!n.available) return message('Network status needs NetworkManager.', 'Connection Status');
  const lines = n.devices.map((d) => `${d.type === 'wifi' ? 'Wi-Fi' : 'Wired'} (${d.device}): ${d.state}${d.connection ? ' · ' + d.connection : ''}${d.ip ? ' · ' + d.ip : ''}`);
  message([`Internet: ${n.connectivity === 'full' ? 'Connected' : n.connectivity || 'Unknown'}`, ...lines].join('\n'), 'Connection Status');
}
