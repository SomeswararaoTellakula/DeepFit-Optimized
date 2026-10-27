// Arena detector stress test: the same realistic camera-facing tracks (arena_tracks.py) through
//   OLD = the logic currently in arena.js, run the way the game runs it (60 Hz loop, a camera frame repeated
//         until the next one arrives, smoothing stepped every loop)
//   NEW = motion.js detectors fed only on new camera frames
// node arena_bench.mjs [tracks.json] [--json]      (make the tracks first: python3 arena_tracks.py 25)
import fs from 'fs';
const M = await import(process.env.MOTION || new URL('../../static/arena/motion.js', import.meta.url).href);
const { LandmarkFilter, bodyInfo, DodgeReader, JumpMeter, SideAnswer, StepCounter } = M;
const tracksArg = process.argv.slice(2).find((a) => !a.startsWith('--'));
const D = JSON.parse(fs.readFileSync(tracksArg || new URL('./arena_tracks.json', import.meta.url), 'utf8'));
const med = (a) => { const s = [...a].sort((x, y) => x - y), n = s.length; return n ? (n % 2 ? s[n >> 1] : (s[n / 2 - 1] + s[n / 2]) / 2) : NaN; };
const mean = (a) => a.length ? a.reduce((x, y) => x + y, 0) / a.length : NaN;
const p90 = (a) => { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.floor(0.9 * (s.length - 1))] : NaN; };
const toLm = (f) => f && f.map((p) => ({ x: p[0], y: p[1], v: p[2] }));

// run a track through a 60 Hz loop; cb(now, ctx) gets old (every tick) and new (fresh frames only) views
function loop(tr, cb) {
  const frames = tr.frames, end = frames[frames.length - 1][0];
  const oldF = new LandmarkFilter(), newF = new LandmarkFilter();
  let k = -1, lastK = -1, ctx = {};
  for (let now = 0; now <= end; now += 1000 / 60) {
    while (k + 1 < frames.length && frames[k + 1][0] <= now) k++;
    const raw = k >= 0 ? toLm(frames[k][1]) : null;
    // OLD: detect() every tick -> the same camera frame again until a new one arrives
    const oLm = oldF.step(raw, now);
    ctx.old = { raw: raw ? bodyInfo(raw, tr.vw, tr.vh) : null, sm: oLm ? bodyInfo(oLm, tr.vw, tr.vh) : null };
    // NEW: only when the camera delivered a new frame
    ctx.fresh = k !== lastK;
    if (ctx.fresh) {
      lastK = k;
      const nLm = newF.step(raw, now);
      ctx.new = { raw: raw ? bodyInfo(raw, tr.vw, tr.vh) : null, sm: nLm ? bodyInfo(nLm, tr.vw, tr.vh) : null };
    }
    cb(now, ctx);
  }
}
// standing still at the start (what Calibrate measures): medians of the smoothed body over 0.4-1.6 s
function baseFrom(tr, scope = 'full') {
  const xs = [];
  loop(tr, (now, c) => { if (now > 400 && now < 1600 && c.old.sm) xs.push(c.old.sm); });
  const g = (f) => med(xs.map(f));
  return scope === 'upper' ? { hipX: g((b) => b.shX), hipY: g((b) => b.shY) + 1.5 * g((b) => b.sw), sw: g((b) => b.sw), bodyPx: g((b) => b.bodyPx), ankY: g((b) => b.ankY) }
                           : { hipX: g((b) => b.hipX), hipY: g((b) => b.hipY), sw: g((b) => b.sw), bodyPx: g((b) => b.bodyPx), ankY: g((b) => b.ankY), torso: g((b) => b.torso) };
}

// ------------------------------------------------------------------ dodge
function dodge() {
  const R = { old: { rt: [], ok: 0, peak: [], wrong: 0, n: 0 }, new: { rt: [], ok: 0, peak: [], wrong: 0, n: 0 } };
  for (const tr of D.dodge) {
    const base = baseFrom(tr), WIN = 1500;
    for (const cue of tr.truth.cues) {
      const t0 = cue.t * 1000, safe = cue.mdir, cross = cue.cross * 1000;
      // OLD (verbatim logic from Dodge.update, 'cue' state)
      let st = { onset: null, pend: null, peak: 0, lastX: null, lastT: t0, done: false, ok: false };
      // NEW
      const dr = new DodgeReader(); dr.start(t0, safe, base); let newDone = false, newOk = false;
      loop(tr, (now, c) => {
        if (now < t0) { return; }
        if (!st.done) {
          const b = c.old.sm, rb = c.old.raw;
          if (b) {
            const d = b.hipX - base.hipX, dt = (now - st.lastT) / 1000;
            if (dt > 0 && st.lastX != null) st.peak = Math.max(st.peak, ((b.hipX - st.lastX) / dt / base.sw) * safe);
            st.lastX = b.hipX; st.lastT = now;
            const drr = rb ? rb.hipX - base.hipX : 0;
            if (!st.onset && rb) {
              if (Math.abs(drr) > 0.25 * base.sw) { if (st.pend && st.pend.dir === Math.sign(drr)) st.onset = st.pend; else st.pend = { rt: now - t0, dir: Math.sign(drr) }; }
              else st.pend = null;
            }
            if (d * safe > 0.8 * base.sw) { st.done = true; st.ok = true; }
          }
          if (now - t0 > WIN) st.done = true;
        }
        if (!newDone && c.fresh) {
          if (dr.feed(now, c.new.raw, c.new.sm)) { newDone = true; newOk = true; }
        }
        if (!newDone && now - t0 > WIN) newDone = true;
      });
      const nr = dr.result();
      for (const [k, onset, peak, ok] of [['old', st.onset, st.peak, st.ok], ['new', nr.rt != null ? { rt: nr.rt, dir: nr.wrong_first ? -safe : safe } : null, nr.peak_v, newOk]]) {
        R[k].n++; if (ok) R[k].ok++;
        if (onset) R[k].rt.push((t0 + onset.rt) - cross);
        R[k].peak.push(peak - cue.peak_sw_s);
        const wrongSeen = onset ? onset.dir !== safe : false;
        if (wrongSeen !== cue.wrong) R[k].wrong++;
      }
    }
  }
  for (const k of ['old', 'new']) {
    const r = R[k];
    console.log(`dodge ${k}: dodged ${r.ok}/${r.n} | reaction time error vs truth: mean ${mean(r.rt).toFixed(0)} ms, |err| mean ${mean(r.rt.map(Math.abs)).toFixed(0)} ms, p90 ${p90(r.rt.map(Math.abs)).toFixed(0)} ms (n=${r.rt.length}) | peak speed error: mean ${mean(r.peak).toFixed(2)} sw/s, |err| p90 ${p90(r.peak.map(Math.abs)).toFixed(2)} | wrong-way calls ${r.wrong}`);
  }
  return R;
}

// ------------------------------------------------------------------ jump
function jump() {
  const R = { old: { err: [], falseClear: 0, missed: 0, n: 0, nNo: 0 }, new: { err: [], falseClear: 0, missed: 0, n: 0, nNo: 0 } };
  for (const tr of D.jump) {
    const base = baseFrom(tr), cpp = (tr.truth.height_cm * 0.88) / base.bodyPx, TRAVEL = 2200;
    for (const L of tr.truth.logs) {
      const tArr = L.tArr * 1000, t0 = tArr - TRAVEL, w0 = tArr - 400, w1 = tArr + 300;
      // OLD (Jump.update)
      let hist = [], rawY = [], peak = 0, tPeak = null;
      const jm = new JumpMeter(); let started = false; const histN = [];
      loop(tr, (now, c) => {
        const b = c.old.sm;
        if (b) { hist.push({ t: now, y: b.hipY }); hist = hist.filter((h) => now - h.t < 4000); }
        if (now >= w0 && now <= w1 && b) {
          const ref = hist.filter((h) => h.t > t0 - 200 && h.t < w0 - 100).map((h) => h.y);
          const bs = ref.length ? med(ref) : base.hipY;
          rawY = rawY.concat(c.old.raw ? [c.old.raw.hipY] : []).slice(-3);
          const rise = bs - (rawY.length ? med(rawY) : b.hipY);
          if (rise > peak) { peak = rise; tPeak = now; }
        }
        // NEW: same baseline (smoothed hips just before the window), raw hips on new frames inside the window
        if (c.fresh && c.new.sm) { histN.push({ t: now, y: c.new.sm.hipY }); }
        if (now >= w0 && now <= w1 && c.fresh) {
          if (!started) { const ref = histN.filter((h) => h.t > t0 - 200 && h.t < w0 - 100).map((h) => h.y); jm.start(ref.length ? med(ref) : base.hipY, cpp, base.torso); started = true; }
          jm.feed(now, c.new.raw);
        }
      });
      const oCm = peak * cpp, oOk = oCm >= 5 && tPeak != null;
      const nr = started ? jm.result() : { ok: false, cm: 0 };
      for (const [k, ok, cm] of [['old', oOk, oCm], ['new', nr.ok, nr.cm]]) {
        if (L.h >= 12) { R[k].n++; if (!ok) R[k].missed++; else R[k].err.push(cm - L.h); }
        else { R[k].nNo++; if (ok) R[k].falseClear++; }
      }
    }
  }
  for (const k of ['old', 'new']) {
    const r = R[k];
    console.log(`jump ${k}: real jumps ${r.n} (missed ${r.missed}) | height error: mean ${mean(r.err).toFixed(1)} cm, |err| mean ${mean(r.err.map(Math.abs)).toFixed(1)} cm, p90 ${p90(r.err.map(Math.abs)).toFixed(1)} cm | toe-raise / no jump counted as cleared: ${r.falseClear}/${r.nNo}`);
  }
  return R;
}

// ------------------------------------------------------------------ bowler
function bowler() {
  const R = { old: { right: 0, n: 0 }, new: { right: 0, n: 0 } };
  for (const tr of D.bowler) {
    const upper = tr.truth.upper, base = baseFrom(tr, upper ? 'upper' : 'full'), thr = upper ? 0.4 : 0.45;
    const pos = (b) => (upper ? b.shX : b.hipX);
    for (const ball of tr.truth.balls) {
      const t0 = ball.t0 * 1000, tEnd = t0 + 1750 + 1700;
      let oAns = null; const sa = new SideAnswer(); sa.start(base.hipX, base.sw, thr); let nAns = null;
      loop(tr, (now, c) => {
        if (now < t0 || now > tEnd) return;
        const t = now - t0;
        if (!oAns && c.old.sm && t > 1100) { const d = pos(c.old.sm) - base.hipX; if (Math.abs(d) > thr * base.sw) oAns = d < 0 ? 'L' : 'R'; }
        if (!nAns && c.fresh && t > 1100 && c.new.sm && c.new.raw) { const a = sa.feed(now, pos(c.new.raw), pos(c.new.sm)); if (a) nAns = a.side; }
      });
      const want = ball.mdir === 0 ? null : (ball.mdir < 0 ? 'L' : 'R');
      for (const [k, a] of [['old', oAns], ['new', nAns]]) { R[k].n++; if (a === want) R[k].right++; }
    }
  }
  for (const k of ['old', 'new']) console.log(`bowler ${k}: answer read right ${R[k].right}/${R[k].n} (${(100 * R[k].right / R[k].n).toFixed(1)}%)`);
  return R;
}

// ------------------------------------------------------------------ bull run steps
function escape() {
  const R = { old: [], new: [] };
  for (const tr of D.escape) {
    const base = baseFrom(tr), t0 = tr.truth.t0 * 1000, t1 = t0 + tr.truth.secs * 1000;
    let sign = 0, steps = 0; const sc = new StepCounter();
    loop(tr, (now, c) => {
      if (c.fresh && now >= t0 && now <= t1) sc.feed(now, c.new.raw, base.bodyPx);      // as the game does: from the start of the run
      if (now < t0 || now > t1) return;
      const b = c.old.sm;
      if (b) {
        const d = b.lk.y - b.rk.y, thr = 0.05 * base.bodyPx;
        if (d > thr && sign !== 1) { if (sign) steps++; sign = 1; } else if (d < -thr && sign !== -1) { if (sign) steps++; sign = -1; }
      }
    });
    const want = tr.truth.steps - 1;
    R.old.push(steps - want); R.new.push(sc.steps - want);
  }
  for (const k of ['old', 'new']) console.log(`bull run ${k}: step count error mean ${mean(R[k]).toFixed(1)}, |err| mean ${mean(R[k].map(Math.abs)).toFixed(1)}, exact ${R[k].filter((x) => x === 0).length}/${R[k].length}`);
  return R;
}

const out = { dodge: dodge(), jump: jump(), bowler: bowler(), escape: escape() };
if (process.argv.includes('--json')) fs.writeFileSync(new URL('./arena_bench_result.json', import.meta.url), JSON.stringify(out));
