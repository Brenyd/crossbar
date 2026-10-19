'use strict';
// Apps category (open apps + your Flatpaks and AppImages), Store › Install Apps (Flathub browser,
// AppImage installer), and your own XMB folders in any category.

const APP_CATS = [['apps', 'Apps'], ['game', 'Game'], ['tv', 'TV & Video Services'], ['video', 'Video'],
  ['music', 'Music'], ['photo', 'Photo'], ['party', 'Social']];
S.apps = [];
S.folders = [];

async function loadApps() {
  try { S.apps = await api.get('/api/apps'); } catch (e) { S.apps = []; }
}
async function loadFolders() {
  try { S.folders = await api.get('/api/xmb/folders'); } catch (e) { S.folders = []; }
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

// ---- installed apps -------------------------------------------------------------------------------
function appItem(a) {
  const custom = a.art && a.art_custom;
  return {
    key: `app:${a.key}`, label: a.name, sub: `${a.kind === 'flatpak' ? 'Flatpak' : 'AppImage'} · {ok} open`,
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
function appsIn(cat) { return S.apps.filter((a) => a.category === cat).map(appItem); }
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
function applyExtras(cat, items) {
  if (cat !== 'apps' && cat !== 'settings') items = [...items, ...appsIn(cat)];
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
