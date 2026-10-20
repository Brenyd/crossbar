'use strict';
// Settings › Network › VPN: set-up wizard, locations, protocol, port forwarding, split tunneling.

const VPN_APPS = [
  ['steam', 'Steam (and the games it runs)'], ['games', 'GOG, Epic, Lutris and Emulator Games'],
  ['discord', 'Discord'], ['browser', 'Web Browser'],
];
const vpnStatus = () => api.get('/api/vpn');
function vpnRefresh() { if (S.stack.length) reloadFolder(); }

async function vpnConnect() {
  const j = await call(() => api.post('/api/vpn/connect'), 'Connecting the VPN…');
  if (!j) return;
  for (let i = 0; i < 120; i++) {
    await new Promise((r) => setTimeout(r, 700));
    const cur = (await api.get('/api/jobs').catch(() => [])).find((x) => x.id === j.id);
    if (!cur || cur.status === 'running') continue;
    if (cur.status === 'done') {
      const ip = await api.get('/api/vpn/ip').catch(() => ({}));
      toast(`VPN connected${ip.vpn ? ` · VPN apps are seen as ${ip.vpn}${ip.vpn_country ? ` (${ip.vpn_country})` : ''}` : ''}`, 'network');
    } else toast(`VPN: ${cur.message}`, 'info');
    break;
  }
  vpnRefresh();
}

// the sign-in step of the wizard (and VPN › Account)
async function vpnSignIn(p, protocol) {
  if (p.kind === 'import') {
    const r = await Dialog.ask({ title: `${p.name}: OpenVPN Sign-In`, buttons: ['Save', 'Skip'],
      body: 'Only needed for OpenVPN (.ovpn) files: the username and password from your account page (not always your login).',
      fields: [{ key: 'username', label: 'Username' }, { key: 'password', label: 'Password', secret: true }] });
    if (r.button !== 0) return api.post('/api/vpn/setup', { provider: p.id, protocol, fields: {} }).catch(() => null);
    return call(() => api.post('/api/vpn/setup', { provider: p.id, protocol, fields: r.values }), 'Saved');
  }
  const r = await Dialog.ask({ title: `Sign In to ${p.name}`, buttons: ['Sign In', 'Cancel'], fields: p.fields,
    body: p.id === 'nord' ? 'Make a token at my.nordaccount.com › NordVPN › Advanced settings › Set up NordVPN manually.' : '' });
  if (r.button !== 0) return null;
  toast(`Checking with ${p.name}…`, 'network');
  return call(() => api.post('/api/vpn/setup', { provider: p.id, protocol, fields: r.values }), `Signed in to ${p.name}`);
}

async function vpnImportBrowse(p, path) {
  const r = await api.get(`/api/fs?ext=vpn${path ? `&path=${encodeURIComponent(path)}` : ''}`);
  const take = async (target) => {
    const res = await call(() => api.post('/api/vpn/import', { provider: p.id, path: target }));
    if (!res) return;
    toast(`${res.imported} location${res.imported === 1 ? '' : 's'} added`, 'network');
    while (S.stack.length && S.stack.at(-1).source?.vpnBrowse) S.stack.pop();
    if (res.locations.some((l) => l.protocol === 'openvpn')) await vpnSignIn(p, 'openvpn');
    else await api.post('/api/vpn/setup', { provider: p.id, fields: {} }).catch(() => null);
    openFolder(vpnLocationsFolder());
  };
  const items = (r.files || []).map((f) => ({ key: `vf:${f.path}`, label: f.name, icon: 'download',
    sub: /\.zip$/i.test(f.path) ? 'Import every location in this .zip' : 'Import this location', action: () => take(f.path) }));
  if (path && (r.files || []).filter((f) => !/\.zip$/i.test(f.path)).length > 1)
    items.unshift({ key: 'all', label: 'Import Every File Here', icon: 'add', sub: path, action: () => take(path) });
  for (const d of r.dirs) items.push({ key: `d:${d.path}`, label: d.name, icon: 'folder', vpnBrowse: true, children: () => vpnImportBrowse(p, d.path) });
  if (!items.length) items.push({ key: 'none', label: 'No VPN files here', icon: 'info', sub: 'WireGuard .conf, OpenVPN .ovpn, or a .zip of them' });
  return items;
}

// Set Up: pick the provider → protocol → sign in / import → location
function vpnProvidersFolder() {
  return { key: 'vpn-providers', label: 'Set Up a VPN', icon: 'network', sub: 'Pick your VPN service',
    children: async () => (await api.get('/api/vpn/providers')).map((p) => ({
      key: `vp:${p.id}`, label: p.name, icon: 'network', badge: p.kind === 'api' ? 'SIGN IN' : 'IMPORT',
      sub: p.kind === 'api' ? `${p.protocols.map((x) => (x === 'wireguard' ? 'WireGuard' : 'OpenVPN')).join(' or ')}${p.port_forward ? ' · port forwarding' : ''}`
        : 'Import the config files from your account page',
      action: async () => {
        let protocol = p.protocols[0];
        if (p.kind === 'api' && p.protocols.length > 1) {
          protocol = await choose([['wireguard', 'WireGuard (faster, recommended)'], ['openvpn', 'OpenVPN']]);
          if (!protocol) return;
        }
        if (p.kind === 'import') {
          await message(`${p.hint}.\n\nPut the file(s) on a USB stick or in Downloads, then pick them on the next screen. A folder or .zip of several files gives you several locations.`, p.name);
          openFolder({ key: `vpn-import:${p.id}`, label: `Import ${p.name} Files`, icon: 'folder', vpnBrowse: true, children: () => vpnImportBrowse(p, null) });
          return;
        }
        if (!(await vpnSignIn(p, protocol))) return;
        openFolder(vpnLocationsFolder());
      } })) };
}

function vpnLocationsFolder() {
  return { key: 'vpn-locations', label: 'Location', icon: 'network', sub: 'Where your traffic comes out',
    children: async () => {
      const [st, regs] = await Promise.all([vpnStatus(), api.get('/api/vpn/regions')]);
      if (!regs.length) return [{ key: 'none', label: 'No locations', icon: 'info', sub: 'Import some VPN files first' }];
      const pf = st.port_forward && st.provider === 'pia';
      return regs.map((r) => ({ key: `vr:${r.id}`, label: r.name, icon: r.id === st.region ? 'check' : 'network',
        badge: r.port_forward ? 'PORT FWD' : (r.protocol ? r.protocol.toUpperCase() : ''),
        sub: [r.id === st.region ? 'Current' : '', r.latency != null ? `${r.latency} ms` : '', pf && !r.port_forward ? 'no port forwarding here' : '']
          .filter(Boolean).join(' · '),
        action: async () => {
          const s = await call(() => api.post('/api/vpn/region', { id: r.id, name: r.name }));
          if (!s) return;
          toast(`VPN location: ${r.name}`, 'network');
          back();
          if (s.connected ? await confirmBox(`Switch the VPN to ${r.name} now?`) : await confirmBox(`Connect to ${r.name} now?`)) vpnConnect();
          else vpnRefresh();
        } }));
    } };
}

function vpnSplitFolder() {
  return { key: 'vpn-split', label: 'Split Tunneling', icon: 'network', sub: 'Choose what uses the VPN',
    children: async () => {
      const st = await vpnStatus();
      const setOpt = async (body, msg) => {
        const r = await call(() => api.post('/api/vpn/options', body), msg);
        if (r && 'split' in body && r.connected && await confirmBox('Reconnect the VPN now so this takes effect?')) { vpnConnect(); return; }
        if (r) reloadFolder();
      };
      const appImages = (S.apps || []).filter((a) => a.kind === 'appimage').map((a) => [`app:${a.key}`, a.name]);
      const rows = [{ key: 'on', label: 'Split Tunneling', icon: st.split ? 'check' : 'power',
        sub: st.split ? 'On · only the apps and sites below use the VPN' : 'Off · everything uses the VPN',
        action: () => setOpt({ split: !st.split }, st.split ? 'Everything will use the VPN' : 'Only chosen apps and sites will use the VPN') }];
      if (!st.split) return rows;
      rows.push({ key: 'apps', label: 'Apps That Use the VPN', icon: 'apps', sub: st.vpn_apps.length ? `${st.vpn_apps.length} chosen` : 'None yet',
        children: async () => {
          const cur = (await vpnStatus()).vpn_apps;
          const list = [['torrents', 'Torrents'], ...VPN_APPS, ...appImages].map(([id, label]) => {
            const on = cur.includes(id);
            return { key: `a:${id}`, label, icon: on ? 'check' : 'apps', sub: on ? 'Uses the VPN · {ok} change' : 'Doesn\'t use the VPN · {ok} change',
              action: () => setOpt({ vpn_apps: on ? cur.filter((x) => x !== id) : [...cur, id] }, `${label}: ${on ? 'no VPN' : 'uses the VPN'} (from the next time it starts)`) };
          });
          list.push({ key: 'note', label: 'How This Works', icon: 'info', sub: 'Changes apply when an app next starts',
            action: () => message('Apps chosen here start in their own group, and only that group\'s traffic (and its DNS) goes through the VPN.\nTorrents with "Only Use the VPN" on always use it.\nFlatpak apps put themselves in a group of their own when they start, so they can\'t be chosen.\nChanges apply the next time an app starts.', 'Split Tunneling') });
          return list;
        } });
      rows.push({ key: 'sites', label: 'Sites That Use the VPN', icon: 'network', sub: st.vpn_sites.length ? st.vpn_sites.join(', ') : 'None',
        children: async () => {
          const cur = (await vpnStatus()).vpn_sites;
          return [...cur.map((x) => ({ key: `x:${x}`, label: x, icon: 'network', sub: '{ok} remove',
            action: () => setOpt({ vpn_sites: cur.filter((y) => y !== x) }, `${x} no longer uses the VPN`) })),
          { key: 'add', label: 'Add a Site or Address…', icon: 'add', sub: 'e.g. bbc.co.uk, 203.0.113.5 or 192.0.2.0/24',
            action: async () => {
              const r = await Dialog.ask({ title: 'Use the VPN For', buttons: ['Add', 'Cancel'], fields: [{ key: 'x', label: 'Site name, address or network' }],
                body: 'Traffic to this goes through the VPN, from any app.\nSite names are looked up when the VPN connects.' });
              if (r.button === 0 && r.values.x.trim()) setOpt({ vpn_sites: [...cur, r.values.x.trim()] }, `${r.values.x.trim()} uses the VPN`);
            } }];
        } });
      return rows;
    } };
}

// a job with a live results window (speed test, leak tests)
async function jobDialog(path, title, render) {
  const j = await call(() => api.post(path));
  if (!j) return;
  let open = true;
  Dialog.ask({ title, body: 'Starting…', buttons: ['Close'] }).then(() => { open = false; });
  $('.dlg-body').classList.add('long');                // a solid backdrop: results are read, not glanced at
  while (open) {
    await new Promise((r) => setTimeout(r, 600));
    const cur = (await api.get('/api/jobs').catch(() => [])).find((x) => x.id === j.id);
    if (!cur || !open) break;
    $('.dlg-body').textContent = render(cur).filter((x) => x != null && x !== '').join('\n');
    if (cur.status !== 'running') break;
  }
  if (S.stack.length) reloadFolder();
}
const LEAK_MARK = { leak: '⚠ ', protected: '✓ ', exposed: '⚠ ', 'not-vpn': '⚠ ', 'not-chosen': '⚠ ' };
function torrentLeakTest() {
  return jobDialog('/api/leaktest/torrent', 'Torrent IP Leak Test', (cur) => {
    const r = cur.result;
    if (!r) return [cur.message, '', 'The torrent engine announces a made-up torrent to WhatIsMyIP.net\'s tracker,', 'which records the address it came from.'];
    return [`${LEAK_MARK[r.verdict] || ''}${cur.message}`, '',
      r.seen.length ? 'Trackers saw:' : 'Nothing reached the tracker (blocked, or "Only Use the VPN" with the VPN off).',
      ...r.seen.map((x) => `   ${x.ip}${x.ip === r.isp_ip ? '  ← your real address' : ''}${x.agent ? `   (${x.agent})` : ''}`),
      r.verdict === 'not-chosen' ? 'Split tunneling is on and Torrents isn\'t one of the VPN apps. Turn on Torrents › Settings ›\nNetwork & VPN › Only Use the VPN (or add Torrents in VPN › Split Tunneling).' : '',
      r.isp_ip ? `Your address without the VPN: ${r.isp_ip}` : 'Your address without the VPN isn\'t known yet: check it once with the VPN off (Check My Address).',
      `VPN: ${r.vpn ? 'on' : 'off'}${r.bound ? ` · torrents bound to ${r.bound}` : ''}`];
  });
}
function dnsLeakTest() {
  return jobDialog('/api/leaktest/dns', 'DNS Leak Test', (cur) => {
    const r = cur.result;
    if (!r) return [cur.message, '', 'Made-up names are looked up, then bash.ws reports which DNS servers did it.'];
    return [`${LEAK_MARK[r.verdict] || ''}${cur.message}`, '',
      `DNS servers used (${r.servers.length}):`, ...r.servers.slice(0, 8).map((x) => `   ${x.ip}  ${x.country}${x.asn ? ` · ${x.asn}` : ''}`),
      `Seen as: ${r.ip || '?'}${r.ip_country ? `  ${r.ip_country}` : ''}${r.ip_asn ? ` · ${r.ip_asn}` : ''}${r.ip === r.isp_ip ? '  ← your real address' : ''}`,
      r.split ? 'Tested as an app that uses the VPN (split tunneling is on).' : '',
      r.verdict === 'not-vpn' && r.split ? 'VPN apps aren\'t going through the VPN: see Leak Tests › Check Split Tunneling.' : '',
      r.verdict !== 'not-vpn' && r.conclusion ? `bash.ws: ${r.conclusion}` : ''];
  });
}
async function checkMyAddress() {
  const ip = await call(() => api.get('/api/vpn/ip'));
  if (!ip) return;
  const lines = [];
  if (!ip.connected) lines.push(`VPN off. Everything is seen as ${ip.normal || '?'}${ip.country ? ` (${ip.country})` : ''}.`);
  else if (!ip.split) lines.push(`Everything uses the VPN, seen as ${ip.vpn || ip.normal || '?'}${ip.vpn_country ? ` (${ip.vpn_country})` : ''}.`);
  else {
    lines.push(`Apps that use the VPN are seen as: ${ip.vpn || '(couldn\'t check)'}${ip.vpn_country ? ` (${ip.vpn_country})` : ''}`);
    lines.push(`Everything else is seen as: ${ip.normal || '?'}${ip.country ? ` (${ip.country})` : ''}`);
    lines.push('', 'Split tunneling is on, so only the apps and sites you chose use the VPN —', 'the rest (and this menu) use your normal connection, as intended.');
  }
  message(lines.join('\n'), 'Your Address');
}
async function checkSplit() {
  toast('Checking split tunneling…', 'network');
  const r = await call(() => api.get('/api/vpn/check'));
  if (!r) return;
  const ok = r.app && r.vpn && r.app === r.vpn && r.app !== r.isp_ip;
  const lines = [!r.connected ? 'The VPN is off: connect it first.' : !r.split ? 'Split tunneling is off: everything uses the VPN.'
    : ok ? '✓ Working: VPN apps come out of the VPN.' : '⚠ Not working: VPN apps aren\'t using the VPN.', '',
    `A VPN app is seen as: ${r.app || '?'}${r.app && r.app === r.isp_ip ? '  ← your real address' : ''}`,
    `The VPN's own address is seen as: ${r.vpn || '?'}`,
    `Crossbar itself is seen as: ${r.normal || '?'}`,
    `VPN app group: ${r.group?.exists ? (r.group.member ? 'ready' : 'you\'re not in it yet') : 'not made yet'}${r.app_gid_ok === false ? ' · the test app didn\'t get it' : ''}`];
  if (r.split && r.connected) lines.push(`VPN connection: ${r.iface} · address ${r.vpn_addr || 'not found'} · routing rules ${r.rules ? 'in place' : 'missing'}${r.reapplied ? ' (just put back)' : ''}`);
  if (r.split_error) lines.push(`Setting up the rules failed: ${r.split_error}`);
  if (r.vpn_error) lines.push(`Through the VPN's address: ${r.vpn_error}`);
  if (r.app_error) lines.push(`Test app: ${r.app_error}`);
  if (r.helper?.error) lines.push(`System helper: ${r.helper.error}`);
  else if (r.helper?.nft) { const m = r.helper.nft.match(/counter packets (\d+)/); if (m) lines.push(`Packets sent through the VPN for apps so far: ${m[1]}`); }
  message(lines.filter((x, i) => x !== '' || i === 1).join('\n'), 'Split Tunneling Check');
}
const LEAK_FOLDER = { key: 'leaks', label: 'Leak Tests', icon: 'search', sub: 'Torrent IP and DNS',
  children: async () => [
    { key: 'tleak', label: 'Torrent IP Leak Test', icon: 'download', sub: 'What address trackers see from your torrent client', action: torrentLeakTest },
    { key: 'dleak', label: 'DNS Leak Test', icon: 'network', sub: 'Which DNS servers your lookups go to', action: dnsLeakTest },
    { key: 'ip', label: 'Check My Address', icon: 'search', sub: 'What websites see',
      action: checkMyAddress },
    { key: 'split', label: 'Check Split Tunneling', icon: 'network', sub: 'Do VPN apps really use the VPN?', action: checkSplit },
  ] };

const VPN_ITEM = {
  key: 'vpn', label: 'VPN', icon: 'network', sub: 'PIA, Mullvad, NordVPN, Proton, WireGuard, OpenVPN…',
  children: async () => {
    const st = await vpnStatus();
    if (!st.available) return [{ key: 'na', label: 'The VPN needs NetworkManager', icon: 'info' }];
    if (!st.configured) return [vpnProvidersFolder(), { key: 'how', label: 'How This Works', icon: 'info', sub: 'No VPN app needed',
      action: () => message('Crossbar connects with WireGuard or OpenVPN itself, through NetworkManager.\nPIA, Mullvad and NordVPN: sign in here and pick a location.\nOther services: import the WireGuard or OpenVPN files from your account page.', 'VPN') }];
    const where = st.region_name || 'No location yet';
    const items = [];
    items.push(st.connected
      ? { key: 'conn', label: 'Disconnect', icon: 'power', sub: `Connected · ${where} · ${st.protocol === 'openvpn' ? 'OpenVPN' : 'WireGuard'}`,
          action: async () => { if (await call(() => api.post('/api/vpn/disconnect'), 'VPN disconnected')) vpnRefresh(); } }
      : { key: 'conn', label: st.connecting ? 'Connecting…' : 'Connect', icon: 'network',
          sub: st.error ? `Last try: ${st.error}` : `${st.provider_name} · ${where}`, action: st.region ? vpnConnect : () => openFolder(vpnLocationsFolder()) });
    items.push(vpnLocationsFolder());
    if (st.protocols.length > 1 && st.kind === 'api') items.push({ key: 'proto', label: 'Protocol', icon: 'settings', sub: st.protocol === 'openvpn' ? 'OpenVPN' : 'WireGuard',
      action: async () => {
        const p = await choose([['wireguard', 'WireGuard (faster)'], ['openvpn', 'OpenVPN']], st.protocol === 'openvpn' ? 1 : 0);
        if (p && p !== st.protocol && await call(() => api.post('/api/vpn/options', { protocol: p }), `VPN protocol: ${p === 'openvpn' ? 'OpenVPN' : 'WireGuard'}`)) {
          if (st.connected && await confirmBox('Reconnect now with the new protocol?')) vpnConnect(); else vpnRefresh();
        }
      } });
    if (st.pf_supported) items.push({ key: 'pf', label: 'Port Forwarding', icon: 'network',
      sub: !st.port_forward ? 'Off' : st.forwarded_port ? `On · port ${st.forwarded_port} (the torrent client uses it)` : st.pf_error || (st.connected ? 'On · waiting for a port…' : 'On · when connected'),
      action: async () => {
        if (await call(() => api.post('/api/vpn/options', { port_forward: !st.port_forward }), `Port forwarding ${st.port_forward ? 'off' : 'on'}`)) {
          if (st.connected && await confirmBox('Reconnect now so it takes effect?')) vpnConnect(); else vpnRefresh();
        }
      } });
    items.push({ ...vpnSplitFolder(), sub: !st.split ? 'Off · everything uses the VPN' : (() => {
      const n = st.vpn_apps.length + st.vpn_sites.length;
      const what = [st.vpn_apps.length ? `${st.vpn_apps.length} app${st.vpn_apps.length === 1 ? '' : 's'}` : '', st.vpn_sites.length ? `${st.vpn_sites.length} site${st.vpn_sites.length === 1 ? '' : 's'}` : ''].filter(Boolean).join(' and ');
      return n ? `On · ${what} ${n === 1 ? 'uses' : 'use'} the VPN` : 'On · nothing uses the VPN yet: add apps here';
    })() });
    items.push({ key: 'auto', label: 'Connect at Startup', icon: 'power', sub: st.autoconnect ? 'On' : 'Off',
      action: async () => { if (await call(() => api.post('/api/vpn/options', { autoconnect: !st.autoconnect }))) vpnRefresh(); } });
    items.push(LEAK_FOLDER);
    const prov = (await api.get('/api/vpn/providers')).find((p) => p.id === st.provider);
    items.push({ key: 'acct', label: 'Account', icon: 'user', sub: `${st.provider_name}${st.username ? ` · ${st.username}` : ''}`,
      children: async () => [
        ...(prov.kind === 'api' ? [{ key: 'signin', label: 'Sign In Again', icon: 'user', action: async () => { if (await vpnSignIn(prov, st.protocol)) back(); } }]
          : [{ key: 'more', label: 'Import More Locations…', icon: 'add', vpnBrowse: true, children: () => vpnImportBrowse(prov, null) },
             { key: 'creds', label: 'OpenVPN Username & Password', icon: 'user', action: () => vpnSignIn(prov, 'openvpn') }]),
        vpnProvidersFolder(),
        { key: 'forget', label: 'Sign Out & Remove', icon: 'power', sub: 'Deletes the saved sign-in, keys and imported files',
          action: async () => { if (await confirmSafe(`Remove ${st.provider_name} from this console?`)) { await call(() => api.post('/api/vpn/forget', { provider: st.provider }), 'VPN removed'); back(); vpnRefresh(); } } },
      ] });
    return items;
  },
};
