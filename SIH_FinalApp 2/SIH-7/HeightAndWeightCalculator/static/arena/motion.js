// DeepFit Arena - motion reading shared by every level.
//
// 1. LandmarkFilter: a One Euro filter on every body point (Casiez, Roussel & Vogel, CHI 2012). Standing
//    still -> strong smoothing (no jitter); moving fast -> almost none (no lag). Visibility is smoothed too,
//    so one bad frame doesn't make a hand "disappear".
// 2. classifyMove: reads the 11 dance moves from the body points. Compared with the first version it
//    - uses the elbow when the wrist is lost (hands above the top of the picture, motion blur),
//    - accepts natural variations (hands on the waist, not exactly on the hip joint; arms a bit bent),
//    - tells "hands on head" (elbows bent out) from "hands up" (arms reaching up),
//    - can see a squat from the hips dropping when the knees/ankles are out of view.
// 3. MoveTracker: a move counts only when it is HELD for ~0.3 s (by the clock, not by frame count, so a slow
//    phone is not stricter than a fast laptop) and the hands have SETTLED. Arms passing through a pose on
//    the way to another one (e.g. through "arms out" while raising both hands) are no longer counted.
//
// Landmarks: 33 x {x, y, v}, normalised, as the camera sees them (not mirrored). Left/right = the
// athlete's own left/right (MediaPipe 11/13/15/23/25/27 = left).

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

// ------------------------------------------------------------------ One Euro filter
class OneEuro {
  constructor(minCutoff, beta, dCutoff) { this.minCutoff = minCutoff; this.beta = beta; this.dCutoff = dCutoff; this.x = null; this.dx = 0; }
  static alpha(cutoff, dt) { const tau = 1 / (2 * Math.PI * cutoff); return 1 / (1 + tau / dt); }
  step(x, dt) {
    if (this.x == null || !(dt > 0)) { this.x = x; this.dx = 0; return x; }
    const dx = (x - this.x) / dt;
    this.dx += OneEuro.alpha(this.dCutoff, dt) * (dx - this.dx);
    const cutoff = this.minCutoff + this.beta * Math.abs(this.dx);
    this.x += OneEuro.alpha(cutoff, dt) * (x - this.x);
    return this.x;
  }
}

export class LandmarkFilter {
  // units: normalised picture coordinates per second. minCutoff 1.5 Hz at rest; beta 8 opens it up fast.
  constructor({ minCutoff = 1.5, beta = 8, dCutoff = 1.0 } = {}) { this.o = { minCutoff, beta, dCutoff }; this.reset(); }
  reset() { this.f = null; this.t = null; this.v = null; }
  step(lm, tMs) {
    if (!lm) { if (this.t != null && tMs - this.t > 400) this.reset(); return null; }
    const dt = this.t == null ? 0 : (tMs - this.t) / 1000;
    if (this.t != null && dt > 0.4) this.reset();                 // person lost for a while: start fresh
    if (!this.f) { this.f = lm.map(() => [new OneEuro(this.o.minCutoff, this.o.beta, this.o.dCutoff), new OneEuro(this.o.minCutoff, this.o.beta, this.o.dCutoff)]); this.v = lm.map((p) => p.v); }
    this.t = tMs;
    const d = this.t == null ? 0 : Math.max(dt, 0);
    return lm.map((p, i) => {
      this.v[i] = d ? 0.5 * this.v[i] + 0.5 * p.v : p.v;
      return { x: this.f[i][0].step(p.x, d), y: this.f[i][1].step(p.y, d), v: this.v[i] };
    });
  }
}

// ------------------------------------------------------------------ geometry helpers
export function angle(a, b, c) {
  const v1x = a.x - b.x, v1y = a.y - b.y, v2x = c.x - b.x, v2y = c.y - b.y;
  const n = Math.hypot(v1x, v1y) * Math.hypot(v2x, v2y);
  return n === 0 ? 180 : Math.acos(clamp((v1x * v2x + v1y * v2y) / n, -1, 1)) * 180 / Math.PI;
}
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

// One arm, read from shoulder S, elbow E, wrist W (pixels). Returns its state as booleans.
function readArm(lm, P, sIdx, eIdx, wIdx, ctx) {
  const { T, nose, headTop, hip, midX } = ctx;
  const S = P(sIdx), E = P(eIdx);
  // a point the model places ABOVE the top of the picture is still a usable direction (hands up, camera
  // close), even though its visibility score is low
  const above = (i) => lm[i].y < 0 && lm[i].y > -1;
  const eVis = lm[eIdx].v >= 0.4 || above(eIdx);
  let W = P(wIdx), wVis = lm[wIdx].v >= 0.4 || above(wIdx);
  // wrist lost: above the top of the picture (hands up near the camera) or blurred -> extend the forearm
  // from the elbow (forearm ~ upper arm in length).
  if (!wVis && eVis) { W = { x: E.x + (E.x - S.x) * 0.95, y: E.y + (E.y - S.y) * 0.95 }; wVis = true; }
  if (!wVis) return null;
  const bend = eVis ? angle(S, E, W) : 165;                       // 180 = straight arm
  const elbowUp = eVis && E.y < S.y - 0.25 * T;
  const up = (W.y < nose.y - 0.3 * T && bend > 105) || (elbowUp && W.y < S.y - 0.75 * T && bend > 120);
  const onHead = dist(W, headTop) < 0.7 * T && W.y < nose.y + 0.3 * T && W.y > nose.y - 0.95 * T && bend < 120;
  const out = Math.abs(W.y - S.y) < 0.38 * T && Math.abs(W.x - S.x) > 0.62 * T && bend > 125;
  // hands on hips / waist: wrist at waist height on its own side, elbow bent and pointing outwards
  const sideOk = Math.sign(W.x - midX) === Math.sign(S.x - midX) || Math.abs(W.x - midX) > 0.15 * T;
  const onHip = W.y > S.y + 0.45 * T && W.y < hip.y + 0.3 * T && sideOk && bend < 145 &&
                (!eVis || Math.abs(E.x - midX) > Math.abs(W.x - midX) + 0.05 * T);
  const down = W.y > S.y + 0.2 * T && !onHip && bend > 135;
  return { up, onHead, out, onHip, down, W, bend };
}

// classifyMove(lm, {vw, vh, scope, base}) -> one of the dance moves, 'neutral' or 'unknown'
// base (optional): standing hip height and torso in pixels, for seeing a squat without the knees.
export function classifyMove(lm, { vw = 640, vh = 480, scope = 'full', base = null } = {}) {
  if (!lm) return 'unknown';
  const P = (i) => ({ x: lm[i].x * vw, y: lm[i].y * vh });
  const vis = (t, ...ids) => ids.every((i) => lm[i].v >= t);
  if (!vis(0.5, 11, 12) || !vis(0.3, 0)) return 'unknown';
  const sh = { x: (P(11).x + P(12).x) / 2, y: (P(11).y + P(12).y) / 2 };
  const sw = Math.max(1, dist(P(11), P(12)));
  const hipsOk = vis(0.5, 23, 24);
  if (!hipsOk && scope !== 'upper' && !base) return 'unknown';
  const hip = hipsOk ? { x: (P(23).x + P(24).x) / 2, y: (P(23).y + P(24).y) / 2 } : { x: sh.x, y: sh.y + 1.5 * sw };
  const T = Math.max(dist(hip, sh), 0.9 * sw, 1);                 // torso length: the unit for every rule
  const nose = P(0);
  const ctx = { T, nose, headTop: { x: nose.x, y: nose.y - 0.35 * T }, hip, midX: sh.x };
  // squat: bent knees, or (knees out of view) the hips dropped well below their standing height
  // (seen from the front, bent knees often still look almost straight - the thighs point at the camera - so
  // the hip drop is the main signal; the knee angle catches squats with the knees pushed out)
  if (scope !== 'upper') {
    if (base && hipsOk && hip.y > base.hipY + 0.25 * base.torso) return 'squat';
    if (vis(0.5, 23, 24, 25, 26) && vis(0.3, 27, 28)) {
      const knee = (angle(P(23), P(25), P(27)) + angle(P(24), P(26), P(28))) / 2;
      if (knee < 130) return 'squat';
    }
  }
  const L = readArm(lm, P, 11, 13, 15, ctx), R = readArm(lm, P, 12, 14, 16, ctx);
  if (!L || !R) return 'unknown';
  if (L.onHead && R.onHead) return 'hands_on_head';
  if (L.up && R.up) return 'hands_up';
  if (L.out && R.out) return 'arms_out';
  if (L.up && !R.up && !R.out && R.W.y > sh.y) return 'left_hand_up';
  if (R.up && !L.up && !L.out && L.W.y > sh.y) return 'right_hand_up';
  if (L.onHip && R.onHip && hipsOk) return 'hands_on_hips';
  if (L.onHip && R.onHip && scope === 'upper') return 'hands_on_hips';
  if (L.down && R.down) return 'neutral';
  if ((L.down || L.onHip) && (R.down || R.onHip)) return 'neutral';  // one hand resting at the waist
  return 'unknown';
}

// ------------------------------------------------------------------ MoveTracker
// feed(t, move, lm) every frame. Returns the move the moment it is confirmed (once), else null.
// .reading = what the camera sees right now, .progress = 0..1 hold progress (for the on-screen ring).
export class MoveTracker {
  constructor({ holdMs = 300, settleMs = 150, still = 1.6, gapMs = 220 } = {}) {
    this.o = { holdMs, settleMs, still, gapMs }; this.reset();
  }
  reset() { this.cand = null; this.since = 0; this.seen = 0; this.last = null; this.neutralSince = null; this.hist = []; this.reading = 'unknown'; this.progress = 0; this.speed = 0; }
  // how fast the hands moved over the last ~settleMs, in torso lengths per second (start-to-end, so camera
  // noise doesn't add up the way frame-to-frame differences do on a fast camera)
  handSpeed(t, lm, T) {
    if (!lm) return this.speed;
    this.hist.push({ t, w: [lm[15], lm[16]].map((p) => ({ x: p.x, y: p.y })), T });
    this.hist = this.hist.filter((h) => t - h.t <= Math.max(this.o.settleMs, 60));
    const a = this.hist[0], dt = (t - a.t) / 1000;
    this.speed = dt > 0.04 ? Math.max(...a.w.map((w, i) => Math.hypot(w.x - this.hist[this.hist.length - 1].w[i].x, w.y - this.hist[this.hist.length - 1].w[i].y))) / dt / T : this.speed;
    return this.speed;
  }
  feed(t, move, lm) {
    // torso in normalised units, so the speed limit is the same near or far from the camera
    let T = 0.25;
    if (lm) { const sx = (lm[11].x + lm[12].x) / 2, sy = (lm[11].y + lm[12].y) / 2, hx = (lm[23].x + lm[24].x) / 2, hy = (lm[23].y + lm[24].y) / 2;
      T = Math.max(Math.hypot(hx - sx, hy - sy), 1.2 * Math.hypot(lm[11].x - lm[12].x, lm[11].y - lm[12].y), 0.05); }
    this.handSpeed(t, lm, T);
    this.reading = move;
    if (move === 'unknown') {                                    // a short dropout doesn't break a hold
      if (this.cand && t - this.seen > this.o.gapMs) { this.cand = null; this.progress = 0; }
      return null;
    }
    if (move !== this.cand) { this.cand = move; this.since = t; }
    this.seen = t;
    const settled = this.hist.length > 1 && this.speed < this.o.still;
    this.progress = clamp((t - this.since) / this.o.holdMs, 0, 1);
    if (move === 'neutral') {
      this.neutralSince = this.neutralSince || t;
      if (t - this.neutralSince >= 120) this.last = null;            // back to rest: the same move may count again
      return null;
    }
    this.neutralSince = null;
    if (this.progress >= 1 && settled && move !== this.last) { this.last = move; return move; }
    return null;
  }
  get restingFor() { return this.neutralSince; }
}
