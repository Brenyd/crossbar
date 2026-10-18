'use strict';
// Social: Discord voice channels you can join/leave right here, plus other voice apps.

async function discordAction(action, body = {}, ok) {
  const r = await call(() => api.post(`/api/discord/${action}`, body), ok);
  setTimeout(() => (S.stack.length ? reloadFolder() : refresh('party')), 300);
  return r;
}

async function joinVoice(ch, current) {
  if (current && current.id === ch.id) return discordAction('leave', {}, `Left ${ch.name}`);
  let r = await call(() => api.post('/api/discord/join', { channel_id: ch.id }));
  if (r?.already) {
    if (!(await confirmBox(`You're in ${current?.name || 'another voice channel'}.\nMove to ${ch.name}?`))) return;
    r = await call(() => api.post('/api/discord/join', { channel_id: ch.id, force: true }));
  }
  if (r?.channel) { Sfx.ok(); toast(`Joined ${ch.name}`, 'voice'); }
  setTimeout(() => (S.stack.length ? reloadFolder() : refresh('party')), 300);
}

async function setupDiscord() {
  const st = await api.get('/api/discord/state');
  const intro = 'One-time setup (Discord requires it for apps that control voice):\n' +
    '1. On any device: discord.com/developers/applications › New Application.\n' +
    '2. OAuth2 › Redirects: add http://127.0.0.1:7777/discord/callback and save.\n' +
    '3. App Testers: add your Discord username, then accept the invite Discord sends you.\n' +
    '   (Without this Discord refuses with "invalid scope".)\n' +
    '4. Copy the Client ID and Client Secret (OAuth2 page) into the boxes below.\n' +
    'Discord then opens and asks you to approve Crossbar once.';
  const r = await Dialog.ask({ title: 'Set Up Discord', body: intro, buttons: ['Continue', 'Cancel'],
    fields: [{ key: 'client_id', label: 'Client ID', value: '' }, { key: 'client_secret', label: 'Client Secret', secret: true }] });
  if (r.button !== 0) return;
  if (r.values.client_id.trim() || !st.configured) {
    if (!r.values.client_id.trim() || !r.values.client_secret.trim()) return toast('Both the Client ID and Client Secret are needed', 'info');
    await api.post('/api/discord/config', r.values);
  }
  toast('Discord will open — sign in if asked, then approve Crossbar', 'voice');
  await call(() => api.post('/api/discord/link'));
  pollJobs();
}

function memberLine(members) {
  if (!members) return '';
  if (!members.length) return 'Nobody here';
  const names = members.slice(0, 4).map((m) => m.name + (m.muted ? ' 🔇' : '')).join(', ');
  return `${members.length} in channel: ${names}${members.length > 4 ? '…' : ''}`;
}

function addChannelFolder() {
  return {
    key: 'add-voice', label: 'Add Voice Channel…', icon: 'add', sub: 'Pick from your servers',
    children: async () => {
      const guilds = await api.get('/api/discord/guilds');
      if (!guilds.length) return [{ key: 'none', label: 'No servers found', icon: 'info' }];
      return guilds.map((g) => ({
        key: `g:${g.id}`, label: g.name, icon: 'folder',
        children: async () => {
          const chans = await api.get(`/api/discord/channels?guild_id=${encodeURIComponent(g.id)}`);
          if (!chans.length) return [{ key: 'none', label: 'No voice channels', icon: 'info' }];
          return chans.map((c) => ({ key: `c:${c.id}`, label: c.name, icon: 'voice', sub: 'A: add to Social',
            action: async () => { await call(() => api.post('/api/discord/save', { id: c.id, name: c.name, guild: g.name, guild_id: g.id }), `Added ${c.name}`); } }));
        },
      }));
    },
  };
}

async function socialItems() {
  const items = [];
  const d = await api.get('/api/discord/state').catch(() => ({ configured: false }));
  if (!d.configured || !d.linked) {
    items.push({ key: 'dc-setup', label: 'Set Up Discord', icon: 'voice', sub: 'Join voice channels straight from Crossbar', action: setupDiscord });
  } else {
    const cur = d.channel;
    if (cur) {
      items.push({ key: 'dc-cur', label: `In Voice: ${cur.name}`, icon: 'voice', badge: d.mute ? 'MUTED' : 'LIVE',
        sub: memberLine(cur.members), action: () => discordAction('leave', {}, `Left ${cur.name}`),
        options: [{ label: 'Leave', action: () => discordAction('leave', {}, `Left ${cur.name}`) },
                  { label: d.mute ? 'Unmute Microphone' : 'Mute Microphone', action: () => discordAction('mute') },
                  { label: d.deaf ? 'Undeafen' : 'Deafen', action: () => discordAction('deaf') }] });
      items.push({ key: 'dc-mute', label: d.mute ? 'Unmute Microphone' : 'Mute Microphone', icon: 'mic', action: () => discordAction('mute') });
      items.push({ key: 'dc-deaf', label: d.deaf ? 'Undeafen' : 'Deafen', icon: 'sound', action: () => discordAction('deaf') });
    }
    if (!d.running) items.push({ key: 'dc-start', label: 'Start Discord', icon: 'voice', sub: 'Discord isn\'t running', action: () => discordAction('open') });
    else if (d.error) items.push({ key: 'dc-err', label: 'Discord isn\'t answering', icon: 'info', sub: d.error, action: setupDiscord });
    for (const c of d.saved || []) {
      const here = cur && cur.id === c.id;
      items.push({
        key: `dc:${c.id}`, label: c.name, icon: 'voice', badge: here ? 'JOINED' : '',
        sub: [c.guild, here ? 'A: leave' : memberLine(c.members)].filter(Boolean).join(' · '),
        action: () => joinVoice(c, cur),
        options: [{ label: here ? 'Leave' : 'Join', action: () => joinVoice(c, cur) },
                  { label: 'Remove from Social', action: () => discordAction('remove', { id: c.id }, `Removed ${c.name}`) }],
      });
    }
    if (d.connected) items.push(addChannelFolder());
    items.push({ key: 'dc-open', label: 'Open Discord', icon: 'window', sub: 'Text chat, friends, settings — Guide combo to come back', action: () => discordAction('open') });
    items.push({ key: 'dc-relink', label: 'Discord Account', icon: 'account', sub: d.user ? `Linked · ${d.user}` : 'Linked',
      options: [{ label: 'Link Again', action: setupDiscord },
                { label: 'Unlink', action: async () => { if (await confirmBox('Unlink Discord from Crossbar?')) discordAction('unlink'); } }],
      action: () => Options.show([{ label: 'Link Again', action: setupDiscord },
                                  { label: 'Unlink', action: async () => { if (await confirmBox('Unlink Discord from Crossbar?')) discordAction('unlink'); } }]) });
  }
  // other voice apps (Mumble, TeamSpeak, Element…) and saved links, as before
  const pty = S.state.party;
  items.push({ key: 'other', label: 'Other Voice Apps', icon: 'folder', sub: 'Mumble, TeamSpeak, Element, links',
    children: async () => [
      ...S.state.party.services.filter((x) => !x.id.startsWith('discord')).map((x) => ({
        key: `svc:${x.id}`, label: x.name, icon: 'voice', sub: x.native ? 'Installed' : x.available ? 'Runs in a web window' : 'Not installed',
        action: () => call(() => api.post('/api/party/start', { service: x.id }), `Opening ${x.name}…`) })),
      ...pty.channels.map((c, i) => ({ key: `ch:${i}`, label: c.name, icon: 'link', sub: c.url,
        action: () => call(() => api.post('/api/party/start', { url: c.url }), `Joining ${c.name}…`),
        options: [{ label: 'Remove', action: async () => { S.state = await api.post('/api/party/remove', { index: i }); reloadFolder(); } }] })),
      { key: 'add', label: 'Add Link…', icon: 'add', sub: 'mumble://, Matrix room or other voice link', action: addChannel },
    ] });
  return items;
}
