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

// ------------------------------------------------------------------ PunchDetector (Shadow Boxing)
// A real punch goes FORWARD, towards the camera: in the picture the fist hardly moves sideways - it stays in
// front of the shoulder and just gets bigger. So a punch is read from MediaPipe's 3D "world" points (metres,
// z = towards the camera): the wrist shoots forward of the shoulder with the elbow (nearly) straight.
// Side punches (hooks, or reaching out to the side) are read from the 2D picture as well.
// Each arm must come back (retract) before it can punch again, so holding an arm out never scores twice.
// feed() returns the punches that landed in this frame: [{ arm: 'L'|'R' (athlete's own side = screen side in
// the mirrored view), kind: 'forward'|'side', wx: wrist x in mirrored pixels }].
const ang3 = (a, b, c) => {
  const v1 = [a.x - b.x, a.y - b.y, a.z - b.z], v2 = [c.x - b.x, c.y - b.y, c.z - b.z];
  const n = Math.hypot(...v1) * Math.hypot(...v2);
  return n === 0 ? 180 : Math.acos(clamp((v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2]) / n, -1, 1)) * 180 / Math.PI;
};
export class PunchDetector {
  constructor({ fwdReach = 0.3, fwdStraight = 120, sideReach = 1.15, back = 0.15 } = {}) {
    this.o = { fwdReach, fwdStraight, sideReach, back };
    this.arm = { L: this.fresh(), R: this.fresh() };
  }
  fresh() { return { armed: true, ext: 0, len: [], lastZ: null, lastT: null, reach: 0, side: 0, hist: [] }; }
  reset() { this.arm = { L: this.fresh(), R: this.fresh() }; }
  feed(t, lm, world, { vw = 640, vh = 480 } = {}) {
    const out = [];
    if (!lm) return out;
    const px = (i) => ({ x: (1 - lm[i].x) * vw, y: lm[i].y * vh });                   // mirrored pixels
    const sw = Math.max(8, Math.abs(px(11).x - px(12).x)), mid = (px(11).x + px(12).x) / 2;
    for (const [name, s, e, w] of [['L', 11, 13, 15], ['R', 12, 14, 16]]) {
      const A = this.arm[name];
      if (lm[s].v < 0.5) { A.ext = 0; continue; }
      // --- 3D: how far the fist is in front of the shoulder, as a share of the arm's length
      let fwd = null, straight = 180, speed = 0;
      if (world && world[s] && world[e] && world[w] && world[w].v >= 0.2 && world[e].v >= 0.2) {
        const S3 = world[s], E3 = world[e], W3 = world[w];
        const len = Math.hypot(S3.x - E3.x, S3.y - E3.y, S3.z - E3.z) + Math.hypot(E3.x - W3.x, E3.y - W3.y, E3.z - W3.z);
        A.len.push(len); if (A.len.length > 45) A.len.shift();
        const L = clamp([...A.len].sort((a, b) => a - b)[A.len.length >> 1], 0.35, 0.9);   // steady arm length
        fwd = (S3.z - W3.z) / L; straight = ang3(S3, E3, W3);
        // MediaPipe's depth is squeezed and offset differently for every person and camera, so the reach is
        // measured from this arm's own resting (guard) position over the last few seconds
        A.hist.push({ t, f: fwd }); A.hist = A.hist.filter((h) => t - h.t < 4000);
        const fs = A.hist.map((h) => h.f).sort((a, b) => a - b), base = fs[Math.floor(fs.length * 0.2)];
        fwd -= Math.max(-0.1, Math.min(0.35, base));
        if (A.lastZ != null && t > A.lastT) speed = (A.lastZ - W3.z) / ((t - A.lastT) / 1000);   // m/s towards the camera
        A.lastZ = W3.z; A.lastT = t;
      }
      // --- 2D: how far the fist is out to the side of the body, in shoulder widths
      const W2 = px(w), side = lm[w].v >= 0.2 ? Math.abs(W2.x - mid) / sw : 0;
      const straight2 = lm[e].v >= 0.2 && lm[w].v >= 0.2 ? angle(px(s), px(e), W2) : 0;
      A.reach = fwd ?? 0; A.side = side;
      // (the elbow angle in depth is noisy, so a fist far in front of the shoulder counts whatever the angle)
      const forward = fwd != null && (fwd > 0.45 || (fwd > this.o.fwdReach && straight > this.o.fwdStraight - 15) || (fwd > 0.22 && speed > 1.4 && straight > 105));
      const sideways = side > this.o.sideReach && straight2 > 135;
      const retracted = (fwd == null || fwd < this.o.back || straight < 95) && side < 0.85;
      if (retracted) A.armed = true;
      if (A.armed && (forward || sideways)) {
        A.ext++;
        if (A.ext >= 2) { A.armed = false; A.ext = 0; out.push({ arm: name, kind: forward ? 'forward' : 'side', wx: W2.x, sideOf: Math.sign(W2.x - mid) }); }
      } else A.ext = 0;
    }
    return out;
  }
}

// ------------------------------------------------------------------ body measurements (shared by the game and its tests)
// lm: 33 x {x, y, v}, normalised, UN-mirrored (as the camera sees). Results are in MIRRORED screen pixels, so
// "move to the left of the screen" = "move to your own left".
export function bodyInfo(lm, vw, vh) {
  const P = (i) => ({ x: (1 - lm[i].x) * vw, y: lm[i].y * vh, v: lm[i].v });
  const ls = P(11), rs = P(12), lh = P(23), rh = P(24), la = P(27), ra = P(28), nose = P(0), le = P(2), re = P(5);
  const lk = P(25), rk = P(26);
  const ank = (la.y + ra.y) / 2;
  return {
    hipX: (lh.x + rh.x) / 2, hipY: (lh.y + rh.y) / 2, shX: (ls.x + rs.x) / 2, shY: (ls.y + rs.y) / 2,
    sw: Math.max(8, Math.abs(ls.x - rs.x)), nose, ankY: ank, bodyPx: ank - nose.y, lk, rk, la, ra,
    torso: Math.hypot((lh.x + rh.x) / 2 - (ls.x + rs.x) / 2, (lh.y + rh.y) / 2 - (ls.y + rs.y) / 2),
    full: [0, 23, 24, 27, 28].every((i) => lm[i].v >= 0.5),
    upper: [0, 11, 12].every((i) => lm[i].v >= 0.5),          // head + shoulders (hips may be behind a desk)
    face: [0, 2, 5].every((i) => lm[i].v >= 0.5), eyeDist: Math.hypot(le.x - re.x, le.y - re.y),
  };
}
const med = (a) => { const s = [...a].sort((x, y) => x - y), n = s.length; return n ? (n % 2 ? s[n >> 1] : (s[n / 2 - 1] + s[n / 2]) / 2) : NaN; };

// The detectors below are fed ONLY on new camera frames (the game loop runs at 60 Hz, a webcam at 10-30 fps: a
// repeated frame would look like "no movement, then a jump" and would also fake the two-frames-agree checks).

// Raider Dodge: reaction time = when the hips (raw points, no smoothing lag) cross 0.25 shoulder widths to either
// side, confirmed by the next frame, with the moment interpolated between the two frames (a 10 fps camera is not
// 100 ms "slower"); peak sideways speed over 0.12 s windows (start-to-end, so camera jitter doesn't add up);
// dodged = the smoothed hips get 0.8 shoulder widths to the safe side.
export class DodgeReader {
  constructor({ onsetSw = 0.25, safeSw = 0.8, speedWinMs = 120 } = {}) { this.o = { onsetSw, safeSw, speedWinMs }; }
  start(t0, safe, base) {        // safe: +1 = towards larger mirrored x
    this.t0 = t0; this.safe = safe; this.base = base; this.onset = null; this.pend = null; this.prev = null;
    this.hist = []; this.peak = 0; this.dodged = false; this.wrong = null;
  }
  feed(t, raw, sm) {
    const b = this.base, sw = b.sw;
    if (raw) {
      const dr = raw.hipX - b.hipX, thr = this.o.onsetSw * sw;
      if (!this.onset) {
        if (Math.abs(dr) > thr) {
          const dir = Math.sign(dr);
          if (this.pend && this.pend.dir === dir) this.onset = this.pend;
          else {
            let tc = t;     // when it crossed: between the previous frame and this one
            if (this.prev && Math.sign(this.prev.dr) === dir && Math.abs(this.prev.dr) < thr && t > this.prev.t)
              tc = this.prev.t + (t - this.prev.t) * (thr - Math.abs(this.prev.dr)) / Math.max(1e-6, Math.abs(dr) - Math.abs(this.prev.dr));
            else if (this.prev && t > this.prev.t && Math.abs(this.prev.dr) < thr)
              tc = this.prev.t + (t - this.prev.t) * 0.5;
            this.pend = { rt: tc - this.t0, dir };
          }
        } else this.pend = null;
      }
      // started the wrong way: the hips went 0.2 shoulder widths the wrong way, and were already heading that way
      // on the frame before (so one jumpy frame can't say it), before getting past 0.25 to the safe side
      if (this.wrong == null) {
        if (dr * this.safe > thr) this.wrong = false;
        else if (this.prev && -dr * this.safe > 0.8 * thr && -this.prev.dr * this.safe > 0.3 * thr) this.wrong = true;
      }
      this.prev = { t, dr };
      this.hist.push({ t, x: raw.hipX });
      this.hist = this.hist.filter((h) => t - h.t <= this.o.speedWinMs + 1);
      const a = this.hist[0];
      if (t - a.t >= this.o.speedWinMs * 0.75) this.peak = Math.max(this.peak, ((raw.hipX - a.x) / ((t - a.t) / 1000) / sw) * this.safe);
    }
    if (sm && (sm.hipX - b.hipX) * this.safe > this.o.safeSw * sw) this.dodged = true;
    return this.dodged;
  }
  result() {
    return { rt: this.onset ? Math.round(this.onset.rt) : null, wrong_first: !!this.wrong,
             peak_v: +this.peak.toFixed(2), ok: this.dodged };
  }
}

// Log Jump: how high the hips rose above where they were just before the log came. The top of the jump is found
// by fitting the flight's free-fall curve (as the camera tests do), so it is right between frames and one bad
// frame can't make a jump. Rising on the toes (< 8 cm) is not a jump.
export class JumpMeter {
  constructor({ minCm = 8 } = {}) { this.o = { minCm }; }
  start(baseY, cmPerPx, torso = null) { this.baseY = baseY; this.cpp = cmPerPx; this.s = []; this.torso = torso; }
  feed(t, raw) {
    if (!raw) return;
    // a hip put in the wrong place for a frame would look like a jump: the torso can't change length mid-jump
    if (this.torso && (raw.torso < 0.75 * this.torso || raw.torso > 1.33 * this.torso)) return;
    this.s.push({ t, v: (this.baseY - raw.hipY) * this.cpp });
  }
  live() { return this.s.length ? Math.max(0, med(this.s.slice(-3).map((p) => p.v))) : 0; }
  result() {
    const G = 981, vals = this.s.map((p) => p.v).sort((a, b) => a - b);
    // the second-highest frame (one jumpy frame can't make a jump) - unless the camera gave only a few frames
    const robust = vals.length >= 4 ? vals[vals.length - 2] : (vals.length ? vals[vals.length - 1] : 0);
    let apex = robust, tPeak = null;
    let pts = this.s.filter((p) => p.v >= 0.5 * robust && robust > 0);
    // the curve fit is only for real flight: time spent above half the height must match free fall, and the fit
    // may only add what a gap between two frames can hide (a slow rise on the toes is not a flight)
    let gap = 0; for (let i = 1; i < this.s.length; i++) gap = Math.max(gap, (this.s[i].t - this.s[i - 1].t) / 1000);
    const above = pts.length ? (pts[pts.length - 1].t - pts[0].t) / 1000 : 0;
    const ballistic = robust > 0 && above <= 1.5 * 2 * Math.sqrt(robust / G) + gap;
    const maxGain = 0.5 * G * (gap / 2) * (gap / 2) + 2;
    if (!ballistic) pts = [];
    for (let it = 0; it < 3 && pts.length >= 3; it++) {
      const t0 = pts[0].t, xs = pts.map((p) => (p.t - t0) / 1000), ys = pts.map((p, i) => p.v + 0.5 * G * xs[i] * xs[i]);
      const n = xs.length, mx = xs.reduce((a, b) => a + b) / n, my = ys.reduce((a, b) => a + b) / n;
      const sxx = xs.reduce((a, x) => a + (x - mx) * (x - mx), 0); if (sxx <= 1e-9) break;
      const b = xs.reduce((a, x, i) => a + (x - mx) * (ys[i] - my), 0) / sxx, a = my - b * mx;
      const res = pts.map((p, i) => p.v - (a + b * xs[i] - 0.5 * G * xs[i] * xs[i]));
      let worst = 0; res.forEach((r, i) => { if (Math.abs(r) > Math.abs(res[worst])) worst = i; });
      if (Math.abs(res[worst]) > 5 && n > 3) { pts = pts.filter((_, i) => i !== worst); continue; }
      const top = b / G;
      if (top >= Math.min(...xs) - 0.1 && top <= Math.max(...xs) + 0.1) {
        const ap = a + b * b / (2 * G);
        if (ap >= robust - 3 && ap <= robust + maxGain) { apex = Math.max(ap, robust); tPeak = t0 + top * 1000; }
      }
      break;
    }
    if (tPeak == null && this.s.length) { const k = this.s.findIndex((p) => p.v === robust); tPeak = k >= 0 ? this.s[k].t : null; }
    const cm = Math.max(0, apex);
    return { ok: cm >= this.o.minCm && tPeak != null, cm: +cm.toFixed(1), tPeak };
  }
}

// Read the Bowler: the player's answer = the first clear step (or lean, in the upper-body game) to one side,
// seen in the smoothed AND the raw points on two new frames in a row (one jumpy frame can't answer).
export class SideAnswer {
  constructor({ thrSw = 0.45 } = {}) { this.o = { thrSw }; }
  start(baseX, sw, thrSw = this.o.thrSw) { this.baseX = baseX; this.sw = sw; this.thr = thrSw; this.n = 0; this.dir = 0; this.answer = null; }
  feed(t, rawX, smX) {
    if (this.answer || rawX == null || smX == null) return this.answer;
    const ds = smX - this.baseX, dr = rawX - this.baseX, lim = this.thr * this.sw;
    const dir = Math.abs(ds) > lim && Math.abs(dr) > lim && Math.sign(ds) === Math.sign(dr) ? Math.sign(ds) : 0;
    if (dir && dir === this.dir) this.n++; else { this.dir = dir; this.n = dir ? 1 : 0; }
    if (this.n >= 2) this.answer = { side: dir < 0 ? 'L' : 'R', t };
    return this.answer;
  }
}

// Bull Run: a step = the knees swap which one is higher. Fed the RAW points of each new frame (smoothing lags
// and flattens fast knees). Two pose-model mistakes are undone first:
//  - left/right mix-up: running on the spot the knees never cross sideways, so they are put back in the
//    left-right order they had over the last ~30 frames;
//  - a knee or ankle put in the wrong place: the shin (knee to ankle) keeps its length when a knee is lifted
//    (the thigh doesn't - it points at the camera), so a frame whose shin suddenly changes length is skipped.
// Feed it while the player gets ready too (counting = false): it learns the shin lengths and the knee order.
export class StepCounter {
  constructor() { this.steps = 0; this.sign = 0; this.order = []; this.shL = []; this.shR = []; }
  feed(t, body, bodyPx, counting = true) {
    if (!body || !body.la || !body.ra) return false;
    let lk = body.lk, rk = body.rk, la = body.la, ra = body.ra;
    if (Math.min(lk.v ?? 1, rk.v ?? 1) < 0.3) return false;                      // knees not really seen
    const feetSeen = Math.min(la.v ?? 1, ra.v ?? 1) >= 0.3;
    const sx = Math.sign(lk.x - rk.x);
    if (Math.abs(lk.x - rk.x) > 0.03 * bodyPx) { this.order.push(sx); if (this.order.length > 31) this.order.shift(); }
    const usual = Math.sign(this.order.reduce((a, b) => a + b, 0));
    if (usual && sx === -usual && Math.abs(lk.x - rk.x) > 0.03 * bodyPx) { [lk, rk] = [rk, lk]; [la, ra] = [ra, la]; }
    if (feetSeen) {          // (feet cut off by the bottom of the picture: count with the knees alone)
      const sl = Math.hypot(lk.x - la.x, lk.y - la.y), sr = Math.hypot(rk.x - ra.x, rk.y - ra.y);
      if (this.shL.length >= 5) {
        const ml = med(this.shL), mr = med(this.shR);
        if (sl < 0.7 * ml || sl > 1.4 * ml || sr < 0.7 * mr || sr > 1.4 * mr) return false;
      }
      this.shL.push(sl); this.shR.push(sr);
      if (this.shL.length > 45) { this.shL.shift(); this.shR.shift(); }
    }
    if (!counting) return false;
    const d = lk.y - rk.y, thr = 0.05 * bodyPx;
    let stepped = false;
    if (d > thr && this.sign !== 1) { if (this.sign) { this.steps++; stepped = true; } this.sign = 1; }
    else if (d < -thr && this.sign !== -1) { if (this.sign) { this.steps++; stepped = true; } this.sign = -1; }
    return stepped;
  }
}
