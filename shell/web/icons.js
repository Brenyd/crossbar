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
  return `<svg viewBox="0 0 64 64" class="i">${ICONS[name] || ICONS.folder}</svg>`;
}
Object.assign(ICONS, {
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
  browser: '<rect x="6" y="10" width="52" height="44" rx="3"/><path d="M6 22h52"/><circle cx="13" cy="16" r="1.5"/><circle cx="19" cy="16" r="1.5"/>',
});
