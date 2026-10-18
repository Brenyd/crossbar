'use strict';
// Game › Trophies: RetroAchievements (by console) and Steam.

function achievementItems(data) {
  const list = data.achievements || [];
  if (!list.length) return [{ key: 'none', label: data.note || 'No achievements', icon: 'info' }];
  const got = list.filter((a) => a.earned).length;
  return [
    { key: 'sum', label: `${got} of ${list.length} unlocked`, icon: 'trophy', sub: data.title + (data.console ? ` · ${data.console}` : ''),
      progress: list.length ? got / list.length : 0 },
    ...list.map((a, i) => ({
      key: `a:${i}`, label: a.title, sub: [a.earned ? `Unlocked ${a.when}${a.hardcore ? ' · hardcore' : ''}` : 'Locked',
        a.points ? `${a.points} pts` : '', a.desc].filter(Boolean).join(' · '),
      ...(a.icon ? { art: a.icon, artTitle: a.title, artShape: 'poster' } : { icon: a.earned ? 'trophy' : 'info' }),
      badge: a.earned ? '' : 'LOCKED',
      action: () => message(`${a.title}\n\n${a.desc || ''}\n\n${a.earned ? `Unlocked ${a.when}` : 'Not unlocked yet'}${a.points ? ` · ${a.points} points` : ''}`, data.title),
    })),
  ];
}

function raFolder(st) {
  return {
    key: 'ra', label: 'RetroAchievements', icon: 'trophy',
    sub: st.ra.ready ? `${st.ra.user} · by console` : 'Sign in and add your Web API key in Settings › Games & Emulation › Emulation',
    children: async () => {
      if (!st.ra.ready) return [{ key: 'setup', label: 'Set Up RetroAchievements', icon: 'settings', sub: 'Settings › Games & Emulation › Emulation › RetroAchievements', action: () => openSettingsFolder('emulation') }];
      const d = await api.get('/api/trophies/ra');
      const items = [{ key: 'me', label: d.user, icon: 'user', sub: `${d.points} points${d.hardcore_points ? ` · ${d.hardcore_points} hardcore` : ''}${d.rank ? ` · rank #${d.rank}` : ''}`,
        ...(d.pic ? { art: d.pic, artTitle: d.user, artShape: 'poster' } : {}) }];
      if (!d.consoles.length) items.push({ key: 'none', label: 'No achievements yet', icon: 'info', sub: 'Play a supported game with RetroAchievements on' });
      for (const c of d.consoles) {
        items.push({ key: `c:${c.id}`, label: c.name, icon: 'folder', sub: `${c.games.length} game${c.games.length === 1 ? '' : 's'} · ${c.earned}/${c.total} unlocked`,
          progress: c.total ? c.earned / c.total : 0,
          children: async () => c.games.map((g) => ({
            key: `g:${g.id}`, label: g.title, sub: `${g.earned}/${g.total}${g.award ? ' · ' + g.award.replace('-', ' ') : ''}`,
            progress: g.total ? g.earned / g.total : 0,
            ...(g.icon ? { art: g.icon, artTitle: g.title, artShape: 'poster' } : { icon: 'game' }),
            children: async () => achievementItems(await api.get(`/api/trophies/ra/game?id=${g.id}`)),
          })) });
      }
      return items;
    },
  };
}

async function steamSetup(st) {
  const r = await Dialog.ask({ title: 'Steam Achievements', buttons: ['Save', 'Cancel'],
    body: 'Get a free Steam Web API key at steamcommunity.com/dev/apikey (any domain name works).\nUsed for achievements and Social › Friends. In Steam\'s privacy settings, Game details and Friends List must be Public.',
    fields: [{ key: 'key', label: 'Steam Web API key' }, { key: 'steamid', label: 'SteamID64 (leave empty to use this console\'s Steam)', value: '' }] });
  if (r.button !== 0) return;
  if (await call(() => api.post('/api/trophies/steam-setup', r.values), 'Steam achievements set up')) reloadFolder();
}

function steamFolder(st) {
  return {
    key: 'steam', label: 'Steam', icon: 'trophy', sub: st.steam.ready ? 'Your games, most recent first' : 'Needs a Steam Web API key',
    options: [{ label: 'Set Up…', action: () => steamSetup(st) }],
    children: async () => {
      if (!st.steam.ready) return [{ key: 'setup', label: 'Set Up Steam Achievements', icon: 'settings', sub: 'A free key from steamcommunity.com/dev/apikey', action: () => steamSetup(st) }];
      const games = await api.get('/api/trophies/steam');
      if (!games.length) return [{ key: 'none', label: 'No played games found', icon: 'info', sub: 'Is your Steam profile\'s Game details setting Public?' }];
      return games.map((g) => ({ key: `s:${g.id}`, label: g.title, sub: `${g.hours} h played`, art: g.icon, artTitle: g.title,
        children: async () => achievementItems(await api.get(`/api/trophies/steam/game?id=${g.id}`)) }));
    },
  };
}

const TROPHIES_FOLDER = {
  key: 'trophies', label: 'Trophies', icon: 'trophy', sub: 'RetroAchievements and Steam achievements',
  children: async () => {
    const st = await api.get('/api/trophies');
    return [raFolder(st), steamFolder(st)];
  },
};
