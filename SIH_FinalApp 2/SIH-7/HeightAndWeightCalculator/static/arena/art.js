// DeepFit Arena - everything the game draws: themed worlds, cartoon characters, effects.
// Pure canvas drawing, no image files, so the game loads instantly on a slow connection.

const TAU = Math.PI * 2;
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const lerp = (a, b, u) => a + (b - a) * u;

// deterministic "random" so scenery doesn't flicker between frames
function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }
const R = rng(20251026);
const CROWD = Array.from({ length: 140 }, () => ({ x: R(), row: Math.floor(R() * 3), c: ['#ef4444', '#f59e0b', '#22c55e', '#3b82f6', '#a855f7', '#ec4899', '#facc15', '#14b8a6', '#f97316'][Math.floor(R() * 9)], ph: R() * TAU, s: 0.8 + R() * 0.4 }));
const STARS = Array.from({ length: 120 }, () => ({ x: R(), y: R() * 0.5, r: 0.5 + R() * 1.3, ph: R() * TAU }));
const SPECKS = Array.from({ length: 260 }, () => ({ x: R(), y: R(), r: 0.6 + R() * 2.2, d: R() < 0.5 }));
const CLOUDS = Array.from({ length: 6 }, (_, i) => ({ x: i / 6 + R() * 0.1, y: 0.05 + R() * 0.18, s: 0.6 + R() * 0.7 }));
const HOUSES = Array.from({ length: 10 }, () => ({ w: 0.16 + R() * 0.1, h: 0.18 + R() * 0.16, c: ['#fca5a5', '#fde68a', '#a7f3d0', '#bfdbfe', '#f5d0fe', '#fdba74', '#c4b5fd'][Math.floor(R() * 7)], door: R() }));
const FLAGS = ['#ef4444', '#f59e0b', '#22c55e', '#3b82f6', '#a855f7', '#ec4899'];

export const PALETTE = {
  player: { jersey: '#16a34a', jersey2: '#22c55e', shorts: '#1e3a8a', skin: '#c68642', hair: '#1f1308', shoe: '#f8fafc', num: '7' },
  raider: { jersey: '#dc2626', jersey2: '#f87171', shorts: '#111827', skin: '#8d5524', hair: '#111', shoe: '#fbbf24', num: '9', band: '#facc15' },
  bowler: { jersey: '#2563eb', jersey2: '#60a5fa', shorts: '#e5e7eb', skin: '#a0622d', hair: '#111', shoe: '#f8fafc', num: '18' },
  coach: { jersey: '#db2777', jersey2: '#f472b6', shorts: '#312e81', skin: '#c68642', hair: '#2b1608', shoe: '#fde047', num: '★' },
};

// ------------------------------------------------------------------ effects
export const FX = { parts: [], texts: [], shake: 0, flash: null };

export function burst(x, y, { n = 24, colors = ['#fde047', '#22c55e', '#22d3ee', '#f472b6'], speed = 380, size = 7, gravity = 700, shape = 'mix', life = 0.9 } = {}) {
  for (let i = 0; i < n; i++) {
    const a = Math.random() * TAU, v = speed * (0.35 + Math.random() * 0.75);
    FX.parts.push({ x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v - speed * 0.35, life, max: life,
                    c: colors[i % colors.length], s: size * (0.6 + Math.random() * 0.8), g: gravity,
                    shape: shape === 'mix' ? ['star', 'circle', 'square'][i % 3] : shape, rot: Math.random() * TAU, vr: (Math.random() - 0.5) * 12 });
  }
}
export function dust(x, y, n = 10, color = 'rgba(214,180,140,0.8)') {
  for (let i = 0; i < n; i++) {
    FX.parts.push({ x: x + (Math.random() - 0.5) * 40, y, vx: (Math.random() - 0.5) * 160, vy: -40 - Math.random() * 90, life: 0.7, max: 0.7,
                    c: color, s: 6 + Math.random() * 10, g: -20, shape: 'puff', rot: 0, vr: 0 });
  }
}
export function confetti(W, H, n = 160) {
  for (let i = 0; i < n; i++) {
    FX.parts.push({ x: Math.random() * W, y: -20 - Math.random() * H * 0.4, vx: (Math.random() - 0.5) * 120, vy: 120 + Math.random() * 220,
                    life: 3.5, max: 3.5, c: FLAGS[i % FLAGS.length], s: 6 + Math.random() * 7, g: 60, shape: 'square', rot: Math.random() * TAU, vr: (Math.random() - 0.5) * 10 });
  }
}
export function floatText(x, y, text, { color = '#fde047', size = 46, life = 1.1, stroke = '#1e1b4b' } = {}) {
  FX.texts.push({ x, y, text, color, size, life, max: life, stroke });
}
export function shake(px) { FX.shake = Math.max(FX.shake, px); }

export function fxStep(dt) {
  for (const p of FX.parts) { p.vy += p.g * dt; p.x += p.vx * dt; p.y += p.vy * dt; p.rot += p.vr * dt; p.life -= dt; }
  FX.parts = FX.parts.filter((p) => p.life > 0);
  for (const t of FX.texts) t.life -= dt;
  FX.texts = FX.texts.filter((t) => t.life > 0);
  FX.shake *= Math.pow(0.0015, dt);
  if (FX.shake < 0.3) FX.shake = 0;
}
function star(g, r) {
  g.beginPath();
  for (let i = 0; i < 10; i++) { const a = -Math.PI / 2 + i * Math.PI / 5, rr = i % 2 ? r * 0.45 : r; g.lineTo(Math.cos(a) * rr, Math.sin(a) * rr); }
  g.closePath(); g.fill();
}
export function fxDraw(g, font) {
  for (const p of FX.parts) {
    const a = clamp(p.life / p.max, 0, 1);
    g.save(); g.globalAlpha = p.shape === 'puff' ? a * 0.6 : Math.min(1, a * 1.6); g.fillStyle = p.c; g.translate(p.x, p.y); g.rotate(p.rot);
    if (p.shape === 'star') star(g, p.s);
    else if (p.shape === 'square') g.fillRect(-p.s / 2, -p.s / 3, p.s, p.s * 0.66);
    else if (p.shape === 'puff') { g.beginPath(); g.arc(0, 0, p.s * (1.6 - a), 0, TAU); g.fill(); }
    else { g.beginPath(); g.arc(0, 0, p.s / 2, 0, TAU); g.fill(); }
    g.restore();
  }
  for (const t of FX.texts) {
    const u = 1 - t.life / t.max, pop = u < 0.15 ? 0.6 + u / 0.15 * 0.5 : 1.1 - Math.min(0.1, (u - 0.15));
    g.save(); g.globalAlpha = clamp(t.life / (t.max * 0.35), 0, 1);
    g.translate(t.x, t.y - u * 90); g.scale(pop, pop);
    g.font = `${Math.round(t.size)}px ${font}`; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.lineJoin = 'round'; g.lineWidth = Math.max(4, t.size * 0.16); g.strokeStyle = t.stroke; g.strokeText(t.text, 0, 0);
    g.fillStyle = t.color; g.fillText(t.text, 0, 0);
    g.restore();
  }
}

// ------------------------------------------------------------------ small helpers
function skyGrad(g, W, y0, y1, stops) {
  const gr = g.createLinearGradient(0, y0, 0, y1);
  stops.forEach(([o, c]) => gr.addColorStop(o, c));
  g.fillStyle = gr; g.fillRect(0, y0, W, y1 - y0);
}
function glow(g, x, y, r, color, alpha = 1) {
  const gr = g.createRadialGradient(x, y, 0, x, y, r);
  gr.addColorStop(0, color); gr.addColorStop(1, 'rgba(0,0,0,0)');
  g.save(); g.globalAlpha = alpha; g.fillStyle = gr; g.fillRect(x - r, y - r, 2 * r, 2 * r); g.restore();
}
function cloud(g, x, y, s) {
  g.beginPath();
  for (const [dx, dy, r] of [[0, 0, 30], [32, -12, 34], [66, 0, 28], [30, 10, 30]]) { g.moveTo(x + dx * s + r * s, y + dy * s); g.arc(x + dx * s, y + dy * s, r * s, 0, TAU); }
  g.fill();
}
function persp(g, W, horizon, groundY, H, color, lines = 9, alpha = 0.5) {
  g.save(); g.strokeStyle = color; g.globalAlpha = alpha; g.lineWidth = 2;
  const vx = W / 2;
  for (let i = -lines; i <= lines; i++) { g.beginPath(); g.moveTo(vx + i * W * 0.02, horizon); g.lineTo(vx + i * W * 0.35, H); g.stroke(); }
  for (let k = 1; k < 10; k++) { const y = horizon + (H - horizon) * Math.pow(k / 10, 1.8); g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke(); }
  g.restore();
}

// ------------------------------------------------------------------ worlds
/** Background of a level. groundY = where the player's feet are on screen. t = seconds. */
export function drawWorld(g, world, W, H, groundY, t, o = {}) {
  const horizon = clamp(groundY - H * 0.42, H * 0.22, H * 0.5);
  switch (world) {
    case 'kabaddi': case 'title': return kabaddi(g, W, H, horizon, groundY, t, o);
    case 'jungle': return jungle(g, W, H, horizon, groundY, t, o);
    case 'street': return street(g, W, H, horizon, groundY, t, o);
    case 'lab': return lab(g, W, H, horizon, groundY, t, o);
    case 'stadium': return stadium(g, W, H, horizon, groundY, t, o);
    case 'stage': return stage(g, W, H, horizon, groundY, t, o);
    default: g.fillStyle = '#050b18'; g.fillRect(0, 0, W, H);
  }
}

function bunting(g, W, H, t) {
  for (const [y0, sag, n, off] of [[H * 0.04, H * 0.07, 16, 0], [H * 0.1, H * 0.05, 13, 0.5]]) {
    g.strokeStyle = '#3f1d0b'; g.lineWidth = 2; g.beginPath();
    for (let i = 0; i <= 40; i++) { const u = i / 40, x = u * W, y = y0 + Math.sin(u * Math.PI) * sag; i ? g.lineTo(x, y) : g.moveTo(x, y); }
    g.stroke();
    for (let i = 0; i < n; i++) {
      const u = (i + off) / n, x = u * W, y = y0 + Math.sin(u * Math.PI) * sag, sw = Math.sin(t * 2 + i) * 4, s = Math.min(W, H) * 0.028;
      g.fillStyle = FLAGS[i % FLAGS.length]; g.beginPath(); g.moveTo(x - s * 0.6, y); g.lineTo(x + s * 0.6, y); g.lineTo(x + sw, y + s * 1.3); g.closePath(); g.fill();
    }
  }
}
function palms(g, W, horizon, color) {
  g.fillStyle = color; g.strokeStyle = color;
  for (let i = 0; i < 9; i++) {
    const x = (i + 0.3) / 9 * W + (i % 2 ? 20 : -15), h = horizon * (0.35 + (i % 3) * 0.08), lean = (i % 2 ? 1 : -1) * 18;
    g.lineWidth = 7; g.beginPath(); g.moveTo(x, horizon); g.quadraticCurveTo(x + lean * 0.3, horizon - h * 0.5, x + lean, horizon - h); g.stroke();
    for (let k = 0; k < 6; k++) {
      const a = -Math.PI / 2 + (k - 2.5) * 0.55, L = 46 + (k % 2) * 12;
      g.lineWidth = 9; g.beginPath(); g.moveTo(x + lean, horizon - h);
      g.quadraticCurveTo(x + lean + Math.cos(a) * L * 0.6, horizon - h + Math.sin(a) * L * 0.6 - 10, x + lean + Math.cos(a) * L, horizon - h + Math.sin(a) * L + 18);
      g.stroke();
    }
  }
}
function crowd(g, W, horizon, t, dim = 1, excite = 0) {
  const base = horizon;
  for (let row = 2; row >= 0; row--) {
    for (const p of CROWD) {
      if (p.row !== row) continue;
      const s = (10 + row * 3) * p.s, x = p.x * W, jump = Math.max(0, Math.sin(t * (5 + excite * 4) + p.ph)) * (2 + excite * 9);
      const y = base - row * 9 - jump;
      g.globalAlpha = 0.85 * dim; g.fillStyle = p.c; g.beginPath(); g.roundRect ? g.roundRect(x - s * 0.55, y - s * 0.9, s * 1.1, s * 1.3, 4) : g.rect(x - s * 0.55, y - s * 0.9, s * 1.1, s * 1.3); g.fill();
      g.fillStyle = '#4a2a15'; g.beginPath(); g.arc(x, y - s * 1.2, s * 0.42, 0, TAU); g.fill();
      if (excite > 0.3 && p.ph > 3) { g.strokeStyle = '#4a2a15'; g.lineWidth = 3; g.beginPath(); g.moveTo(x - s * 0.5, y - s * 0.8); g.lineTo(x - s * 0.8, y - s * 1.8 - jump); g.stroke(); }
    }
  }
  g.globalAlpha = 1;
}
function kabaddi(g, W, H, horizon, groundY, t, o) {
  skyGrad(g, W, 0, horizon, [[0, '#4c1d95'], [0.45, '#db2777'], [0.8, '#fb923c'], [1, '#fde68a']]);
  glow(g, W * 0.72, horizon - H * 0.02, H * 0.42, 'rgba(253,224,71,0.55)');
  g.fillStyle = '#fde047'; g.beginPath(); g.arc(W * 0.72, horizon - H * 0.02, H * 0.09, Math.PI, 0); g.fill();
  palms(g, W, horizon, '#3b0f2e');
  crowd(g, W, horizon, t, 1, o.excite || 0);
  // mud court
  const gr = g.createLinearGradient(0, horizon, 0, H); gr.addColorStop(0, '#9a5b2b'); gr.addColorStop(1, '#6b3a17');
  g.fillStyle = gr; g.fillRect(0, horizon, W, H - horizon);
  g.fillStyle = 'rgba(60,30,10,0.35)';
  for (const s of SPECKS) { const y = horizon + s.y * (H - horizon); g.beginPath(); g.arc(s.x * W, y, s.r * (0.4 + s.y), 0, TAU); g.fill(); }
  // court lines (white lime) in perspective
  g.strokeStyle = 'rgba(255,255,255,0.85)'; g.lineWidth = 4;
  const vx = W / 2;
  for (const k of [-1.15, 1.15]) { g.beginPath(); g.moveTo(vx + k * W * 0.08, horizon + 6); g.lineTo(vx + k * W * 0.7, H); g.stroke(); }
  g.beginPath(); g.moveTo(vx, horizon + 6); g.lineTo(vx, H); g.stroke();
  for (const d of [0.25, 0.62]) { const y = horizon + (H - horizon) * d; g.beginPath(); g.moveTo(vx - W * (0.08 + 0.62 * d), y); g.lineTo(vx + W * (0.08 + 0.62 * d), y); g.stroke(); }
  bunting(g, W, H, t);
  // warm dust motes
  g.fillStyle = 'rgba(255,220,160,0.5)';
  for (let i = 0; i < 24; i++) { const x = ((i * 97 + t * 18 * (1 + i % 3)) % W), y = horizon + ((i * 53) % (H - horizon)) - Math.sin(t + i) * 10; g.beginPath(); g.arc(x, y, 1.8, 0, TAU); g.fill(); }
}
function jungle(g, W, H, horizon, groundY, t) {
  skyGrad(g, W, 0, horizon + 2, [[0, '#38bdf8'], [1, '#e0f2fe']]);
  glow(g, W * 0.15, H * 0.12, H * 0.3, 'rgba(255,255,220,0.8)');
  g.fillStyle = 'rgba(255,255,255,0.92)';
  for (const c of CLOUDS) cloud(g, ((c.x + t * 0.008 * c.s) % 1.2 - 0.1) * W, c.y * H, c.s * H / 600);
  const hills = [['#86efac', 0.55, 0.11, 0.02], ['#4ade80', 0.4, 0.08, 0.05], ['#16a34a', 0.25, 0.06, 0.1]];
  for (const [c, hh, amp, sp] of hills) {
    g.fillStyle = c; g.beginPath(); g.moveTo(0, horizon);
    for (let x = 0; x <= W; x += 12) g.lineTo(x, horizon - H * hh * 0.35 - Math.sin(x / W * 6 + t * sp + hh * 9) * H * amp);
    g.lineTo(W, horizon + 4); g.lineTo(0, horizon + 4); g.fill();
  }
  // trees
  for (let i = 0; i < 7; i++) {
    const x = ((i + 0.5) / 7) * W + (i % 2 ? 24 : -10), s = H * (0.07 + (i % 3) * 0.015), y = horizon;
    g.fillStyle = '#713f12'; g.fillRect(x - s * 0.12, y - s * 1.3, s * 0.24, s * 1.3);
    g.fillStyle = i % 2 ? '#15803d' : '#166534';
    for (const [dx, dy, r] of [[0, -1.6, 0.75], [-0.5, -1.25, 0.55], [0.5, -1.25, 0.55]]) { g.beginPath(); g.arc(x + dx * s, y + dy * s, r * s, 0, TAU); g.fill(); }
  }
  const gr = g.createLinearGradient(0, horizon, 0, H); gr.addColorStop(0, '#65a30d'); gr.addColorStop(1, '#3f6212');
  g.fillStyle = gr; g.fillRect(0, horizon, W, H - horizon);
  // dirt track
  g.fillStyle = '#b45309'; g.beginPath(); g.moveTo(W * 0.46, horizon); g.lineTo(W * 0.54, horizon); g.lineTo(W * 1.1, H); g.lineTo(-W * 0.1, H); g.fill();
  g.fillStyle = 'rgba(120,53,15,0.35)';
  for (const s of SPECKS) { if (!s.d) continue; const y = horizon + s.y * (H - horizon); g.beginPath(); g.arc(W / 2 + (s.x - 0.5) * W * (0.1 + s.y), y, s.r, 0, TAU); g.fill(); }
  // flowers
  for (const s of SPECKS) { if (s.d) continue; const y = horizon + s.y * (H - horizon), x = s.x * W; if (Math.abs(x - W / 2) < W * (0.06 + 0.5 * s.y)) continue; g.fillStyle = s.r > 1.8 ? '#fde047' : '#f9a8d4'; g.beginPath(); g.arc(x, y, 1.5 + s.y * 2.5, 0, TAU); g.fill(); }
}
function street(g, W, H, horizon, groundY, t, o) {
  const scroll = o.scroll || 0;
  skyGrad(g, W, 0, horizon, [[0, '#0ea5e9'], [1, '#bae6fd']]);
  g.fillStyle = 'rgba(255,255,255,0.9)';
  for (const c of CLOUDS) cloud(g, (((c.x - scroll * 0.00004 - t * 0.004) % 1.2 + 1.2) % 1.2 - 0.1) * W, c.y * H * 0.7, c.s * H / 650);
  // houses scroll slower (parallax)
  let x = -((scroll * 0.35) % (W * 1.6));
  for (let k = 0; k < 2; k++) for (const hs of HOUSES) {
    const w = hs.w * W, h = hs.h * H, y = horizon;
    g.fillStyle = hs.c; g.fillRect(x, y - h, w - 6, h);
    g.fillStyle = 'rgba(0,0,0,0.12)'; g.fillRect(x, y - h, w - 6, 8);
    g.fillStyle = '#78350f'; g.fillRect(x + (w - 6) * (0.15 + 0.5 * hs.door), y - h * 0.42, (w - 6) * 0.18, h * 0.42);
    g.fillStyle = '#1e3a8a';
    for (let wx = 0; wx < 2; wx++) g.fillRect(x + (w - 6) * (0.18 + wx * 0.46), y - h * 0.8, (w - 6) * 0.2, h * 0.18);
    x += w;
  }
  // road
  const gr = g.createLinearGradient(0, horizon, 0, H); gr.addColorStop(0, '#a8a29e'); gr.addColorStop(1, '#57534e');
  g.fillStyle = gr; g.fillRect(0, horizon, W, H - horizon);
  g.fillStyle = '#e7e5e4'; g.fillRect(0, horizon, W, 6);
  // speed dashes
  g.fillStyle = 'rgba(255,255,255,0.75)';
  for (let i = 0; i < 12; i++) {
    const y = horizon + (H - horizon) * (0.35 + 0.05 * (i % 3)), dx = ((i * 211 - scroll * 1.6) % (W + 200) + W + 200) % (W + 200) - 100;
    g.fillRect(dx, y + (i % 4) * (H - horizon) * 0.14, W * 0.07, 6);
  }
  // lamp posts (fast parallax)
  for (let i = 0; i < 4; i++) {
    const lx = ((i * W * 0.42 - scroll * 0.9) % (W * 1.68) + W * 1.68) % (W * 1.68) - W * 0.1;
    g.fillStyle = '#334155'; g.fillRect(lx, horizon - H * 0.3, 6, H * 0.3 + 10);
    g.fillRect(lx, horizon - H * 0.3, 34, 6); g.fillStyle = '#fde047'; g.beginPath(); g.arc(lx + 34, horizon - H * 0.3 + 10, 7, 0, TAU); g.fill();
  }
}
function lab(g, W, H, horizon, groundY, t) {
  skyGrad(g, W, 0, H, [[0, '#020617'], [0.6, '#0b1b3a'], [1, '#082f49']]);
  persp(g, W, H * 0.55, groundY, H, '#22d3ee', 10, 0.25);
  g.strokeStyle = 'rgba(34,211,238,0.25)'; g.lineWidth = 1.5;
  for (let i = 0; i < 14; i++) {
    const x = (i * 137 % 100) / 100 * W, y = ((i * 71 + t * 20) % 100) / 100 * H * 0.6, r = 14 + (i % 4) * 8;
    g.beginPath(); for (let k = 0; k < 6; k++) { const a = k / 6 * TAU + t * 0.3; g.lineTo(x + Math.cos(a) * r, y + Math.sin(a) * r); } g.closePath(); g.stroke();
  }
}
function stadium(g, W, H, horizon, groundY, t, o) {
  const dark = o.dark || 0;
  skyGrad(g, W, 0, horizon, [[0, '#020617'], [1, '#312e81']]);
  for (const s of STARS) { g.globalAlpha = 0.5 + 0.5 * Math.sin(t * 2 + s.ph); g.fillStyle = '#fff'; g.beginPath(); g.arc(s.x * W, s.y * horizon, s.r, 0, TAU); g.fill(); }
  g.globalAlpha = 1;
  // stands with flash bulbs
  g.fillStyle = '#1e1b4b'; g.fillRect(0, horizon - H * 0.12, W, H * 0.12);
  for (const p of CROWD) {
    const on = Math.sin(t * 3 + p.ph * 7) > 0.97;
    g.fillStyle = on ? '#fff' : p.c; g.globalAlpha = on ? 1 : 0.55;
    g.fillRect(p.x * W, horizon - H * 0.11 + p.row * H * 0.03 + (p.ph % 1) * 6, 4, 4);
  }
  g.globalAlpha = 1;
  // floodlight towers
  for (const fx of [0.08, 0.92]) {
    const x = fx * W, top = H * 0.05;
    g.fillStyle = '#475569'; g.fillRect(x - 4, top, 8, horizon - top);
    g.fillStyle = dark > 0.5 ? '#334155' : '#fefce8'; g.fillRect(x - 40, top - 26, 80, 30);
    if (dark < 0.5) {
      glow(g, x, top - 10, H * 0.35, 'rgba(254,252,232,0.55)');
      g.save(); g.globalAlpha = 0.12; g.fillStyle = '#fefce8'; g.beginPath(); g.moveTo(x - 30, top); g.lineTo(x + 30, top); g.lineTo(W / 2 + (fx < 0.5 ? -W * 0.05 : W * 0.05), H); g.lineTo(W / 2 + (fx < 0.5 ? -W * 0.45 : W * 0.45), H); g.fill(); g.restore();
    }
  }
  // outfield with mowing stripes
  const gr = g.createLinearGradient(0, horizon, 0, H); gr.addColorStop(0, '#15803d'); gr.addColorStop(1, '#14532d');
  g.fillStyle = gr; g.fillRect(0, horizon, W, H - horizon);
  g.fillStyle = 'rgba(255,255,255,0.05)';
  for (let k = 0; k < 8; k += 2) { const y0 = horizon + (H - horizon) * Math.pow(k / 8, 1.6), y1 = horizon + (H - horizon) * Math.pow((k + 1) / 8, 1.6); g.fillRect(0, y0, W, y1 - y0); }
  // pitch strip towards the bowler
  const pw0 = W * 0.035, pw1 = W * 0.24, pitchTop = horizon + (H - horizon) * 0.08;
  g.fillStyle = '#d6b37a'; g.beginPath(); g.moveTo(W / 2 - pw0, pitchTop); g.lineTo(W / 2 + pw0, pitchTop); g.lineTo(W / 2 + pw1, H); g.lineTo(W / 2 - pw1, H); g.fill();
  g.strokeStyle = '#fff'; g.lineWidth = 3;
  const crease = pitchTop + (H - pitchTop) * 0.06; g.beginPath(); g.moveTo(W / 2 - pw0 * 1.8, crease); g.lineTo(W / 2 + pw0 * 1.8, crease); g.stroke();
  // far stumps
  g.fillStyle = '#fef3c7'; for (const dx of [-6, 0, 6]) g.fillRect(W / 2 + dx - 1.5, pitchTop - 22, 3, 22);
  if (dark) { g.fillStyle = `rgba(0,0,0,${0.82 * dark})`; g.fillRect(0, 0, W, H); }
}
function stage(g, W, H, horizon, groundY, t, o) {
  const beat = o.beat || 0;
  skyGrad(g, W, 0, H, [[0, '#1e1b4b'], [0.7, '#581c87'], [1, '#2e1065']]);
  // spotlights
  g.save(); g.globalCompositeOperation = 'lighter';
  [['rgba(236,72,153,0.22)', 0.2, 1.1], ['rgba(34,211,238,0.2)', 0.8, -1.3], ['rgba(250,204,21,0.18)', 0.5, 0.7]].forEach(([c, fx, sp]) => {
    const a = Math.sin(t * sp) * 0.5, x0 = fx * W, y0 = -10, L = H * 1.3;
    g.fillStyle = c; g.beginPath(); g.moveTo(x0, y0); g.lineTo(x0 + Math.sin(a - 0.15) * L, y0 + Math.cos(a - 0.15) * L); g.lineTo(x0 + Math.sin(a + 0.15) * L, y0 + Math.cos(a + 0.15) * L); g.fill();
  });
  g.restore();
  // speaker stacks
  for (const sx of [0.05, 0.95]) {
    const x = sx * W, y = horizon + 10, w = W * 0.07, h = H * 0.3;
    g.fillStyle = '#0f172a'; g.fillRect(x - w / 2, y - h, w, h);
    for (let k = 0; k < 2; k++) { g.fillStyle = '#1e293b'; g.beginPath(); g.arc(x, y - h * (0.3 + k * 0.42), w * (0.32 + 0.04 * beat), 0, TAU); g.fill(); g.fillStyle = '#475569'; g.beginPath(); g.arc(x, y - h * (0.3 + k * 0.42), w * 0.1, 0, TAU); g.fill(); }
  }
  // light-up dance floor
  const rows = 6, cols = 10;
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const y0 = horizon + (H - horizon) * Math.pow(r / rows, 1.5), y1 = horizon + (H - horizon) * Math.pow((r + 1) / rows, 1.5);
    const w0 = W * (0.3 + 0.7 * r / rows), w1 = W * (0.3 + 0.7 * (r + 1) / rows);
    const xa0 = W / 2 - w0 / 2 + c * w0 / cols, xa1 = xa0 + w0 / cols, xb0 = W / 2 - w1 / 2 + c * w1 / cols, xb1 = xb0 + w1 / cols;
    const lit = ((r * 7 + c * 3 + Math.floor(t * 2)) % 5 === 0);
    g.fillStyle = lit ? ['#f472b6', '#22d3ee', '#facc15', '#a78bfa'][(r + c) % 4] : ((r + c) % 2 ? '#1e1b4b' : '#312e81');
    g.globalAlpha = lit ? 0.55 + 0.4 * beat : 0.9;
    g.beginPath(); g.moveTo(xa0, y0); g.lineTo(xa1, y0); g.lineTo(xb1, y1); g.lineTo(xb0, y1); g.closePath(); g.fill();
  }
  g.globalAlpha = 1;
}

// ------------------------------------------------------------------ front-view cartoon figure from body points
// P[i] = {x, y} screen points for MediaPipe indices (0 nose, 2/5 eyes, 11-16 arms, 23-28 legs).
const DARK = '#0f172a';
function seg(g, a, b, w, color) {
  g.strokeStyle = DARK; g.lineWidth = w + 5; g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.stroke();
  g.strokeStyle = color; g.lineWidth = w; g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.stroke();
}
function dot(g, p, r, color) { g.fillStyle = DARK; g.beginPath(); g.arc(p.x, p.y, r + 2.5, 0, TAU); g.fill(); g.fillStyle = color; g.beginPath(); g.arc(p.x, p.y, r, 0, TAU); g.fill(); }
export function drawFigure(g, P, st, { glowColor = null, alpha = 1, face = 1 } = {}) {
  const sw = Math.hypot(P[11].x - P[12].x, P[11].y - P[12].y);
  const torso = Math.hypot((P[11].x + P[12].x) / 2 - (P[23].x + P[24].x) / 2, (P[11].y + P[12].y) / 2 - (P[23].y + P[24].y) / 2);
  const u = Math.max(sw * 0.55, torso * 0.45, 10);           // body unit
  g.save(); g.globalAlpha = alpha; g.lineCap = 'round'; g.lineJoin = 'round';
  if (glowColor) { g.shadowColor = glowColor; g.shadowBlur = 24; }
  const mid = (a, b, f = 0.5) => ({ x: lerp(P[a].x, P[b].x, f), y: lerp(P[a].y, P[b].y, f) });
  // shadow on the ground
  const fy = Math.max(P[27].y, P[28].y);
  g.fillStyle = 'rgba(0,0,0,0.25)'; g.beginPath(); g.ellipse((P[27].x + P[28].x) / 2, fy + u * 0.12, u * 1.2, u * 0.22, 0, 0, TAU); g.fill();
  // legs
  for (const [h, k, a] of [[23, 25, 27], [24, 26, 28]]) {
    seg(g, P[h], P[k], u * 0.42, st.skin); seg(g, P[k], P[a], u * 0.36, st.skin);
    seg(g, P[h], mid(h, k, 0.55), u * 0.5, st.shorts);
    g.fillStyle = DARK; g.beginPath(); g.ellipse(P[a].x, P[a].y + u * 0.05, u * 0.32, u * 0.17, 0, 0, TAU); g.fill();
    g.fillStyle = st.shoe; g.beginPath(); g.ellipse(P[a].x, P[a].y + u * 0.03, u * 0.26, u * 0.12, 0, 0, TAU); g.fill();
  }
  // torso (jersey)
  const ls = P[11], rs = P[12], lh = P[23], rh = P[24];
  const pad = u * 0.12;
  g.fillStyle = st.jersey; g.strokeStyle = DARK; g.lineWidth = 4;
  g.beginPath();
  g.moveTo(ls.x + Math.sign(ls.x - rs.x) * pad, ls.y - pad * 0.5); g.lineTo(rs.x + Math.sign(rs.x - ls.x) * pad, rs.y - pad * 0.5);
  g.lineTo(rh.x + Math.sign(rh.x - lh.x) * pad * 0.6, rh.y + pad); g.lineTo(lh.x + Math.sign(lh.x - rh.x) * pad * 0.6, lh.y + pad);
  g.closePath(); g.fill(); g.stroke();
  // jersey stripe + number
  const cx = (ls.x + rs.x + lh.x + rh.x) / 4, cy = (ls.y + rs.y + lh.y + rh.y) / 4;
  g.fillStyle = st.jersey2; g.globalAlpha = alpha * 0.9;
  g.beginPath(); g.moveTo(ls.x, ls.y); g.lineTo(rs.x, rs.y); g.lineTo(lerp(rs.x, rh.x, 0.18), lerp(rs.y, rh.y, 0.18)); g.lineTo(lerp(ls.x, lh.x, 0.18), lerp(ls.y, lh.y, 0.18)); g.fill();
  g.globalAlpha = alpha;
  if (st.num) { g.fillStyle = '#fff'; g.font = `900 ${Math.round(u * 0.62)}px system-ui`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(st.num, cx, cy + u * 0.08); }
  // arms
  for (const [s, e, w] of [[11, 13, 15], [12, 14, 16]]) {
    seg(g, P[s], P[e], u * 0.34, st.skin); seg(g, P[e], P[w], u * 0.3, st.skin);
    seg(g, P[s], mid(s, e, 0.35), u * 0.42, st.jersey);
    dot(g, P[w], u * 0.17, st.skin);
  }
  // head
  const hx = P[0].x, hy = P[0].y - u * 0.1, hr = u * 0.62;
  seg(g, { x: (ls.x + rs.x) / 2, y: (ls.y + rs.y) / 2 }, { x: hx, y: hy + hr * 0.6 }, u * 0.3, st.skin);
  dot(g, { x: hx, y: hy }, hr, st.skin);
  g.fillStyle = st.hair; g.beginPath(); g.arc(hx, hy - hr * 0.05, hr * 1.02, Math.PI * 1.02, Math.PI * 1.98); g.fill();
  if (st.band) { g.fillStyle = st.band; g.fillRect(hx - hr, hy - hr * 0.45, hr * 2, hr * 0.22); }
  if (face) {
    g.fillStyle = DARK; for (const dx of [-0.32, 0.32]) { g.beginPath(); g.arc(hx + dx * hr, hy + hr * 0.05, hr * 0.11, 0, TAU); g.fill(); }
    g.strokeStyle = DARK; g.lineWidth = Math.max(2, hr * 0.08); g.beginPath(); g.arc(hx, hy + hr * 0.25, hr * 0.32, 0.2 * Math.PI, 0.8 * Math.PI); g.stroke();
  }
  g.restore();
}

/** Body points (normalised, as a camera sees a person facing it) for each move - used by the
 *  dancing coach and by the simulated player. Index -> [x, y]. */
export function movePose(move, { run = 0, squatDepth = 1 } = {}) {
  const sq = move === 'squat' ? squatDepth : 0, dy = (a, b) => a + (b - a) * sq;
  const P = {};
  P[0] = [0.5, dy(0.18, 0.33)]; P[2] = [0.515, dy(0.165, 0.315)]; P[5] = [0.485, dy(0.165, 0.315)];
  P[11] = [0.56, dy(0.3, 0.45)]; P[12] = [0.44, dy(0.3, 0.45)];
  P[23] = [0.54, dy(0.55, 0.68)]; P[24] = [0.46, dy(0.55, 0.68)];
  P[25] = sq ? [0.6, 0.74] : [0.545, 0.72 - Math.max(0, run) * 0.08]; P[26] = sq ? [0.4, 0.74] : [0.455, 0.72 - Math.max(0, -run) * 0.08];
  P[27] = [0.55, 0.9]; P[28] = [0.45, 0.9];
  let lw = [0.58, sq ? 0.62 : 0.58], rw = [0.42, sq ? 0.62 : 0.58];
  if (move === 'hands_up') { lw = [0.56, 0.02]; rw = [0.44, 0.02]; }
  if (move === 'left_hand_up') lw = [0.56, 0.02];
  if (move === 'right_hand_up') rw = [0.44, 0.02];
  if (move === 'hands_on_head') { lw = [0.53, 0.1]; rw = [0.47, 0.1]; }
  if (move === 'arms_out') { lw = [0.8, 0.31]; rw = [0.2, 0.31]; }
  if (move === 'hands_on_hips') { lw = [0.57, 0.53]; rw = [0.43, 0.53]; }
  P[15] = lw; P[16] = rw;
  const ls = P[11], rs = P[12];
  if (move === 'hands_on_hips' || move === 'hands_on_head') { P[13] = [Math.max(ls[0], lw[0]) + 0.08, (ls[1] + lw[1]) / 2]; P[14] = [Math.min(rs[0], rw[0]) - 0.08, (rs[1] + rw[1]) / 2]; }
  else { P[13] = [(ls[0] + lw[0]) / 2, (ls[1] + lw[1]) / 2]; P[14] = [(rs[0] + rw[0]) / 2, (rs[1] + rw[1]) / 2]; }
  return P;
}

// ------------------------------------------------------------------ side-view runner (raider) and front-view bowler
/** Side-view cartoon runner. x, footY = point on the ground; h = standing height px; dir +1 = faces right. */
export function drawRunner(g, x, footY, h, st, { dir = 1, phase = 0, lean = 0.25, reach = 0, alpha = 1 } = {}) {
  const u = h / 10;
  g.save(); g.globalAlpha = alpha; g.lineCap = 'round'; g.lineJoin = 'round';
  g.fillStyle = 'rgba(0,0,0,0.25)'; g.beginPath(); g.ellipse(x, footY + u * 0.2, u * 2.2, u * 0.45, 0, 0, TAU); g.fill();
  const hip = { x, y: footY - u * 4.6 };
  const leg = (ph) => {
    const th = 0.75 * Math.sin(ph), kn = 0.2 + 0.9 * Math.max(0, -Math.cos(ph));
    const k = { x: hip.x + dir * Math.sin(th) * u * 2.4, y: hip.y + Math.cos(th) * u * 2.4 };
    const a = { x: k.x + dir * Math.sin(th - kn) * u * 2.3, y: k.y + Math.cos(th - kn) * u * 2.3 };
    return [k, a];
  };
  const sh = { x: hip.x + dir * Math.sin(lean) * u * 3.2, y: hip.y - Math.cos(lean) * u * 3.2 };
  const arm = (ph, isReach) => {
    if (isReach) { const e = { x: sh.x + dir * u * 1.8, y: sh.y + u * 0.2 }; return [e, { x: e.x + dir * u * 1.7, y: e.y - u * 0.3 }]; }
    const a = -0.9 * Math.sin(ph);
    const e = { x: sh.x + dir * Math.sin(a) * u * 1.6, y: sh.y + Math.cos(a) * u * 1.6 };
    return [e, { x: e.x + dir * Math.sin(a + 1.4) * u * 1.4, y: e.y + Math.cos(a + 1.4) * u * 1.4 }];
  };
  const [k2, a2] = leg(phase + Math.PI), [e2, w2] = arm(phase + Math.PI, false);
  // back limbs (darker)
  seg(g, sh, e2, u * 0.75, shade(st.skin)); seg(g, e2, w2, u * 0.65, shade(st.skin));
  seg(g, hip, k2, u * 0.95, shade(st.skin)); seg(g, k2, a2, u * 0.8, shade(st.skin)); shoe(g, a2, dir, u, st.shoe);
  // torso
  seg(g, hip, sh, u * 2.0, st.jersey);
  g.fillStyle = '#fff'; g.font = `900 ${Math.round(u * 1.1)}px system-ui`; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(st.num || '', (hip.x + sh.x) / 2, (hip.y + sh.y) / 2);
  seg(g, hip, { x: hip.x + dir * u * 0.3, y: hip.y + u * 0.9 }, u * 1.6, st.shorts);
  const [k1, a1] = leg(phase), [e1, w1] = arm(phase, reach > 0);
  seg(g, hip, k1, u * 0.95, st.skin); seg(g, k1, a1, u * 0.8, st.skin); shoe(g, a1, dir, u, st.shoe);
  // head
  const head = { x: sh.x + dir * u * 0.5, y: sh.y - u * 1.25 };
  dot(g, head, u * 1.05, st.skin);
  g.fillStyle = st.hair; g.beginPath(); g.arc(head.x - dir * u * 0.1, head.y - u * 0.15, u * 1.08, Math.PI * (dir > 0 ? 1.0 : 1.05), Math.PI * (dir > 0 ? 1.95 : 2.0)); g.fill();
  if (st.band) { g.fillStyle = st.band; g.save(); g.translate(head.x, head.y - u * 0.45); g.fillRect(-u * 1.05, -u * 0.18, u * 2.1, u * 0.36); g.restore(); }
  g.fillStyle = DARK; g.beginPath(); g.arc(head.x + dir * u * 0.5, head.y, u * 0.16, 0, TAU); g.fill();
  g.strokeStyle = DARK; g.lineWidth = u * 0.18; g.beginPath(); g.moveTo(head.x + dir * u * 0.25, head.y - u * 0.35); g.lineTo(head.x + dir * u * 0.75, head.y - u * 0.25); g.stroke();
  // front arm on top
  seg(g, sh, e1, u * 0.75, st.skin); seg(g, e1, w1, u * 0.65, st.skin); dot(g, w1, u * 0.35, st.skin);
  g.restore();
}
function shoe(g, a, dir, u, c) { g.fillStyle = DARK; g.beginPath(); g.ellipse(a.x + dir * u * 0.35, a.y, u * 0.75, u * 0.38, 0, 0, TAU); g.fill(); g.fillStyle = c; g.beginPath(); g.ellipse(a.x + dir * u * 0.35, a.y - u * 0.04, u * 0.6, u * 0.26, 0, 0, TAU); g.fill(); }
function shade(hex) {
  const n = parseInt(hex.slice(1), 16); const f = 0.72;
  return `rgb(${Math.round((n >> 16) * f)},${Math.round(((n >> 8) & 255) * f)},${Math.round((n & 255) * f)})`;
}

/** The bowler, seen from the batter's end. All the direction cues (drift, lean, front foot, arm path)
 *  come from the Read-the-Bowler test and are unchanged. Returns the hand position. */
export function drawBowler(g, cx, groundY, H, t, dir, { showBall = false, reveal = 0 } = {}) {
  const smooth = (a, b, x) => { const u = clamp((x - a) / (b - a), 0, 1); return u * u * (3 - 2 * u); };
  const z = smooth(0, 1.4, t);
  const h = H * (0.12 + 0.2 * z);                         // grows as he runs in
  const foot = groundY - H * (0.32 - 0.2 * z);
  const cue = smooth(0.9, 1.75, t);
  const x = cx + dir * h * 0.35 * cue;
  const lean = dir * 0.25 * smooth(1.2, 1.75, t);
  const run = t < 1.4 ? Math.sin(t * 13) : 0;
  const u = h / 10;
  const hipY = foot - u * 4.6;
  const P = {};
  P[23] = { x: x + u * 0.8, y: hipY }; P[24] = { x: x - u * 0.8, y: hipY };
  const lift = (s) => Math.max(0, s) * u * 1.6;
  P[25] = { x: x + u * 0.9 + dir * u * 0.6 * cue, y: hipY + u * 2.3 - lift(run) }; P[26] = { x: x - u * 0.9 + dir * u * 0.6 * cue, y: hipY + u * 2.3 - lift(-run) };
  P[27] = { x: x + u * 1.0 + dir * u * 1.2 * cue, y: foot - lift(run) * 0.6 }; P[28] = { x: x - u * 1.0 + dir * u * 1.2 * cue, y: foot - lift(-run) * 0.6 };
  const shx = x + Math.sin(lean) * u * 3.4, shy = hipY - Math.cos(lean) * u * 3.4;
  P[11] = { x: shx + u * 1.1, y: shy }; P[12] = { x: shx - u * 1.1, y: shy };
  P[0] = { x: shx + Math.sin(lean) * u * 1.2, y: shy - u * 1.6 };
  // bowling arm (right arm, screen-left of him as he faces us): windmill over the top
  const armT = smooth(1.35, 1.75, t);
  const a0 = Math.PI * 0.55, a1 = -Math.PI * 0.5 + dir * 0.5 * cue;
  const aa = t < 1.35 ? Math.PI * 0.5 + 0.35 * Math.sin(t * 13) : a0 + (a1 - a0) * armT - (armT > 0 ? Math.PI * 2 * 0 : 0);
  const S = P[12];
  P[14] = { x: S.x + Math.cos(aa) * u * 1.8, y: S.y + Math.sin(aa) * u * 1.8 };
  P[16] = { x: S.x + Math.cos(aa) * u * 3.4, y: S.y + Math.sin(aa) * u * 3.4 };
  const L = P[11], fa = t < 1.35 ? Math.PI * 0.5 - 0.35 * Math.sin(t * 13) : Math.PI * 0.15 - dir * 0.4 * cue;
  P[13] = { x: L.x + Math.cos(fa) * u * 1.8, y: L.y + Math.sin(fa) * u * 1.8 };
  P[15] = { x: L.x + Math.cos(fa) * u * 3.3, y: L.y + Math.sin(fa) * u * 3.3 };
  drawFigure(g, P, PALETTE.bowler, { face: 1 });
  const hand = P[16];
  if (t < 1.75 && !showBall) drawBall(g, hand.x, hand.y, u * 0.55, t * 8);
  return { hand, h, foot, x };
}
export function drawBall(g, x, y, r, rot = 0) {
  g.save(); g.translate(x, y); g.rotate(rot);
  const gr = g.createRadialGradient(-r * 0.35, -r * 0.35, r * 0.1, 0, 0, r);
  gr.addColorStop(0, '#fca5a5'); gr.addColorStop(0.5, '#dc2626'); gr.addColorStop(1, '#7f1d1d');
  g.fillStyle = gr; g.beginPath(); g.arc(0, 0, r, 0, TAU); g.fill();
  g.strokeStyle = '#fef3c7'; g.lineWidth = Math.max(1, r * 0.14); g.beginPath(); g.arc(0, 0, r * 0.75, -0.9, 0.9); g.stroke();
  g.restore();
}

// ------------------------------------------------------------------ props
export function drawLog(g, x, groundY, r, rot) {
  g.save();
  g.fillStyle = 'rgba(0,0,0,0.3)'; g.beginPath(); g.ellipse(x + r * 0.6, groundY + r * 0.12, r * 2.2, r * 0.3, 0, 0, TAU); g.fill();
  // body going back in depth
  g.fillStyle = '#78350f'; g.strokeStyle = DARK; g.lineWidth = 4;
  g.beginPath(); g.moveTo(x, groundY - 2 * r); g.lineTo(x + r * 2.6, groundY - 2 * r - r * 0.5); g.lineTo(x + r * 2.6, groundY - r * 0.5); g.lineTo(x, groundY); g.closePath(); g.fill(); g.stroke();
  g.strokeStyle = 'rgba(0,0,0,0.35)'; g.lineWidth = 3;
  for (let k = 0; k < 4; k++) { const off = ((k * 0.25 + rot / TAU) % 1) * r * 2.6; g.beginPath(); g.moveTo(x + off, groundY - 2 * r - off * 0.19); g.lineTo(x + off, groundY - off * 0.19); g.stroke(); }
  g.fillStyle = '#5b2a0b'; g.beginPath(); g.ellipse(x + r * 2.6, groundY - r - r * 0.5, r * 0.35, r, 0, 0, TAU); g.fill();
  // end face, rolling
  g.translate(x, groundY - r);
  g.fillStyle = '#f59e0b'; g.beginPath(); g.arc(0, 0, r, 0, TAU); g.fill(); g.strokeStyle = DARK; g.lineWidth = 4; g.stroke();
  g.strokeStyle = '#b45309'; g.lineWidth = 3;
  for (const f of [0.75, 0.5, 0.25]) { g.beginPath(); g.arc(0, 0, r * f, 0, TAU); g.stroke(); }
  g.rotate(rot); g.strokeStyle = '#92400e'; g.lineWidth = 3;
  for (let k = 0; k < 3; k++) { g.rotate(TAU / 3); g.beginPath(); g.moveTo(0, 0); g.lineTo(r * 0.85, 0); g.stroke(); }
  g.restore();
}
export function drawBull(g, x, groundY, h, phase, dir = 1) {
  const u = h / 10;
  g.save(); g.lineCap = 'round';
  g.fillStyle = 'rgba(0,0,0,0.28)'; g.beginPath(); g.ellipse(x, groundY + u * 0.3, u * 6, u * 0.8, 0, 0, TAU); g.fill();
  const bodyY = groundY - u * 5.2 + Math.sin(phase * 2) * u * 0.3;
  // legs (gallop)
  for (const [dx, ph] of [[-3.4, 0], [-2.2, 1.2], [2.4, 2.6], [3.4, 3.8]]) {
    const a = Math.sin(phase + ph) * 0.6;
    seg(g, { x: x + dir * dx * u, y: bodyY + u * 1.2 }, { x: x + dir * (dx * u + Math.sin(a) * u * 3.4), y: groundY - u * 0.2 + Math.max(0, -Math.cos(phase + ph)) * -u * 0.8 }, u * 1.1, '#5b3416');
  }
  // body
  g.fillStyle = '#7c4a21'; g.strokeStyle = DARK; g.lineWidth = 5;
  g.beginPath(); g.ellipse(x, bodyY, u * 4.6, u * 2.6, 0, 0, TAU); g.fill(); g.stroke();
  g.fillStyle = '#9a6a3a'; g.beginPath(); g.ellipse(x + dir * u * 1.2, bodyY - u * 1.2, u * 1.8, u * 1.2, 0, 0, TAU); g.fill();   // hump
  // tail
  g.strokeStyle = DARK; g.lineWidth = u * 0.35; g.beginPath(); g.moveTo(x - dir * u * 4.4, bodyY - u * 0.5); g.quadraticCurveTo(x - dir * u * 6, bodyY - u * 2 + Math.sin(phase * 3) * u, x - dir * u * 6.2, bodyY + u * 0.8); g.stroke();
  // head
  const hx = x + dir * u * 5.2, hy = bodyY + u * 0.6;
  g.fillStyle = '#6b3a17'; g.beginPath(); g.ellipse(hx, hy, u * 1.9, u * 1.6, 0, 0, TAU); g.fill(); g.lineWidth = 5; g.strokeStyle = DARK; g.stroke();
  g.fillStyle = '#fbcfe8'; g.beginPath(); g.ellipse(hx + dir * u * 1.1, hy + u * 0.7, u * 1.0, u * 0.75, 0, 0, TAU); g.fill(); g.stroke();
  g.fillStyle = DARK; g.beginPath(); g.arc(hx + dir * u * 0.9, hy + u * 0.7, u * 0.15, 0, TAU); g.arc(hx + dir * u * 1.35, hy + u * 0.7, u * 0.15, 0, TAU); g.fill();
  g.strokeStyle = '#facc15'; g.lineWidth = u * 0.22; g.beginPath(); g.arc(hx + dir * u * 1.12, hy + u * 1.25, u * 0.4, 0, Math.PI); g.stroke();   // nose ring
  // horns
  g.strokeStyle = '#fef3c7'; g.lineWidth = u * 0.55;
  for (const s of [-1, 1]) { g.beginPath(); g.moveTo(hx + s * u * 0.9, hy - u * 1.1); g.quadraticCurveTo(hx + s * u * 2.6, hy - u * 1.6, hx + s * u * 2.3, hy - u * 3.2); g.stroke(); }
  // angry eyes
  g.fillStyle = '#fff'; g.beginPath(); g.arc(hx - dir * u * 0.2, hy - u * 0.3, u * 0.42, 0, TAU); g.fill();
  g.fillStyle = '#dc2626'; g.beginPath(); g.arc(hx - dir * u * 0.12, hy - u * 0.28, u * 0.2, 0, TAU); g.fill();
  g.strokeStyle = DARK; g.lineWidth = u * 0.25; g.beginPath(); g.moveTo(hx - dir * u * 0.8, hy - u * 1.0); g.lineTo(hx + dir * u * 0.3, hy - u * 0.6); g.stroke();
  g.restore();
}

/** Glowing scan rings around the face for the pulse check. */
export function drawScanner(g, cx, cy, r, t, progress, bpm) {
  g.save();
  g.strokeStyle = 'rgba(34,211,238,0.9)'; g.lineWidth = 4; g.shadowColor = '#22d3ee'; g.shadowBlur = 18;
  for (let k = 0; k < 3; k++) {
    const rr = r * (1 + k * 0.12), a0 = t * (k % 2 ? -1.2 : 0.9) + k;
    g.beginPath(); g.arc(cx, cy, rr, a0, a0 + Math.PI * (0.6 + 0.2 * k)); g.stroke();
    g.beginPath(); g.arc(cx, cy, rr, a0 + Math.PI, a0 + Math.PI * (1.6 + 0.2 * k)); g.stroke();
  }
  g.strokeStyle = '#22c55e'; g.lineWidth = 9; g.beginPath(); g.arc(cx, cy, r * 1.42, -Math.PI / 2, -Math.PI / 2 + progress * TAU); g.stroke();
  // scan line
  const sy = cy - r + ((t * 0.8) % 1) * 2 * r;
  const gr = g.createLinearGradient(0, sy - 12, 0, sy + 12); gr.addColorStop(0, 'rgba(34,211,238,0)'); gr.addColorStop(0.5, 'rgba(34,211,238,0.6)'); gr.addColorStop(1, 'rgba(34,211,238,0)');
  g.shadowBlur = 0; g.fillStyle = gr; g.fillRect(cx - r, sy - 12, 2 * r, 24);
  g.restore();
  // ECG line
  if (bpm) {
    const w = r * 2.2, x0 = cx - w / 2, y0 = cy + r * 1.75; g.save(); g.strokeStyle = '#f43f5e'; g.lineWidth = 4; g.shadowColor = '#f43f5e'; g.shadowBlur = 12; g.beginPath();
    for (let i = 0; i <= 120; i++) {
      const ph = ((i / 120) * 3 - t * bpm / 60) % 1, ecg = ph < 0 ? ph + 1 : ph;
      const yy = ecg > 0.45 && ecg < 0.5 ? -1 : ecg > 0.5 && ecg < 0.55 ? 0.6 : ecg > 0.6 && ecg < 0.7 ? -0.2 : 0;
      const X = x0 + (i / 120) * w, Y = y0 + yy * r * 0.35; i ? g.lineTo(X, Y) : g.moveTo(X, Y);
    }
    g.stroke(); g.restore();
  }
}
