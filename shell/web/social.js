'use strict';
// Social: Discord voice channels you can join/leave right here (through Discord's own web
// client, see crossbar/discordweb.py), plus other voice apps.

async function discordAction(action, body = {}, ok) {
  const r = await call(() => api.post(`/api/discord/${action}`, body), ok);
  setTimeout(() => (S.stack.length ? reloadFolder() : refresh('party')), 300);
  return r;
}

async function joinVoice(ch, cur) {
  if (cur && cur.channel_id === ch.id) return discordAction('leave', {}, `Left ${ch.name}`);
  if (cur && !(await confirmBox(`You're in ${cur.channel}.\nMove to ${ch.name}?`))) return;
  toast(`Joining ${ch.name}…`, 'voice');
  const r = await call(() => api.post('/api/discord/join', { guild_id: ch.guild_id, channel_id: ch.id }));
  if (r?.voice) { Sfx.ok(); toast(`Joined ${ch.name}`, 'voice'); }
  setTimeout(() => (S.stack.length ? reloadFolder() : refresh('party')), 300);
}

function openDiscord(msg) {
  toast(msg || 'Opening Discord — Quick Menu (Select + Start) brings you back', 'voice');
  return call(() => api.post('/api/discord/open'));
}

// Settings › Accounts › Discord: sign in, and pick which voice channels show up in Social
// (none by default, so Social only lists the ones you use).
function voiceChannelPicker() {
  return {
    key: 'dc-pick', label: 'Voice Channels in Social', icon: 'voice', sub: 'Choose which voice channels show up in Social',
    children: async () => {
      const st = await api.get('/api/discord/state').catch(() => ({}));
      const saved = st.saved || [];
      const guilds = await api.get('/api/discord/guilds').catch((e) => { toast(e.message, 'info'); return []; });
      if (!guilds.length) return [{ key: 'none', label: 'No servers found', icon: 'info', sub: 'Sign in to Discord first' }];
      return guilds.map((g) => ({
        key: `g:${g.id}`, label: g.name, icon: 'folder',
        sub: (() => { const n = saved.filter((x) => x.guild_id === g.id).length; return n ? `${n} shown in Social` : 'None shown'; })(),
        children: async () => {
          const chans = await api.get(`/api/discord/channels?guild_id=${encodeURIComponent(g.id)}`).catch(() => []);
          if (!chans.length) return [{ key: 'none', label: 'No voice channels found', icon: 'info', sub: 'Collapsed categories hide channels: open Discord to expand them' }];
          const now = (await api.get('/api/discord/state').catch(() => ({}))).saved || saved;
          return chans.map((c) => {
            const on = now.some((x) => x.id === c.id);
            return { key: `c:${c.id}`, label: c.name, icon: on ? 'check' : 'voice', sub: on ? 'Shown in Social — {ok} to hide' : 'Hidden — {ok} to show',
              action: async () => {
                await call(() => api.post(`/api/discord/${on ? 'remove' : 'save'}`, { id: c.id, name: c.name, guild: g.name, guild_id: g.id }),
                  on ? `${c.name} hidden` : `${c.name} shown in Social`);
                reloadFolder();
              } };
          });
        },
      }));
    },
  };
}

const DISCORD_ACCOUNT_FOLDER = {
  key: 'discord', label: 'Discord', icon: 'voice', sub: 'Sign in, voice channels shown in Social',
  children: async () => {
    const d = await api.get('/api/discord/state').catch(() => ({}));
    if (!d.signed_in) {
      return [{ key: 'signin', label: 'Sign In to Discord', icon: 'voice', sub: 'Scan the QR code with the Discord app on your phone',
        action: () => openDiscord('Scan the QR code with the Discord app on your phone, then come back with the Quick Menu') }];
    }
    return [
      voiceChannelPicker(),
      { key: 'open', label: 'Open Discord', icon: 'window', sub: 'Full client: chat, friends, Discord settings', action: () => openDiscord() },
      { key: 'out', label: 'Sign Out on This Console', icon: 'account', sub: d.error ? `Not answering: ${d.error}` : 'Signed in',
        action: async () => { if (await confirmBox('Sign out of Discord on this console?')) { await discordAction('signout'); reloadFolder(); } } },
    ];
  },
};

async function socialItems() {
  const items = [];
  const d = await api.get('/api/discord/state').catch(() => ({ running: false }));
  if (!d.signed_in) {
    items.push({ key: 'dc-signin', label: 'Sign In to Discord', icon: 'voice',
      sub: 'Discord shows a QR code: scan it with the Discord app on your phone',
      action: () => openDiscord('Scan the QR code with the Discord app on your phone, then come back with the Quick Menu') });
  } else {
    const cur = d.voice;
    if (cur) {
      items.push({ key: 'dc-cur', label: `In Voice: ${cur.channel}`, icon: 'voice', badge: d.deaf ? 'DEAFENED' : d.mute ? 'MUTED' : 'LIVE',
        sub: `${cur.guild || 'Discord'} · {ok} leave`, action: () => discordAction('leave', {}, `Left ${cur.channel}`),
        options: [{ label: 'Leave', action: () => discordAction('leave', {}, `Left ${cur.channel}`) },
                  { label: d.mute ? 'Unmute Microphone' : 'Mute Microphone', action: () => discordAction('mute') },
                  { label: d.deaf ? 'Undeafen' : 'Deafen', action: () => discordAction('deaf') }] });
      items.push({ key: 'dc-mute', label: d.mute ? 'Unmute Microphone' : 'Mute Microphone', icon: 'mic', action: () => discordAction('mute') });
      items.push({ key: 'dc-deaf', label: d.deaf ? 'Undeafen' : 'Deafen', icon: 'sound', action: () => discordAction('deaf') });
    }
    for (const c of d.saved || []) {
      const here = cur && cur.channel_id === c.id;
      items.push({
        key: `dc:${c.id}`, label: c.name, icon: 'voice', badge: here ? 'JOINED' : '',
        sub: [c.guild, here ? '{ok} leave' : '{ok} join'].filter(Boolean).join(' · '),
        action: () => joinVoice(c, cur),
        options: [{ label: here ? 'Leave' : 'Join', action: () => joinVoice(c, cur) },
                  { label: 'Remove from Social', action: () => discordAction('remove', { id: c.id }, `Removed ${c.name}`) }],
      });
    }
    if (!(d.saved || []).length) {
      items.push({ key: 'dc-choose', label: 'Choose Voice Channels', icon: 'voice', sub: 'Pick which ones show here (Settings › Accounts › Discord)',
        action: () => { openSettingsFolder('accounts'); setTimeout(() => openFolder(DISCORD_ACCOUNT_FOLDER), 400); } });
    }
    items.push({ key: 'dc-open', label: 'Open Discord', icon: 'window', sub: 'Text chat, friends and settings — Quick Menu (Select + Start) to come back',
      action: () => openDiscord() });
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
