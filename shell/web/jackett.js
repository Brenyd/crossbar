'use strict';
// Apps › Torrents › Jackett: install it, add any tracker Jackett supports (public, semi-private,
// private with your account), fill in each tracker's own settings form, and search them all from
// Torrents › Search. Everything Jackett's web page offers for a tracker is here, with a controller.

const jkPost = (path, body, ok) => call(() => api.post(`/api/jackett/${path}`, body || {}), ok);
const JK_DRAFT = {};          // tracker id -> {setting id: value} typed in but not saved yet
const JK_TYPE_ICON = { Public: 'network', 'Semi-Private': 'user', Private: 'account' };

// Big lists (Jackett knows 500+ sites) are split into letter folders of about 40.
function jkLetterFolders(prefix, list, row) {
  if (list.length <= 60) return list.map(row);
  const groups = [];
  let cur = null;
  for (const ix of list) {
    const c = /[a-z]/i.test(ix.name[0]) ? ix.name[0].toUpperCase() : '#';
    if (!cur || (cur.items.length >= 40 && cur.last !== c)) { cur = { first: c, last: c, items: [] }; groups.push(cur); }
    cur.items.push(ix); cur.last = c;
  }
  return groups.map((g) => ({ key: `${prefix}:${g.first}`, label: g.first === g.last ? g.first : `${g.first} – ${g.last}`, icon: 'folder',
    sub: `${g.items.length} sites · ${g.items.slice(0, 3).map((x) => x.name).join(', ')}…`, children: async () => g.items.map(row) }));
}

function jkTrackerRow(ix) {
  const bits = [ix.type_name, ix.language, ix.cats.join(', ')].filter(Boolean);
  return { key: `jx:${ix.id}`, label: ix.name, icon: ix.configured ? 'check' : (JK_TYPE_ICON[ix.type_name] || 'network'),
    badge: ix.configured ? 'ADDED' : ix.type_name.toUpperCase(),
    sub: ix.configured && ix.error ? `⚠ ${ix.error}` : `${bits.join(' · ')}${ix.description ? ` — ${ix.description}` : ''}`,
    children: () => jkSetupRows(ix),
    options: [{ label: ix.configured ? 'Settings…' : 'Add…', action: () => openFolder(jkTrackerRow(ix)) },
      ...(ix.configured ? [{ label: 'Test', action: () => jkTest(ix) }, { label: 'Remove', action: () => jkRemove(ix) }] : []),
      ...(ix.site ? [{ label: 'Open the Site', action: () => (typeof openBrowser === 'function' ? openBrowser(ix.site) : message(ix.site, ix.name)) }] : [])] };
}

async function jkTest(ix) {
  toast(`Testing ${ix.name}…`, 'search');
  if (await jkPost('test', { id: ix.id })) toast(`${ix.name} works`, 'check');
  reloadFolder();
}
async function jkRemove(ix) {
  if (!(await confirmBox(`Remove ${ix.name} from Jackett?\nIts settings and sign-in are deleted.`))) return;
  if (await jkPost('remove', { id: ix.id }, `${ix.name} removed`)) { delete JK_DRAFT[ix.id]; if (S.stack.at(-1)?.source?.key === `jx:${ix.id}`) back(); else reloadFolder(); }
}

// One tracker's settings form, exactly as Jackett describes it (text, password, choice, several
// choices, on/off, info text, a captcha picture), then Save & Test.
async function jkSetupRows(ix) {
  const form = await api.get(`/api/jackett/config?id=${encodeURIComponent(ix.id)}`);
  const draft = JK_DRAFT[ix.id] || (JK_DRAFT[ix.id] = {});
  const val = (f) => (f.id in draft ? draft[f.id] : f.value);
  const set = (f, v) => { draft[f.id] = v; reloadFolder(); };
  const rows = [];
  const needs = form.some((f) => ['inputstring', 'password'].includes(f.type) && /user|pass|key|cookie|pid|token|email/i.test(f.id));
  rows.push({ key: 'about', label: ix.name, icon: 'info', badge: ix.type_name.toUpperCase(),
    sub: `${ix.configured ? (ix.error ? `⚠ ${ix.error}` : 'Added · in Search') : needs ? 'Fill in your account below, then Save & Test' : 'Check the options below, then Save & Test'}`,
    action: () => message([ix.description, ix.site, ix.cats.length ? `Has: ${ix.cats.join(', ')}` : ''].filter(Boolean).join('\n\n'), ix.name) });
  for (const f of form) {
    const name = f.name || f.id;
    if (f.type === 'displayinfo') {
      const first = (f.value || '').split('\n').find((l) => l.trim()) || '';
      rows.push({ key: `f:${f.id}`, label: name, icon: 'info', sub: `${first.slice(0, 140)}${(f.value || '').length > first.length ? ' · {ok} read all' : ''}`,
        action: () => message(f.value || '', name) });
    } else if (f.type === 'inputbool') {
      const on = !!val(f);
      rows.push({ key: `f:${f.id}`, label: name, icon: on ? 'check' : 'power', sub: on ? 'On' : 'Off', action: () => set(f, !on) });
    } else if (f.type === 'inputselect') {
      const cur = val(f);
      const opt = (f.options || []).find(([k]) => k === String(cur));
      rows.push({ key: `f:${f.id}`, label: name, icon: 'settings', sub: opt ? opt[1] : String(cur ?? ''),
        action: async () => {
          const v = await choose((f.options || []).map(([k, l]) => [k, `${check(k === String(cur))}${l}`]), Math.max(0, (f.options || []).findIndex(([k]) => k === String(cur))));
          if (v !== null) set(f, v);
        } });
    } else if (f.type === 'inputcheckbox') {
      const cur = new Set((f.id in draft ? draft[f.id] : f.values) || []);
      const names = (f.options || []).filter(([k]) => cur.has(k)).map(([, l]) => l);
      rows.push({ key: `f:${f.id}`, label: name, icon: 'settings', sub: names.length ? names.join(', ').slice(0, 140) : 'None chosen',
        action: () => {
          const show = (i) => Options.show([
            ...(f.options || []).map(([k, l], j) => ({ label: `${cur.has(k) ? '✓' : '–'}  ${l}`, action: () => { if (cur.has(k)) cur.delete(k); else cur.add(k); draft[f.id] = [...cur]; show(j); } })),
            { label: 'Done', action: () => reloadFolder() }], i);
          show(0);
        } });
    } else if (f.type === 'displayimage') {
      rows.push({ key: `f:${f.id}`, label: name, icon: 'photo', sub: 'A picture to type into the next box ({ok} to see it)',
        action: () => jkCaptcha(ix, form, f, draft) });
    } else if (f.type === 'password' || (f.type === 'inputstring' && f.id === 'password')) {
      rows.push({ key: `f:${f.id}`, label: name, icon: 'account', sub: f.id in draft ? '•••••• (new, not saved yet)' : f.set ? 'Saved (•••••• — {ok} to change)' : 'Not set',
        action: async () => {
          const r = await Dialog.ask({ title: `${ix.name}: ${name}`, buttons: ['OK', 'Cancel'], fields: [{ key: 'v', label: name, secret: true }] });
          if (r.button === 0 && r.values.v) set(f, r.values.v);
        } });
    } else {   // inputstring, inputtags
      const cur = val(f) ?? '';
      const secretish = /cookie|key|token|pid|passkey|rss/i.test(f.id);
      rows.push({ key: `f:${f.id}`, label: name, icon: 'keyboard',
        sub: cur ? (secretish ? `•••••• ${String(cur).slice(-4)}` : String(cur)) : 'Not set',
        action: async () => {
          const r = await Dialog.ask({ title: `${ix.name}: ${name}`, buttons: ['OK', 'Cancel'],
            fields: [{ key: 'v', label: name, value: secretish ? '' : String(cur), secret: secretish }],
            body: f.type === 'inputtags' ? 'Separate several with commas.' : secretish ? 'Paste it from your account page on the site (the on-screen keyboard can paste).' : '' });
          if (r.button === 0) set(f, r.values.v.trim());
        } });
    }
  }
  const changed = Object.keys(draft).length;
  rows.push({ key: 'save', label: ix.configured ? 'Save & Test' : 'Add & Test', icon: 'check',
    sub: ix.configured ? (changed ? `${changed} change${changed === 1 ? '' : 's'} to save` : 'Nothing changed · {ok} tests it again') : 'Jackett checks it works (and signs in, for an account)',
    action: () => jkSave(ix) });
  if (ix.configured) {
    rows.push({ key: 'remove', label: 'Remove This Tracker', icon: 'power', action: () => jkRemove(ix) });
    if (changed) rows.push({ key: 'undo', label: 'Undo Changes', icon: 'refresh', action: () => { delete JK_DRAFT[ix.id]; reloadFolder(); } });
  }
  rows.push({ key: 'web', label: 'Set Up in Jackett\'s Web Page', icon: 'browser', sub: 'For anything this form can\'t do (Jackett\'s own page, in the browser)',
    action: () => jkWebPage() });
  return rows;
}

async function jkCaptcha(ix, form, f, draft) {
  const text = form.find((x) => x.type === 'inputstring' && /captcha/i.test(x.id) && x.id !== f.id);
  const p = Dialog.ask({ title: `${ix.name}: type what the picture shows`, buttons: ['OK', 'Cancel'],
    body: 'Type the letters and numbers in the picture (it changes each time Jackett asks the site).',
    fields: text ? [{ key: 'v', label: text.name || 'Text', value: draft[text.id] || '' }] : [] });
  const body = $('.dlg-body');
  if (body && f.image) body.insertAdjacentHTML('afterbegin', `<img alt="" src="${esc(f.image)}" style="display:block;max-width:640px;max-height:260px;margin:0 auto 18px;background:#fff;border-radius:6px">`);
  const r = await p;
  if (r.button === 0 && text) { draft[text.id] = (r.values.v || '').trim(); reloadFolder(); }
}

async function jkSave(ix) {
  toast(`${ix.configured ? 'Saving' : 'Adding'} ${ix.name}: Jackett is checking it…`, 'search');
  const r = await api.post('/api/jackett/config', { id: ix.id, values: JK_DRAFT[ix.id] || {} }).catch((e) => ({ error: e.message }));
  if (r?.error || !r) {
    message(`${ix.name} didn't work:\n\n${r?.error || 'no answer from Jackett'}\n\nCheck the details and try again. A site behind Cloudflare may need FlareSolverr (Jackett › Settings).`, 'Jackett');
    reloadFolder();
    return;
  }
  delete JK_DRAFT[ix.id];
  toast(`${ix.name} is in Search`, 'check');
  Sfx.ok();
  back();
}

function jkWebPage() {
  const url = 'http://127.0.0.1:9117/UI/Dashboard';
  if (typeof openBrowser === 'function') openBrowser(url); else message(url, 'Jackett');
}

function jkTrackerList(key, label, sub, filter) {
  return { key, label, icon: 'folder', sub,
    children: async () => {
      const all = (await api.get('/api/jackett/indexers')).filter(filter);
      if (!all.length) return [{ key: 'none', label: 'Nothing here', icon: 'info' }];
      return jkLetterFolders(key, all, jkTrackerRow);
    } };
}

const JACKETT_FOLDER = {
  key: 'jackett', label: 'Jackett', icon: 'search', sub: 'Hundreds of torrent sites in one search — public, and private with your account',
  children: async () => {
    const st = await api.get('/api/jackett').catch((e) => ({ error: e.message }));
    const about = { key: 'about', label: 'How Jackett Works', icon: 'info', sub: 'One search across the sites you add',
      action: () => message([
        'Jackett (github.com/Jackett/Jackett) knows how to search hundreds of torrent sites, including private',
        'ones you have an account with. Add the sites you use here, and Torrents › Search looks through all of them',
        'at once, next to your search plugins (each site\'s results and problems are shown).',
        '', 'Crossbar downloads the official Jackett build into your home folder and runs it on this console only',
        '(127.0.0.1:9117). Your trackers and sign-ins are kept by Jackett in ~/.config/Jackett.',
        '', 'Sites behind Cloudflare\'s "checking your browser" page need FlareSolverr: set its address in Settings.'].join('\n'), 'Jackett') };
    if (!st.installed) {
      return [{ key: 'install', label: 'Install Jackett', icon: 'download', sub: 'Downloads the official Linux build from Jackett\'s GitHub (about 50 MB)',
        action: async () => { if (await jkPost('install', {}, 'Installing Jackett…')) { pollJobs(); setTimeout(reloadFolder, 1500); } } }, about];
    }
    if (!st.running) {
      return [{ key: 'start', label: 'Start Jackett', icon: 'power', sub: st.error || `Installed${st.version ? ` · ${st.version}` : ''} · not running`,
        action: async () => { toast('Starting Jackett…', 'search'); if (await jkPost('start')) reloadFolder(); } }, about];
    }
    const items = [];
    items.push({ key: 'state', label: `Jackett ${st.version || ''}`.trim(), icon: st.error ? 'info' : 'check',
      sub: st.error ? `⚠ ${st.error}` : `${st.configured} tracker${st.configured === 1 ? '' : 's'} · in Search: ${st.search ? 'on' : 'off'} ({ok} turn ${st.search ? 'off' : 'on'})`,
      action: async () => { if (st.error) { message(st.error, 'Jackett'); return; } if (await jkPost('settings', { search: !st.search }, `Jackett in Search: ${st.search ? 'off' : 'on'}`)) reloadFolder(); } });
    if (st.error) items.push({ key: 'pw', label: 'Admin Password…', icon: 'account', sub: 'If you gave Jackett a password in its web page', action: jkPassword });
    items.push({ key: 'mine', label: 'Your Trackers', icon: 'check', sub: st.configured ? `${st.configured} added` : 'None yet: Add a Tracker',
      children: async () => {
        const mine = await api.get('/api/jackett/indexers?configured=1');
        if (!mine.length) return [{ key: 'none', label: 'No trackers yet', icon: 'info', sub: 'Add a Tracker, then search from Torrents › Search' }];
        return mine.map(jkTrackerRow);
      } });
    items.push({ key: 'add', label: 'Add a Tracker', icon: 'add', sub: 'Every site Jackett supports',
      children: async () => {
        const all = await api.get('/api/jackett/indexers');
        const n = (t) => all.filter((i) => i.type_name === t).length;
        return [
          { key: 'find', label: 'Find by Name…', icon: 'search', sub: `${all.length} sites`,
            action: async () => {
              const r = await Dialog.ask({ title: 'Find a Tracker', buttons: ['Find', 'Cancel'], fields: [{ key: 'q', label: 'Site name (part of it is fine)' }] });
              const q = r.button === 0 ? r.values.q.trim().toLowerCase() : '';
              if (!q) return;
              const hits = all.filter((i) => i.name.toLowerCase().includes(q) || i.id.includes(q) || i.site.toLowerCase().includes(q));
              openFolder({ key: `jfind:${q}`, label: `“${r.values.q.trim()}”`, icon: 'search',
                children: async () => (hits.length ? hits.map(jkTrackerRow) : [{ key: 'none', label: 'No site by that name', icon: 'info' }]) });
            } },
          jkTrackerList('jpub', 'Public', `${n('Public')} sites · no account needed`, (i) => i.type_name === 'Public'),
          jkTrackerList('jsemi', 'Semi-Private', `${n('Semi-Private')} sites · free account`, (i) => i.type_name === 'Semi-Private'),
          jkTrackerList('jpriv', 'Private', `${n('Private')} sites · your account (invite only)`, (i) => i.type_name === 'Private'),
        ];
      } });
    items.push({ key: 'settings', label: 'Settings', icon: 'settings', sub: 'FlareSolverr, admin password, start-up, update',
      children: async () => {
        const s = await api.get('/api/jackett');
        return [
          { key: 'fs', label: 'FlareSolverr', icon: 'network', sub: s.flaresolverr || 'Not set · for sites behind Cloudflare\'s browser check',
            action: async () => {
              const r = await Dialog.ask({ title: 'FlareSolverr', buttons: ['Save', 'Cancel'], fields: [{ key: 'u', label: 'Address (e.g. http://127.0.0.1:8191), or empty', value: s.flaresolverr || '' }],
                body: 'FlareSolverr solves Cloudflare\'s checks for Jackett. Run it yourself (it\'s a separate program),\nthen enter its address. Jackett restarts to use it.' });
              if (r.button === 0 && await jkPost('settings', { flaresolverr: r.values.u.trim() }, 'FlareSolverr saved')) setTimeout(reloadFolder, 2500);
            } },
          { key: 'pw', label: 'Admin Password', icon: 'account', sub: s.has_password ? 'Saved' : 'None (only needed if you set one in Jackett\'s web page)', action: jkPassword },
          { key: 'auto', label: 'Start with Crossbar', icon: s.autostart ? 'check' : 'power', sub: s.autostart ? 'On · ready when you search' : 'Off · starts when you open Jackett',
            action: async () => { if (await jkPost('settings', { autostart: !s.autostart })) reloadFolder(); } },
          ...(s.ours ? [{ key: 'update', label: 'Update Jackett', icon: 'refresh', sub: `Installed: ${s.version || '?'} · gets the newest release`,
            action: async () => { if (await jkPost('install', {}, 'Updating Jackett…')) pollJobs(); } }] : []),
          { key: 'web', label: 'Open Jackett\'s Web Page', icon: 'browser', sub: 'Everything else Jackett has, in the browser', action: jkWebPage },
          { key: 'stop', label: 'Stop Jackett', icon: 'power', sub: 'Until you open Jackett or start Crossbar again',
            action: async () => { if (await jkPost('stop', {}, 'Jackett stopped')) { back(); reloadFolder(); } } },
        ];
      } });
    items.push(about);
    return items;
  },
};

async function jkPassword() {
  const r = await Dialog.ask({ title: 'Jackett Admin Password', buttons: ['Save', 'Cancel'], fields: [{ key: 'p', label: 'Password (empty if none)', secret: true }],
    body: 'Only if you set an admin password in Jackett\'s own web page: Crossbar signs in with it.' });
  if (r.button === 0 && await jkPost('settings', { admin_password: r.values.p }, 'Saved')) reloadFolder();
}
