// the first version, copied from arena.js (classify + "5 frames in a row")
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
function angle(a, b, c) { const v1x = a.x - b.x, v1y = a.y - b.y, v2x = c.x - b.x, v2y = c.y - b.y; const n = Math.hypot(v1x, v1y) * Math.hypot(v2x, v2y); return n === 0 ? 180 : Math.acos(clamp((v1x * v2x + v1y * v2y) / n, -1, 1)) * 180 / Math.PI; }
export function classifyOld(lm, scope, vw = 640, vh = 480) {
  const P = (i) => ({ x: lm[i].x * vw, y: lm[i].y * vh });
  const vis = (...ids) => ids.every((i) => lm[i].v >= 0.5);
  if (!vis(0, 11, 12, 15, 16)) return 'unknown';
  const hipsOk = vis(23, 24);
  if (!hipsOk && scope !== 'upper') return 'unknown';
  const sh = { x: (P(11).x + P(12).x) / 2, y: (P(11).y + P(12).y) / 2 };
  const hp = hipsOk ? { x: (P(23).x + P(24).x) / 2, y: (P(23).y + P(24).y) / 2 } : { x: sh.x, y: sh.y + 1.5 * Math.hypot(P(11).x - P(12).x, P(11).y - P(12).y) };
  const torso = Math.max(Math.hypot(hp.x - sh.x, hp.y - sh.y), 1), nose = P(0), lw = P(15), rw = P(16);
  const near = (a, b, k) => Math.hypot(a.x - b.x, a.y - b.y) < k * torso;
  if (vis(25, 26, 27, 28)) { const knee = (angle(P(23), P(25), P(27)) + angle(P(24), P(26), P(28))) / 2; if (knee < 125) return 'squat'; }
  const upL = lw.y < nose.y - 0.45 * torso, upR = rw.y < nose.y - 0.45 * torso;
  if (upL && upR) return 'hands_up';
  const head = { x: nose.x, y: nose.y - 0.35 * torso };
  if (near(lw, head, 0.5) && near(rw, head, 0.5)) return 'hands_on_head';
  const lowL = lw.y > sh.y + 0.2 * torso, lowR = rw.y > sh.y + 0.2 * torso;
  if (upL && lowR) return 'left_hand_up';
  if (upR && lowL) return 'right_hand_up';
  const lsh = P(11), rsh = P(12);
  if (Math.abs(lw.y - lsh.y) < 0.3 * torso && Math.abs(rw.y - rsh.y) < 0.3 * torso && Math.abs(lw.x - lsh.x) > 0.7 * torso && Math.abs(rw.x - rsh.x) > 0.7 * torso) return 'arms_out';
  let bl = 180, br = 180;
  if (vis(13, 14)) { bl = angle(lsh, P(13), lw); br = angle(rsh, P(14), rw); }
  if (hipsOk && near(lw, P(23), 0.4) && near(rw, P(24), 0.4) && bl < 130 && br < 130) return 'hands_on_hips';
  if (lowL && lowR && bl > 140 && br > 140) return 'neutral';
  return 'unknown';
}
export function runOld(frames, scope) {
  const got = []; let cand = null, n = 0, last = null;
  for (const f of frames) {
    if (!f.lm) continue;                       // the game skips frames with no person
    const mv = classifyOld(f.lm, scope);
    if (mv === cand) n++; else { cand = mv; n = 1; }
    const stable = n >= 5 ? mv : null;
    if (stable && stable !== 'neutral' && stable !== 'unknown' && stable !== last) { got.push(stable); last = stable; }
    if (stable === 'neutral') last = null;
  }
  return got;
}
