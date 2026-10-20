'use strict';
// IPTV (Xtream): Live TV under TV & Video Services, Movies + TV Shows under Video.
// What shows up is chosen in Settings › Media › IPTV.

const IPTV_KIND = { live: 'Live TV', vod: 'Movies', series: 'TV Shows' };
const qs = (o) => Object.entries(o).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');

// art: the poster / channel logo, remembered with what you watched (Video's and TV's big tile)
async function iptvPlay(body, label, art) {
  const r = await call(() => api.post('/api/iptv/play', { ...body, title: label, art: art || '' }));
  if (r) setTimeout(loadState, 1500);
  if (r) toast(`Playing ${r.title || label}`, 'play');
}

function iptvSetupItem(kind) {
  return { key: `iptv-setup-${kind}`, label: `Choose ${IPTV_KIND[kind]} Categories`, icon: 'settings',
    sub: 'Pick what shows here in Settings › Media › IPTV', action: () => openIptvSettings(kind) };
}

function iptvTopFolder(kind) {
  const icon = { live: 'tv', vod: 'video', series: 'video' }[kind];
  return {
    key: `iptv:${kind}`, label: IPTV_KIND[kind], icon, sub: 'IPTV',
    children: async () => {
      const cats = await api.get(`/api/iptv/categories?${qs({ kind, shown: 1 })}`);
      if (!cats.length) return [iptvSetupItem(kind)];
      return cats.map((c) => ({ key: `cat:${c.id}`, label: c.name, icon: 'folder', children: () => iptvItems(kind, c) }));
    },
  };
}

// Big on-demand categories (thousands of titles, each with a poster) are shown a page at a time.
const IPTV_PAGE = 60;
function iptvPaged(list, make, start = 0) {
  const out = list.slice(start, start + IPTV_PAGE).map(make);
  if (list.length > start + IPTV_PAGE) {
    const next = Math.min(list.length, start + 2 * IPTV_PAGE);
    out.push({ key: `more:${start}`, label: `More… (${start + IPTV_PAGE + 1}–${next} of ${list.length})`, icon: 'folder',
      children: async () => iptvPaged(list, make, start + IPTV_PAGE) });
  }
  return out;
}

async function iptvItems(kind, cat) {
  const list = await api.get(`/api/iptv/items?${qs({ kind, cat: cat.id })}`);
  if (!list.length) return [{ key: 'none', label: 'Nothing here', icon: 'info' }];
  if (kind === 'series') {
    return iptvPaged(list, (s) => ({ key: `s:${s.id}`, label: s.name, art: s.icon || '', artTitle: s.name, artShape: 'poster',
      sub: [s.year, s.rating && `★ ${s.rating}`].filter(Boolean).join(' · '),
      children: async () => {
        const info = await api.get(`/api/iptv/series?${qs({ id: s.id })}`);
        if (!info.seasons.length) return [{ key: 'none', label: 'No episodes', icon: 'info' }];
        return info.seasons.map((se) => ({ key: `se:${se.season}`, label: `Season ${se.season}`, icon: 'folder', sub: `${se.episodes.length} episodes`,
          children: async () => se.episodes.map((e) => ({ key: `e:${e.id}`, label: `${e.num}. ${e.title}`, icon: 'play', sub: e.plot,
            action: () => iptvPlay({ kind: 'episode', series: s.id, id: e.id }, `${s.name} · ${e.title}`, s.icon) })) }));
      } }));
  }
  const make = (it) => ({
    key: `i:${it.id}`, label: kind === 'live' && it.num ? `${it.num}  ${it.name}` : it.name,
    ...(it.icon ? { art: it.icon, artTitle: it.name, ...(kind === 'live' ? {} : { artShape: 'poster' }) } : { icon: kind === 'live' ? 'tv' : 'video' }),
    sub: kind === 'live' ? '{ok} watch · {prev}/{next} change channel' : (it.rating ? `★ ${it.rating}` : ''),
    action: () => iptvPlay({ kind, cat: cat.id, id: it.id }, it.name, it.icon),
    options: kind === 'live' ? [{ label: 'Watch', action: () => iptvPlay({ kind, cat: cat.id, id: it.id }, it.name) },
      { label: 'Hide This Channel', action: async () => { await call(() => api.post('/api/iptv/hide', { id: it.id, on: true }), `Hid ${it.name}`); reloadFolder(); } }] : undefined,
  });
  return kind === 'live' ? list.map(make) : iptvPaged(list, make);
}

// ---- Settings › Media › IPTV ------------------------------------------------
async function iptvLogin() {
  const st = S.state.iptv || {};
  const r = await Dialog.ask({ title: 'IPTV Sign In (Xtream Codes)', buttons: ['Sign In', 'Cancel'],
    body: 'Use the details your IPTV provider gave you for “Xtream Codes API”.',
    fields: [{ key: 'server', label: 'Server URL (e.g. http://provider.tv:8080)', value: st.server || '' },
             { key: 'username', label: 'Username', value: st.username || '' },
             { key: 'password', label: 'Password', secret: true }] });
  if (r.button !== 0) return;
  await call(() => api.post('/api/iptv/login', r.values), 'Signing in to IPTV…');
  pollJobs();
}

function categoryToggles(kind) {
  return {
    key: `iptv-cats-${kind}`, label: `${IPTV_KIND[kind]} Categories`, icon: 'folder',
    sub: `${(S.state.iptv?.shown || {})[kind] || 0} shown — choose which appear in ${kind === 'live' ? 'TV & Video Services' : 'Video'}`,
    children: async () => {
      const cats = await api.get(`/api/iptv/categories?${qs({ kind })}`);
      return cats.map((c) => ({ key: `t:${c.id}`, label: c.name, icon: c.shown ? 'check' : 'folder', sub: c.shown ? 'Shown — {ok} to hide' : 'Hidden — {ok} to show',
        action: async () => { await api.post('/api/iptv/show', { kind, cat: c.id, on: !c.shown }); await loadState(); reloadFolder(); },
        ...(kind === 'live' && c.shown ? { options: [{ label: 'Choose Channels…', action: () => openFolder(channelToggles(c)) }] } : {}) }));
    },
  };
}

function channelToggles(cat) {
  return { key: `ch-${cat.id}`, label: cat.name, icon: 'tv',
    children: async () => (await api.get(`/api/iptv/items?${qs({ kind: 'live', cat: cat.id, all: 1 })}`)).map((it) => ({
      key: `c:${it.id}`, label: it.name, icon: it.hidden ? 'tv' : 'check', sub: it.hidden ? 'Hidden — {ok} to show' : 'Shown — {ok} to hide',
      action: async () => { await api.post('/api/iptv/hide', { id: it.id, on: !it.hidden }); reloadFolder(); } })) };
}

function iptvSettingsFolder() {
  return {
    key: 'iptv', label: 'IPTV', icon: 'tv', sub: S.state.iptv?.linked ? `Signed in · ${S.state.iptv.username}` : 'Xtream Codes sign-in',
    children: async () => {
      const st = await api.get('/api/iptv/status');
      if (!st.linked) return [{ key: 'login', label: 'Sign In', icon: 'account', sub: 'Server, username and password from your provider', action: iptvLogin }];
      return [
        { key: 'acct', label: 'Account', icon: 'account', sub: `${st.username} · ${st.server}${st.expires ? ' · expires ' + st.expires : ''}`,
          action: () => Options.show([{ label: 'Refresh Channel List', action: async () => { await call(() => api.post('/api/iptv/refresh'), 'Channel list will reload'); } },
                                      { label: 'Sign In Again', action: iptvLogin },
                                      { label: 'Sign Out', action: async () => { if (await confirmBox('Sign out of IPTV?')) { await call(() => api.post('/api/iptv/logout')); await loadState(); reloadFolder(); } } }]) },
        categoryToggles('live'), categoryToggles('vod'), categoryToggles('series'),
      ];
    },
  };
}

function openIptvSettings(kind) {
  openSettingsFolder('media');
  setTimeout(() => openFolder(S.state.iptv?.linked ? categoryToggles(kind) : iptvSettingsFolder()), 400);
}
