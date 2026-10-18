'use strict';
// File Browser (Users › File Browser): browse, open, copy/cut/paste, rename, delete.

const Clip = { paths: [], move: false };
const fmtSize = (n) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : n < 1073741824 ? `${(n / 1048576).toFixed(1)} MB` : `${(n / 1073741824).toFixed(2)} GB`);
const FILE_ICON = { folder: 'folder', music: 'music', video: 'video', photo: 'photo', file: 'demo' };

async function filesAfterChange(msg) { if (msg) toast(msg, 'folder'); await reloadFolder(); }

async function pasteInto(dir) {
  if (!Clip.paths.length) return toast('Nothing to paste — use Copy or Cut first', 'info');
  const r = await call(() => api.post(`/api/files/${Clip.move ? 'move' : 'copy'}`, { paths: Clip.paths, dest: dir }));
  if (!r) return;
  if (Clip.move) Clip.paths = [];
  pollJobs();
  setTimeout(() => reloadFolder(), 800);
}

function openFile(f, list) {
  const same = list.filter((x) => x.kind === f.kind);
  const i = same.findIndex((x) => x.path === f.path);
  if (f.kind === 'music') return call(() => api.post('/api/music/play', { paths: same.map((x) => x.path), index: i }), `Playing ${f.name}`);
  if (f.kind === 'video') return call(() => api.post('/api/video/play', { paths: same.map((x) => x.path), index: i }));
  if (f.kind === 'photo') return Viewer.start(same.map((x) => ({ name: x.name, path: x.path })), i);
  message(`${f.name}\n${fmtSize(f.size)}\nThis kind of file can't be opened here.`, 'File');
}

function fileOptions(f, dir) {
  const opts = [];
  if (!f.dir) opts.push({ label: 'Open', action: () => openFile(f, dir.entries) });
  opts.push({ label: 'Copy', action: () => { Clip.paths = [f.path]; Clip.move = false; toast(`Copied ${f.name} — open a folder and Paste`, 'folder'); } });
  opts.push({ label: 'Cut', action: () => { Clip.paths = [f.path]; Clip.move = true; toast(`Cut ${f.name} — open a folder and Paste`, 'folder'); } });
  if (f.dir && Clip.paths.length) opts.push({ label: 'Paste Into', action: () => pasteInto(f.path) });
  opts.push({ label: 'Rename…', action: async () => {
    const r = await Dialog.ask({ title: 'Rename', fields: [{ key: 'name', label: 'New name', value: f.name }], buttons: ['Rename', 'Cancel'] });
    if (r.button === 0 && r.values.name.trim() && r.values.name !== f.name) {
      if (await call(() => api.post('/api/files/rename', { path: f.path, name: r.values.name }))) filesAfterChange('Renamed');
    }
  } });
  opts.push({ label: 'Move to Trash', action: async () => {
    if (await confirmBox(`Move ${f.name} to the Trash?`)) { if (await call(() => api.post('/api/files/trash', { paths: [f.path] }))) filesAfterChange(`${f.name} moved to Trash`); }
  } });
  opts.push({ label: 'Delete Permanently', action: async () => {
    if (await confirmBox(`Permanently delete ${f.name}?\nThis can't be undone.`)) { if (await call(() => api.post('/api/files/delete', { paths: [f.path] }))) filesAfterChange(`Deleted ${f.name}`); }
  } });
  opts.push({ label: 'Information', action: () => message(`${f.name}\n${f.dir ? 'Folder' : fmtSize(f.size)}\nModified ${new Date(f.mtime * 1000).toLocaleString()}\n${f.path}`, 'Information') });
  return opts;
}

function folderNode(path, label, icon = 'folder') {
  const node = {
    key: `fs:${path}`, label, icon, hidden: false,
    children: async () => {
      const dir = await api.get(`/api/files?path=${encodeURIComponent(path)}&hidden=${node.hidden ? 1 : 0}`);
      const here = {
        key: 'here', label: 'This Folder', icon: 'settings',
        sub: `${dir.entries.length} items · ${fmtSize(dir.free)} free${Clip.paths.length ? ` · ${Clip.move ? 'cut' : 'copied'}: ${Clip.paths.map((p) => p.split('/').pop()).join(', ')}` : ''}`,
        action: () => Options.show(hereOptions()),
        options: null,
      };
      const hereOptions = () => [
        ...(Clip.paths.length ? [{ label: `Paste Here (${Clip.move ? 'move' : 'copy'})`, action: () => pasteInto(dir.path) }] : []),
        { label: 'New Folder…', action: async () => {
          const r = await Dialog.ask({ title: 'New Folder', fields: [{ key: 'name', label: 'Name' }], buttons: ['Create', 'Cancel'] });
          if (r.button === 0 && r.values.name.trim() && await call(() => api.post('/api/files/mkdir', { path: dir.path, name: r.values.name }))) filesAfterChange('Folder created');
        } },
        { label: node.hidden ? 'Hide Hidden Files' : 'Show Hidden Files', action: () => { node.hidden = !node.hidden; reloadFolder(); } },
      ];
      here.options = hereOptions();
      return [here, ...dir.entries.map((f) => (f.dir
        ? { ...folderNode(f.path, f.name), options: fileOptions(f, dir) }
        : { key: `f:${f.path}`, label: f.name, icon: FILE_ICON[f.kind] || 'demo',
            ...(f.kind === 'photo' || f.kind === 'video' ? { art: thumb(f.path), artTitle: f.name } : {}),
            sub: `${fmtSize(f.size)} · ${new Date(f.mtime * 1000).toLocaleDateString()}`,
            action: () => openFile(f, dir.entries), options: fileOptions(f, dir) }))];
    },
  };
  return node;
}

function fileBrowserItem() {
  return {
    key: 'files', label: 'File Browser', icon: 'folder', sub: 'Copy, move, rename and delete files',
    children: async () => {
      const places = await api.get('/api/files/places');
      return [
        ...places.map((p) => folderNode(p.path, p.name, p.drive ? 'download' : 'folder')),
        { key: 'trash', label: 'Trash', icon: 'demo', sub: 'Things you moved to the Trash',
          children: async () => [...(await folderNode(`${S.state.home || '~'}/.local/share/Trash/files`, 'Trash').children()).slice(1),
            { key: 'empty', label: 'Empty Trash', icon: 'power', action: async () => {
              if (await confirmBox('Permanently delete everything in the Trash?')) { await call(() => api.post('/api/files/empty-trash'), 'Trash emptied'); reloadFolder(); }
            } }] },
      ];
    },
  };
}
