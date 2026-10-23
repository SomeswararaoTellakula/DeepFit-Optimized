// Realistic dance-move motion for testing move recognition: arm angles move along arcs (so arms pass through
// other poses on the way), every person is different, MediaPipe-like noise, dropouts, hands leaving the frame,
// motion blur, slow and fast cameras.
export function rng(seed) { let s = seed >>> 0; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
const D = Math.PI / 180;
// per-arm pose: a1 upper-arm angle, a2 forearm angle (deg, 0 = down, 90 = outward, 180 = up, 270 = inward), f = upper-arm foreshortening
export const ARM = {
  neutral: { a1: 10, a2: 6, f: 1, f2: 1 },
  up: { a1: 168, a2: 176, f: 1, f2: 1 },
  out: { a1: 90, a2: 92, f: 1, f2: 1 },
  head: { a1: 112, a2: 242, f: 0.6, f2: 1 },
  hip: { a1: 40, a2: 312, f: 0.9, f2: 1 },
  fwd: { a1: 80, a2: 82, f: 0.25, f2: 0.3 },
};
export const MOVE = {
  neutral: ['neutral', 'neutral', 0], hands_up: ['up', 'up', 0], arms_out: ['out', 'out', 0], hands_on_head: ['head', 'head', 0],
  hands_on_hips: ['hip', 'hip', 0], left_hand_up: ['up', 'neutral', 0], right_hand_up: ['neutral', 'up', 0], squat: ['fwd', 'fwd', 95],
};
export function jitterArm(a, r, k = 1) { return { a1: a.a1 + (r() - 0.5) * 30 * k, a2: a.a2 + (r() - 0.5) * 40 * k, f: Math.min(1, a.f * (0.8 + r() * 0.35)), f2: a.f2 }; }
export function makePerson(r, scope) {
  return { scope, cx: 0.5 + (r() - 0.5) * 0.2, scale: scope === 'upper' ? 1.5 + r() * 0.4 : 0.7 + r() * 0.25, foot: scope === 'upper' ? 1.75 + r() * 0.2 : 0.93 + r() * 0.05,
    shw: 0.105 + r() * 0.025, ua: 0.16 + r() * 0.02, fa: 0.14 + r() * 0.02, sigma: 0.003 + r() * 0.007, squatArms: r() < 0.5 ? 'fwd' : 'neutral', squatDepth: 70 + r() * 40, splay: r() };
}
export function pose(p, armL, armR, knee) {   // 3D-ish -> normalised image points (camera view, not mirrored)
  const k2 = knee * D / 2, hipY = 0.02 + 0.49 * Math.cos(k2) + 0.02, shY = hipY + 0.29, noseY = shY + 0.1;
  const pts = {};
  const put = (i, X, Y) => { pts[i] = { x: p.cx + X * p.scale * 0.75, y: p.foot - Y * p.scale }; };
  put(0, 0, noseY); put(2, 0.03, noseY + 0.02); put(5, -0.03, noseY + 0.02);
  for (const [s, si, ei, wi, hi, ki, ai, arm] of [[1, 11, 13, 15, 23, 25, 27, armL], [-1, 12, 14, 16, 24, 26, 28, armR]]) {
    const S = { X: s * p.shw, Y: shY };
    const d = (a) => ({ x: Math.sin(a * D) * s, y: -Math.cos(a * D) });
    const u = d(arm.a1), v = d(arm.a2);
    const E = { X: S.X + u.x * p.ua * arm.f, Y: S.Y - u.y * p.ua * arm.f * -1 };
    E.Y = S.Y + (-u.y) * p.ua * arm.f * -1 * -1; // y up: -cos -> down
    E.Y = S.Y - Math.cos(arm.a1 * D) * p.ua * arm.f * -1 * -1;
    const W = { X: E.X + v.x * p.fa * arm.f2, Y: E.Y - Math.cos(arm.a2 * D) * p.fa * arm.f2 };
    put(si, S.X, S.Y); put(ei, E.X, E.Y); put(wi, W.X, W.Y);
    put(hi, s * 0.07, hipY);
    const kx = s * (0.07 + 0.08 * Math.sin(k2) * p.splay), ky = 0.04 + 0.245 * Math.cos(k2);
    put(ki, kx, ky); put(ai, s * 0.075, 0.04);
  }
  return pts;
}
const lerpArm = (a, b, u) => ({ a1: a.a1 + (b.a1 - a.a1) * u, a2: a.a2 + (b.a2 - a.a2) * u, f: a.f + (b.f - a.f) * u, f2: a.f2 + (b.f2 - a.f2) * u });
const ease = (u) => u * u * (3 - 2 * u);
// a performance of `seq`: returns frames [{t, lm}] at the given fps, plus the true move intervals
export function perform(r, p, seq, fps, hard = 0) {
  const keys = [];      // {t, L, R, knee, move}
  let t = 0;
  const target = (m) => {
    const [l, rr, kn] = MOVE[m];
    const jk = (m === 'neutral' ? 0.4 : 1) * (1 + hard * 0.4); const L = jitterArm(m === 'squat' ? ARM[p.squatArms] : ARM[l], r, jk), R = jitterArm(m === 'squat' ? ARM[p.squatArms] : ARM[rr], r, jk);
    return { L, R, knee: kn ? p.squatDepth : 0, move: m };
  };
  let cur = target('neutral'); keys.push({ t: 0, ...cur, hold: true }); t = 500 + r() * 400; keys.push({ t, ...cur, hold: true });
  for (let i = 0; i < seq.length; i++) {
    const nxt = target(seq[i]);
    t += 250 + r() * 650; keys.push({ t, ...nxt });           // transition (slow movers too)
    t += (hard ? 300 + r() * 300 : 400 + r() * 600); keys.push({ t, ...nxt, hold: true }); // hold
    if (i === seq.length - 1 || r() < 0.5) { const n = target('neutral'); t += 300 + r() * 300; keys.push({ t, ...n }); t += 250 + r() * 400; keys.push({ t, ...n, hold: true }); }
  }
  t += 1200; keys.push({ t, ...keys[keys.length - 1] });
  const frames = []; let ft = 0; const dt = 1000 / fps;
  let prev = null;
  const gauss = () => { let u = 0; for (let i = 0; i < 6; i++) u += r(); return (u - 3) / Math.sqrt(0.5); };
  while (ft < t) {
    let k = 0; while (k < keys.length - 2 && keys[k + 1].t <= ft) k++;
    const a = keys[k], b = keys[k + 1], u = ease(Math.min(1, Math.max(0, (ft - a.t) / Math.max(1, b.t - a.t))));
    const L = lerpArm(a.L, b.L, u), R = lerpArm(a.R, b.R, u), knee = a.knee + (b.knee - a.knee) * u;
    const pts = pose(p, L, R, knee);
    const lm = Array.from({ length: 33 }, (_, i) => pts[i] ? { ...pts[i] } : { x: p.cx, y: 0.5, v: 0.2 });
    for (let i = 0; i < 33; i++) {
      if (!pts[i]) continue;
      let sig = p.sigma * (1 + hard), v = 0.97 - r() * 0.05;
      if (prev && (i === 15 || i === 16 || i === 13 || i === 14)) {     // motion blur on fast hands
        const sp = Math.hypot(lm[i].x - prev[i].x, lm[i].y - prev[i].y) / (dt / 1000);
        sig += sp * 0.01; if (sp > 1.5 && r() < 0.3) v = 0.2 + r() * 0.3;
      }
      const off = lm[i].y < 0 || lm[i].y > 1 || lm[i].x < 0 || lm[i].x > 1;
      if (off) { v = 0.05 + r() * 0.3; sig += 0.03; }
      lm[i].x += gauss() * sig * 0.75; lm[i].y += gauss() * sig; lm[i].v = v;
    }
    if (r() < 0.02) { const w = r() < 0.5 ? 15 : 16; lm[w].x += (r() - 0.5) * 0.15; lm[w].y += (r() - 0.5) * 0.15; }   // a glitch frame
    if (p.scope === 'upper') for (const i of [23, 24, 25, 26, 27, 28]) lm[i].v = Math.min(lm[i].v, 0.1);
    const keep = r() > 0.02;                                     // dropped frame (no person found)
    frames.push({ t: ft, lm: keep ? lm : null });
    prev = pose(p, L, R, knee); ft += dt * (0.8 + r() * 0.4);
  }
  return frames;
}
