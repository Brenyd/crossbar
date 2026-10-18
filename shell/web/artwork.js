'use strict';
// Game artwork from SteamGridDB: "Change Artwork…" on any game or ROM, plus Settings › Games & Emulation › Artwork.

async function sgdbKeyDialog() {
  const r = await Dialog.ask({ title: 'SteamGridDB', buttons: ['Save', 'Cancel'],
    body: 'SteamGridDB has community artwork for almost every game.\nGet a free API key: steamgriddb.com › sign in › Preferences › API.',
    fields: [{ key: 'key', label: 'SteamGridDB API key' }] });
  if (r.button !== 0 || !r.values.key.trim()) return false;
  return !!(await call(() => api.post('/api/art/settings', { key: r.values.key.trim() }), 'SteamGridDB connected'));
}

function gridItems(target, list) {
  if (!list.length) return [{ key: 'none', label: 'No artwork found', icon: 'info', sub: 'Try Search SteamGridDB with a different name' }];
  return list.map((g) => ({
    key: `grid:${g.id}`, label: [g.style && g.style[0].toUpperCase() + g.style.slice(1), g.author && `by ${g.author}`].filter(Boolean).join(' · ') || 'Artwork',
    sub: `${g.size}${g.votes ? ` · ${g.votes > 0 ? '+' : ''}${g.votes}` : ''} · {ok} to use`,
    art: g.thumb, artTitle: target.title,
    action: async () => {
      if (!(await call(() => api.post('/api/art/set', { key: target.key, url: g.url }), `New artwork for ${target.title}`))) return;
      artDone(target);
    },
  }));
}

function artDone(target) {
  // leave the picker (everything above the folder it was opened from) and show the new art
  while (S.stack.length && S.stack.at(-1).source?.artPicker) S.stack.pop();
  refresh('game');
  if (S.stack.length) reloadFolder(); else render();
  target.done && target.done();
}

function matchFolder(target, m) {
  return { key: `m:${m.id}`, label: m.name, icon: 'game', sub: [m.year, m.verified ? 'verified' : ''].filter(Boolean).join(' · ') || 'SteamGridDB',
    artPicker: true, children: async () => gridItems(target, await api.get(`/api/art/grids?game_id=${m.id}`)) };
}

async function searchArt(target) {
  const r = await Dialog.ask({ title: 'Search SteamGridDB', buttons: ['Search', 'Cancel'], fields: [{ key: 'q', label: 'Game name', value: target.title }] });
  if (r.button !== 0 || !r.values.q.trim()) return;
  openFolder({ label: `“${r.values.q.trim()}”`, icon: 'search', artPicker: true,
    children: async () => {
      const found = await api.get(`/api/art/search?q=${encodeURIComponent(r.values.q.trim())}`);
      return found.length ? found.map((m) => matchFolder(target, m)) : [{ key: 'none', label: 'Nothing found', icon: 'info', sub: 'Try a shorter name' }];
    } });
}

// target: {key: 'steam:123' | 'rom:snes:file.sfc' …, title, steam: appid?, custom: bool}
async function changeArtwork(target) {
  let st = await api.get('/api/art').catch(() => ({}));
  if (!st.ready) {
    if (!(await confirmBox('Choosing artwork uses SteamGridDB, which needs a free API key. Add one now?', 'Change Artwork'))) return;
    if (!(await sgdbKeyDialog())) return;
  }
  openFolder({ label: `Artwork: ${target.title}`, icon: 'photo', artPicker: true,
    children: async () => {
      const items = [{ key: 'search', label: 'Search SteamGridDB…', icon: 'search', sub: 'Pick a different game or spelling', action: () => searchArt(target) }];
      if (target.custom) {
        items.push({ key: 'reset', label: 'Use Original Artwork', icon: 'refresh', sub: 'Forget your pick for this game',
          action: async () => { if (await call(() => api.post('/api/art/reset', { key: target.key }), 'Artwork reset')) artDone(target); } });
      }
      if (target.steam) {
        items.push(...gridItems(target, await api.get(`/api/art/grids?steam_appid=${encodeURIComponent(target.steam)}`)).filter((i) => i.key !== 'none'));
      } else {
        const found = await api.get(`/api/art/search?q=${encodeURIComponent(target.title.replace(/[([][^)\]]*[)\]]/g, ' ').trim())}`);
        if (found.length) {
          items.push(...gridItems(target, await api.get(`/api/art/grids?game_id=${found[0].id}`)).filter((i) => i.key !== 'none'));
          if (found.length > 1) {
            items.push({ key: 'other', label: 'Other Matches', icon: 'folder', sub: `${found.length - 1} more on SteamGridDB`, artPicker: true,
              children: async () => found.slice(1).map((m) => matchFolder(target, m)) });
          }
        }
      }
      if (items.length <= (target.custom ? 2 : 1)) items.push({ key: 'none', label: 'No artwork found', icon: 'info', sub: 'Try Search SteamGridDB with a different name' });
      return items;
    } });
}

const ART_SETTINGS = {
  key: 'artwork', label: 'Artwork', icon: 'photo', sub: 'Game pictures from SteamGridDB',
  children: async () => {
    const st = await api.get('/api/art');
    return [
      { key: 'key', label: 'SteamGridDB API Key', icon: 'account', sub: st.ready ? 'Connected — {ok} to change' : 'Not set — free key at steamgriddb.com › Preferences › API',
        action: async () => { if (await sgdbKeyDialog()) { refresh('game'); reloadFolder(); } },
        options: st.ready ? [{ label: 'Remove Key', action: async () => { await call(() => api.post('/api/art/settings', { key: '' }), 'Key removed'); reloadFolder(); } }] : [] },
      { key: 'auto', label: 'Fill In Missing Artwork', icon: 'photo',
        sub: !st.ready ? 'Needs the API key' : st.auto ? 'On — games and ROMs without pictures get one automatically' : 'Off',
        action: async () => { if (!st.ready) return; await call(() => api.post('/api/art/settings', { auto: !st.auto })); refresh('game'); reloadFolder(); } },
      { key: 'how', label: 'Change a Game\'s Artwork', icon: 'info', sub: 'Highlight a game, press {menu}, choose Change Artwork…',
        action: () => message(gl('Highlight any game or ROM, press {menu} for options and choose Change Artwork….\nYou can pick from community artwork or search for a different game.'), 'Artwork') },
      { key: 'reset', label: 'Reset All Artwork', icon: 'refresh', sub: st.overrides ? `${st.overrides} game${st.overrides === 1 ? '' : 's'} with your own pick` : 'Nothing changed yet',
        action: async () => { if (await confirmBox('Go back to the original artwork for every game?')) { await call(() => api.post('/api/art/reset-all'), 'Artwork reset'); refresh('game'); reloadFolder(); } } },
    ];
  },
};

SETTINGS_FOLDERS.push(ART_SETTINGS);
SETTINGS_ORDER.splice(SETTINGS_ORDER.indexOf('games') + 1, 0, 'artwork');
