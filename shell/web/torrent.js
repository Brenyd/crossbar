'use strict';
// Apps › Torrents: search (qBittorrent search plugins), transfers, adding links / files, plugins
// (official and community, with sign-in), and the settings that matter, all with a controller.

const tSize = (n) => (n == null || n < 0 ? '?' : n >= 1e12 ? `${(n / 1e12).toFixed(2)} TB` : n >= 1e9 ? `${(n / 1e9).toFixed(2)} GB`
  : n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n >= 1e3 ? `${(n / 1e3).toFixed(0)} kB` : `${n} B`);
const tRate = (n) => `${tSize(n || 0)}/s`;
const tEta = (s) => (!s || s >= 8640000 ? '' : s >= 86400 ? `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`
  : s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m` : `${Math.max(1, Math.floor(s / 60))}m`);
const tPost = (path, body, ok) => call(() => api.post(`/api/torrent/${path}`, body || {}), ok);

// ---- transfers ------------------------------------------------------------------------------------
function torrentRow(t) {
  const act = (what, extra = {}, ok) => async () => { if (await tPost('action', { hashes: [t.hash], what, ...extra }, ok)) reloadFolder(); };
  const bits = [t.state_name];
  if (!t.done) bits.push(`${(t.progress * 100).toFixed(1)}%`);
  if (t.dlspeed) bits.push(`↓ ${tRate(t.dlspeed)}`);
  if (t.upspeed) bits.push(`↑ ${tRate(t.upspeed)}`);
  if (!t.done && tEta(t.eta)) bits.push(`${tEta(t.eta)} left`);
  bits.push(tSize(t.size));
  if (t.done) bits.push(`ratio ${t.ratio}`);
  const opts = [
    { label: t.paused ? 'Resume' : 'Pause', action: act(t.paused ? 'resume' : 'pause') },
    { label: 'Files…', action: () => openFolder(torrentFilesFolder(t)) },
    { label: t.sequential ? 'Download in Any Order' : 'Download in Order (to watch while it downloads)', action: act('sequential', {}, 'Changed') },
    { label: t.forced ? 'Stop Forcing' : 'Force Start (skip the queue)', action: act('force', { on: !t.forced }) },
    { label: 'Speed Limit…', action: async () => {
      const v = await choose([[0, 'No limit'], [256e3, '256 kB/s'], [1e6, '1 MB/s'], [2.5e6, '2.5 MB/s'], [5e6, '5 MB/s'], [10e6, '10 MB/s']]);
      if (v !== null) act('limit', { dl: v, up: v ? Math.max(64e3, v / 4) : 0 }, v ? `Limited to ${tRate(v)}` : 'No limit')();
    } },
    { label: 'Move to Top of Queue', action: act('top') },
    { label: 'Check Files Again', action: act('recheck', {}, 'Checking…') },
    { label: 'Ask Trackers for Peers', action: act('reannounce', {}, 'Asked the trackers') },
    { label: 'Open Folder', action: () => { if (typeof openFilesAt === 'function') openFilesAt(t.save_path); else message(t.save_path, 'Saved in'); } },
    { label: 'Remove (keep files)', action: async () => { if (await confirmBox(`Remove ${t.name}?\nWhat's downloaded stays.`)) act('delete', { files: false }, 'Removed')(); } },
    { label: 'Remove and Delete Files', action: async () => { if (await confirmSafe(`Delete ${t.name} and its files?`)) act('delete', { files: true }, 'Deleted')(); } },
  ];
  return { key: `t:${t.hash}`, label: t.name, icon: t.done ? 'check' : t.paused ? 'power' : 'download', sub: bits.join(' · '),
    progress: t.done ? undefined : t.progress, action: () => Options.show(opts), options: opts };
}

function transfersFolder(filter, label) {
  return { key: `tl:${filter}`, label, icon: 'download', live: true,
    children: async () => {
      const ts = await api.get(`/api/torrent/list?filter=${filter}`);
      if (!ts.length) return [{ key: 'none', label: 'Nothing here', icon: 'info', sub: 'Search, or add a magnet link / .torrent file' }];
      return ts.map(torrentRow);
    } };
}

function torrentFilesFolder(t) {
  return { key: `tf:${t.hash}`, label: 'Files', icon: 'folder', sub: t.name,
    children: async () => {
      const fs = await api.get(`/api/torrent/files?hash=${t.hash}`);
      const set = async (ids, p, ok) => { if (await tPost('fileprio', { hash: t.hash, ids, priority: p }, ok)) reloadFolder(); };
      const rows = fs.map((f) => ({ key: `f:${f.index}`, label: f.name.split('/').pop(), icon: f.priority ? 'check' : 'power',
        sub: `${f.priority ? (f.priority >= 6 ? 'High priority' : 'Downloading') : 'Skipped'} · ${tSize(f.size)} · ${(f.progress * 100).toFixed(0)}%`,
        action: () => set([f.index], f.priority ? 0 : 1, f.priority ? 'Skipped' : 'Downloading'),
        options: [{ label: f.priority ? 'Skip This File' : 'Download This File', action: () => set([f.index], f.priority ? 0 : 1) },
          { label: 'High Priority', action: () => set([f.index], 7, 'High priority') }] }));
      if (fs.length > 1) rows.unshift({ key: 'all', label: 'Download Everything', icon: 'check', action: () => set(fs.map((f) => f.index), 1, 'Downloading all files') });
      return rows;
    } };
}

// ---- adding ---------------------------------------------------------------------------------------
async function torrentAddMagnet() {
  const r = await Dialog.ask({ title: 'Add a Magnet Link', buttons: ['Add', 'Cancel'], fields: [{ key: 'u', label: 'magnet:?xt=… or a link to a .torrent' }],
    body: 'Tip: paste with the keyboard, or use Search to skip typing.' });
  if (r.button !== 0 || !r.values.u.trim()) return;
  if (await tPost('add', { urls: [r.values.u.trim()] }, 'Added')) toast('Torrent added', 'download');
}
async function torrentFileBrowse(path) {
  const r = await api.get(`/api/fs?ext=torrent${path ? `&path=${encodeURIComponent(path)}` : ''}`);
  const items = (r.files || []).map((f) => ({ key: `tfile:${f.path}`, label: f.name, icon: 'download', sub: 'Add this torrent',
    action: async () => { if (await tPost('add', { path: f.path }, 'Torrent added')) { while (S.stack.length && S.stack.at(-1).source?.torrentBrowse) S.stack.pop(); render(); } } }));
  for (const d of r.dirs) items.push({ key: `d:${d.path}`, label: d.name, icon: 'folder', torrentBrowse: true, children: () => torrentFileBrowse(d.path) });
  if (!items.length) items.push({ key: 'none', label: 'No .torrent files here', icon: 'info' });
  return items;
}

// ---- search ---------------------------------------------------------------------------------------
const T_CATS = [['all', 'Everything'], ['movies', 'Movies'], ['tv', 'TV'], ['music', 'Music'], ['games', 'Games'], ['anime', 'Anime'],
  ['software', 'Software'], ['books', 'Books']];
async function torrentSearch() {
  const r = await Dialog.ask({ title: 'Search Torrents', buttons: ['Search', 'Cancel'], fields: [{ key: 'q', label: 'What are you looking for?' }] });
  const q = r.button === 0 ? r.values.q.trim() : '';
  if (!q) return;
  const cat = await choose(T_CATS);
  if (!cat) return;
  const s = await tPost('search/start', { pattern: q, category: cat });
  if (!s) return;
  openFolder({ key: `ts:${s.id}`, label: `“${q}”`, icon: 'search', live: true,
    children: async () => {
      const res = await api.get(`/api/torrent/search?id=${s.id}`);
      const rows = res.results.slice(0, 150).map((x, i) => ({ key: `sr:${i}:${x.url.slice(-40)}`, label: x.name, icon: 'download',
        badge: (x.engine || '').toUpperCase().slice(0, 14), sub: `${tSize(x.size)} · ${x.seeds >= 0 ? x.seeds : '?'} seeds · ${x.peers >= 0 ? x.peers : '?'} peers`,
        action: async () => { if (await tPost('search/download', { url: x.url, engine: x.engine }, `Downloading ${x.name}`)) pollJobs(); },
        options: [{ label: 'Download', action: () => tPost('search/download', { url: x.url, engine: x.engine }, `Downloading ${x.name}`) },
          ...(x.page ? [{ label: 'Open Its Page', action: () => (typeof openBrowser === 'function' ? openBrowser(x.page) : message(x.page, 'Page')) }] : [])] }));
      rows.unshift({ key: 'state', label: res.running ? `Searching… ${res.total} found so far` : `${res.total} found`, icon: res.running ? 'refresh' : 'search',
        sub: 'Most seeds first · {ok} on a result downloads it',
        action: () => tPost('search/stop', { id: s.id }, 'Search stopped') });
      return rows;
    } });
}

// ---- search plugins -------------------------------------------------------------------------------
async function pluginSignIn(name) {
  const fields = await call(() => api.get(`/api/torrent/plugin-login?name=${encodeURIComponent(name)}`));
  if (!fields) return;
  if (!fields.length) return message('This plugin doesn\'t ask for a sign-in in a way Crossbar can fill in.\nSee its help page for how it\'s set up.', name);
  const r = await Dialog.ask({ title: `Sign In: ${name}`, buttons: ['Save', 'Cancel'],
    body: `Saved in the plugin's own settings on this console.${fields.some((f) => f.set) ? '\nLeave a box empty to keep what\'s there.' : ''}`,
    fields: fields.map((f) => ({ key: f.key, label: `${f.label}${f.set ? ' (set)' : ''}`, secret: f.secret })) });
  if (r.button !== 0) return;
  if (await tPost('plugin/login', { name, values: r.values }, `${name}: signed in`)) reloadFolder();
}
async function pluginInstall(url, label, login) {
  toast(`Installing ${label}…`, 'download');
  const p = await tPost('plugin/install', { url });
  if (!p) return;
  toast(`${p.full_name} installed`, 'search');
  if (p.login || login) await pluginSignIn(p.name);
  if (S.stack.length) reloadFolder();
}
function pluginListFolder(key, label, sub, load) {
  return { key, label, icon: 'folder', sub, children: async () => {
    const [list, have] = await Promise.all([load(), api.get('/api/torrent/plugins')]);
    const names = new Set(have.map((p) => p.url));
    return list.map((p) => ({ key: `pl:${p.url}`, label: p.name, icon: names.has(p.url) ? 'check' : 'download',
      badge: p.login ? 'LOGIN' : (p.broken ? 'BROKEN' : ''),
      sub: [names.has(p.url) ? 'Installed' : '', p.version ? `v${p.version}` : '', p.updated, p.comments].filter(Boolean).join(' · ').slice(0, 140),
      action: () => pluginInstall(p.url, p.name, p.login),
      options: [{ label: names.has(p.url) ? 'Install Again (update)' : 'Install', action: () => pluginInstall(p.url, p.name, p.login) },
        ...(p.help ? [{ label: 'Help Page', action: () => (typeof openBrowser === 'function' ? openBrowser(p.help) : message(p.help, p.name)) }] : []),
        ...(p.site ? [{ label: 'Open the Site', action: () => (typeof openBrowser === 'function' ? openBrowser(p.site) : message(p.site, p.name)) }] : [])] }));
  } };
}
const PLUGINS_FOLDER = {
  key: 'tplugins', label: 'Search Plugins', icon: 'search', sub: 'The sites Search looks through',
  children: async () => {
    const have = await api.get('/api/torrent/plugins');
    const rows = have.map((p) => ({ key: `ip:${p.name}`, label: p.full_name, icon: p.enabled ? 'check' : 'power',
      badge: p.login ? 'LOGIN' : '', sub: `${p.enabled ? 'On' : 'Off'} · v${p.version}`,
      action: async () => { if (await tPost('plugin/action', { name: p.name, what: 'enable', enable: !p.enabled }, `${p.full_name} ${p.enabled ? 'off' : 'on'}`)) reloadFolder(); },
      options: [{ label: p.enabled ? 'Turn Off' : 'Turn On', action: async () => { await tPost('plugin/action', { name: p.name, what: 'enable', enable: !p.enabled }); reloadFolder(); } },
        ...(p.login ? [{ label: 'Sign In…', action: () => pluginSignIn(p.name) }] : []),
        { label: 'Remove', action: async () => { if (await confirmBox(`Remove ${p.full_name}?`)) { await tPost('plugin/action', { name: p.name, what: 'remove' }, 'Removed'); reloadFolder(); } } }] }));
    return [
      pluginListFolder('tp-off', 'Get Official Plugins', 'Maintained by the qBittorrent project', () => api.get('/api/torrent/plugins/official')),
      { key: 'tp-un', label: 'Get Community Plugins', icon: 'folder', sub: 'From the qBittorrent wiki list (use at your own risk)',
        children: async () => {
          const all = await api.get('/api/torrent/plugins/unofficial');
          return [pluginListFolder('tp-pub', 'Public Sites', `${all.filter((p) => !p.private).length} plugins`, async () => all.filter((p) => !p.private)),
            pluginListFolder('tp-priv', 'Private Sites (sign-in)', `${all.filter((p) => p.private).length} plugins · you'll be asked for your account`, async () => all.filter((p) => p.private)),
            { key: 'warn', label: 'About Community Plugins', icon: 'info', sub: 'Written by other people',
              action: () => message('These plugins are small Python programs written by the community and listed on the qBittorrent wiki.\nThey run on this console when you search, so only install ones you trust. Sites change: if one stops finding things, update or remove it.', 'Community Plugins') }];
        } },
      { key: 'tp-url', label: 'Install from a Link…', icon: 'add', sub: 'Any plugin .py address',
        action: async () => { const r = await Dialog.ask({ title: 'Install a Plugin', buttons: ['Install', 'Cancel'], fields: [{ key: 'u', label: 'https://….py' }] });
          if (r.button === 0 && r.values.u.trim()) pluginInstall(r.values.u.trim(), 'the plugin', false); } },
      { key: 'tp-up', label: 'Update All', icon: 'refresh', action: () => tPost('plugin/action', { name: 'all', what: 'update' }, 'Updating plugins…') },
      ...rows,
    ];
  },
};

// ---- settings ---------------------------------------------------------------------------------------
async function torrentSettingsSet(body, msg) { if (await tPost('settings', body, msg)) reloadFolder(); }
const speedChoices = [[0, 'No limit'], [500e3, '500 kB/s'], [1e6, '1 MB/s'], [2.5e6, '2.5 MB/s'], [5e6, '5 MB/s'], [10e6, '10 MB/s'], [25e6, '25 MB/s'], [50e6, '50 MB/s']];
function pickSetting(title, key, choices, cur, fmt = (v) => v) {
  return { label: title, sub: fmt(cur), action: async () => {
    const v = await choose(choices.map(([val, l]) => [val, `${check(val === cur)}${l}`]), Math.max(0, choices.findIndex(([val]) => val === cur)));
    if (v !== null) torrentSettingsSet({ [key]: v }, `${title}: ${choices.find(([val]) => val === v)[1]}`);
  } };
}
const TSET_FOLDER = {
  key: 'tsettings', label: 'Settings', icon: 'settings', sub: 'Folder, VPN, speed, seeding, connections',
  children: async () => {
    const s = await api.get('/api/torrent/settings');
    const vpn = await api.get('/api/vpn').catch(() => ({}));
    const lim = (v) => (v ? tRate(v) : 'No limit');
    const tog = (key, label, on, sub) => ({ key, label, icon: on ? 'check' : 'power', sub: `${on ? 'On' : 'Off'}${sub ? ` · ${sub}` : ''}`,
      action: () => torrentSettingsSet({ [key]: !on }, `${label}: ${on ? 'off' : 'on'}`) });
    const group = (key, label, sub, rows) => ({ key, label, icon: 'folder', sub, children: async () => rows.map((r, i) => ({ key: `${key}:${i}`, icon: 'settings', ...r })) });
    const iface = s.current_network_interface || '';
    const addStopKey = 'add_stopped_enabled' in s ? 'add_stopped_enabled' : 'start_paused_enabled';
    return [
      { key: 'save', label: 'Download Folder', icon: 'folder', sub: s.save_path, children: () => torrentFolderPick(null) },
      group('net', 'Network & VPN', s.vpn_only ? 'Only through the VPN' : (iface ? `Bound to ${iface}` : 'Any connection'), [
        { label: 'Only Use the VPN', icon: s.vpn_only ? 'check' : 'power',
          sub: s.vpn_only ? `On · no VPN, no torrent traffic${vpn.configured ? '' : ' (set up a VPN first)'}` : 'Off',
          action: () => torrentSettingsSet({ vpn_only: !s.vpn_only, ...(s.vpn_only ? { current_network_interface: '' } : {}) }, `Only use the VPN: ${s.vpn_only ? 'off' : 'on'}`) },
        { label: 'Network Interface', sub: iface || 'Any', action: async () => {
          const v = await choose([['', `${check(!iface)}Any`], ...s.interfaces.filter((i) => i.value).map((i) => [i.value, `${check(i.value === iface)}${i.name}`])]);
          if (v !== null) torrentSettingsSet({ current_network_interface: v, vpn_only: false }, `Interface: ${v || 'any'}`);
        } },
        { label: 'Use the VPN\'s Forwarded Port', icon: s.use_vpn_port ? 'check' : 'power',
          sub: `${s.use_vpn_port ? 'On' : 'Off'}${vpn.forwarded_port ? ` · VPN port ${vpn.forwarded_port}` : ' · PIA / Proton port forwarding'}`,
          action: () => torrentSettingsSet({ use_vpn_port: !s.use_vpn_port }) },
        { label: 'Listening Port', sub: String(s.listen_port), action: async () => {
          const r = await Dialog.ask({ title: 'Listening Port', buttons: ['Save', 'Random', 'Cancel'], fields: [{ key: 'p', label: '1024–65535', value: String(s.listen_port) }] });
          if (r.button === 1) torrentSettingsSet({ listen_port: 20000 + Math.floor(Math.random() * 40000) }, 'New random port');
          else if (r.button === 0 && /^\d+$/.test(r.values.p) && +r.values.p >= 1024 && +r.values.p <= 65535) torrentSettingsSet({ listen_port: +r.values.p }, `Port ${r.values.p}`);
        } },
        { ...tog('upnp', 'UPnP / NAT-PMP (open the port on your router)', s.upnp), label: 'Open the Port on Your Router (UPnP)' },
      ]),
      group('speed', 'Speed Limits', `↓ ${lim(s.dl_limit)} · ↑ ${lim(s.up_limit)}`, [
        pickSetting('Download Limit', 'dl_limit', speedChoices, s.dl_limit, lim),
        pickSetting('Upload Limit', 'up_limit', speedChoices, s.up_limit, lim),
        pickSetting('Slow Mode Download', 'alt_dl_limit', speedChoices.slice(1), s.alt_dl_limit, lim),
        pickSetting('Slow Mode Upload', 'alt_up_limit', speedChoices.slice(1), s.alt_up_limit, lim),
      ]),
      group('queue', 'Queue', s.queueing_enabled ? `${s.max_active_downloads} downloads at once` : 'Everything at once', [
        { ...tog('queueing_enabled', 'Queue', s.queueing_enabled, 'limit how many run at once'), label: 'Use a Queue' },
        pickSetting('Downloads at Once', 'max_active_downloads', [[1, '1'], [2, '2'], [3, '3'], [5, '5'], [10, '10'], [-1, 'No limit']], s.max_active_downloads, (v) => (v < 0 ? 'No limit' : v)),
        pickSetting('Uploads at Once', 'max_active_uploads', [[1, '1'], [3, '3'], [5, '5'], [10, '10'], [-1, 'No limit']], s.max_active_uploads, (v) => (v < 0 ? 'No limit' : v)),
        pickSetting('Active Torrents at Once', 'max_active_torrents', [[3, '3'], [5, '5'], [10, '10'], [20, '20'], [-1, 'No limit']], s.max_active_torrents, (v) => (v < 0 ? 'No limit' : v)),
      ]),
      group('seed', 'Seeding', s.max_ratio_enabled ? `Stop at ratio ${s.max_ratio}` : 'Seed until removed', [
        pickSetting('Stop Seeding at Ratio', 'max_ratio', [[-1, 'Never'], [0.5, '0.5'], [1, '1.0'], [1.5, '1.5'], [2, '2.0'], [3, '3.0']],
          s.max_ratio_enabled ? s.max_ratio : -1, (v) => (v < 0 ? 'Never' : v)),
        pickSetting('Stop Seeding After', 'max_seeding_time', [[-1, 'Never'], [60, '1 hour'], [360, '6 hours'], [1440, '1 day'], [10080, '1 week']],
          s.max_seeding_time_enabled ? s.max_seeding_time : -1, (v) => (v < 0 ? 'Never' : `${v} minutes`)),
        pickSetting('Then', 'max_ratio_act', [[0, 'Stop it'], [1, 'Remove it (keep files)']], s.max_ratio_act, (v) => (v ? 'Remove it' : 'Stop it')),
      ]),
      group('conn', 'Connections & Privacy', `${s.max_connec} connections · encryption ${['preferred', 'required', 'off'][s.encryption] || ''}`, [
        pickSetting('Connections (total)', 'max_connec', [[100, '100'], [200, '200'], [500, '500'], [1000, '1000']], s.max_connec),
        pickSetting('Connections per Torrent', 'max_connec_per_torrent', [[50, '50'], [100, '100'], [200, '200']], s.max_connec_per_torrent),
        pickSetting('Encryption', 'encryption', [[0, 'Preferred'], [1, 'Required'], [2, 'Off']], s.encryption, (v) => ['Preferred', 'Required', 'Off'][v]),
        tog('anonymous_mode', 'Anonymous Mode', s.anonymous_mode, 'hides client details'),
        tog('dht', 'DHT (find peers without trackers)', s.dht),
        tog('pex', 'Peer Exchange', s.pex),
        tog('lsd', 'Local Peer Discovery', s.lsd),
      ]),
      group('add', 'Adding Torrents', s[addStopKey] ? 'Added paused' : 'Start straight away', [
        tog(addStopKey, 'Add Paused', s[addStopKey], 'check files first'),
        pickSetting('Delete the .torrent File After Adding', 'auto_delete_mode', [[0, 'Never'], [1, 'If added'], [2, 'Always']], s.auto_delete_mode, (v) => ['Never', 'If added', 'Always'][v]),
        tog('incomplete_files_ext', 'Mark Unfinished Files (.!qB)', s.incomplete_files_ext),
      ]),
      { key: 'notify', label: 'Notify When Downloads Finish', icon: s.notify ? 'check' : 'power', sub: s.notify ? 'On' : 'Off', action: () => torrentSettingsSet({ notify: !s.notify }) },
      { key: 'auto', label: 'Keep Seeding in the Background', icon: s.autostart ? 'check' : 'power',
        sub: s.autostart ? 'On · starts with Crossbar' : 'Off · runs once you open Torrents', action: () => torrentSettingsSet({ autostart: !s.autostart }) },
    ];
  },
};
async function torrentFolderPick(path) {
  const r = await api.get(`/api/fs${path ? `?path=${encodeURIComponent(path)}` : ''}`);
  const items = [];
  if (path) items.push({ key: 'use', label: 'Download Here', icon: 'check', sub: path, action: async () => {
    if (await tPost('settings', { save_path: path }, `Downloads go to ${path}`)) { while (S.stack.length && S.stack.at(-1).source?.key !== 'tsettings') S.stack.pop(); reloadFolder(); }
  } });
  for (const d of r.dirs) items.push({ key: `d:${d.path}`, label: d.name, icon: 'folder', children: () => torrentFolderPick(d.path) });
  return items;
}

// ---- the Torrents item (Apps) -----------------------------------------------------------------------
S.torrent = null;
function torrentsItem() {
  const t = S.torrent || {};
  const sub = !t.available && t.available !== undefined ? 'Needs qbittorrent-nox (Update Crossbar installs it)'
    : t.running ? `↓ ${tRate(t.dl)} · ↑ ${tRate(t.up)} · ${t.downloading} downloading${t.vpn_bound ? ' · VPN only' : ''}`
      : 'Search, download and seed';
  return { key: 'torrents', label: 'Torrents', icon: 'download', sub, live: true,
    children: async () => {
      const st = await call(() => api.post('/api/torrent/start'));
      if (!st) return [{ key: 'na', label: 'The torrent engine isn\'t running', icon: 'info', sub: 'Needs qbittorrent-nox: Settings › System › Update Crossbar' }];
      S.torrent = st;
      return [
        { key: 'speed', label: `↓ ${tRate(st.dl)}   ↑ ${tRate(st.up)}`, icon: st.status === 'connected' ? 'network' : 'info',
          sub: `${st.count} torrents · ${st.status === 'connected' ? 'reachable' : st.status === 'firewalled' ? 'firewalled (port not open)' : 'offline'}${st.vpn_bound ? ` · bound to ${st.interface}` : ''}${st.alt_speed ? ' · slow mode' : ''}`,
          options: [{ label: 'Pause Everything', action: () => tPost('action', { hashes: ['all'], what: 'pause' }, 'Everything paused') },
            { label: 'Resume Everything', action: () => tPost('action', { hashes: ['all'], what: 'resume' }, 'Everything resumed') },
            { label: st.alt_speed ? 'Normal Speed' : 'Slow Mode (limits in Settings)', action: () => tPost('altspeed', {}, st.alt_speed ? 'Normal speed' : 'Slow mode') }] },
        { key: 'search', label: 'Search', icon: 'search', sub: 'Through your search plugins', action: torrentSearch },
        transfersFolder('downloading', 'Downloading'),
        transfersFolder('completed', 'Finished & Seeding'),
        transfersFolder('all', 'All Torrents'),
        { key: 'add', label: 'Add a Torrent', icon: 'add', sub: 'Magnet link or .torrent file', children: async () => [
          { key: 'magnet', label: 'Magnet Link…', icon: 'link', action: torrentAddMagnet },
          { key: 'file', label: '.torrent File…', icon: 'folder', torrentBrowse: true, children: () => torrentFileBrowse(null) }] },
        PLUGINS_FOLDER,
        TSET_FOLDER,
        { key: 'tleak', label: 'Leak Tests', icon: 'search', sub: 'What address trackers see, and where DNS goes', children: LEAK_FOLDER.children },
        { key: 'quit', label: 'Stop the Torrent Engine', icon: 'power', sub: 'Stops downloading and seeding until you open Torrents again',
          action: async () => { if (await confirmBox('Stop all downloading and seeding?')) { await tPost('stop', {}, 'Torrent engine stopped'); back(); } } },
      ];
    } };
}
