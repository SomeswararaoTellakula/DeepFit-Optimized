// Dance-off move recognition benchmark: first version vs motion.js on realistic synthetic motion.
// Run: node tools/dance_bench/bench.mjs [tries per setting]   (HARD=1 for double noise, more pose variety, short holds)
import { rng, makePerson, perform } from './gen.mjs';
import { runOld } from './old.mjs';
// the game's own motion.js (loaded as a module from its source, so this always tests the real file)
import { readFileSync } from 'node:fs';
const src = readFileSync(new URL('../../static/arena/motion.js', import.meta.url), 'utf8');
const { LandmarkFilter, classifyMove, MoveTracker } = await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));
const FULL = ['hands_up', 'left_hand_up', 'right_hand_up', 'arms_out', 'hands_on_head', 'hands_on_hips', 'squat'];
const UPPER = FULL.filter((m) => m !== 'squat' && m !== 'hands_on_hips');
function ed(a, b) { const d = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]); for (let j = 0; j <= b.length; j++) d[0][j] = j;
  for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++) d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)); return d[a.length][b.length]; }
function runNew(frames, scope, base) {
  const f = new LandmarkFilter(), tr = new MoveTracker(), got = [];
  for (const fr of frames) {
    const lm = f.step(fr.lm, fr.t);
    if (!lm) { tr.feed(fr.t, 'unknown', null); continue; }
    const mv = classifyMove(lm, { vw: 640, vh: 480, scope, base });
    const c = tr.feed(fr.t, mv, lm); if (c) got.push(c);
  }
  return got;
}
function baseOf(frames) {          // calibration: standing still at the start, as the game does
  const st = frames.slice(0, 8).filter((x) => x.lm).map((x) => x.lm);
  const hipY = st.reduce((a, l) => a + (l[23].y + l[24].y) / 2, 0) / st.length * 480;
  const shY = st.reduce((a, l) => a + (l[11].y + l[12].y) / 2, 0) / st.length * 480;
  return { hipY, torso: hipY - shY };
}
const N = +(process.argv[2] || 400), out = {};
for (const scope of ['full', 'upper']) for (const fps of [30, 20, 12]) {
  const r = rng(1234 + fps + (scope === 'upper' ? 7 : 0)); const moves = scope === 'upper' ? UPPER : FULL;
  const acc = { old: [0, 0, 0, 0], new: [0, 0, 0, 0] };   // moves read right, total moves, perfect tries, tries
  const conf = {};
  for (let k = 0; k < N; k++) {
    const p = makePerson(r, scope);
    const seq = []; while (seq.length < 5) { const m = moves[Math.floor(r() * moves.length)]; if (m !== seq[seq.length - 1]) seq.push(m); }
    const frames = perform(r, p, seq, fps, +(process.env.HARD || 0));
    const base = scope === 'full' ? baseOf(frames) : null;
    for (const [name, got] of [['old', runOld(frames, scope)], ['new', runNew(frames, scope, base)]]) {
      const d = ed(seq, got); acc[name][0] += Math.max(0, seq.length - d); acc[name][1] += seq.length; acc[name][2] += d === 0 ? 1 : 0; acc[name][3]++;
      if (name === 'new' && d) { const key = seq.join(',') + ' -> ' + got.join(','); conf[key] = 1; }
    }
  }
  const pc = (a, b) => (100 * a / b).toFixed(1) + '%';
  out[`${scope} ${fps}fps`] = { old_moves: pc(acc.old[0], acc.old[1]), new_moves: pc(acc.new[0], acc.new[1]), old_perfect: pc(acc.old[2], acc.old[3]), new_perfect: pc(acc.new[2], acc.new[3]) };
  if (process.argv[3]) console.log(scope, fps, Object.keys(conf).slice(0, 8));
}
console.table(out);
