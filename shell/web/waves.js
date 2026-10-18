// Flowing ribbon background. Colour follows the month (or a fixed theme).
const THEMES = [
  ['#9aa1ad', '#2a2d33'], ['#c8a23a', '#3a2a08'], ['#78a83e', '#1c2a0c'], ['#d07aa0', '#3a1426'],
  ['#4aa05a', '#0e2a14'], ['#8a5cc0', '#22123a'], ['#2aa8a8', '#06302e'], ['#3a78c8', '#0a1e3a'],
  ['#6a50c8', '#160e3a'], ['#d0902a', '#3a2006'], ['#9a6634', '#2a160a'], ['#c04040', '#360c0c'],
];
const Waves = (() => {
  const cv = document.getElementById('waves');
  const ctx = cv.getContext('2d');
  let w, h, t = 0, theme = THEMES[new Date().getMonth()];
  const SCALE = 0.5; // render at half res: smooth enough, cheap on software GL in a VM
  function resize() {
    w = cv.width = Math.round(innerWidth * SCALE);
    h = cv.height = Math.round(innerHeight * SCALE);
  }
  addEventListener('resize', resize);
  resize();
  const sparks = Array.from({ length: 40 }, () => ({ x: Math.random(), y: Math.random(), s: Math.random() }));

  function hexA(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
  }
  function wave(x, phase, amp, freq) {
    return Math.sin(x * freq + phase) * amp + Math.sin(x * freq * 0.47 + phase * 1.7) * amp * 0.6;
  }
  function frame() {
    t += 0.004;
    const [hi, lo] = theme;
    const g = ctx.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, lo);
    g.addColorStop(0.55, hexA(hi, 0.55));
    g.addColorStop(1, lo);
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);

    ctx.globalCompositeOperation = 'lighter';
    for (let L = 0; L < 5; L++) {
      const base = h * (0.56 + L * 0.018);
      const amp = h * (0.05 + L * 0.012);
      const ph = t * (1 + L * 0.25) + L * 1.3;
      const thick = h * (0.02 + 0.015 * Math.sin(t + L));
      ctx.beginPath();
      for (let x = 0; x <= w; x += 6) ctx.lineTo(x, base + wave(x / w * 6, ph, amp, 1));
      for (let x = w; x >= 0; x -= 6) ctx.lineTo(x, base + wave(x / w * 6, ph + 0.4, amp, 1) + thick);
      ctx.closePath();
      ctx.fillStyle = hexA('#ffffff', 0.035);
      ctx.fill();
      ctx.beginPath();
      for (let x = 0; x <= w; x += 6) ctx.lineTo(x, base + wave(x / w * 6, ph, amp, 1));
      ctx.strokeStyle = hexA('#ffffff', 0.10 + 0.03 * L);
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    for (const p of sparks) {
      p.x = (p.x + 0.0004 * (0.5 + p.s)) % 1;
      const y = h * 0.6 + wave(p.x * 6, t * 1.4, h * 0.07, 1) + (p.y - 0.5) * h * 0.08;
      ctx.fillStyle = hexA('#ffffff', 0.25 + 0.4 * Math.abs(Math.sin(t * 3 + p.s * 9)));
      ctx.fillRect(p.x * w, y, 1.5, 1.5);
    }
    ctx.globalCompositeOperation = 'source-over';
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  return {
    setTheme(name) {
      theme = name === 'auto' || !(name in THEMES) ? THEMES[new Date().getMonth()] : THEMES[name];
      document.documentElement.style.setProperty('--accent', theme[0]);
    },
  };
})();
