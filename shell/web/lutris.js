'use strict';
// Store › Install Apps › Lutris: the community install scripts from lutris.net, from the controller.
// Search a game, pick one of its installers, see what it needs — files it downloads for you, and files
// you provide yourself (a setup.exe you bought, a disc image…) — choose those and the install folder,
// then Install. Lutris's own installer engine does the work; anything it asks along the way (a version,
// a disc, a menu choice) comes up here. Installed games appear in Game.

const LT_DRAFT = {};          // installer key -> {files: {file id: path}, target}
const ltKey = (inst) => `${inst.game_slug || inst.slug}::${inst.version}`;

// a file / folder picker in the menu: onPick(path) when chosen
function ltBrowse(title, mode, onPick, path = null) {
  return { key: `ltb:${mode}:${path || 'top'}`, label: path ? path.split('/').pop() || '/' : title, icon: 'folder', ltBrowse: true,
    children: async () => {
      const r = await api.get(`/api/fs?ext=any${path ? `&path=${encodeURIComponent(path)}` : ''}`);
      const rows = [];
      if (mode === 'folder' && path) rows.push({ key: 'use', label: 'Use This Folder', icon: 'check', sub: path, action: () => ltDone(onPick, path) });
      for (const d of r.dirs) rows.push(ltBrowse(title, mode, onPick, d.path));
      if (mode === 'file') {
        for (const f of r.files || []) rows.push({ key: `f:${f.path}`, label: f.name, icon: 'download', sub: 'Use this file', action: () => ltDone(onPick, f.path) });
      }
      if (!rows.length) rows.push({ key: 'none', label: mode === 'file' ? 'Nothing here' : 'No folders here', icon: 'info' });
      return rows;
    } };
}
function ltDone(onPick, path) {
  while (S.stack.length && S.stack.at(-1).source?.ltBrowse) S.stack.pop();
  render();
  onPick(path);
}

async function ltInstallerRows(inst, scriptPath = null) {
  const k = ltKey(inst);
  const d = LT_DRAFT[k] || (LT_DRAFT[k] = { files: {}, target: inst.default_target });
  const rows = [];
  const busy = (await api.get('/api/lutris').catch(() => ({}))).busy;
  rows.push({ key: 'about', label: inst.version || 'Installer', icon: 'info', badge: (inst.runner || '').toUpperCase(),
    sub: [inst.description || inst.notes ? `${(inst.description || inst.notes).split('\n')[0].slice(0, 140)} · {ok} read all` : '', inst.user ? `by ${inst.user}` : '',
      `${inst.steps} step${inst.steps === 1 ? '' : 's'}`].filter(Boolean).join(' · '),
    action: () => message([inst.description, inst.notes ? `Notes:\n${inst.notes}` : '', inst.runner ? `Runs with: ${inst.runner}` : '',
      inst.requires ? `Needs ${inst.requires} installed first` : ''].filter(Boolean).join('\n\n') || 'No notes.', `${inst.name} · ${inst.version}`) });
  if (inst.requires) rows.push({ key: 'req', label: `Needs ${inst.requires}`, icon: 'info', sub: 'Install that one first (it adds to it)' });
  const mine = inst.files.filter((f) => f.user);
  for (const f of inst.files) {
    if (f.user) {
      const p = d.files[f.id];
      rows.push({ key: `uf:${f.id}`, label: `Your file: ${f.label}`, icon: p ? 'check' : 'folder',
        sub: p ? `${p} · {ok} change` : 'Not chosen yet · {ok} point to the file you downloaded',
        children: undefined,
        action: () => openFolder(ltBrowse(`Choose: ${f.label}`, 'file', (path) => { d.files[f.id] = path; toast(`Using ${path.split('/').pop()}`, 'check'); reloadFolder(); })) });
    } else if (f.steam) {
      rows.push({ key: `sf:${f.id}`, label: `From Steam: ${f.label}`, icon: 'info', sub: 'Needs Steam files: install this one in Lutris itself' });
    } else {
      rows.push({ key: `df:${f.id}`, label: `Downloaded for you: ${f.filename || f.label}`, icon: 'download', sub: f.url.slice(0, 140) });
    }
  }
  if (inst.creates_folder) {
    rows.push({ key: 'target', label: 'Install Folder', icon: 'folder', sub: `${d.target} · {ok} change`,
      action: () => openFolder(ltBrowse('Install where?', 'folder', (path) => {
        d.target = `${path.replace(/\/$/, '')}/${(inst.default_target || '').split('/').pop() || inst.game_slug}`;
        reloadFolder();
      })) });
  }
  const missing = mine.filter((f) => !d.files[f.id]);
  const blocked = inst.files.some((f) => f.steam);
  rows.push({ key: 'install', label: busy ? 'Another install is running' : 'Install', icon: 'download',
    sub: busy ? 'Wait for it to finish (Downloads shows it)' : blocked ? 'This installer needs Steam\'s files' : missing.length ? `Choose ${missing.length === 1 ? 'your file' : `your ${missing.length} files`} first`
      : 'Lutris downloads what it needs and runs the installer; questions come up here',
    action: async () => {
      if (busy || blocked) return;
      if (missing.length) { toast(`Choose ${missing.map((f) => f.label).join(', ')} first`, 'info'); return; }
      const body = { slug: inst.game_slug, version: inst.version, name: inst.name, target: inst.creates_folder ? d.target : null, files: d.files,
        script_path: scriptPath };
      const j = await call(() => api.post('/api/lutris/install', body), `Installing ${inst.name}…`);
      if (j) { pollJobs(); ltWatch(j.id, inst.name); }
    } });
  rows.push({ key: 'how', label: 'About Lutris Installers', icon: 'info', sub: 'Written by the Lutris community',
    action: () => message('Lutris installers are community scripts from lutris.net. Lutris\'s own installer engine runs them:\nit downloads what it can, sets up Wine or the emulator, and asks you for anything it can\'t get\n(a setup file you bought, a disc image, a choice of version).\n\nThe game shows up in Game when it\'s done, and starts through Lutris.', 'Lutris') });
  return rows;
}

// the install's progress, live, in a dialog you can close (it keeps going: Downloads shows it)
async function ltWatch(jobId, name) {
  let open = true;
  Dialog.ask({ title: `Installing ${name}`, body: 'Starting…', buttons: ['Hide (keeps installing)'] }).then(() => { open = false; });
  while (open) {
    await new Promise((r) => setTimeout(r, 700));
    if (!open) break;
    const cur = (await api.get('/api/jobs').catch(() => [])).find((x) => x.id === jobId);
    if (!cur) break;
    const st = await api.get('/api/lutris').catch(() => ({}));
    if (st.pending) { Dialog.close?.(0); open = false; ltAnswer(st.pending); break; }
    $('.dlg-body').textContent = [cur.status === 'error' ? `⚠ ${cur.message}` : cur.message,
      cur.progress ? `${Math.round(cur.progress * 100)}%` : '',
      cur.status === 'done' ? `\n✓ Installed. ${name} is in Game.` : ''].filter(Boolean).join('\n');
    if (cur.status !== 'running') break;
  }
}

// Lutris's installer is asking something: answer it here
let ltAsking = null;
async function ltAnswer(q) {
  if (!q || ltAsking === q.id) return;
  ltAsking = q.id;
  const send = (body) => call(() => api.post('/api/lutris/answer', { id: q.id, ...body }), null).then(() => { ltAsking = null; });
  if (q.event === 'ask_menu') {
    toast(`${q.game}: choose one`, 'info');
    const v = await choose(q.options.map(([k, l]) => [k, `${check(k === q.preselect)}${l}`]), Math.max(0, q.options.findIndex(([k]) => k === q.preselect)));
    send({ answer: v ?? q.preselect });
  } else if (q.event === 'ask_yesno') {
    send({ answer: await confirmBox(q.question, q.title || q.game) });
  } else if (q.event === 'ask_disc') {
    const r = await Dialog.ask({ title: `${q.game}: insert the disc`, body: `${q.message}\n\nInsert or mount the disc (or its image), then:`,
      buttons: ['Find It Automatically', 'Choose the Folder…'] });
    if (r.button === 1) openFolder(ltBrowse('Where is the disc?', 'folder', (path) => send({ path })));
    else send({ path: null });
  } else if (q.event === 'ask_file') {
    const yes = await confirmBox(q.question, q.title || q.game);
    if (!yes) { send({ path: null }); return; }
    openFolder(ltBrowse(q.message || 'Choose the file', 'file', (path) => send({ path })));
  }
}
EventHooks.push((ev) => {
  if (ev.type !== 'lutris-ask') return false;
  ltAnswer(ev);
  return true;
});

function ltGameRow(g) {
  return { key: `lg:${g.slug}`, label: g.name, art: g.art || undefined, icon: g.art ? undefined : 'game',
    sub: [g.year, (g.platforms || []).join(', ')].filter(Boolean).join(' · '),
    children: async () => {
      const list = await api.get(`/api/lutris/installers?slug=${encodeURIComponent(g.slug)}`);
      if (!list.length) return [{ key: 'none', label: 'No installers for this one', icon: 'info' }];
      return list.map((inst) => {
        const yours = inst.files.filter((f) => f.user).length;
        return { key: `li:${inst.slug}`, label: inst.version || inst.name, icon: 'download', badge: (inst.runner || '').toUpperCase(),
          sub: [yours ? `You provide ${yours} file${yours === 1 ? '' : 's'}` : 'Downloads everything itself', inst.requires ? `needs ${inst.requires}` : '',
            (inst.description || inst.notes || '').split('\n')[0].slice(0, 100)].filter(Boolean).join(' · '),
          children: () => ltInstallerRows(inst) };
      });
    } };
}

const LUTRIS_FOLDER = {
  key: 'lutris', label: 'Lutris', icon: 'game', sub: 'Community install scripts for thousands of games and apps (lutris.net)',
  children: async () => {
    const st = await api.get('/api/lutris').catch(() => ({}));
    if (!st.installed) {
      return [{ key: 'setup', label: 'Install Lutris', icon: 'download', sub: 'The Arch package (never touches your graphics drivers or kernel)',
        action: async () => { if (await call(() => api.post('/api/lutris/setup'), 'Installing Lutris…')) { pollJobs(); setTimeout(reloadFolder, 3000); } } },
      { key: 'flatpak', label: 'Or: the Lutris Flatpak', icon: 'store', sub: 'Flatpak (Flathub) › search “Lutris” — Crossbar uses either one',
        action: () => openFolder(FLATHUB_FOLDER) }];
    }
    const rows = [];
    if (st.busy) {
      rows.push({ key: 'busy', label: `Installing ${st.game || '…'}`, icon: 'refresh',
        sub: st.pending ? 'Waiting for your answer · {ok} answer it' : 'Downloads shows the progress',
        action: () => (st.pending ? ltAnswer(st.pending) : st.job && ltWatch(st.job, st.game || 'game')) });
    }
    rows.push({ key: 'search', label: 'Search Lutris…', icon: 'search', sub: `Lutris ${st.version || ''} (${st.kind === 'flatpak' ? 'Flatpak' : 'installed'})`.trim(),
      action: async () => {
        const r = await Dialog.ask({ title: 'Search Lutris', buttons: ['Search', 'Cancel'], fields: [{ key: 'q', label: 'Game or app' }] });
        const q = r.button === 0 ? r.values.q.trim() : '';
        if (!q) return;
        openFolder({ key: `lsearch:${q}`, label: `“${q}”`, icon: 'search',
          children: async () => {
            const res = await api.get(`/api/lutris/search?q=${encodeURIComponent(q)}`);
            return res.length ? res.map(ltGameRow) : [{ key: 'none', label: 'Nothing on Lutris by that name', icon: 'info' }];
          } });
      } });
    rows.push({ key: 'script', label: 'Install from a Script File…', icon: 'folder', sub: 'A Lutris .yml install script you have (Downloads, USB stick…)',
      ltBrowse: true, children: async function scriptBrowse(path) {
        const r = await api.get(`/api/fs?ext=lutris${typeof path === 'string' ? `&path=${encodeURIComponent(path)}` : ''}`);
        const items = (r.files || []).map((f) => ({ key: `ls:${f.path}`, label: f.name, icon: 'download', sub: 'Install with this script',
          children: async () => { const inst = await api.get(`/api/lutris/script?path=${encodeURIComponent(f.path)}`); return ltInstallerRows(inst, f.path); } }));
        for (const d of r.dirs) items.push({ key: `lsd:${d.path}`, label: d.name, icon: 'folder', ltBrowse: true, children: () => scriptBrowse(d.path) });
        return items.length ? items : [{ key: 'none', label: 'No scripts here', icon: 'info' }];
      } });
    rows.push({ key: 'about', label: 'How This Works', icon: 'info', sub: 'Your own files, discs, Wine — all from here',
      action: () => message('Lutris installers are community scripts from lutris.net (thousands of games and apps).\n\nPick a game, then one of its installers: it shows what it downloads itself and what you provide\n(a setup file you bought — GOG, a store, a disc image). Point it to those files, pick the install folder,\nand Install. Lutris\'s own engine runs the script; anything it asks comes up on the screen.\n\nThe game appears in Game when it\'s done.', 'Lutris') });
    return rows;
  },
};
