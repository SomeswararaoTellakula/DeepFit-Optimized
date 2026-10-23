// Run: node tools/dance_bench/punch.mjs [boxers]   (HARD=1 doubles the camera noise; SEED=n changes the random boxers)
// Shadow Boxing benchmark: a boxer at a laptop (upper body, ~1 m from the camera) throws real punches -
// forward jabs/crosses (towards the camera) and side hooks - at pads that pop up left or right.
// Old rule (first version): a wrist within 0.9 shoulder widths of a pad drawn 1.6 shoulder widths to the side.
// New rule: PunchDetector (3D forward reach from MediaPipe world points + 2D side reach).
import { rng } from './gen.mjs';
import { readFileSync } from 'node:fs';
const src = readFileSync(new URL('../../static/arena/motion.js', import.meta.url), 'utf8');
const { PunchDetector } = await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));
const r = rng(+(process.env.SEED || 42)), HARD = +(process.env.HARD || 0);
const gauss = () => { let u = 0; for (let i = 0; i < 6; i++) u += r(); return (u - 3) / Math.sqrt(0.5); };
const lerp = (a, b, u) => ({ x: a.x + (b.x - a.x) * u, y: a.y + (b.y - a.y) * u, z: a.z + (b.z - a.z) * u });
// arm poses for the athlete's LEFT arm (camera coords, metres, x to the image right = athlete's left, y down, z towards camera negative)
const POSE = {
  guard: { e: { x: 0.2, y: 0.24, z: -0.08 }, w: { x: 0.09, y: -0.02, z: -0.2 } },
  jab: { e: { x: 0.13, y: 0.02, z: -0.27 }, w: { x: 0.08, y: -0.02, z: -0.55 } },
  hook: { e: { x: 0.42, y: 0.0, z: -0.12 }, w: { x: 0.68, y: -0.04, z: -0.18 } },
  block: { e: { x: 0.16, y: 0.12, z: -0.18 }, w: { x: 0.07, y: -0.12, z: -0.32 } },   // defence: hands up and a bit forward
};
const mirror = (p) => ({ x: -p.x, y: p.y, z: p.z });
function person() {
  return { D: 0.8 + r() * 0.5, cx: (r() - 0.5) * 0.15, sh: 0.17 + r() * 0.03, armK: 0.9 + r() * 0.2, zComp: 0.55 + r() * 0.35, zNoise: 0.04 + r() * 0.04 * (1 + HARD), sig: (0.004 + r() * 0.006) * (1 + HARD), jit: 0.6 + r() * 0.8 };
}
function frameOf(p, L, R, bob) {
  const S = { L: { x: p.sh, y: 0, z: 0 }, R: { x: -p.sh, y: 0, z: 0 } };
  const pts3 = {};    // true 3D, relative to the mid-shoulder
  const put = (i, q) => { pts3[i] = { x: q.x + p.cx + bob.x, y: q.y + bob.y, z: q.z }; };
  put(0, { x: 0, y: -0.2, z: -0.08 }); put(2, { x: 0.03, y: -0.23, z: -0.1 }); put(5, { x: -0.03, y: -0.23, z: -0.1 });
  put(11, S.L); put(12, S.R); put(23, { x: 0.1, y: 0.5, z: 0 }); put(24, { x: -0.1, y: 0.5, z: 0 });
  const arm = (pose, s, side) => { const k = p.armK; return { e: { x: s.x + side * (pose.e.x - 0.18) * k + (side < 0 ? 0 : 0), y: pose.e.y * k, z: pose.e.z * k }, w: { x: s.x + side * (pose.w.x - 0.18) * k, y: pose.w.y * k, z: pose.w.z * k } }; };
  const a = arm(L, S.L, 1), b = arm(R, S.R, -1);
  put(13, a.e); put(15, a.w); put(14, b.e); put(16, b.w);
  const lm = Array.from({ length: 33 }, () => ({ x: 0.5, y: 1.4, v: 0.05 })), world = Array.from({ length: 33 }, () => ({ x: 0, y: 0, z: 0, v: 0.05 }));
  for (const i in pts3) {
    const q = pts3[i], d = p.D + q.z;
    lm[i] = { x: 0.5 + 0.866 * q.x / d + gauss() * p.sig * 0.75, y: 0.42 + 0.866 * (4 / 3) * q.y / d + gauss() * p.sig, v: 0.95 };
    world[i] = { x: q.x + gauss() * 0.015, y: q.y + gauss() * 0.015, z: q.z * p.zComp + gauss() * p.zNoise, v: 0.95 };
  }
  for (const i of [23, 24]) lm[i].v = 0.1;
  return { lm, world, pts3 };
}
const poseMix = (a, b, u) => ({ e: lerp(a.e, b.e, u), w: lerp(a.w, b.w, u) });
function oldRule() {                         // the first version, per frame
  let armed = true;
  return (lm, pad, vw = 640, vh = 480) => {
    const px = (i) => ({ x: (1 - lm[i].x) * vw, y: lm[i].y * vh });
    const sw = Math.abs(px(11).x - px(12).x), shX = (px(11).x + px(12).x) / 2, shY = (px(11).y + px(12).y) / 2;
    const guard = [15, 16].every((i) => lm[i].v < 0.4 || Math.abs(px(i).x - shX) < 1.0 * sw); if (guard) armed = true;
    if (!pad) return false;
    const P = { x: shX + pad.side * 1.6 * sw, y: shY + pad.dy * sw };
    const hit = armed && [15, 16].some((i) => lm[i].v >= 0.4 && Math.hypot(px(i).x - P.x, px(i).y - P.y) < 0.9 * sw);
    if (hit) armed = false; return hit;
  };
}
const N = +(process.argv[2] || 200);
const tot = { old: { fwd: 0, side: 0 }, new: { fwd: 0, side: 0 } }; let nf = 0, ns = 0, fpOld = 0, fpNew = 0, secs = 0;
for (let k = 0; k < N; k++) {
  const p = person(), fps = [30, 20, 15][k % 3], dt = 1000 / fps;
  // timeline: 8 pads; each answered by a punch of that side's arm (70 % forward, 30 % hook); between pads: guard with bobbing, sometimes a block
  const events = []; let t = 600;
  for (let i = 0; i < 8; i++) {
    const side = r() < 0.5 ? -1 : 1, kind = r() < 0.7 ? 'jab' : 'hook', rt = 250 + r() * 200, ext = 110 + r() * 100, hold = 40 + r() * 110, back = 180 + r() * 150;
    events.push({ t, side, kind, rt, ext, hold, back, block: r() < 0.3 }); t += rt + ext + hold + back + 500 + r() * 700;
  }
  const old = oldRule(), det = new PunchDetector(); let ft = 0, pad = null, pi = 0, gotOld = new Set(), gotNew = new Set(), bobPh = r() * 6;
  while (ft < t) {
    while (pi < events.length && ft >= events[pi].t + events[pi].rt + events[pi].ext + events[pi].hold + events[pi].back + 400) pi++;
    const ev = events[pi];
    let L = POSE.guard, R = POSE.guard;
    pad = ev && ft >= ev.t && !gotNew.has(pi) ? { side: ev.side, dy: 0, i: pi } : (ev && ft >= ev.t ? { side: ev.side, dy: 0, i: pi } : null);
    if (ev && ft >= ev.t + ev.rt) {
      const u = ft - ev.t - ev.rt, f = u < ev.ext ? u / ev.ext : u < ev.ext + ev.hold ? 1 : Math.max(0, 1 - (u - ev.ext - ev.hold) / ev.back);
      const pz = poseMix(POSE.guard, POSE[ev.kind], f * f * (3 - 2 * f));
      if (ev.side < 0) L = pz; else R = pz;     // screen-left pad -> athlete's left arm (mirrored view)
    } else if (ev && ev.block && ft > ev.t - 450 && ft < ev.t - 50) { L = poseMix(POSE.guard, POSE.block, 0.8); R = poseMix(POSE.guard, POSE.block, 0.8); }
    const bob = { x: Math.sin(ft / 300 + bobPh) * 0.03 * p.jit, y: Math.sin(ft / 170) * 0.015 * p.jit };
    const { lm, world } = frameOf(p, L, R, bob);
    // motion blur: a fast fist sometimes gets a low visibility score
    if (ev && ft >= ev.t + ev.rt && ft < ev.t + ev.rt + ev.ext && r() < 0.35) { const w = ev.side < 0 ? 15 : 16; lm[w].v = 0.25; world[w].v = 0.25; }
    const punching = ev && ft >= ev.t + ev.rt && ft < ev.t + ev.rt + ev.ext + ev.hold + ev.back;
    if (r() > 0.02) {
      // as in the game: a pad disappears once it is hit; a "false punch" = one counted while the boxer was NOT punching
      if (old(lm, pad && !gotOld.has(pi) ? pad : null)) { if (punching) gotOld.add(pi); else fpOld++; }
      const pus = det.feed(ft, lm, world); det.dbg = det.dbg || {}; if (punching) { const a = ev.side < 0 ? 'L' : 'R'; det.dbg[a] = Math.max(det.dbg[a] || -9, det.arm[a].reach); }
      for (const pu of pus) {
        if (!pad || gotNew.has(pi)) continue;
        const toPad = (pu.arm === 'L' ? -1 : 1) === ev.side || pu.sideOf === ev.side;
        if (toPad && punching) gotNew.add(pi); else if (toPad) fpNew++;
      }
    }
    ft += dt * (0.85 + r() * 0.3);
  }
  if (process.env.DEBUG) for (const [i, ev] of events.entries()) if (ev.kind === 'jab' && !gotNew.has(i)) console.log('miss', JSON.stringify({ fps, zComp: p.zComp.toFixed(2), zNoise: p.zNoise.toFixed(3), D: p.D.toFixed(2), ext: Math.round(ev.ext), hold: Math.round(ev.hold), maxF: (det.dbg[ev.side < 0 ? 'L' : 'R'] || 0).toFixed(2) }));
  for (const [i, ev] of events.entries()) { const key = ev.kind === 'jab' ? 'fwd' : 'side'; if (ev.kind === 'jab') nf++; else ns++; if (gotOld.has(i)) tot.old[key]++; if (gotNew.has(i)) tot.new[key]++; }
  secs += t / 1000;
}
const pc = (a, b) => (100 * a / b).toFixed(1) + '%';
console.table({ 'forward punches (jab/cross) counted': { old: pc(tot.old.fwd, nf), new: pc(tot.new.fwd, nf) }, 'side punches (hooks) counted': { old: pc(tot.old.side, ns), new: pc(tot.new.side, ns) },
  'false punches per minute': { old: (fpOld / secs * 60).toFixed(2), new: (fpNew / secs * 60).toFixed(2) } });
