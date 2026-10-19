'use strict';
// Apps category (open apps + your Flatpaks and AppImages), Store › Install Apps (Flathub browser,
// AppImage installer), and your own XMB folders in any category.

const APP_CATS = [['apps', 'Apps'], ['game', 'Game'], ['tv', 'TV & Video Services'], ['video', 'Video'],
  ['music', 'Music'], ['photo', 'Photo'], ['party', 'Social']];
S.apps = [];
S.ext = [];        // Lutris + Steam's non-Steam games
S.folders = [];
S.tags = {};
S.hidden = {};    // key -> name: games / apps / ROMs you hid from the XMB

async function loadApps() {
  const [a, x] = await Promise.all([api.get('/api/apps').catch(() => []), api.get('/api/extgames').catch(() => [])]);
  S.apps = a; S.ext = x;
}
async function loadFolders() {
  const [f, t, h] = await Promise.all([api.get('/api/xmb/folders').catch(() => []), api.get('/api/xmb/tags').catch(() => ({})),
    api.get('/api/xmb/hidden').catch(() => ({}))]);
  S.folders = f; S.tags = t; S.hidden = h || {};
}

// Options.show as a question: resolves with the picked value (or null on Back)
function choose(list, sel = 0) {
  return new Promise((resolve) => {
    let done = false;
    Options.show(list.map(([value, label]) => ({ label, action: () => { done = true; resolve(value); } })), sel);
    const watch = setInterval(() => { if (!Options.open) { clearInterval(watch); if (!done) resolve(null); } }, 150);
  });
}
const pickCategory = (cur = 'apps') => choose(APP_CATS.map(([id, name]) => [id, `${check(id === cur)}${name}`]), Math.max(0, APP_CATS.findIndex(([id]) => id === cur)));

// the line under an app or game: "Play" where games live, "Start" everywhere else
const verbFor = (cat) => (cat === 'game' ? 'Play' : 'Start');

// ---- installed apps -------------------------------------------------------------------------------
function appItem(a) {
  const custom = a.art && a.art_custom;
  return {
    key: `app:${a.key}`, label: a.name, sub: verbFor(a.category), badge: a.kind === 'flatpak' ? 'FLATPAK' : 'APPIMG',
    ...(custom ? { art: a.art, artTitle: a.name } : { art: a.icon, artTitle: a.name, artShape: 'square' }),
    action: () => openApp(a),
    options: [
      { label: 'Open', action: () => openApp(a) },
      { label: 'Show In…', action: () => moveApp(a) },
      { label: 'Change Artwork…', action: () => changeArtwork({ key: `app:${a.key}`, title: a.name, custom: !!a.art_custom }) },
      { label: 'Uninstall', action: () => uninstallApp(a) },
    ],
  };
}
async function openApp(a) {
  Sfx.ok();
  await call(() => api.post('/api/apps/launch', { key: a.key, name: a.name }));
}
async function moveApp(a) {
  const cat = await pickCategory(a.category);
  if (!cat || cat === a.category) return;
  await call(() => api.post('/api/apps/category', { key: a.key, category: cat }), `${a.name} is now in ${APP_CATS.find(([id]) => id === cat)[1]}`);
  await loadApps(); refreshAll();
}
async function uninstallApp(a) {
  if (!(await confirmBox(`Uninstall ${a.name}?${a.kind === 'appimage' ? '\nThe AppImage file is deleted.' : ''}`))) return;
  await call(() => api.post('/api/apps/uninstall', { key: a.key, name: a.name }), `Removing ${a.name}…`);
}
// Lutris games and Steam's non-Steam games: games like any other (Starting… screen, Quick Menu)
function extItem(g) {
  const play = () => { Sfx.ok(); return call(() => api.post('/api/launch', { provider: g.kind, id: g.launch_id, title: g.name })); };
  return {
    key: g.key, label: g.name, sub: verbFor(g.category), badge: g.tag,
    ...(g.art ? { art: g.art, artTitle: g.name, ...(g.poster ? { artShape: 'poster' } : {}) } : { art: '', artTitle: g.name }),
    action: play,
    options: [
      { label: 'Play', action: play },
      { label: 'Show In…', action: async () => {
        const cat = await pickCategory(g.category);
        if (!cat || cat === g.category) return;
        await call(() => api.post('/api/apps/category', { key: g.key, category: cat }), `${g.name} moved`);
        await loadApps(); refreshAll();
      } },
      { label: 'Change Artwork…', action: () => changeArtwork({ key: g.key, title: g.name, custom: !!g.art_custom }) },
    ],
  };
}
function appsIn(cat) {
  return [...S.ext.filter((g) => g.category === cat).map(extItem), ...S.apps.filter((a) => a.category === cat).map(appItem)];
}

// ---- tags: [STEAM] [GOG] [SNES] [LUTRIS]…, editable on anything that has one ---------------------------------
async function editTag(it) {
  const auto = it.autoBadge ?? it.badge ?? '';
  const r = await Dialog.ask({ title: 'Edit Tag', buttons: ['Save', 'Automatic', 'Cancel'],
    body: `The little label next to ${it.label}. Leave it empty to hide it.`, fields: [{ key: 'text', label: 'Tag', value: it.badge || '' }] });
  if (r.button === 2 || r.button === null) return;
  const text = r.button === 1 ? null : r.values.text.trim().toUpperCase();
  S.tags = await call(() => api.post('/api/xmb/folders/tag', { key: it.key, text })) || S.tags;
  toast(r.button === 1 ? `Tag back to ${auto || 'none'}` : text ? `Tag: ${text}` : 'Tag hidden', 'info');
  for (const c of CATS) refresh(c.id);
  if (S.stack.length) reloadFolder();
}
const TAGGABLE = /^(steam|gog|epic|demo|rom|app|lutris|shortcut):/;
// game-like rows get their tag (yours if you set one), Y › Edit Tag… and Y › Hide;
// the ones you hid are left out (Settings › Games & Emulation › Hidden Games & Apps brings them back)
function decorate(items) {
  return (items || []).filter((it) => !(it && it.key && S.hidden[it.key])).map((it) => {
    if (!it || !it.key || !TAGGABLE.test(it.key)) return it;
    const own = S.tags[it.key];
    const out = { ...it, autoBadge: it.badge || '', badge: own !== undefined ? own : it.badge };
    const opts = [...(it.options || [])];
    if (!opts.some((o) => o.label === 'Edit Tag…')) opts.push({ label: 'Edit Tag…', action: () => editTag(out) });
    if (LAUNCHOPTS.test(it.key) && !opts.some((o) => o.label === 'Launch Options…'))
      opts.push({ label: 'Launch Options…', action: () => openFolder(launchOptionsFolder(out)) });
    if (LAUNCHOPTS.test(it.key) && !opts.some((o) => o.label === 'Windows Components…'))
      opts.push({ label: 'Windows Components…', action: () => openFolder(windowsComponentsFolder(out)) });
    if (!opts.some((o) => o.label === 'Hide')) opts.push({ label: 'Hide', action: () => setHidden(out.key, out.label, true) });
    out.options = opts;
    return out;
  });
}
async function setHidden(key, label, on) {
  const h = await call(() => api.post('/api/xmb/folders/hide', { key, label, on }));
  if (!h) return;
  S.hidden = h;
  toast(on ? `${label} hidden — Settings › Games & Emulation › Hidden Games & Apps brings it back` : `${label} is back`, 'info');
  refreshAll();
}
// Settings › Games & Emulation › Hidden Games & Apps
const HIDDEN_FOLDER = {
  key: 'hidden', label: 'Hidden Games & Apps', icon: 'folder', sub: 'Things you hid with Y › Hide',
  children: async () => {
    S.hidden = await api.get('/api/xmb/hidden').catch(() => S.hidden);
    const keys = Object.keys(S.hidden).sort((a, b) => S.hidden[a].localeCompare(S.hidden[b]));
    if (!keys.length) return [{ key: 'none', label: 'Nothing hidden', icon: 'info', sub: 'Press Y on a game, app or ROM › Hide' }];
    const kind = (k) => ({ app: 'App', rom: 'ROM', lutris: 'Lutris', shortcut: 'Non-Steam game', steam: 'Steam', gog: 'GOG', epic: 'Epic' })[k.split(':')[0]] || 'Game';
    return keys.map((k) => ({ key: `hid:${k}`, label: S.hidden[k], icon: 'game', sub: `${kind(k)} · {ok} show it again`,
      action: async () => { await setHidden(k, S.hidden[k], false); reloadFolder(); },
      options: [{ label: 'Show Again', action: async () => { await setHidden(k, S.hidden[k], false); reloadFolder(); } },
        { label: 'Show Everything Again', action: async () => {
          if (!(await confirmBox(`Show all ${keys.length} hidden items again?`))) return;
          for (const x of keys) await api.post('/api/xmb/folders/hide', { key: x, on: false }).catch(() => null);
          S.hidden = {}; refreshAll(); reloadFolder(); } }] }));
  },
};
function refreshAll() { for (const c of CATS) refresh(c.id); if (S.stack.length) reloadFolder(); }

// the XMB version of the app switcher: everything open, A switches, Y closes
function openNowItems() {
  return (S.state.windows || []).filter((w) => w.app !== 'crossbar-player').map((w) => ({
    key: `open:${w.con_id}`, label: w.title || w.app, icon: 'window', badge: 'OPEN', sub: `${w.game ? 'Game' : 'App'} · {ok} switch to it`,
    action: () => api.post('/api/window/focus', { con_id: w.con_id }),
    options: [{ label: 'Switch To', action: () => api.post('/api/window/focus', { con_id: w.con_id }) },
      { label: 'Close', action: async () => { await api.post('/api/window/close', { con_id: w.con_id }); setTimeout(loadState, 800); } },
      { label: 'Force Close', action: async () => { if (await confirmBox(`Force close ${w.title}?\nUnsaved work is lost.`)) { await api.post('/api/window/kill', { con_id: w.con_id }); setTimeout(loadState, 800); } } }],
  }));
}

CATS.push({
  id: 'apps', label: 'Apps', icon: 'apps', live: true,
  async load() {
    await loadApps();
    const items = openNowItems();
    for (const j of S.jobs.filter((j) => j.kind === 'install' && j.provider === 'flatpak' && j.status === 'running')) {
      items.push({ key: `job:${j.id}`, label: j.title, icon: 'download', sub: `Installing… ${j.message}`, progress: j.progress, badge: 'FLATPAK',
        ...(j.cancellable ? { action: () => cancelJob(j), options: jobOptions(j) } : {}) });
    }
    if (typeof torrentsItem === 'function') {           // Torrents, with live speeds while it runs
      S.torrent = await api.get('/api/torrent').catch(() => S.torrent);
      items.push(torrentsItem());
    }
    items.push(...appsIn('apps'));
    items.push({ key: 'install-apps', label: 'Install Apps', icon: 'download', sub: 'Flatpaks from Flathub, or an AppImage you have', children: async () => INSTALL_APPS.children() });
    return items;
  },
});

// ---- Store › Install Apps ---------------------------------------------------------------------------
const square = (url) => (url ? { art: url, artShape: 'square' } : { icon: 'apps' });

function flathubItem(h) {
  const inst = S.apps.some((a) => a.key === `flatpak:${h.id}`);
  return {
    key: `fh:${h.id}`, label: h.name, sub: h.summary || h.developer, badge: inst ? 'INSTALLED' : h.verified ? 'VERIFIED' : '',
    ...square(h.icon), artTitle: h.name,
    children: async () => flathubDetails(h.id),
  };
}

function pagedList(fetchPage) {
  // the first page, then "More…" fetches the next one into the same list
  return async () => {
    const pages = [await fetchPage(1)];
    const build = () => {
      const items = pages.flatMap((p) => p.apps.map(flathubItem));
      const last = pages.at(-1);
      if (!items.length) return [{ key: 'none', label: 'Nothing found', icon: 'info', sub: 'Try another search or category' }];
      if (last.pages && last.page < last.pages) {
        items.push({ key: `more:${last.page}`, label: 'More…', icon: 'add', sub: `Page ${last.page + 1} of ${last.pages}`,
          action: async () => { pages.push(await fetchPage(last.page + 1)); const f = S.stack.at(-1); f.items = build(); renderColumn(true); } });
      }
      return items;
    };
    return build();
  };
}

async function flathubDetails(id) {
  const a = await api.get(`/api/flathub/app?id=${encodeURIComponent(id)}`);
  await loadApps();
  const inst = S.apps.find((x) => x.key === `flatpak:${id}`);
  const job = S.jobs.find((j) => j.provider === 'flatpak' && j.game_id === id && j.status === 'running');
  const items = [];
  if (job) items.push({ key: 'job', label: `Installing… ${job.message}`, icon: 'download', progress: job.progress, ...(job.cancellable ? { action: () => cancelJob(job) } : {}) });
  else if (inst) {
    items.push({ key: 'open', label: `Open ${a.name}`, icon: 'play', sub: 'Installed', action: () => openApp(inst) });
    items.push({ key: 'move', label: 'Show In…', icon: 'folder', sub: APP_CATS.find(([c]) => c === inst.category)?.[1] || 'Apps', action: () => moveApp(inst) });
    items.push({ key: 'rm', label: 'Uninstall', icon: 'power', action: () => uninstallApp(inst) });
  } else {
    items.push({ key: 'install', label: `Install ${a.name}`, icon: 'download', sub: 'For you only (no password) · pick where it shows up',
      action: async () => {
        const cat = await pickCategory(/game/i.test(id) ? 'game' : 'apps');
        if (!cat) return;
        if (await call(() => api.post('/api/apps/install-flatpak', { id, name: a.name, category: cat }), `Installing ${a.name}…`)) setTimeout(reloadFolder, 800);
      } });
  }
  items.push({ key: 'about', label: 'About', icon: 'info', sub: a.summary, action: () => message(`${a.summary}\n\n${a.description}`.slice(0, 1800), a.name) });
  if (a.developer) items.push({ key: 'dev', label: a.developer, icon: 'user', sub: 'Developer' });
  a.screenshots.forEach((u, i) => items.push({ key: `shot:${i}`, label: `Screenshot ${i + 1}`, art: u, artTitle: a.name }));
  return items;
}

async function flathubSearch() {
  const r = await Dialog.ask({ title: 'Search Flathub', buttons: ['Search', 'Cancel'], fields: [{ key: 'q', label: 'App name or what it does' }] });
  if (r.button !== 0 || !r.values.q.trim()) return;
  const q = r.values.q.trim();
  openFolder({ label: `“${q}”`, icon: 'search', children: pagedList(async () => api.get(`/api/flathub/search?q=${encodeURIComponent(q)}`)) });
}

const FLATHUB_FOLDER = {
  key: 'flathub', label: 'Flatpak (Flathub)', icon: 'store', sub: 'Thousands of apps: browse, search, install',
  children: async () => {
    const col = (kind, label, sub) => ({ key: `c:${kind}`, label, icon: 'folder', sub,
      children: pagedList(async (p) => api.get(`/api/flathub/collection?kind=${kind}&page=${p}`)) });
    return [
      { key: 'search', label: 'Search Flathub…', icon: 'search', sub: 'Find an app by name', action: flathubSearch },
      col('popular', 'Popular', 'Most installed this month'),
      col('trending', 'Trending', 'Getting popular right now'),
      col('recently-added', 'New Apps', 'Just arrived on Flathub'),
      col('recently-updated', 'Recently Updated', 'Fresh versions'),
      { key: 'cats', label: 'Categories', icon: 'folder', sub: 'Games, Audio & Video, Productivity…',
        children: async () => (await api.get('/api/flathub/categories')).map((c) => ({ key: `cat:${c.id}`, label: c.name, icon: 'folder',
          children: pagedList(async (p) => api.get(`/api/flathub/category?id=${encodeURIComponent(c.id)}&page=${p}`)) })) },
    ];
  },
};

// AppImage: browse to the file; it's moved to ~/Applications and shows up in the category you pick
async function appimageBrowse(path) {
  const r = await api.get(`/api/fs?ext=.appimage${path ? `&path=${encodeURIComponent(path)}` : ''}`);
  const items = (r.files || []).map((f) => ({
    key: `ai:${f.path}`, label: f.name, icon: 'download', sub: 'Install this AppImage',
    action: async () => {
      const cat = await pickCategory('apps');
      if (!cat) return;
      const res = await call(() => api.post('/api/apps/install-appimage', { path: f.path, category: cat }));
      if (!res) return;
      toast(`${res.name} installed (moved to ~/Applications)`, 'download');
      while (S.stack.length && S.stack.at(-1).source?.appimageBrowse) S.stack.pop();
      await loadApps(); refreshAll();
    },
  }));
  for (const d of r.dirs) items.push({ key: `d:${d.path}`, label: d.name, icon: 'folder', appimageBrowse: true, children: () => appimageBrowse(d.path) });
  if (!items.length) items.push({ key: 'none', label: 'No AppImages here', icon: 'info', sub: 'Look in Downloads or on a USB stick' });
  return items;
}

const INSTALL_APPS = {
  key: 'install-apps', label: 'Install Apps', icon: 'download', sub: 'Flatpaks from Flathub, or an AppImage you have',
  children: async () => [
    FLATHUB_FOLDER,
    { key: 'appimage', label: 'AppImage', icon: 'folder', sub: 'Pick an .AppImage file (Downloads, USB stick…): it moves to ~/Applications',
      appimageBrowse: true, children: () => appimageBrowse(null) },
  ],
};

// ---- your own folders, in any category ---------------------------------------------------------------
const FOLDER_CATS = ['photo', 'music', 'video', 'tv', 'game', 'apps', 'store', 'party', 'users'];
const SKIP_KEYS = /^(none|err|loading|more:|job:|open:)/;

async function newFolder(cat, thenKey) {
  const r = await Dialog.ask({ title: 'New Folder', buttons: ['Create', 'Cancel'], fields: [{ key: 'name', label: 'Folder name' }] });
  if (r.button !== 0 || !r.values.name.trim()) return;
  const f = await call(() => api.post('/api/xmb/folders/create', { cat, name: r.values.name.trim() }), `Folder “${r.values.name.trim()}” created`);
  if (f && thenKey) await api.post('/api/xmb/folders/move', { key: thenKey, cat, folder: f.id });
  await loadFolders(); refresh(cat); if (S.stack.length) reloadFolder();
}
async function moveToFolder(cat, key) {
  const fs = S.folders.filter((f) => f.cat === cat);
  const inOne = fs.find((f) => f.items.includes(key));
  const pick = await choose([...fs.filter((f) => f !== inOne).map((f) => [f.id, `Into “${f.name}”`]), ['new', 'Into a New Folder…'],
    ...(inOne ? [['out', `Take Out of “${inOne.name}”`]] : [])]);
  if (!pick) return;
  if (pick === 'new') return newFolder(cat, key);
  await call(() => api.post('/api/xmb/folders/move', { key, cat, folder: pick === 'out' ? null : pick }));
  await loadFolders(); refresh(cat); if (S.stack.length) reloadFolder();
}
function withFolderOptions(cat, it) {
  if (!it.key || SKIP_KEYS.test(it.key) || it.key.startsWith('folder:')) return it;
  return { ...it, options: [...(it.options || []), { label: 'Move to Folder…', action: () => moveToFolder(cat, it.key) }] };
}

// after a category loads: apps placed in it, then your folders (holding the items you put in them)
// games and apps in A–Z order (whatever store they're from); pinned rows (Trophies, Return to…,
// open apps, Install Apps…) stay where they are
const SORTABLE = /^(app:|steam:|gog:|epic:|demo:|lutris:|shortcut:|emu:|rom:)/;
function alphabetical(items) {
  const first = items.findIndex((i) => i && i.key && SORTABLE.test(i.key) && i.progress == null);
  if (first < 0) return items;
  const isS = (i) => i && i.key && SORTABLE.test(i.key) && i.progress == null;    // downloads keep their place
  const sorted = items.filter(isS).sort((a, b) => String(a.label).localeCompare(String(b.label), undefined, { numeric: true, sensitivity: 'base' }));
  const head = items.slice(0, first).filter((i) => !isS(i)), tail = items.slice(first).filter((i) => !isS(i));
  return [...head, ...sorted, ...tail];
}
function applyExtras(cat, items) {
  if (cat !== 'apps' && cat !== 'settings') items = [...items, ...appsIn(cat)];
  items = decorate(items);
  if (cat === 'game' || cat === 'apps') items = alphabetical(items);
  if (!FOLDER_CATS.includes(cat)) return items;
  const fs = S.folders.filter((f) => f.cat === cat);
  const inside = new Set(fs.flatMap((f) => f.items));
  const top = items.filter((i) => !inside.has(i.key)).map((i) => withFolderOptions(cat, i));
  const folderItems = fs.map((f) => {
    const members = f.items.map((k) => items.find((i) => i.key === k)).filter(Boolean).map((i) => withFolderOptions(cat, i));
    return { key: `folder:${f.id}`, label: f.name, icon: 'folder', sub: `${members.length} item${members.length === 1 ? '' : 's'}`,
      children: async () => members.length ? members : [{ key: 'none', label: 'Empty folder', icon: 'info', sub: 'Press Y on anything in this category › Move to Folder…' }],
      options: [
        { label: 'Rename', action: async () => { const r = await Dialog.ask({ title: 'Rename Folder', buttons: ['Save', 'Cancel'], fields: [{ key: 'name', label: 'Name', value: f.name }] });
          if (r.button === 0 && r.values.name.trim()) { await call(() => api.post('/api/xmb/folders/rename', { id: f.id, name: r.values.name.trim() })); await loadFolders(); refresh(cat); } } },
        { label: 'Delete Folder', action: async () => { if (await confirmBox(`Delete the folder “${f.name}”?\nWhat's in it goes back to the list.`)) { await call(() => api.post('/api/xmb/folders/delete', { id: f.id })); await loadFolders(); refresh(cat); } } },
        { label: 'New Folder…', action: () => newFolder(cat) },
      ] };
  });
  // folders go after the pinned rows at the top (Trophies, Return to…, Open apps…), before the list itself
  let at = top.findIndex((i) => i.art !== undefined || /^(app:|steam:|gog:|epic:|rom:)/.test(i.key));
  if (at < 0) at = top.length;
  const out = [...top.slice(0, at), ...folderItems, ...top.slice(at)];
  return out;
}

// ---- Y › Launch Options… : environment variables, launch command, Proton / Wine version per game ----------
const LAUNCHOPTS = /^(steam|shortcut|lutris|gog|epic):/;
const LO_PRESETS = [
  ['Frame Rate Overlay (MangoHud)', { env: ['MANGOHUD', '1'] }],
  ['GameMode (CPU performance mode)', { pre: 'gamemoderun' }],
  ['DXVK Frame Rate Counter', { env: ['DXVK_HUD', 'fps'] }],
  ['Proton Log (for troubleshooting)', { env: ['PROTON_LOG', '1'] }],
  ['Use WineD3D Instead of DXVK', { env: ['PROTON_USE_WINED3D', '1'] }],
  ['Turn Off Esync', { env: ['PROTON_NO_ESYNC', '1'] }],
  ['Turn Off Fsync', { env: ['PROTON_NO_FSYNC', '1'] }],
  ['NVIDIA DLSS / NVAPI', { env: ['PROTON_ENABLE_NVAPI', '1'] }],
  ['Native Wayland (Proton 10+)', { env: ['PROTON_ENABLE_WAYLAND', '1'] }],
  ['Limit to 60 FPS (DXVK)', { env: ['DXVK_FRAME_RATE', '60'] }],
];
function launchOptionsFolder(it) {
  const key = it.key, name = it.label;
  const get = () => api.get(`/api/launchopts?key=${encodeURIComponent(key)}`);
  const save = async (body, msg) => {
    const r = await call(() => api.post('/api/launchopts/save', { key, ...body }));
    if (r) toast(r.pending ? `${msg} · goes in when you next start it here (Steam restarts once)` : msg, 'settings');
    return r;
  };
  const editVar = async (o, k = '', v = '') => {
    const r = await Dialog.ask({ title: k ? `Edit ${k}` : 'Add Variable', buttons: k ? ['Save', 'Remove', 'Cancel'] : ['Add', 'Cancel'],
      body: 'Set for this game only, e.g. DXVK_HUD = fps', fields: [{ key: 'k', label: 'Name', value: k }, { key: 'v', label: 'Value', value: v }] });
    if (r.button === null || r.button === (k ? 2 : 1)) return;
    const env = { ...o.env };
    if (k) delete env[k];
    if (!(k && r.button === 1)) { const nk = r.values.k.trim().toUpperCase(); if (!nk) return; env[nk] = r.values.v.trim(); }
    if (await save({ env }, k && r.button === 1 ? `Removed ${k}` : 'Variable saved')) reloadFolder();
  };
  return {
    key: `lo:${key}`, label: 'Launch Options', icon: 'settings', sub: name,
    children: async () => {
      const o = await get();
      const nvars = Object.keys(o.env).length;
      const items = [];
      if (o.pending) items.push({ key: 'apply', label: 'Apply Now', icon: 'refresh', sub: 'Saved, waiting for Steam: it closes and reopens to take them',
        action: async () => { if (await call(() => api.post('/api/launchopts/apply'), 'Applying launch options…')) { pollJobs(); setTimeout(reloadFolder, 4000); } } });
      if (o.tools.length) items.push({ key: 'tool', label: o.kind === 'lutris' ? 'Wine Version' : 'Proton / Wine Version', icon: 'game', sub: o.tool_name,
        children: async () => o.tools.map((t) => ({ key: `t:${t.id}`, label: t.name, icon: t.id === o.tool ? 'check' : 'game',
          sub: t.id === o.tool ? 'Current' : (t.note || ''),
          action: async () => { if (await save({ tool: t.id }, `${name}: ${t.name}`)) { back(); reloadFolder(); } } })) });
      items.push({ key: 'env', label: 'Environment Variables', icon: 'settings', sub: nvars ? Object.entries(o.env).map(([k, v]) => `${k}=${v}`).join('  ') : 'None',
        children: async () => {
          const cur = await get();
          return [...Object.entries(cur.env).map(([k, v]) => ({ key: `e:${k}`, label: `${k} = ${v}`, icon: 'settings', sub: '{ok} edit or remove',
            action: () => editVar(cur, k, v),
            options: [{ label: 'Edit', action: () => editVar(cur, k, v) },
              { label: 'Remove', action: async () => { const env = { ...cur.env }; delete env[k]; if (await save({ env }, `Removed ${k}`)) reloadFolder(); } }] })),
            { key: 'add', label: 'Add Variable…', icon: 'add', sub: 'Any NAME = value', action: () => editVar(cur) }];
        } });
      if (o.can_command) items.push({ key: 'cmd', label: 'Launch Command', icon: 'game', sub: o.command,
        action: async () => {
          const r = await Dialog.ask({ title: 'Launch Command', buttons: ['Save', 'Cancel'],
            body: '%command% is the game. Put tools before it and game options after it,\ne.g. gamemoderun %command% -dx11',
            fields: [{ key: 'c', label: 'Command', value: o.command }] });
          if (r.button === 0 && await save({ command: r.values.c.trim() || '%command%' }, 'Launch command saved')) reloadFolder();
        } });
      items.push({ key: 'presets', label: 'Add a Common Option', icon: 'add', sub: 'MangoHud, GameMode, Proton log, WineD3D, esync / fsync…',
        children: async () => LO_PRESETS.map(([label, p]) => {
          const on = p.env ? o.env[p.env[0]] === p.env[1] : (` ${o.command} `).includes(` ${p.pre} `);
          return { key: `p:${label}`, label, icon: on ? 'check' : 'add', sub: on ? 'On · {ok} turn off' : (p.env ? `${p.env[0]}=${p.env[1]}` : `${p.pre} %command%`),
            action: async () => {
              const cur = await get();
              let body;
              if (p.env) { const env = { ...cur.env }; if (on) delete env[p.env[0]]; else env[p.env[0]] = p.env[1]; body = { env }; }
              else if (!cur.can_command) return toast('This one is set in Steam itself', 'info');
              else body = { command: on ? cur.command.replace(new RegExp(`(^|\\s)${p.pre}(?=\\s)`), '').trim() : `${p.pre} ${cur.command}` };
              if (await save(body, `${label}: ${on ? 'off' : 'on'}`)) { reloadFolder(); }
            } };
        }) });
      items.push({ key: 'reset', label: 'Reset to Defaults', icon: 'refresh', sub: 'No variables, plain command, default version',
        action: async () => { if (await confirmBox(`Reset ${name}'s launch options?`)) { const r = await call(() => api.post('/api/launchopts/reset', { key })); if (r) { toast('Launch options reset', 'settings'); reloadFolder(); } } } });
      if (o.kind === 'steam') items.push({ key: 'how', label: 'About Steam Games', icon: 'info', sub: 'Saved in Steam, so Steam shows the same settings',
        action: () => message('These are the same launch options and Proton version you\'d set in Steam › Properties.\nSteam only reads them when it starts, and writes its own copy back when it quits, so Crossbar saves them and puts them in place the next time you start this game from the XMB (Steam closes and reopens once). Apply Now does it straight away.', 'Launch Options') });
      return items;
    },
  };
}

// ---- Y › Windows & Proton › Windows Components… : winetricks / protontricks for one game's prefix ----------
function windowsComponentsFolder(it) {
  const key = it.key, name = it.label;
  const install = async (verbs, label) => {
    if (!(await confirmBox(`Install ${label} for ${name}?\nIt goes into this game's own Windows folder only.`))) return;
    if (await call(() => api.post('/api/wintricks/install', { key, verbs, name }), `Installing ${label}… (see Downloads)`)) pollJobs();
  };
  const row = (c) => ({ key: `wt:${c.id}`, label: c.name, icon: c.installed ? 'check' : 'download',
    sub: c.installed ? 'Installed' + (c.about ? ` · ${c.about}` : '') : (c.about || c.id), badge: c.id.toUpperCase(),
    action: () => install([c.id], c.name),
    options: [{ label: c.installed ? 'Install Again' : 'Install', action: () => install([c.id], c.name) }] });
  return {
    key: `wt:${key}`, label: 'Windows Components', icon: 'download', sub: name,
    children: async () => {
      const st = await api.get(`/api/wintricks?key=${encodeURIComponent(key)}`);
      const items = [];
      if (!st.available) items.push({ key: 'missing', label: 'winetricks isn\'t installed', icon: 'info', sub: 'Settings › System › Update Crossbar installs it' });
      items.push(...st.groups.map((g) => ({ key: `g:${g.name}`, label: g.name, icon: 'folder',
        sub: `${g.items.filter((c) => c.installed).length} of ${g.items.length} installed`, children: async () => g.items.map(row) })));
      items.push({ key: 'search', label: 'Search All Components…', icon: 'search', sub: 'Everything winetricks has (DLLs, fonts, apps, settings)',
        action: async () => {
          const r = await Dialog.ask({ title: 'Search Components', buttons: ['Search', 'Cancel'], fields: [{ key: 'q', label: 'Name, e.g. directplay or d3dx' }] });
          const q = r.button === 0 ? r.values.q.trim().toLowerCase() : '';
          if (!q) return;
          const all = await call(() => api.get('/api/wintricks/all'));
          if (!all) return;
          const hits = all.filter((c) => c.id.includes(q) || c.name.toLowerCase().includes(q)).slice(0, 80);
          openFolder({ key: `wts:${q}`, label: `“${q}”`, icon: 'search', children: async () => hits.length
            ? hits.map((c) => row({ ...c, about: `${c.group} · ${c.name}`, name: c.id, installed: st.installed.includes(c.id) }))
            : [{ key: 'none', label: 'Nothing found', icon: 'info', sub: 'Try a shorter word' }] });
        } });
      items.push({ key: 'have', label: 'Installed in This Game', icon: 'info', sub: st.installed.length ? st.installed.slice(-6).join(', ') : 'Nothing yet',
        action: () => message(st.installed.length ? st.installed.join('\n') : 'Nothing installed with winetricks yet.', name) });
      items.push({ key: 'how', label: 'How This Works', icon: 'info', sub: `${st.how} · ${st.prefix}`,
        action: () => message(`Components are installed into ${name}'s own Windows folder (its Wine / Proton prefix), never system-wide.\nUsing: ${st.how}\nFolder: ${st.prefix}\nIf a game breaks, removing its prefix (or Steam › Properties › Verify) starts it fresh.`, 'Windows Components') });
      return items;
    },
  };
}
