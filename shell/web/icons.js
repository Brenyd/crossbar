// Original line-art icons (64x64, stroked in currentColor).
const ICONS = {
  users: '<circle cx="32" cy="22" r="11"/><path d="M12 56c2-12 10-18 20-18s18 6 20 18"/>',
  settings: '<circle cx="32" cy="32" r="9"/><path d="M32 6v8M32 50v8M6 32h8M50 32h8M13.6 13.6l5.7 5.7M44.7 44.7l5.7 5.7M13.6 50.4l5.7-5.7M44.7 19.3l5.7-5.7"/><circle cx="32" cy="32" r="18"/>',
  game: '<path d="M14 22h36c6 0 10 5 10 12l-2 12c-1 6-8 8-12 3l-5-6H23l-5 6c-4 5-11 3-12-3L4 34c0-7 4-12 10-12z"/><path d="M18 30v10M13 35h10"/><circle cx="44" cy="31" r="2"/><circle cx="49" cy="37" r="2"/>',
  store: '<path d="M10 22h44l-4 34H14z"/><path d="M22 22v-4a10 10 0 0 1 20 0v4"/><path d="M26 36l6 6 6-6M32 30v12"/>',
  party: '<path d="M8 14h34v22H22l-8 8v-8H8z"/><path d="M46 24h10v20h-6v7l-7-7H28v-4"/>',
  music: '<path d="M24 46V14l26-6v32"/><circle cx="18" cy="46" r="6"/><circle cx="44" cy="40" r="6"/>',
  folder: '<path d="M6 18h18l5 6h29v28H6z"/>',
  download: '<path d="M32 8v32M20 28l12 12 12-12M10 50h44"/>',
  search: '<circle cx="27" cy="27" r="15"/><path d="M38 38l16 16"/>',
  link: '<path d="M26 38l12-12"/><path d="M22 30l-6 6a8 8 0 0 0 12 12l6-6M42 34l6-6a8 8 0 0 0-12-12l-6 6"/>',
  power: '<path d="M32 8v22"/><path d="M20 16a20 20 0 1 0 24 0"/>',
  restart: '<path d="M50 32a18 18 0 1 1-6-13.4"/><path d="M46 8v12H34"/>',
  info: '<circle cx="32" cy="32" r="24"/><path d="M32 28v16M32 20v2"/>',
  palette: '<path d="M32 8a24 24 0 1 0 0 48c4 0 5-3 3-6s-1-6 3-6h6c6 0 12-4 12-12 0-14-11-24-24-24z"/><circle cx="20" cy="30" r="3"/><circle cx="28" cy="18" r="3"/><circle cx="42" cy="20" r="3"/>',
  sound: '<path d="M10 24h10l12-10v36L20 40H10z"/><path d="M42 22a14 14 0 0 1 0 20M48 16a22 22 0 0 1 0 32"/>',
  mic: '<rect x="24" y="8" width="16" height="28" rx="8"/><path d="M16 30a16 16 0 0 0 32 0M32 46v10M24 56h16"/>',
  play: '<circle cx="32" cy="32" r="24"/><path d="M27 21l16 11-16 11z"/>',
  voice: '<path d="M10 32c0-10 10-18 22-18s22 8 22 18-10 18-22 18c-3 0-6-.5-9-1.5L12 54l3-10c-3-3-5-7-5-12z"/><path d="M24 30v4M32 26v12M40 30v4"/>',
  add: '<circle cx="32" cy="32" r="24"/><path d="M32 22v20M22 32h20"/>',
  window: '<rect x="8" y="12" width="48" height="40" rx="3"/><path d="M8 22h48"/>',
  demo: '<path d="M14 10h36v44H14z"/><path d="M22 22h20M22 30h20M22 38h12"/>',
  user: '<circle cx="32" cy="24" r="12"/><path d="M14 56c2-10 9-16 18-16s16 6 18 16"/>',
  refresh: '<path d="M50 24A20 20 0 0 0 14 22M14 40a20 20 0 0 0 36 2"/><path d="M50 10v14H36M14 54V40h14"/>',
};
function icon(name) {
  const themed = typeof Theme !== 'undefined' && Theme.icon(name);     // the theme pack's own icon
  if (themed) return themed;
  return `<svg viewBox="0 0 64 64" class="i">${ICONS[name] || ICONS.folder}</svg>`;
}
Object.assign(ICONS, {
  apps: '<rect x="10" y="10" width="18" height="18" rx="4"/><rect x="36" y="10" width="18" height="18" rx="4"/><rect x="10" y="36" width="18" height="18" rx="4"/><rect x="36" y="36" width="18" height="18" rx="4"/>',
  photo: '<rect x="8" y="14" width="48" height="38" rx="3"/><circle cx="22" cy="26" r="5"/><path d="M8 46l14-12 10 8 8-6 16 12"/>',
  video: '<rect x="6" y="14" width="40" height="36" rx="3"/><path d="M46 26l12-7v26l-12-7z"/>',
  tv: '<rect x="6" y="12" width="52" height="34" rx="3"/><path d="M22 54h20M32 46v8"/><path d="M27 23l11 6-11 6z"/>',
  network: '<circle cx="32" cy="32" r="24"/><path d="M8 32h48M32 8c8 8 8 40 0 48M32 8c-8 8-8 40 0 48"/>',
  display: '<rect x="6" y="10" width="52" height="34" rx="3"/><path d="M24 54h16M32 44v10"/>',
  wifi: '<path d="M8 26a34 34 0 0 1 48 0M16 34a22 22 0 0 1 32 0M24 42a10 10 0 0 1 16 0"/><circle cx="32" cy="50" r="2.5"/>',
  spotify: '<circle cx="32" cy="32" r="24"/><path d="M19 25c9-3 19-2 27 3M21 33c7-2 15-1 21 2M23 40c6-1 11 0 16 2"/>',
  shuffle: '<path d="M8 20h10l22 24h14M8 44h10l6-7M34 27l6-7h14M48 14l6 6-6 6M48 38l6 6-6 6"/>',
  account: '<circle cx="32" cy="24" r="10"/><path d="M14 54c2-10 9-16 18-16s16 6 18 16"/><circle cx="50" cy="16" r="6"/>',
  system: '<rect x="14" y="14" width="36" height="36" rx="3"/><rect x="24" y="24" width="16" height="16"/><path d="M24 8v6M32 8v6M40 8v6M24 50v6M32 50v6M40 50v6M8 24h6M8 32h6M8 40h6M50 24h6M50 32h6M50 40h6"/>',
  check: '<path d="M14 34l12 12 24-26"/>',
  trophy: '<path d="M20 10h24v12a12 12 0 0 1-24 0z"/><path d="M20 14h-8v4a8 8 0 0 0 8 8M44 14h8v4a8 8 0 0 1-8 8"/><path d="M32 34v10M22 54h20M26 44h12v10H26z"/>',
  retro: '<rect x="6" y="20" width="52" height="26" rx="6"/><path d="M14 33h10M19 28v10"/><circle cx="42" cy="36" r="2.5"/><circle cx="50" cy="30" r="2.5"/><path d="M28 30h4M33 30h4"/>',
  keyboard: '<rect x="4" y="16" width="56" height="32" rx="4"/><path d="M12 25h4M22 25h4M32 25h4M42 25h4M52 25h0M12 33h4M22 33h4M32 33h4M42 33h4M20 41h24"/>',
  browser: '<rect x="6" y="10" width="52" height="44" rx="3"/><path d="M6 22h52"/><circle cx="13" cy="16" r="1.5"/><circle cx="19" cy="16" r="1.5"/>',
});
Object.assign(ICONS, {
  bluetooth: '<path d="M20 20l24 22-12 10V12l12 10-24 22"/>',
  clock: '<circle cx="32" cy="32" r="24"/><path d="M32 18v15l10 6"/>',
});

// Emulation › ROMs: one original line drawing per system (its hardware: pad, handheld, console),
// so each folder is recognisable at a glance. Used as `sys-<id>`; a theme can replace any of them.
const SYS_TXT = (x, y, s, t) => `<text x="${x}" y="${y}" font-size="${s}" font-family="sans-serif" font-weight="700" text-anchor="middle" style="fill:currentColor;stroke:none">${t}</text>`;
const SYS_DPAD = (x, y, r = 5) => `<path d="M${x - r} ${y - 1.6}h${r * 2}v3.2h-${r * 2}zM${x - 1.6} ${y - r}h3.2v${r * 2}h-3.2z"/>`;
Object.assign(ICONS, {
  'sys-nes': `<rect x="6" y="20" width="52" height="24" rx="2"/>${SYS_DPAD(17, 32)}<path d="M27 34h4M33 34h4"/><circle cx="44" cy="34" r="3"/><circle cx="52" cy="34" r="3"/>`,
  'sys-snes': `<path d="M18 18h28a14 14 0 0 1 0 28H18a14 14 0 0 1 0-28z"/>${SYS_DPAD(17, 32)}<path d="M27 35l3-2M33 35l3-2"/><circle cx="47" cy="25" r="2.6"/><circle cx="53" cy="32" r="2.6"/><circle cx="41" cy="32" r="2.6"/><circle cx="47" cy="39" r="2.6"/>`,
  'sys-n64': '<path d="M8 22h48l-4 14-6 2-4 14h-4l-3-10h-6l-3 10h-4l-4-14-6-2z"/><path d="M14 26v6M11 29h6"/><circle cx="32" cy="34" r="3.5"/><circle cx="46" cy="27" r="2.2"/><circle cx="50" cy="31" r="2.2"/>',
  'sys-gb': `<path d="M16 6h32v46c0 4-4 8-10 8H16z"/><rect x="21" y="11" width="22" height="18" rx="1"/>${SYS_DPAD(24, 41, 4.5)}<circle cx="38" cy="43" r="2.6"/><circle cx="44" cy="39" r="2.6"/><path d="M26 52h4M33 52h4"/>`,
  'sys-gbc': `<path d="M18 6h28c3 0 4 2 4 4v40c0 6-6 10-12 10H18c-3 0-4-2-4-4V10c0-2 1-4 4-4z"/><rect x="20" y="11" width="24" height="18" rx="2"/>${SYS_DPAD(23, 45, 4.5)}<circle cx="38" cy="47" r="2.6"/><circle cx="44" cy="43" r="2.6"/>${SYS_TXT(32, 36, 5.5, 'COLOR')}`,
  'sys-gba': `<path d="M14 18h36c6 0 10 6 10 14s-4 14-10 14H14C8 46 4 40 4 32s4-14 10-14z"/><rect x="21" y="22" width="22" height="16" rx="1"/>${SYS_DPAD(12, 32, 4)}<circle cx="51" cy="29" r="2.2"/><circle cx="55" cy="34" r="2.2"/>`,
  'sys-nds': `<rect x="12" y="6" width="40" height="24" rx="3"/><rect x="21" y="10" width="22" height="16"/><rect x="12" y="34" width="40" height="24" rx="3"/><rect x="21" y="38" width="22" height="16"/>${SYS_DPAD(16, 44, 3)}<circle cx="48" cy="42" r="1.6"/><circle cx="48" cy="48" r="1.6"/>`,
  'sys-n3ds': `<rect x="10" y="6" width="44" height="24" rx="3"/><rect x="17" y="10" width="30" height="16"/><rect x="12" y="34" width="40" height="24" rx="3"/><rect x="22" y="38" width="20" height="15"/><circle cx="17" cy="41" r="3"/><circle cx="47" cy="41" r="1.6"/><circle cx="47" cy="47" r="1.6"/>${SYS_TXT(32, 21, 9, '3D')}`,
  'sys-gc': '<path d="M32 8l22 12v24L32 56 10 44V20z"/><path d="M10 20l22 12 22-12M32 32v24"/><path d="M24 24l8 4 8-4"/>',
  'sys-wii': '<rect x="25" y="4" width="14" height="56" rx="6"/><path d="M29 14h6M32 11v6"/><circle cx="32" cy="25" r="3"/><circle cx="32" cy="42" r="1.5"/><circle cx="32" cy="48" r="1.5"/>',
  'sys-wiiu': '<rect x="4" y="16" width="56" height="32" rx="9"/><rect x="18" y="20" width="28" height="22" rx="1"/><circle cx="11" cy="25" r="3"/><circle cx="53" cy="25" r="3"/><path d="M8 36h6M11 33v6"/><circle cx="53" cy="37" r="2"/>',
  'sys-mastersystem': `<path d="M8 22h48v18c0 4-3 6-6 6H14c-3 0-6-2-6-6z"/>${SYS_DPAD(18, 34, 5)}${SYS_TXT(42, 38, 8, '1')}${SYS_TXT(51, 38, 8, '2')}<circle cx="42" cy="35" r="4"/><circle cx="51" cy="35" r="4"/>`,
  'sys-genesis': `<path d="M8 28c0-8 8-12 24-12s24 4 24 12c0 10-6 18-12 18-4 0-6-4-12-4s-8 4-12 4C14 46 8 38 8 28z"/>${SYS_DPAD(19, 30, 5)}<circle cx="38" cy="34" r="2.6"/><circle cx="44" cy="31" r="2.6"/><circle cx="50" cy="28" r="2.6"/>`,
  'sys-segacd': '<rect x="6" y="36" width="52" height="16" rx="2"/><path d="M12 44h12"/><circle cx="46" cy="44" r="2"/><ellipse cx="32" cy="22" rx="22" ry="10"/><ellipse cx="32" cy="22" rx="5" ry="2.5"/>',
  'sys-gamegear': `<path d="M6 18h52v28H6z" transform="translate(0 0)"/><path d="M6 18c-2 4-2 24 0 28M58 18c2 4 2 24 0 28"/><rect x="20" y="22" width="24" height="20" rx="1"/>${SYS_DPAD(13, 32, 4)}<circle cx="50" cy="35" r="2.2"/><circle cx="54" cy="30" r="2.2"/>`,
  'sys-saturn': `<path d="M14 20h36c6 0 10 6 10 13s-4 13-10 13H14C8 46 4 40 4 33s4-13 10-13z"/>${SYS_DPAD(15, 33, 5)}<circle cx="40" cy="30" r="2"/><circle cx="46" cy="28" r="2"/><circle cx="52" cy="26" r="2"/><circle cx="40" cy="37" r="2"/><circle cx="46" cy="35" r="2"/><circle cx="52" cy="33" r="2"/>`,
  'sys-dreamcast': `<path d="M14 14h36c4 0 8 4 8 10v12c0 8-4 18-10 18-4 0-6-6-8-10H24c-2 4-4 10-8 10-6 0-10-10-10-18V24c0-6 4-10 8-10z"/><rect x="24" y="18" width="16" height="14" rx="1"/>${SYS_DPAD(14, 30, 4)}<circle cx="49" cy="26" r="2"/><circle cx="53" cy="31" r="2"/><circle cx="45" cy="31" r="2"/><circle cx="49" cy="36" r="2"/>`,
  'sys-psx': `<circle cx="32" cy="32" r="24"/><circle cx="32" cy="32" r="6"/>${SYS_TXT(32, 23, 10, '1')}`,
  'sys-ps2': `<path d="M12 10h30l10 6v38H12z"/><path d="M12 22h40M18 16h18"/>${SYS_TXT(32, 44, 16, '2')}`,
  'sys-ps3': `<path d="M8 40c0-12 8-24 24-24s24 12 24 24v6H8z"/><path d="M8 40h48M14 34h20"/>${SYS_TXT(44, 36, 12, '3')}`,
  'sys-psp': `<path d="M12 18h40c6 0 10 6 10 14s-4 14-10 14H12C6 46 2 40 2 32s4-14 10-14z"/><rect x="18" y="22" width="28" height="18" rx="1"/>${SYS_DPAD(10, 30, 3.5)}<circle cx="54" cy="27" r="1.6"/><circle cx="58" cy="31" r="1.6"/><circle cx="50" cy="31" r="1.6"/><circle cx="54" cy="35" r="1.6"/>`,
  'sys-switch': '<path d="M16 14h-4c-4 0-6 3-6 6v24c0 3 2 6 6 6h4z"/><path d="M48 14h4c4 0 6 3 6 6v24c0 3-2 6-6 6h-4z"/><rect x="18" y="14" width="28" height="36" rx="2"/><circle cx="11" cy="24" r="2.2"/><path d="M9 38h4M11 36v4"/><circle cx="53" cy="24" r="1.6"/><circle cx="53" cy="38" r="2.2"/>',
  'sys-xbox': '<rect x="10" y="14" width="44" height="34" rx="4"/><circle cx="32" cy="31" r="9"/><path d="M27 26l10 10M37 26L27 36"/><path d="M14 52h8M42 52h8"/>',
  'sys-pcengine': '<rect x="12" y="16" width="40" height="32" rx="3"/><rect x="18" y="12" width="28" height="8" rx="1"/><path d="M18 32h28M18 38h28"/><circle cx="46" cy="44" r="1.5"/>',
  'sys-atari2600': '<path d="M12 40h40v14H12z"/><path d="M32 40V16"/><circle cx="32" cy="12" r="5"/><circle cx="20" cy="46" r="3"/><path d="M26 40c0-4 12-4 12 0"/>',
  'sys-arcade': '<path d="M18 6h28v10l-4 8v32H22V24l-4-8z"/><rect x="23" y="12" width="18" height="12" rx="1"/><path d="M18 30h28M27 36v-6"/><circle cx="27" cy="29" r="2"/><circle cx="36" cy="33" r="1.6"/><circle cx="41" cy="33" r="1.6"/>',
  'sys-scummvm': '<path d="M18 8v38l9-9 6 14 6-3-6-13h12z"/><path d="M38 10h18v12H44l-4 4v-4h-2z"/>',
});
