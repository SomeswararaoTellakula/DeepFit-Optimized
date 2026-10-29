// Coachability Challenge - a line-by-line copy of coachability.py.
// Measures how fast an athlete LEARNS a new 5-move pattern over 5 tries.

import 'dart:math' as math;

import 'exercise.dart';
import 'pose.dart';
import 'py.dart';

const Map<String, String> moves = {
  'hands_up': 'Both hands up',
  'left_hand_up': 'Left hand up',
  'right_hand_up': 'Right hand up',
  'hands_on_head': 'Hands on head',
  'arms_out': 'Arms out to the sides',
  'hands_on_hips': 'Hands on hips',
  'squat': 'Squat down',
  'touch_knees': 'Touch your knees',
  'step_left': 'Step to your left',
  'step_right': 'Step to your right',
  'jump': 'Jump',
};
const upperMoves = ['hands_up', 'left_hand_up', 'right_hand_up', 'hands_on_head', 'arms_out', 'hands_on_hips'];
const lowerMoves = ['squat', 'touch_knees', 'step_left', 'step_right', 'jump'];

const tries = 5;
const patternLen = 5;
const stableFrames = 2; // a move must be seen on at least 2 frames in a row ...
const stableSeconds = 0.3; // ... and held about 1/3 s, whatever the frame rate (a jump: one clear frame)
const lateGap = 2.5; // seconds between moves before a move counts as "late"
const neutralToStart = 0.8; // seconds of standing neutral before each try
const finishNeutral = 2.0; // standing neutral this long after moving ends the try early
const reviewTime = 4.0; // seconds to read/hear the tip
const previewBase = 1.5, previewPerStep = 1.3; // time to read/hear the pattern before each try

String moveLabel(String m) => moves[m] ?? m;
String _low(String m) => moveLabel(m).toLowerCase();

/// Random pattern with no move repeated back-to-back, at least two lower- and two upper-body moves.
({String code, List<String> seq}) makePattern([int? seed, int length = patternLen]) {
  final rnd = seed == null ? math.Random() : math.Random(seed);
  while (true) {
    final seq = <String>[];
    for (var i = 0; i < length; i++) {
      var pool = moves.keys.where((m) => seq.isEmpty || m != seq.last).toList();
      // step_left right after step_right (and v.v.) is just "go back"; avoid it
      if (seq.isNotEmpty && (seq.last == 'step_left' || seq.last == 'step_right')) {
        pool = pool.where((m) => m != 'step_left' && m != 'step_right').toList();
      }
      seq.add(pool[rnd.nextInt(pool.length)]);
    }
    if (seq.where(lowerMoves.contains).length >= 2 && seq.where(upperMoves.contains).length >= 2) {
      const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
      final code = List.generate(5, (_) => chars[rnd.nextInt(chars.length)]).join();
      return (code: code, seq: seq);
    }
  }
}

class CoachBase {
  final double hipX, hipY, lAnkY, rAnkY;
  const CoachBase(this.hipX, this.hipY, this.lAnkY, this.rAnkY);
}

/// Which move is the body doing right now? 'neutral', a moves key, or 'unknown'.
String classify(BodyPose pose, CoachBase? base) {
  if (!pose.vis([L.nose, L.lShoulder, L.rShoulder, L.lHip, L.rHip, L.lWrist, L.rWrist])) return 'unknown';
  final sh = pose.mid(L.lShoulder, L.rShoulder);
  final hp = pose.mid(L.lHip, L.rHip);
  final torso = math.max(hypot(hp.x - sh.x, hp.y - sh.y), 1.0);
  final nose = pose.p(L.nose);
  final lw = pose.p(L.lWrist), rw = pose.p(L.rWrist);
  final legs = pose.vis([L.lKnee, L.rKnee, L.lAnkle, L.rAnkle]);

  bool near(Vec a, Vec b, double k) => hypot(a.x - b.x, a.y - b.y) < k * torso;

  // whole-body moves first
  if (legs && base != null) {
    final lift = math.min(base.lAnkY - pose.p(L.lAnkle).y, base.rAnkY - pose.p(L.rAnkle).y);
    if (lift > 0.12 * torso) return 'jump';
    // sideways shift measured along the athlete's own left direction (R_HIP -> L_HIP)
    final l = pose.p(L.lHip), r = pose.p(L.rHip);
    final dx = l.x - r.x, dy = l.y - r.y;
    var n = hypot(dx, dy);
    if (n == 0) n = 1.0;
    final shift = ((hp.x - base.hipX) * dx + (hp.y - base.hipY) * dy) / n;
    if (shift > 0.45 * torso) return 'step_left';
    if (shift < -0.45 * torso) return 'step_right';
    if (near(lw, pose.p(L.lKnee), 0.4) && near(rw, pose.p(L.rKnee), 0.4)) return 'touch_knees';
    final knee = (angle(pose.p(L.lHip), pose.p(L.lKnee), pose.p(L.lAnkle)) +
            angle(pose.p(L.rHip), pose.p(L.rKnee), pose.p(L.rAnkle))) /
        2;
    if (knee < 125) return 'squat';
  }

  final upL = lw.y < nose.y - 0.45 * torso;
  final upR = rw.y < nose.y - 0.45 * torso;
  if (upL && upR) return 'hands_up';
  final head = Vec(nose.x, nose.y - 0.35 * torso);
  if (near(lw, head, 0.5) && near(rw, head, 0.5)) return 'hands_on_head';
  final lowL = lw.y > sh.y + 0.2 * torso;
  final lowR = rw.y > sh.y + 0.2 * torso;
  if (upL && lowR) return 'left_hand_up';
  if (upR && lowL) return 'right_hand_up';
  final lsh = pose.p(L.lShoulder), rsh = pose.p(L.rShoulder);
  if ((lw.y - lsh.y).abs() < 0.3 * torso &&
      (rw.y - rsh.y).abs() < 0.3 * torso &&
      (lw.x - lsh.x).abs() > 0.7 * torso &&
      (rw.x - rsh.x).abs() > 0.7 * torso) {
    return 'arms_out';
  }
  // arms hanging also puts the wrists next to the hips - hands-on-hips needs BENT elbows
  double bendL = 180.0, bendR = 180.0;
  if (pose.vis([L.lElbow, L.rElbow])) {
    bendL = angle(lsh, pose.p(L.lElbow), lw);
    bendR = angle(rsh, pose.p(L.rElbow), rw);
  }
  if (near(lw, pose.p(L.lHip), 0.4) && near(rw, pose.p(L.rHip), 0.4) && bendL < 130 && bendR < 130) {
    return 'hands_on_hips';
  }
  if (lowL && lowR && bendL > 140 && bendR > 140) return 'neutral';
  return 'unknown';
}

class AlignOp {
  final String op; // ok | sub | miss | extra
  final int? ti, di;
  const AlignOp(this.op, this.ti, this.di);
}

/// Edit-distance alignment. Returns (distance, ops).
({int dist, List<AlignOp> ops}) align(List<String> target, List<String> done) {
  final n = target.length, m = done.length;
  final dp = List.generate(n + 1, (_) => List<int>.filled(m + 1, 0));
  for (var i = 0; i <= n; i++) {
    dp[i][0] = i;
  }
  for (var j = 0; j <= m; j++) {
    dp[0][j] = j;
  }
  for (var i = 1; i <= n; i++) {
    for (var j = 1; j <= m; j++) {
      final cost = target[i - 1] == done[j - 1] ? 0 : 1;
      dp[i][j] = math.min(math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1), dp[i - 1][j - 1] + cost);
    }
  }
  final ops = <AlignOp>[];
  var i = n, j = m;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && dp[i][j] == dp[i - 1][j - 1] + (target[i - 1] == done[j - 1] ? 0 : 1)) {
      ops.add(AlignOp(target[i - 1] == done[j - 1] ? 'ok' : 'sub', i - 1, j - 1));
      i -= 1;
      j -= 1;
    } else if (i > 0 && dp[i][j] == dp[i - 1][j] + 1) {
      ops.add(AlignOp('miss', i - 1, null));
      i -= 1;
    } else {
      ops.add(AlignOp('extra', null, j - 1));
      j -= 1;
    }
  }
  return (dist: dp[n][m], ops: ops.reversed.toList());
}

class TryResult {
  final int tryNo;
  final double errors;
  final int editDistance;
  final List<int> lateSteps;
  final List<String> done;
  final String tip;
  final int? tipStep;
  final double seconds;
  const TryResult(this.tryNo, this.errors, this.editDistance, this.lateSteps, this.done, this.tip, this.tipStep, this.seconds);
}

class _Scored {
  final double errors;
  final int dist;
  final List<int> lateSteps;
  final List<String> moves;
  final String tip;
  final int? step;
  const _Scored(this.errors, this.dist, this.lateSteps, this.moves, this.tip, this.step);
}

_Scored scoreTry(List<String> target, List<(String, double)> done, double tStart) {
  final mv = [for (final d in done) d.$1];
  final times = [for (final d in done) d.$2];
  final a = align(target, mv);
  final lateSteps = <int>[];
  var prevT = tStart;
  for (final o in a.ops) {
    if ((o.op == 'ok' || o.op == 'sub') && o.di != null) {
      if (times[o.di!] - prevT > lateGap && o.op == 'ok') lateSteps.add(o.ti!);
      prevT = times[o.di!];
    }
  }
  final errors = a.dist + 0.5 * lateSteps.length;
  // pick the single most useful correction
  String? tip;
  int? step;
  for (final o in a.ops) {
    if (o.op == 'miss') {
      final ti = o.ti!;
      tip = 'You missed step ${ti + 1}: ${_low(target[ti])}. It comes after '
          '${ti == 0 ? 'the start' : _low(target[ti - 1])}.';
      step = ti;
      break;
    }
    if (o.op == 'sub') {
      tip = 'Step ${o.ti! + 1} is ${_low(target[o.ti!])} - you did ${_low(mv[o.di!])}.';
      step = o.ti;
      break;
    }
  }
  if (tip == null) {
    for (final o in a.ops) {
      if (o.op == 'extra') {
        tip = 'Extra move: ${_low(mv[o.di!])}. Go straight to the next step.';
        break;
      }
    }
  }
  if (tip == null && lateSteps.isNotEmpty) {
    final i = lateSteps.first;
    tip = 'Step ${i + 1} (${_low(target[i])}) was late - start it as soon as the step before ends.';
    step = i;
  }
  tip ??= 'Perfect! Keep the same order and go a little faster.';
  return _Scored(pyRound(errors, 1), a.dist, [for (final i in lateSteps) i + 1], mv, tip, step);
}

class CoachScore {
  final double score;
  final int reductionPct;
  final double? slope;
  final String? note;
  const CoachScore(this.score, this.reductionPct, this.slope, this.note);
}

/// 0-100. Mostly how much errors fall (learning), partly final accuracy.
const notSeenNote = "The camera recognised almost none of the moves - stand 2.5-3 m away with your whole body in view, wait for 'Go', and hold each move for a moment.";

CoachScore coachabilityScore(List<double> errors, int n) {
  if (errors.isEmpty) return const CoachScore(0.0, 0, null, 'no tries');
  final first = errors.first;
  final last2 = errors.length >= 2 ? errors.sublist(errors.length - 2) : errors;
  final fin = sumOf(last2) / last2.length;
  final accuracy = math.max(0.0, math.min(1.0, 1 - fin / math.max(n, 1)));
  if (first <= 0.5) {
    // already perfect on the first try: learning can't be measured, rate on accuracy (ceiling)
    return CoachScore(pyRound(75 + 15 * accuracy, 1), 0, null,
        'Perfect from the first try - give a longer pattern to measure learning.');
  }
  final reduction = math.max(0.0, math.min(1.0, (first - fin) / first));
  // least-squares slope of errors per try (negative = improving)
  final xs = [for (var i = 0; i < errors.length; i++) i.toDouble()];
  final mx = sumOf(xs) / xs.length, my = sumOf(errors) / errors.length;
  var sxx = sumOf(xs.map((x) => (x - mx) * (x - mx)));
  if (sxx == 0) sxx = 1;
  final slope = sumOf([for (var i = 0; i < xs.length; i++) (xs[i] - mx) * (errors[i] - my)]) / sxx;
  // every try almost all wrong: most likely the camera did not see the moves, not a slow learner
  final notSeen = errors.reduce(math.min) >= 0.8 * n;
  return CoachScore(pyRound(100 * (0.65 * reduction + 0.35 * accuracy), 1), pyRoundInt(100 * reduction),
      pyRound(slope, 2), notSeen ? notSeenNote : null);
}

/// Percentile against a STARTER norm (mean 45, sd 20) until real data exists.
int starterPercentile(double score) {
  final z = (score - 45.0) / 20.0;
  return pyRoundInt(100 * 0.5 * (1 + erf(z / math.sqrt(2))));
}

class CoachabilityChallenge extends Exercise {
  late String code;
  late List<String> pattern;
  String phase = 'ready'; // ready -> preview -> perform -> review -> ready ... -> done
  final List<TryResult> triesDone = [];
  List<(String, double)> done = [];
  CoachBase? base;
  double? neutralSince;
  double tryStart = 0.0;
  double reviewUntil = 0.0;
  double previewUntil = 0.0;
  String curMove = 'unknown';
  String? _cand;
  int _candN = 0;
  double _candT = 0.0;
  String? _lastAdded;
  final List<CoachBase> _calib = []; // deque(maxlen=15)

  CoachabilityChallenge({int? seed, super.heightCm}) {
    final p = makePattern(seed);
    code = p.code;
    pattern = p.seq;
    feedback = 'Stand still, arms down, facing the camera';
    mirrorLabel = '';
  }

  @override
  String get key => 'coachability';
  @override
  String get name => 'Coachability Challenge';
  @override
  String get metric => 'coachability';
  @override
  String get unit => 'pts';
  @override
  double? get duration => 300.0;
  @override
  String get camera => 'front';

  String? _stableMove(String mv, double t) {
    if (mv == _cand) {
      _candN += 1;
    } else {
      _cand = mv;
      _candN = 1;
      _candT = t;
    }
    if (mv == 'jump') return mv; // in the air for only ~0.3 s: one frame with both feet clearly up is enough
    return (_candN >= stableFrames && t - _candT >= stableSeconds) ? mv : null;
  }

  void _updateBase(BodyPose pose) {
    if (!pose.vis([L.lHip, L.rHip, L.lAnkle, L.rAnkle])) return;
    final hp = pose.mid(L.lHip, L.rHip);
    _calib.add(CoachBase(hp.x, hp.y, pose.p(L.lAnkle).y, pose.p(L.rAnkle).y));
    if (_calib.length > 15) _calib.removeAt(0);
    final n = _calib.length;
    base = CoachBase(sumOf(_calib.map((c) => c.hipX)) / n, sumOf(_calib.map((c) => c.hipY)) / n,
        sumOf(_calib.map((c) => c.lAnkY)) / n, sumOf(_calib.map((c) => c.rAnkY)) / n);
  }

  void _startTry(double t) {
    // Preview first: the pattern is shown and spoken; timing starts only at "Go"
    phase = 'preview';
    previewUntil = t + previewBase + previewPerStep * pattern.length;
    final n = triesDone.length + 1;
    feedback = 'Try $n of $tries: learn the pattern…';
    final steps = [for (var i = 0; i < pattern.length; i++) '${i + 1}, ${moveLabel(pattern[i])}'].join('. ');
    event('try', 'Try $n. $steps.');
  }

  void _go(double t) {
    phase = 'perform';
    done = [];
    tryStart = t;
    _lastAdded = null;
    neutralSince = null;
    feedback = 'Try ${triesDone.length + 1} of $tries: go!';
    event('go', 'Go!');
  }

  void _endTry(double t) {
    final s = scoreTry(pattern, done, tryStart);
    final res = TryResult(triesDone.length + 1, s.errors, s.dist, s.lateSteps, s.moves, s.tip, s.step, pyRound(t - tryStart, 1));
    triesDone.add(res);
    count = triesDone.length;
    feedback = 'Try ${res.tryNo}: ${fmtG(res.errors)} errors. Tip: ${res.tip}';
    event('tip', '${fmtG(res.errors)} errors. ${res.tip}');
    if (triesDone.length >= tries) {
      phase = 'done';
      finished = true;
      final sc = coachabilityScore(errorsPerTry, pattern.length);
      feedback = 'Finished! Coachability ${fmtFixed(sc.score, 0)}/100';
      if (sc.note == notSeenNote) feedback = '$feedback. $notSeenNote';
      event('end', feedback);
    } else {
      phase = 'review';
      reviewUntil = t + reviewTime;
      neutralSince = null;
    }
  }

  List<double> get errorsPerTry => [for (final x in triesDone) x.errors];

  @override
  void process(BodyPose pose, double t) {
    final mv = classify(pose, base);
    final stable = _stableMove(mv, t);
    if (stable != null) curMove = stable;

    if (phase == 'preview') {
      if (stable != null && stable != 'neutral' && stable != 'unknown') {
        _go(t); // the athlete is ready and already moving: start the try now, keep this move
      } else {
        if (t >= previewUntil) _go(t);
        return;
      }
    }

    if (phase == 'ready' || phase == 'review') {
      if (phase == 'review' && t < reviewUntil) return;
      if (stable == 'neutral') {
        _updateBase(pose);
        neutralSince = orNum(neutralSince, t);
        final left = neutralToStart - (t - neutralSince!);
        feedback = left > 0 ? 'Ready…' : 'Go!';
        if (left <= 0 && base != null) _startTry(t);
      } else if (stable != null) {
        neutralSince = null;
        feedback = 'Stand still with your arms down to start the next try';
      }
      return;
    }

    if (phase == 'perform') {
      if (stable != null && stable != 'neutral' && stable != 'unknown' && stable != _lastAdded) {
        done.add((stable, t));
        _lastAdded = stable;
        final k = done.length;
        final ok = k <= pattern.length && pattern[k - 1] == stable;
        event('move', '${ok ? '✓' : '✗'} ${moveLabel(stable)}');
        feedback = '${moveLabel(stable)} ($k/${pattern.length})';
      }
      if (stable == 'neutral') {
        _lastAdded = null; // allow the same move again after returning to neutral
        neutralSince = orNum(neutralSince, t);
      } else if (stable != null) {
        neutralSince = null;
      }
      final timeout = pattern.length * 3.0 + 4.0;
      final finishedMoves = done.length >= pattern.length && stable == 'neutral';
      final gaveUp = done.isNotEmpty && truthy(neutralSince) && t - neutralSince! > finishNeutral;
      if (finishedMoves || gaveUp || t - tryStart > timeout) _endTry(t);
    }
  }

  CoachScore get score => coachabilityScore(errorsPerTry, pattern.length);

  @override
  double value() => score.score;

  int get currentTry => math.min(triesDone.length + (phase == 'perform' ? 1 : 0), tries);

  @override
  Map<String, dynamic> result() {
    final r = super.result();
    final sc = score;
    r['repetitions'] = null;
    r['form_score'] = null;
    r['coachability'] = {
      'score': sc.score,
      'percentile': starterPercentile(sc.score),
      'percentile_note': 'starter norm (mean 45, sd 20) - replace with real data',
      'errors_per_try': errorsPerTry,
      'reduction_pct': sc.reductionPct,
      'slope': sc.slope,
      'note': sc.note,
      'pattern': pattern,
      'pattern_code': code,
      'tips': [for (final x in triesDone) x.tip],
      'tries_completed': triesDone.length,
    };
    if (triesDone.length < tries) r['incomplete'] = true;
    return r;
  }
}
