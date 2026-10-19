'use strict';
// the little tag next to a ROM's name (like [STEAM] on store games); Y › Edit Tag… changes it
const SYSTEM_TAGS = { nes: 'NES', snes: 'SNES', n64: 'N64', gb: 'GB', gbc: 'GBC', gba: 'GBA', nds: 'DS', n3ds: '3DS', gc: 'GAMECUBE', wii: 'WII',
  wiiu: 'WII U', switch: 'SWITCH', mastersystem: 'SMS', genesis: 'GENESIS', segacd: 'SEGA CD', gamegear: 'GAME GEAR', saturn: 'SATURN',
  dreamcast: 'DREAMCAST', psx: 'PS1', ps2: 'PS2', ps3: 'PS3', psp: 'PSP', xbox: 'XBOX', pcengine: 'PC ENGINE', atari2600: '2600',
  arcade: 'ARCADE', scummvm: 'SCUMMVM' };
// Game › Emulation (Emulators, ROMs) and Settings › Games & Emulation › Emulation. EmuDeck-style folders:
// ~/Emulation/roms/<system> for games, ~/Emulation/bios for BIOS files.

const ASPECT_NAMES = { auto: 'Original (as the game intended)', '4:3': '4:3', '16:9': '16:9 (widescreen)', stretch: 'Stretch to fill' };

async function emuInstall(e) {
  if (!(await confirmBox(`Install ${e.name}?\nIt's downloaded from Flathub${e.kind === 'appimage' ? ' (AppImage from its developer)' : ''} and set up for your Emulation folder.`, 'Emulators'))) return;
  const r = await call(() => api.post('/api/emulation/install', { emu: e.id }));
  if (r) { toast(`Installing ${e.name}…`, 'download'); pollJobs(); }
}

function emulatorsFolder() {
  return {
    key: 'emus', label: 'Emulators', icon: 'game', sub: 'Install and set up emulators',
    children: async () => {
      const list = await api.get('/api/emulation/emulators');
      const st = await api.get('/api/emulation');
      const items = [];
      if (!st.flatpak) items.push({ key: 'nofp', label: 'Flatpak isn\'t installed', icon: 'info', sub: 'Most emulators install through Flatpak: sudo pacman -S flatpak' });
      for (const e of list) {
        const job = S.jobs.find((j) => j.kind === 'install' && j.title === e.name && j.status === 'running');
        items.push({
          key: `emu:${e.id}`, label: e.name, icon: e.installed ? 'check' : 'download', badge: e.installed ? 'INSTALLED' : '',
          sub: job ? `Installing… ${job.message}` : (e.systems.length > 1 ? `${e.about} · ${e.systems.slice(0, 4).join(', ')}${e.systems.length > 4 ? '…' : ''}` : e.about),
          progress: job ? job.progress : null,
          action: () => (e.installed ? emuOptions(e) : emuInstall(e)),
          options: job && job.cancellable ? [{ label: 'Cancel Install', action: () => cancelJob(job) }]
            : e.installed ? emuOptionList(e) : [{ label: 'Install', action: () => emuInstall(e) }],
        });
      }
      return items;
    },
  };
}
function emuOptionList(e) {
  return [
    { label: 'Open Settings & Controls', action: () => call(() => api.post('/api/emulation/configure', { emu: e.id }), `Opening ${e.name}…`) },
    { label: 'Uninstall', action: async () => { if (await confirmBox(`Uninstall ${e.name}?\nYour games, BIOS files and saves stay.`)) { await call(() => api.post('/api/emulation/uninstall', { emu: e.id }), `${e.name} removed`); reloadFolder(); } } },
  ];
}
function emuOptions(e) { Options.show(emuOptionList(e)); }

function launchRom(sys, g) {
  Sfx.ok();
  return call(() => api.post('/api/launch', { provider: 'emu', id: `${sys.id}/${g.id}`, title: g.title }), `Starting ${g.title}…`);
}

async function chooseEmulator(sys) {
  const [choices, st] = await Promise.all([api.get(`/api/emulation/choices?system=${sys.id}`), api.get('/api/emulation')]);
  const cur = st.emulator_choice[sys.id] || choices[0]?.value;
  Options.show(choices.map((c) => ({ label: `${check(c.value === cur)}${c.label}${c.installed ? '' : ' — not installed'}`,
    action: async () => { await call(() => api.post('/api/emulation/choose', { system: sys.id, value: c.value }), `${sys.name}: ${c.label}`); } })),
    Math.max(0, choices.findIndex((c) => c.value === cur)));
}

function romsFolder() {
  return {
    key: 'roms', label: 'ROMs', icon: 'folder', sub: 'Your games, by system',
    children: async () => {
      const [systems, st] = await Promise.all([api.get('/api/emulation/systems'), api.get('/api/emulation')]);
      if (!systems.length) {
        return [{ key: 'none', label: 'No games yet', icon: 'info', sub: `Put games in ${st.roms}/<system> (e.g. snes, psx, ps2)`,
                  action: () => message(`Copy your games into:\n${st.roms}/<system>\n\nFor example roms/snes, roms/psx, roms/ps2, roms/gc.\nA system shows up here once it has a game.\n\nBIOS files go in:\n${st.bios}`, 'Emulation') },
                { key: 'mk', label: 'Create ROM Folders', icon: 'add', sub: 'Makes a folder for every system', action: async () => { const r = await call(() => api.post('/api/emulation/folders')); if (r) toast(`Folders ready in ${r.path}`, 'folder'); } }];
      }
      return systems.map((sys) => ({
        key: `sys:${sys.id}`, label: sys.name, icon: ICONS[`sys-${sys.id}`] ? `sys-${sys.id}` : 'folder', sub: `${sys.count} game${sys.count === 1 ? '' : 's'}`,
        options: [{ label: 'Choose Emulator', action: () => chooseEmulator(sys) }],
        children: async () => (await api.get(`/api/emulation/games?system=${sys.id}`)).map((g) => ({
          key: `rom:${sys.id}:${g.id}`, label: g.title, art: g.art || '', artTitle: g.title, sub: g.tags || '', badge: SYSTEM_TAGS[sys.id] || sys.id.toUpperCase(),
          action: () => launchRom(sys, g),
          options: [{ label: 'Play', action: () => launchRom(sys, g) }, { label: 'Choose Emulator', action: () => chooseEmulator(sys) },
            { label: 'Change Artwork…', action: () => changeArtwork({ key: `rom:${sys.id}:${g.id}`, title: g.title, custom: !!g.art_custom }) }],
        })),
      }));
    },
  };
}

const EMULATION_FOLDER = {
  key: 'emulation', label: 'Emulation', icon: 'retro', sub: 'Classic consoles: your games and emulators',
  children: async () => [romsFolder(), emulatorsFolder()],
};

// ---- Settings › Games & Emulation › Emulation -----------------------------------------------------------------------
async function raSignIn() {
  const r = await Dialog.ask({ title: 'RetroAchievements', buttons: ['Sign In', 'Cancel'],
    body: 'Your retroachievements.org account. The password is only used to sign in; emulators get a token.\nThe Web API key (retroachievements.org › Settings) lets Trophies show your progress.',
    fields: [{ key: 'user', label: 'Username' }, { key: 'password', label: 'Password', secret: true }, { key: 'web_key', label: 'Web API key (optional, for Trophies)' }] });
  if (r.button !== 0) return;
  const res = await call(() => api.post('/api/emulation/ra-login', r.values));
  if (res) { toast(`Signed in to RetroAchievements as ${res.user}`, 'trophy'); reloadFolder(); }
}

const EMU_SETTINGS = {
  key: 'emulation', label: 'Emulation', icon: 'retro', sub: 'Folders, BIOS, emulators, achievements',
  children: async () => {
    const st = await api.get('/api/emulation');
    const set = async (body, msg) => { const r = await call(() => api.post('/api/emulation/settings', body)); if (r) { toast(`${msg}${r.applied?.length ? ' · applied to ' + r.applied.join(', ') : ''}`, 'settings'); reloadFolder(); } };
    return [
      { key: 'root', label: 'Emulation Folder', icon: 'folder', sub: `${st.root} — games in roms/, BIOS in bios/`,
        action: async () => {
          const r = await Dialog.ask({ title: 'Emulation Folder', body: 'Where your roms/ and bios/ folders live (an EmuDeck folder works as-is).',
            fields: [{ key: 'root', label: 'Folder', value: st.root }], buttons: ['Save', 'Cancel'] });
          if (r.button === 0 && r.values.root.trim()) set({ root: r.values.root.trim() }, 'Emulation folder saved');
        },
        options: [{ label: 'Create ROM Folders', action: async () => { const r = await call(() => api.post('/api/emulation/folders')); if (r) toast(`Folders ready in ${r.path}`, 'folder'); } }] },
      { key: 'bios', label: 'BIOS Files', icon: 'info', sub: `Checked in ${st.bios}`,
        children: async () => (await api.get('/api/emulation/bios')).map((b) => ({
          key: `b:${b.system}`, label: b.name, icon: b.status === 'ok' ? 'check' : 'info',
          sub: b.status === 'ok' ? 'Found' : b.status === 'missing' ? 'Missing — needed to play' : 'Optional files missing',
          action: () => message([
            b.one_of.length ? `One of these is needed:\n${b.files.filter((f) => b.one_of.includes(f.file)).map((f) => `${f.found ? '✓' : '✗'} ${f.file}`).join('\n')}` : '',
            b.files.filter((f) => !b.one_of.includes(f.file)).map((f) => `${f.found ? '✓' : '✗'} ${f.file}${f.required ? ' (needed)' : ' (optional)'}${f.detail ? ' — ' + f.detail : ''}`).join('\n'),
            `\nPut them in ${st.bios}`].filter(Boolean).join('\n'), `${b.name} BIOS`),
        })) },
      { key: 'emus', label: 'Emulator Settings & Controls', icon: 'game', sub: 'Open an emulator to map buttons and fine-tune it',
        children: async () => {
          const list = (await api.get('/api/emulation/emulators')).filter((e) => e.installed);
          if (!list.length) return [{ key: 'none', label: 'No emulators installed', icon: 'info', sub: 'Game › Emulation › Emulators' }];
          return [{ key: 'tip', label: 'Controllers', icon: 'info', sub: 'Most pads are set up automatically; the Quick Menu (Select + Start) quits a game',
                    action: () => message('Controllers are detected automatically by RetroArch and the standalone emulators.\nTo change buttons, open the emulator here and use its controller settings.\nTo leave a game: Quick Menu (Select + Start) › Close.', 'Controls') },
                  ...list.map((e) => ({ key: `cfg:${e.id}`, label: e.name, icon: 'settings', sub: 'Open its settings (controls, video, audio)',
                    action: () => call(() => api.post('/api/emulation/configure', { emu: e.id }), `Opening ${e.name}…`) }))];
        } },
      { key: 'defaults', label: 'Default Emulator per System', icon: 'game', sub: 'Which emulator runs each system',
        children: async () => (await api.get('/api/emulation/all-systems')).map((sys) => ({
          key: `d:${sys.id}`, label: sys.name, icon: ICONS[`sys-${sys.id}`] ? `sys-${sys.id}` : 'folder', sub: (st.emulator_choice[sys.id] || 'Default').replace(/:$/, '').replace(':', ' · '),
          action: () => chooseEmulator(sys) })) },
      { key: 'aspect', label: 'Aspect Ratio', icon: 'display', sub: ASPECT_NAMES[st.aspect],
        action: () => Options.show(Object.entries(ASPECT_NAMES).map(([v, l]) => ({ label: `${check(st.aspect === v)}${l}`, action: () => set({ aspect: v }, `Aspect ratio: ${l}`) })),
          Math.max(0, Object.keys(ASPECT_NAMES).indexOf(st.aspect))) },
      { key: 'int', label: 'Pixel-Perfect Scaling', icon: 'display', sub: st.integer_scale ? 'On — sharp pixels, small borders (RetroArch)' : 'Off — fill the screen',
        action: () => set({ integer_scale: !st.integer_scale }, `Pixel-perfect scaling ${st.integer_scale ? 'off' : 'on'}`) },
      ...(st.ra.user ? [
        { key: 'ra', label: 'RetroAchievements', icon: 'trophy', sub: `Signed in as ${st.ra.user} · ${st.ra.enabled ? 'on' : 'off'}${st.ra.web_key ? '' : ' · add a Web API key for Trophies'}`,
          action: () => Options.show([
            { label: st.ra.enabled ? 'Turn Off' : 'Turn On', action: () => set({ ra_enabled: !st.ra.enabled }, `RetroAchievements ${st.ra.enabled ? 'off' : 'on'}`) },
            { label: `Hardcore Mode: ${st.ra.hardcore ? 'On' : 'Off'}`, action: () => set({ hardcore: !st.ra.hardcore }, `Hardcore ${st.ra.hardcore ? 'off' : 'on'}`) },
            { label: 'Web API Key (for Trophies)…', action: async () => { const r = await Dialog.ask({ title: 'RetroAchievements Web API Key', body: 'retroachievements.org › Settings › Keys', fields: [{ key: 'k', label: 'Web API key' }], buttons: ['Save', 'Cancel'] }); if (r.button === 0) set({ web_key: r.values.k }, 'Web API key saved'); } },
            { label: 'Sign In Again', action: raSignIn },
            { label: 'Sign Out', action: async () => { if (await confirmBox('Sign out of RetroAchievements?')) set({ ra_signout: true }, 'Signed out'); } },
          ]) },
      ] : [{ key: 'ra', label: 'RetroAchievements', icon: 'trophy', sub: 'Sign in to earn achievements in classic games', action: raSignIn }]),
      { key: 'apply', label: 'Apply to Emulators Again', icon: 'refresh', sub: 'Re-write these settings into every installed emulator',
        action: () => set({}, 'Settings applied') },
    ];
  },
};
SETTINGS_FOLDERS.push(EMU_SETTINGS);
SETTINGS_ORDER.splice(SETTINGS_ORDER.indexOf('games') + 1, 0, 'emulation');
SETTINGS_FOLDERS.sort((a, b) => SETTINGS_ORDER.indexOf(a.key) - SETTINGS_ORDER.indexOf(b.key));
