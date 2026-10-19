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
      toast(`VPN connected${ip.ip ? ` · you're seen as ${ip.ip}${ip.country ? ` (${ip.country})` : ''}` : ''}`, 'network');
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
  return { key: 'vpn-split', label: 'Split Tunneling', icon: 'network', sub: 'Sites and apps that skip the VPN',
    children: async () => {
      const st = await vpnStatus();
      const setOpt = async (body, msg) => { if (await call(() => api.post('/api/vpn/options', body), msg)) reloadFolder(); };
      const appImages = (S.apps || []).filter((a) => a.kind === 'appimage').map((a) => [`app:${a.key}`, a.name]);
      return [
        { key: 'lan', label: 'Local Network', icon: 'info', sub: 'Always reachable (printers, NAS, casting) while the VPN is on' },
        { key: 'sites', label: 'Sites & Addresses', icon: 'network', sub: st.split_exclude.length ? st.split_exclude.join(', ') : 'None — everything goes through the VPN',
          children: async () => {
            const cur = (await vpnStatus()).split_exclude;
            return [...cur.map((x) => ({ key: `x:${x}`, label: x, icon: 'network', sub: '{ok} remove',
              action: async () => setOpt({ split_exclude: cur.filter((y) => y !== x) }, `${x} goes through the VPN again`) })),
            { key: 'add', label: 'Add a Site or Address…', icon: 'add', sub: 'e.g. netflix.com, 203.0.113.5 or 192.0.2.0/24',
              action: async () => {
                const r = await Dialog.ask({ title: 'Skip the VPN', buttons: ['Add', 'Cancel'], fields: [{ key: 'x', label: 'Site name, address or network' }],
                  body: 'Traffic to this goes straight out, not through the VPN.\nSite names are looked up when the VPN connects.' });
                if (r.button === 0 && r.values.x.trim()) setOpt({ split_exclude: [...cur, r.values.x.trim()] }, `${r.values.x.trim()} skips the VPN`);
              } }];
          } },
        { key: 'apps', label: 'Apps That Skip the VPN', icon: 'apps',
          sub: st.split_apps.length ? `${st.split_apps.length} chosen` : 'None',
          children: async () => {
            const cur = (await vpnStatus()).split_apps;
            const rows = [...VPN_APPS, ...appImages].map(([id, label]) => {
              const on = cur.includes(id);
              return { key: `a:${id}`, label, icon: on ? 'check' : 'apps', sub: on ? 'Skips the VPN · {ok} change' : 'Uses the VPN · {ok} change',
                action: () => setOpt({ split_apps: on ? cur.filter((x) => x !== id) : [...cur, id] }, `${label}: ${on ? 'uses the VPN' : 'skips the VPN'} (next time it starts)`) };
            });
            rows.push({ key: 'note', label: 'About Flatpak Apps', icon: 'info', sub: 'Flatpaks always follow the VPN',
              action: () => message('Apps that skip the VPN are started in their own group, whose traffic goes around the tunnel.\nFlatpak apps put themselves in a group of their own when they start, so they can\'t be split off: they always use the VPN.\nChanges apply the next time an app starts.', 'Split Tunneling') });
            return rows;
          } },
      ];
    } };
}

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
    items.push(vpnSplitFolder());
    items.push({ key: 'auto', label: 'Connect at Startup', icon: 'power', sub: st.autoconnect ? 'On' : 'Off',
      action: async () => { if (await call(() => api.post('/api/vpn/options', { autoconnect: !st.autoconnect }))) vpnRefresh(); } });
    items.push({ key: 'ip', label: 'Check My Address', icon: 'search', sub: 'What websites see',
      action: async () => { const ip = await call(() => api.get('/api/vpn/ip')); if (ip) message(`${ip.ip || 'Unknown'}${ip.country ? `\nCountry: ${ip.country}` : ''}${ip.server ? `\nNearest Cloudflare: ${ip.server}` : ''}\nVPN: ${st.connected ? 'on' : 'off'}`, 'Your Address'); } });
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
