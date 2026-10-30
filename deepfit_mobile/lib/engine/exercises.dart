// Every camera test - a line-by-line copy of the classes in exercise_engine.py.
// Thresholds are deliberately identical; change them on BOTH sides (the server
// re-runs each phone result with the Python version).

import 'dart:math' as math;

import 'exercise.dart';
import 'pose.dart';
import 'py.dart';

// ---------------------------------------------------------------- lying / side-view

class SitUps extends Exercise {
  static const downElev = 20.0, upElev = 55.0; // torso angle above the floor, degrees
  static const halfElev = 35.0; // rose past this but lay back down before 55 = a half sit-up
  final rs = RepState(2, 0.25);
  bool _half = false;

  SitUps({super.heightCm}) {
    mirrorLabel = 'Tone rises as you sit up; highest when you are up';
  }

  @override
  String get key => 'situps';
  @override
  String get name => 'Sit-ups';

  @override
  double? mirror(BodyPose pose, double t) {
    final side = pose.bestSide([L.lShoulder, L.lHip], [L.rShoulder, L.rHip]);
    return side != null ? ramp(elevation(pose.p(side[1]), pose.p(side[0])), 5, upElev) : null;
  }

  static const lieHip = 140.0, sitHip = 100.0; // hip angle: lying open > 140, sitting up < 100 (original rule)
  static const lowVis = 0.2; // lying on the floor, the pose model is often unsure - still usable

  @override
  void process(BodyPose pose, double t) {
    // hip angle (average of the sides the camera sees, like the original counter) + torso angle (clearer side)
    final sides = <List<num>>[];
    for (final sd in [
      [L.lShoulder, L.lHip, L.lKnee],
      [L.rShoulder, L.rHip, L.rKnee]
    ]) {
      final v = math.min(pose.pts[sd[0]][2], math.min(pose.pts[sd[1]][2], pose.pts[sd[2]][2]));
      if (v >= lowVis) sides.add([v, sd[0], sd[1], sd[2]]);
    }
    if (sides.isEmpty) {
      feedback = 'Lie down side-on to the camera - shoulder, hip and knee visible';
      return;
    }
    var hipSum = 0.0;
    for (final sd in sides) {
      hipSum += angle(pose.p(sd[1] as int), pose.p(sd[2] as int), pose.p(sd[3] as int));
    }
    final hipRaw = hipSum / sides.length;
    var best = sides.first;
    for (final sd in sides) {
      if (sd[0] > best[0] || (sd[0] == best[0] && sd[1] > best[1])) best = sd;
    }
    final s = best[1] as int, h = best[2] as int;
    final elevRaw = elevation(pose.p(h), pose.p(s));
    if (!bonesOk(pose, [[s, h]])) return;
    final hip = sm('hip', hipRaw, t);
    final elev = sm('elev', elevRaw, t);
    final standing = elev > 65 && hip > 150; // upright on the feet: not lying, not a sit-up
    final lying = !standing && (elev < downElev || (hip > lieHip && elev < 45));
    final sitting = hip < sitHip || (elev > upElev && hip < 135);
    if (rs.stage == 'down') {
      // a half sit-up: rose clearly off the floor but lay back down before sitting up -> not counted
      if (elev > halfElev || hip < 125) {
        _half = true;
      } else if (lying && _half) {
        _half = false;
        invalid += 1;
        fault('half_situp', 'Sit up all the way - chest up to your knees');
      }
    }
    final st = rs.see(lying ? 'down' : (sitting ? 'up' : null), t);
    if (st == 'up') {
      _half = false;
      if (rs.prev == 'down') {
        rep('Rep ${count + 1}! Now lie back down'); // counted as you sit up (original)
      } else {
        feedback = 'Lie back down to start';
      }
    } else if (st == 'down') {
      feedback = count == 0 ? 'Go up!' : 'Good - sit up again';
    }
  }
}

class PartialCurlUp extends Exercise {
  static const downElev = 12.0, upElev = 25.0; // torso lift above the floor, degrees
  final rs = RepState(2, 0.2);
  double maxElev = 0;

  PartialCurlUp({super.heightCm}) {
    mirrorLabel = 'Tone rises as you curl up; highest at the right height (about 25°)';
  }

  @override
  String get key => 'partial_curlup';
  @override
  String get name => 'Partial Curl-up';

  @override
  double? mirror(BodyPose pose, double t) {
    final side = pose.bestSide([L.lShoulder, L.lHip], [L.rShoulder, L.rHip]);
    if (side == null) return null;
    final elev = elevation(pose.p(side[1]), pose.p(side[0]));
    return elev <= 45 ? ramp(elev, 3, upElev) : ramp(elev, 70, 45); // too high = falls again
  }

  @override
  void process(BodyPose pose, double t) {
    final side = pose.bestSide([L.lShoulder, L.lHip, L.lKnee], [L.rShoulder, L.rHip, L.rKnee]);
    if (side == null) {
      feedback = 'Turn side-on so your shoulder, hip and knee are visible';
      return;
    }
    if (!bonesOk(pose, [[side[0], side[1]], [side[1], side[2]]])) return;
    final elev = sm('elev', elevation(pose.p(side[1]), pose.p(side[0])), t);
    maxElev = math.max(maxElev, elev);
    final st = rs.see(elev < downElev ? 'down' : (elev > upElev ? 'up' : null), t);
    if (st == 'up') {
      feedback = 'Lower back down';
    } else if (st == 'down') {
      if (rs.prev == 'up') {
        if (maxElev > 60) {
          invalid += 1;
          fault('full_situp', 'Not counted - only curl up partway, not a full sit-up');
        } else {
          rep();
        }
      } else {
        feedback = 'Curl up';
      }
      maxElev = 0;
    }
  }
}

class PushUps extends Exercise {
  static const down = 95.0, up = 150.0, straight = 150.0; // elbow angle down/up, body line angle
  static const downRatio = 0.76, upRatio = 0.93; // shoulder-to-hand distance vs the straight-arm top (0.71 = 90°)
  static const badLineFrames = 3, badLineShare = 0.2; // line broken >= 3 frames and >= 20 % of the rep = not counted
  bool get kneeVariant => false;
  final rs = RepState(1, 0.25); // one frame is enough: the median + bone check remove glitches
  bool badLineInRep = false;
  int _badN = 0, _repN = 0;
  final Map<String, List<double>> _reachHist = {};

  PushUps({super.heightCm}) {
    mirrorLabel = 'Tone is highest and steady when your body is a straight line';
  }

  @override
  String get key => 'pushups';
  @override
  String get name => 'Push-ups';

  @override
  double? mirror(BodyPose pose, double t) {
    final end = kneeVariant ? L.lKnee : L.lAnkle;
    final endR = kneeVariant ? L.rKnee : L.rAnkle;
    final side = pose.bestSide([L.lShoulder, L.lHip, end], [L.rShoulder, L.rHip, endR]);
    return side != null ? ramp(angle(pose.p(side[0]), pose.p(side[1]), pose.p(side[2])), 135, 172) : null;
  }

  @override
  void process(BodyPose pose, double t) {
    final end = kneeVariant ? L.lKnee : L.lAnkle;
    final endR = kneeVariant ? L.rKnee : L.rAnkle;
    final side = pose.bestSide(
        [L.lShoulder, L.lElbow, L.lWrist, L.lHip, end], [L.rShoulder, L.rElbow, L.rWrist, L.rHip, endR]);
    if (side == null) {
      feedback = 'Turn side-on - shoulder, elbow, wrist, hip and ${kneeVariant ? 'knee' : 'ankle'} must be visible';
      return;
    }
    if (!bonesOk(pose, [[side[0], side[1]], [side[1], side[2]], [side[0], side[3]], [side[3], side[4]]])) return;
    final sh = pose.p(side[0]), el = pose.p(side[1]), wr = pose.p(side[2]), hp = pose.p(side[3]), en = pose.p(side[4]);
    final k = side[0] == L.lShoulder ? 'L' : 'R'; // the two arms look different from the side: keep apart
    final elbow = sm('elbow$k', angle(sh, el, wr), t);
    final body = sm('body$k', angle(sh, hp, en), t);
    // depth a camera a little off side-on can't fake: the shoulder-to-hand line is nearly vertical. The straight-arm
    // reference is the 90th percentile of the last few seconds (one bad frame can't set it).
    final reach = sm('reach$k', hypot(wr.x - sh.x, wr.y - sh.y), t);
    final hist = _reachHist.putIfAbsent(k, () => <double>[]);
    hist.add(reach);
    if (hist.length > 120) hist.removeAt(0);
    final srt = List<double>.from(hist)..sort();
    final top = srt[(0.9 * (srt.length - 1)).toInt()];
    final ratio = (top > 0 && srt.length >= 10) ? reach / top : 1.0;
    final isDown = (elbow < down && ratio < 0.85) || ratio < downRatio;
    final isUp = elbow > up && ratio > upRatio;
    if (!isUp) {
      // body line is judged over this rep's frames only
      _repN += 1;
      if (body < straight) _badN += 1;
    }
    badLineInRep = _badN >= math.max(badLineFrames.toDouble(), badLineShare * _repN);
    final st = rs.see(isDown ? 'down' : (isUp ? 'up' : null), t);
    if (st == 'down') {
      feedback = 'Push up!';
    } else if (st == 'up' && rs.prev != 'down') {
      _badN = 0;
      _repN = 0;
      feedback = 'Lower your chest';
    } else if (st == 'up') {
      if (badLineInRep) {
        invalid += 1;
        fault('body_line', 'Not counted - keep your body straight');
      } else {
        rep();
      }
      _badN = 0;
      _repN = 0;
    } else if (isUp && rs.stage == 'up') {
      _badN = 0; // resting at the top: the next rep starts fresh
      _repN = 0;
    }
  }
}

class ModifiedPushUps extends PushUps {
  ModifiedPushUps({super.heightCm});

  @override
  bool get kneeVariant => true;
  @override
  String get key => 'pushups_modified';
  @override
  String get name => 'Modified Push-ups (knees)';
}

class Plank extends Exercise {
  static const straight = 155.0, maxTorsoElev = 40.0, grace = 2.0;
  static const settle = 0.6; // straight for this long before the clock starts (credited once it starts)
  static const minHold = 3.0; // a break before this much hold = still getting into position, not the end
  double? _goodSince;
  double hold = 0.0;
  bool holding = false;
  double? brokenSince;
  double? _prevT;
  int _lastCalled = 0;

  Plank({super.heightCm}) {
    mirrorLabel = 'Tone rises as your hips line up; steady high tone = perfect plank';
  }

  @override
  String get key => 'plank';
  @override
  String get name => 'Plank Hold';
  @override
  String get metric => 'hold_time';
  @override
  String get unit => 's';
  @override
  double? get duration => 180.0;

  @override
  double? mirror(BodyPose pose, double t) {
    final side = pose.bestSide([L.lShoulder, L.lHip, L.lAnkle], [L.rShoulder, L.rHip, L.rAnkle]);
    return side != null ? ramp(angle(pose.p(side[0]), pose.p(side[1]), pose.p(side[2])), 135, 174) : null;
  }

  @override
  void process(BodyPose pose, double t) {
    var dt = _prevT == null ? 0.0 : math.min(0.5, t - _prevT!);
    _prevT = t;
    final side = pose.bestSide([L.lShoulder, L.lHip, L.lAnkle], [L.rShoulder, L.rHip, L.rAnkle]);
    if (side == null) {
      // can't see the body: the clock pauses, nothing is decided
      feedback = 'Turn side-on - shoulder, hip and ankle visible';
      return;
    }
    if (!bonesOk(pose, [[side[0], side[1]], [side[1], side[2]]])) return;
    final sh = pose.p(side[0]), hp = pose.p(side[1]), an = pose.p(side[2]);
    final good = sm('line', angle(sh, hp, an), t) >= straight && sm('elev', elevation(an, sh), t) <= maxTorsoElev;
    if (good && !holding) {
      _goodSince ??= t;
      if (t - _goodSince! < settle) {
        feedback = 'Hold still in a straight plank…';
        return;
      }
      holding = true;
      event('start', 'Holding');
      dt = t - _goodSince!; // the settling time counts once the plank is confirmed
    } else if (!good && !holding) {
      _goodSince = null;
    }
    if (good) {
      brokenSince = null;
      hold += dt;
      feedback = 'Hold it! ${hold.toInt()} s';
      if (hold.toInt() ~/ 10 > _lastCalled) {
        _lastCalled = hold.toInt() ~/ 10;
        event('tick', '${_lastCalled * 10} seconds');
      }
    } else if (holding) {
      if (brokenSince == null) {
        brokenSince = t;
        fault('line_break', 'Fix your hips - straight line!');
      } else if (t - brokenSince! > grace) {
        if (hold < minHold) {
          // was only settling in: start again, don't end the test
          holding = false;
          hold = 0.0;
          brokenSince = null;
          _goodSince = null;
          feedback = 'Get into a straight plank to start the clock';
          return;
        }
        finished = true;
        feedback = 'Plank ended at ${hold.toInt()} s';
        event('end', feedback);
      }
    } else {
      feedback = 'Get into a straight plank to start the clock';
    }
  }

  @override
  double value() => hold;
}

class Squats extends Exercise {
  static const down = 100.0, up = 160.0, maxLean = 60.0;
  static const leanFrames = 3; // chest too far forward for this many (smoothed) frames = rep not counted
  final rs = RepState(2, 0.25);
  bool leanBad = false;
  int _leanN = 0;

  Squats({super.heightCm}) {
    mirrorLabel = 'Tone rises as you go down; highest at full depth';
  }

  @override
  String get key => 'squats';
  @override
  String get name => 'Squats';

  @override
  double? mirror(BodyPose pose, double t) {
    final side = pose.bestSide([L.lHip, L.lKnee, L.lAnkle], [L.rHip, L.rKnee, L.rAnkle]);
    return side != null ? ramp(angle(pose.p(side[0]), pose.p(side[1]), pose.p(side[2])), 170, down) : null;
  }

  @override
  void process(BodyPose pose, double t) {
    final side = pose.bestSide([L.lShoulder, L.lHip, L.lKnee, L.lAnkle], [L.rShoulder, L.rHip, L.rKnee, L.rAnkle]);
    if (side == null) {
      feedback = 'Step back - hip, knee and ankle must be visible';
      return;
    }
    if (!bonesOk(pose, [[side[1], side[2]], [side[2], side[3]]])) return;
    final sh = pose.p(side[0]), hp = pose.p(side[1]), kn = pose.p(side[2]), an = pose.p(side[3]);
    final knee = sm('knee', angle(hp, kn, an), t);
    final lean = sm('lean', 90 - elevation(hp, sh), t);
    if (knee < 130 && lean > maxLean) {
      _leanN += 1;
      leanBad = _leanN >= leanFrames;
    }
    final st = rs.see(knee < down ? 'down' : (knee > up ? 'up' : null), t);
    if (st == 'down') {
      feedback = 'Drive up!';
    } else if (st == 'up' && rs.prev != 'down') {
      leanBad = false;
      _leanN = 0;
      feedback = 'Squat down';
    } else if (st == 'up') {
      if (leanBad) {
        invalid += 1;
        fault('lean', 'Not counted - keep your chest up');
      } else {
        rep();
      }
      leanBad = false;
      _leanN = 0;
    }
  }
}

// ---------------------------------------------------------------- front-view

class JumpingJacks extends Exercise {
  final rs = RepState(1, 0.15);
  bool _wasOpen = false;

  // jacks are fast (at 10 fps the arms-overhead moment can be a single frame), so no median here; frames where an
  // arm or leg suddenly changes length are skipped instead, and the checks don't care which hand is which
  JumpingJacks({super.heightCm}) {
    sm = Smoother(window: 0.0, minN: 1);
  }

  @override
  String get key => 'jumping_jacks';
  @override
  String get name => 'Jumping Jacks';
  @override
  String get camera => 'front';

  @override
  void process(BodyPose pose, double t) {
    if (!pose.vis([L.lShoulder, L.rShoulder, L.lWrist, L.rWrist, L.lAnkle, L.rAnkle])) {
      feedback = 'Face the camera - hands and feet must be visible';
      return;
    }
    if (!bonesOk(pose, [
      [L.lShoulder, L.lElbow], [L.lElbow, L.lWrist], [L.rShoulder, L.rElbow], [L.rElbow, L.rWrist],
      [L.lHip, L.lAnkle], [L.rHip, L.rAnkle],
    ])) {
      return;
    }
    final shw = sm('shw', math.max(pose.dist(L.lShoulder, L.rShoulder), 1.0), t);
    final feet = sm('feet', (pose.p(L.lAnkle).x - pose.p(L.rAnkle).x).abs() / shw, t);
    final shY = math.min(pose.p(L.lShoulder).y, pose.p(L.rShoulder).y);
    final headY = pose.vis([L.nose]) ? pose.p(L.nose).y : shY - 0.5 * shw;
    final hand = sm('hand', math.max(pose.p(L.lWrist).y, pose.p(L.rWrist).y) - headY, t) / shw; // lower hand vs head
    final low = sm('low', math.min(pose.p(L.lWrist).y, pose.p(L.rWrist).y) - shY, t) / shw;
    String? st;
    if (hand < 0 && feet > 1.3) {
      st = rs.see('open', t);
    } else if (low > 0.3 && feet < 1.0) {
      st = rs.see('closed', t);
    } else {
      st = rs.see(null, t);
    }
    if (st == 'closed' && _wasOpen) {
      rep();
      _wasOpen = false;
    } else if (st == 'open') {
      _wasOpen = true;
      feedback = 'Back together';
    }
  }
}

class DumbbellCurls extends Exercise {
  static const up = 55.0, down = 150.0;
  static const half = 100.0; // bent past this but lowered again before 55 = a half curl
  final Map<String, bool> _mid = {'left': false, 'right': false};
  final Map<String, String> state = {'left': 'down', 'right': 'down'};
  final Map<String, int> counts = {'left': 0, 'right': 0};
  final Map<String, double> _tState = {'left': -1e9, 'right': -1e9};

  DumbbellCurls({super.heightCm});

  @override
  String get key => 'dumbbell_curls';
  @override
  String get name => 'Dumbbell Curls';
  @override
  String get camera => 'front';

  @override
  void process(BodyPose pose, double t) {
    var seen = false;
    const arms = {
      'left': [L.lShoulder, L.lElbow, L.lWrist],
      'right': [L.rShoulder, L.rElbow, L.rWrist],
    };
    for (final entry in arms.entries) {
      final arm = entry.key;
      final s = entry.value[0], e = entry.value[1], w = entry.value[2];
      if (!pose.vis([s, e, w])) continue;
      seen = true;
      final a = sm('a_$arm', angle(pose.p(s), pose.p(e), pose.p(w)), t);
      if (t - _tState[arm]! < 0.2) continue; // a real curl can't flip faster than this
      if (state[arm] == 'down' && a >= up && a < half) {
        _mid[arm] = true; // bending, but not up yet
      } else if (state[arm] == 'down' && a > down && _mid[arm]!) {
        _mid[arm] = false; // lowered again without curling all the way: half rep
        invalid += 1;
        fault('half_curl', '${arm[0].toUpperCase()}${arm.substring(1)} arm: curl all the way up');
      }
      if (state[arm] == 'down' && a < up) {
        _mid[arm] = false;
        _tState[arm] = t;
        state[arm] = 'up';
        counts[arm] = counts[arm]! + 1;
        count += 1;
        feedback = '${arm[0].toUpperCase()}${arm.substring(1)} ${counts[arm]}';
        event('rep', '$arm ${counts[arm]}');
      } else if (state[arm] == 'up' && a > down) {
        state[arm] = 'down';
        _tState[arm] = t;
      }
    }
    if (!seen) feedback = 'Face the camera - shoulders, elbows and wrists visible';
  }
}

// ---------------------------------------------------------------- jumps

class _Stand {
  final double hipY, ankX, ankY, bodyPx, lAnkY, rAnkY;
  final bool bothFeet;
  final double torsoPx; // shoulder -> hip length: the same in a crouch, so it shows walking nearer / further
  const _Stand(this.hipY, this.ankX, this.ankY, this.bodyPx, this.lAnkY, this.rAnkY,
      [this.bothFeet = true, this.torsoPx = 0.0]);
}

class _JumpBaseline {
  final _Stand avg;
  final double cmPerPx;
  const _JumpBaseline(this.avg, this.cmPerPx);
}

class _Landing {
  final double px, ankX, t;
  final List<double> calib = [];
  _Landing(this.px, this.ankX, this.t);
}

/// Shared calibration: stand still, measure body size in pixels to convert to cm.
abstract class _JumpBase extends Exercise {
  static const attemptsMax = 3;
  static const g = 981.0; // cm/s^2 - flight is ballistic, which lets us find the true top of the jump
  static const calibN = 12;
  final List<_Stand> calib = []; // deque(maxlen=12)
  _JumpBaseline? base;
  bool airborne = false;
  final List<double> attempts = [];
  double peakRise = 0.0;
  int landFrames = 0;
  int _upN = 0;
  List<List<double>> _flight = []; // samples while in the air

  _JumpBase({super.heightCm});

  @override
  double? get duration => 180.0;

  static Vec? _avgVisible(BodyPose pose, int a, int b) {
    final pts = [for (final i in [a, b]) if (pose.pts[i][2] >= visMin) pose.pts[i]];
    if (pts.isEmpty) return null;
    return Vec(sumOf(pts.map((p) => p[0])) / pts.length, sumOf(pts.map((p) => p[1])) / pts.length);
  }

  /// Side view: the far hip / ankle is often hidden behind the body - use whichever are visible.
  _Stand? _standing(BodyPose pose) {
    // a hip or ankle put in the wrong place for a frame or two would look like a jump: the rigid parts (torso,
    // thigh, shin) can't change length, so such frames are skipped
    if (!bonesOk(pose, [
      [L.lShoulder, L.lHip], [L.rShoulder, L.rHip], [L.lHip, L.lKnee], [L.rHip, L.rKnee],
      [L.lKnee, L.lAnkle], [L.rKnee, L.rAnkle]
    ], lo: 0.75, hi: 1.33)) return null;
    Vec? head;
    for (final i in [L.nose, L.lEye, L.rEye, L.lEar, L.rEar]) {
      if (pose.pts[i][2] >= visMin) {
        head = pose.p(i);
        break;
      }
    }
    final hip = _avgVisible(pose, L.lHip, L.rHip);
    final ank = _avgVisible(pose, L.lAnkle, L.rAnkle);
    if (head == null || hip == null || ank == null) return null;
    final lv = pose.pts[L.lAnkle][2] >= visMin, rv = pose.pts[L.rAnkle][2] >= visMin;
    final sh = _avgVisible(pose, L.lShoulder, L.rShoulder);
    final torso = sh == null ? 0.0 : math.sqrt((sh.x - hip.x) * (sh.x - hip.x) + (sh.y - hip.y) * (sh.y - hip.y));
    return _Stand(hip.y, ank.x, ank.y, ank.y - head.y, lv ? pose.p(L.lAnkle).y : ank.y,
        rv ? pose.p(L.rAnkle).y : ank.y, lv && rv, torso);
  }

  static const movedFrames = 8; // frames in a row looking bigger / smaller than at calibration
  int _movedN = 0;

  /// The torso looks more than 20% bigger or smaller than when calibrated, for several frames in a row:
  /// the athlete walked nearer or further from the camera after calibrating (a jump doesn't change its size).
  bool _movedAway(_Stand cur) {
    final b = base!.avg.torsoPx;
    final far = b > 0 && cur.torsoPx > 0 && (cur.torsoPx / b - 1).abs() > 0.2;
    _movedN = far ? _movedN + 1 : 0;
    if (_movedN >= movedFrames) {
      _movedN = 0;
      return true;
    }
    return false;
  }

  static double _sd(List<double> vals) {
    final m = sumOf(vals) / vals.length;
    return math.sqrt(sumOf(vals.map((v) => (v - m) * (v - m))) / vals.length);
  }

  bool _calibrate(_Stand cur) {
    calib.add(cur);
    if (calib.length > calibN) calib.removeAt(0);
    if (calib.length < calibN) {
      feedback = 'Stand still for calibration…';
      return false;
    }
    final hips = [for (final c in calib) c.hipY];
    final xs = [for (final c in calib) c.ankX];
    final body = medianOf(calib.map((c) => c.bodyPx));
    // still = the hips and feet only jitter (camera noise), they don't drift or walk
    if (_sd(hips) > 0.015 * body || _sd(xs) > 0.025 * body) {
      feedback = 'Stand still for calibration…';
      return false;
    }
    double med(double Function(_Stand) f) => medianOf(calib.map(f));
    final a = _Stand(med((c) => c.hipY), med((c) => c.ankX), med((c) => c.ankY), med((c) => c.bodyPx),
        med((c) => c.lAnkY), med((c) => c.rAnkY), true, med((c) => c.torsoPx));
    // nose is ~0.92 of standing height; ankle ~0.04 above the floor
    base = _JumpBaseline(a, (heightCm * 0.88) / math.max(a.bodyPx, 1.0));
    calib.clear();
    feedback = 'Ready - jump! (attempt ${attempts.length + 1} of $attemptsMax)';
    event('ready', feedback);
    return true;
  }

  /// Top of the flight from the hip samples: fit a ballistic curve (fixed gravity), so the peak is right even
  /// when no frame landed exactly on it (10-15 fps phones) and one bad frame can't inflate it.
  double _apex(List<List<double>> samples) {
    final vals = [for (final s in samples) s[1]]..sort();
    // the second-highest frame (one jumpy frame can't make a jump) - unless the camera gave only a few frames
    final robust = vals.length >= 4 ? vals[vals.length - 2] : (vals.isNotEmpty ? vals.last : 0.0);
    var pts = [for (final s in samples) if (s[1] >= 0.5 * robust) s];
    // the curve fit is only for real flight: time spent above half the height must match free fall, and the fit
    // may only add what a gap between two frames can hide (a slow rise on the toes is not a flight)
    var gap = 0.0;
    for (var i = 1; i < samples.length; i++) {
      gap = math.max(gap, samples[i][0] - samples[i - 1][0]);
    }
    final above = pts.isNotEmpty ? pts.last[0] - pts.first[0] : 0.0;
    if (!(robust > 0 && above <= 1.5 * 2 * math.sqrt(robust / g) + gap)) pts = [];
    final maxGain = 0.5 * g * (gap / 2) * (gap / 2) + 2;
    for (var it = 0; it < 3; it++) {
      if (pts.length < 3) break;
      final t0 = pts[0][0];
      final xs = [for (final p in pts) p[0] - t0];
      final ys = [for (var i = 0; i < pts.length; i++) pts[i][1] + 0.5 * g * xs[i] * xs[i]];
      final n = xs.length;
      final mx = sumOf(xs) / n, my = sumOf(ys) / n;
      final sxx = sumOf(xs.map((x) => (x - mx) * (x - mx)));
      if (sxx <= 1e-9) break;
      final b = sumOf([for (var i = 0; i < n; i++) (xs[i] - mx) * (ys[i] - my)]) / sxx;
      final a = my - b * mx;
      final res = [for (var i = 0; i < n; i++) pts[i][1] - (a + b * xs[i] - 0.5 * g * xs[i] * xs[i])];
      var worst = 0;
      for (var i = 1; i < n; i++) {
        if (res[i].abs() > res[worst].abs()) worst = i;
      }
      if (res[worst].abs() > 5 && n > 3) {
        pts.removeAt(worst);
        continue;
      }
      final topT = b / g;
      if (minOf(xs) - 0.1 <= topT && topT <= maxOf(xs) + 0.1) {
        final apex = a + b * b / (2 * g);
        if (robust - 3 <= apex && apex <= robust + maxGain) {
          return math.max(apex, robust); // two frames already reached 'robust'; the fit finds the top between frames
        }
      }
      break;
    }
    return robust;
  }

  @override
  double value() => attempts.isEmpty ? 0.0 : maxOf(attempts);

  bool get calibrated => base != null;
}

class VerticalJump extends _JumpBase {
  VerticalJump({super.heightCm});

  @override
  String get key => 'vertical_jump';
  @override
  String get name => 'Vertical Jump';
  @override
  String get metric => 'max_height';
  @override
  String get unit => 'cm';

  @override
  void process(BodyPose pose, double t) {
    final cur = _standing(pose);
    if (cur == null) {
      feedback = 'Whole body must be visible (head to feet)';
      return;
    }
    if (base == null) {
      _calibrate(cur);
      return;
    }
    if (!airborne && _movedAway(cur)) {
      // calibrated while standing somewhere else (e.g. close to the phone): calibrate again where they jump
      base = null;
      feedback = 'Stand still for calibration…';
      return;
    }
    final rise = (base!.avg.hipY - cur.hipY) * base!.cmPerPx;
    if (!airborne) {
      _upN = rise > 6 ? _upN + 1 : 0;
      _flight = [..._flight, [t, rise]];
      if (_flight.length > 2) _flight = _flight.sublist(_flight.length - 2);
      if (_upN >= 2) {
        // two frames in a row: a real take-off, not one bad frame
        airborne = true;
        peakRise = maxOf(_flight.map((f) => f[1]));
        feedback = 'Up!';
      }
    } else {
      _flight.add([t, rise]);
      peakRise = math.max(peakRise, rise);
      if (rise < 3) {
        landFrames += 1;
        if (landFrames >= 3) {
          airborne = false;
          landFrames = 0;
          _upN = 0;
          peakRise = _apex(_flight);
          _flight = [];
          if (peakRise < 8) {
            // a heel raise or a wobble, not a jump: ignore, stay ready
            feedback = 'Ready - jump! (attempt ${attempts.length + 1} of ${_JumpBase.attemptsMax})';
            return;
          }
          attempts.add(peakRise);
          count = attempts.length;
          feedback = 'Jump ${attempts.length}: ${fmtFixed(peakRise, 0)} cm';
          event('rep', '${fmtFixed(peakRise, 0)} centimetres');
          if (attempts.length >= _JumpBase.attemptsMax) {
            finished = true;
          } else {
            base = null; // re-calibrate before next attempt
          }
        }
      } else {
        landFrames = 0;
      }
    }
  }
}

class BroadJump extends _JumpBase {
  static const backToLineCm = 30.0; // later attempts start from the same line as the first
  _JumpBaseline? _start;
  _Landing? _landing;

  BroadJump({super.heightCm});

  @override
  String get key => 'broad_jump';
  @override
  String get name => 'Standing Broad Jump';
  @override
  String get metric => 'distance';
  @override
  String get unit => 'cm';

  @override
  void process(BodyPose pose, double t) {
    final cur = _standing(pose);
    if (cur == null) {
      feedback = 'Whole body must be visible (head to feet)';
      return;
    }
    if (base == null) {
      final start = _start;
      if (start != null && (cur.ankX - start.avg.ankX).abs() * start.cmPerPx > backToLineCm) {
        // standing still at the landing spot is not a new start - wait until they are back at the line
        calib.clear();
        feedback = 'Walk back to the start line';
        return;
      }
      if (_calibrate(cur) && start == null) _start = base;
      return;
    }
    final cpp = base!.cmPerPx;
    final moved = (cur.ankX - base!.avg.ankX).abs() * cpp;
    // take-off = BOTH feet off the floor (walking only lifts one foot at a time); if the far foot is hidden,
    // the visible foot must lift and the hips must rise too
    final lifted = math.min(base!.avg.lAnkY - cur.lAnkY, base!.avg.rAnkY - cur.rAnkY) * cpp;
    final hipUp = (base!.avg.hipY - cur.hipY) * cpp;
    final off = lifted > 4 && (cur.bothFeet || hipUp > 3);
    if (_landing != null) {
      _finishLanding(cur, t);
      return;
    }
    if (!airborne) {
      _upN = off ? _upN + 1 : 0;
      if (_upN >= 2) {
        airborne = true;
        _flight = [];
        feedback = 'Jump!';
      }
    } else {
      // landed = the feet have stopped (a camera that is a little tilted or not exactly side-on makes the
      // floor slope in the picture, so "back at the starting height" is not a reliable landing test)
      _flight.add([t, cur.ankX, cur.ankY]);
      var recent = [for (final f in _flight) if (t - f[0] <= 0.25) f];
      if (recent.length > 6) recent = recent.sublist(recent.length - 6);
      if (moved > 20 && recent.length >= 3) {
        var span = 0.0;
        for (final a in recent) {
          for (final b in recent) {
            span = math.max(span, hypot(a[1] - b[1], a[2] - b[2]));
          }
        }
        span *= cpp;
        if (span < 8) {
          airborne = false;
          _upN = 0;
          final landX = medianOf(recent.map((f) => f[1]));
          _flight = [];
          _landing = _Landing((landX - base!.avg.ankX).abs(), landX, t);
          feedback = 'Hold the landing…';
        }
      }
    }
  }

  /// Turn the landing into cm. If the athlete stands still at the landing spot, the body size there gives a
  /// second scale (a jump towards or away from the camera changes the size), and the two are averaged.
  void _finishLanding(_Stand cur, double t) {
    final l = _landing!;
    final cpp0 = base!.cmPerPx;
    final near = (cur.ankX - l.ankX).abs() * cpp0 < 15;
    if (near) l.calib.add(cur.bodyPx);
    final done = (t - l.t >= 1.5 && l.calib.length >= 6) || !near || t - l.t > 2.5;
    if (!done) return;
    var cpp = cpp0;
    if (l.calib.length >= 6) {
      final srt = List<double>.from(l.calib)..sort();
      final body = medianOf(srt.sublist(srt.length ~/ 2)); // standing up again, not the crouched landing
      if ((body - base!.avg.bodyPx).abs() < 0.25 * base!.avg.bodyPx) {
        cpp = (cpp0 + (heightCm * 0.88) / math.max(body, 1.0)) / 2;
      }
    }
    final moved = l.px * cpp;
    _landing = null;
    attempts.add(moved);
    count = attempts.length;
    feedback = 'Jump ${attempts.length}: ${fmtFixed(moved, 0)} cm - walk back to the start line';
    event('rep', '${fmtFixed(moved, 0)} centimetres');
    if (attempts.length >= _JumpBase.attemptsMax) {
      finished = true;
    } else {
      base = null;
    }
  }
}

// ---------------------------------------------------------------- flexibility / balance / coordination

class SitAndReach extends Exercise {
  static const straightLeg = 150.0, holdTime = 1.0;
  double? best;
  final List<List<double>> window = []; // (t, reach)
  final List<double> legPx = []; // deque(maxlen=30)
  double? _lastReach;

  SitAndReach({super.heightCm}) {
    mirrorLabel = 'Low tone = bend in the knees; tone rises the further you reach';
  }

  @override
  String get key => 'sit_and_reach';
  @override
  String get name => 'Sit and Reach';
  @override
  String get metric => 'reach';
  @override
  String get unit => 'cm';
  @override
  double? get duration => 180.0;

  @override
  double? mirror(BodyPose pose, double t) {
    final side = pose.bestSide([L.lHip, L.lKnee, L.lAnkle], [L.rHip, L.rKnee, L.rAnkle]);
    if (side == null) return null;
    final knee = angle(pose.p(side[0]), pose.p(side[1]), pose.p(side[2]));
    if (knee < straightLeg || _lastReach == null) return 0.3 * ramp(knee, 110, straightLeg);
    return 0.35 + 0.65 * ramp(_lastReach!, -15, 15);
  }

  @override
  void process(BodyPose pose, double t) {
    final side = pose.bestSide([L.lHip, L.lKnee, L.lAnkle, L.lFoot, L.lIndex], [L.rHip, L.rKnee, L.rAnkle, L.rFoot, L.rIndex]);
    if (side == null) {
      feedback = 'Sit side-on - hip, knee, foot and hand must be visible';
      return;
    }
    final hp = pose.p(side[0]), kn = pose.p(side[1]), an = pose.p(side[2]), ft = pose.p(side[3]), fi = pose.p(side[4]);
    if (sm('knee', angle(hp, kn, an), t) < straightLeg) {
      feedback = 'Keep your knees straight';
      window.clear();
      return;
    }
    legPx.add(hypot(an.x - hp.x, an.y - hp.y));
    if (legPx.length > 30) legPx.removeAt(0);
    final sorted = List<double>.from(legPx)..sort();
    final leg = sorted[sorted.length ~/ 2];
    final cmPerPx = (0.47 * heightCm) / math.max(leg, 1.0); // hip-to-ankle ≈ 47% of height
    final direction = ft.x > hp.x ? 1 : -1; // which way the legs point
    final reach = (fi.x - ft.x) * direction * cmPerPx;
    _lastReach = reach;
    window.add([t, reach]);
    while (window.isNotEmpty && t - window.first[0] > holdTime) {
      window.removeAt(0);
    }
    final vals = window.map((w) => w[1]).toList();
    if (window.isNotEmpty && t - window.first[0] >= holdTime * 0.9 && vals.length >= 5 && _still(window)) {
      final held = medianOf(vals);
      if (best == null || held > best! + 0.5) {
        best = held;
        event('rep', '${fmtFixed(held, 0)} centimetres');
      }
      feedback = 'Held ${fmtSigned0(held)} cm - best ${fmtSigned0(best!)} cm';
    } else {
      feedback = 'Reach… ${fmtSigned0(reach)} cm';
    }
  }

  /// Held = the reach isn't moving: the trend over the last second is under 4 cm/s and the points stay within a
  /// few cm of it (camera jitter on the fingertip is allowed, sliding forward or bouncing isn't).
  static bool _still(List<List<double>> window) {
    final ts = [for (final w in window) w[0]], vs = [for (final w in window) w[1]];
    final n = ts.length;
    final mt = sumOf(ts) / n, mv = sumOf(vs) / n;
    final stt = sumOf(ts.map((x) => (x - mt) * (x - mt)));
    final slope = stt > 1e-9 ? sumOf([for (var i = 0; i < n; i++) (ts[i] - mt) * (vs[i] - mv)]) / stt : 0.0;
    final res = [for (var i = 0; i < n; i++) (vs[i] - (mv + slope * (ts[i] - mt))).abs()]..sort();
    return slope.abs() < 4.0 && res[(0.8 * (n - 1)).toInt()] < 5.0;
  }

  @override
  double value() => best ?? 0.0;
}

class FlamingoBalance extends Exercise {
  @override
  double? get duration => 60.0; // standard flamingo test: falls in 60 s
  static const lift = 0.06, downTime = 0.3;
  double balanceTime = 0.0;
  bool balancing = false;
  double? downSince;
  double? _upSince;
  double? _prevT;
  int falls = 0;
  final List<double> _sway = []; // deque(maxlen=12)

  FlamingoBalance({super.heightCm}) {
    mirrorLabel = 'Steady high tone = steady balance; the tone drops and wobbles as you sway';
  }

  @override
  String get key => 'flamingo_balance';
  @override
  String get name => 'Flamingo Balance';
  @override
  String get metric => 'falls';
  @override
  String get unit => 'falls';
  @override
  bool get higherIsBetter => false;
  @override
  String get camera => 'front';

  @override
  double? mirror(BodyPose pose, double t) {
    if (!pose.vis([L.lHip, L.rHip, L.lShoulder, L.rShoulder])) return null;
    final shw = math.max(pose.dist(L.lShoulder, L.rShoulder), 1.0);
    _sway.add(pose.mid(L.lHip, L.rHip).x / shw);
    if (_sway.length > 12) _sway.removeAt(0);
    if (_sway.length < 4) return 1.0;
    final mean = sumOf(_sway) / _sway.length;
    final sd = math.pow(sumOf(_sway.map((v) => (v - mean) * (v - mean))) / _sway.length, 0.5).toDouble();
    return balancing ? ramp(sd, 0.12, 0.02) : 0.2;
  }

  @override
  void process(BodyPose pose, double t) {
    var dt = _prevT == null ? 0.0 : math.min(0.5, t - _prevT!);
    _prevT = t;
    if (!pose.vis([L.lAnkle, L.rAnkle, L.nose])) {
      feedback = 'Whole body must be visible';
      return;
    }
    final body = math.max(pose.mid(L.lAnkle, L.rAnkle).y - pose.p(L.nose).y, 1.0);
    final lifted = sm('lift', (pose.p(L.lAnkle).y - pose.p(L.rAnkle).y).abs() / body, t) > lift;
    if (lifted && !balancing) {
      _upSince ??= t;
      if (t - _upSince! < 0.5) {
        // a wobble while getting into position is not a start
        feedback = 'Hold the position…';
        return;
      }
    } else if (!lifted && !balancing) {
      _upSince = null;
    }
    if (lifted) {
      downSince = null;
      if (!balancing) {
        balancing = true;
        if (_upSince != null) dt = t - _upSince!; // the settling half-second counts once confirmed
        _upSince = null;
        event('start', 'Balancing');
      }
      balanceTime += dt;
      feedback = 'Balancing… ${balanceTime.toInt()} s · falls $falls';
      if (balanceTime >= 60) {
        finished = true;
        feedback = 'Done - $falls falls';
      }
    } else if (balancing) {
      if (downSince == null) {
        downSince = t;
      } else if (t - downSince! >= downTime) {
        balancing = false;
        downSince = null;
        falls += 1;
        fault('fall', 'Fall $falls - lift your foot again');
      }
    } else {
      feedback = 'Lift one foot behind you to start the clock';
    }
  }

  @override
  double value() => falls.toDouble();
}

class PlateTarget {
  final double x, y, r;
  const PlateTarget(this.x, this.y, this.r);
}

class PlateTapping extends Exercise {
  @override
  double? get duration => 60.0; // the test itself: 25 cycles, timed
  static const cycles = 25;
  Map<String, PlateTarget>? targets;
  String nextSide = 'left';
  int touches = 0;
  double? tFirst;
  double? tDone;
  Map<int, Vec> _prevHand = {};

  PlateTapping({super.heightCm});

  /// Distance from point p to the segment a-b (where the hand passed between two frames).
  static double _segDist(Vec p, Vec a, Vec b) {
    final dx = b.x - a.x, dy = b.y - a.y;
    final len2 = dx * dx + dy * dy;
    final u = len2 <= 1e-9 ? 0.0 : math.max(0.0, math.min(1.0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2));
    return hypot(a.x + u * dx - p.x, a.y + u * dy - p.y);
  }

  bool _touched(BodyPose pose, Vec target, double r, double shw) {
    final prev = _prevHand;
    final now = <int, Vec>{
      for (final i in [L.lWrist, L.rWrist, L.lIndex, L.rIndex])
        if (pose.vis([i])) i: pose.p(i)
    };
    _prevHand = now;
    var hit = false;
    for (final pair in [
      [L.lWrist, L.lIndex],
      [L.rWrist, L.rIndex]
    ]) {
      final d = <int, double>{};
      for (final i in pair) {
        final cur = now[i];
        if (cur == null) continue;
        var a = prev[i];
        if (a == null || hypot(cur.x - a.x, cur.y - a.y) > 3.0 * shw) a = cur; // first sight, or an impossible jump
        d[i] = _segDist(target, a, cur);
      }
      // a touch: a hand point is on the target now, or the hand passed over it between two frames (fast tapping
      // at 10-15 fps) - for a pass-over, wrist and fingertip must both have crossed it
      if (d.keys.any((i) => hypot(now[i]!.x - target.x, now[i]!.y - target.y) < r)) {
        hit = true;
      } else if (d.length == 2 && maxOf(d.values) < r) {
        hit = true;
      }
    }
    return hit;
  }

  @override
  String get key => 'plate_tapping';
  @override
  String get name => 'Plate Tapping';
  @override
  String get metric => 'time';
  @override
  String get unit => 's';
  @override
  bool get higherIsBetter => false;
  @override
  String get camera => 'front';

  @override
  void process(BodyPose pose, double t) {
    if (!pose.vis([L.lShoulder, L.rShoulder])) {
      feedback = 'Face the camera - shoulders visible';
      return;
    }
    final shw = math.max(pose.dist(L.lShoulder, L.rShoulder), 1.0);
    final c = pose.mid(L.lShoulder, L.rShoulder);
    if (targets == null) {
      final y = c.y + 0.9 * shw;
      // Image left/right (the athlete sees a mirrored preview)
      targets = {
        'left': PlateTarget(c.x - 1.3 * shw, y, 0.45 * shw),
        'right': PlateTarget(c.x + 1.3 * shw, y, 0.45 * shw),
      };
    }
    final tg = targets![nextSide]!;
    if (_touched(pose, Vec(tg.x, tg.y), tg.r, shw)) {
      touches += 1;
      if (tFirst == null) {
        tFirst = t;
        event('start', 'Go');
      }
      event('tap', nextSide);
      nextSide = nextSide == 'left' ? 'right' : 'left';
      count = touches ~/ 2;
      if (count >= cycles) {
        tDone = t;
        finished = true;
        feedback = 'Done in ${fmtFixed(value(), 1)} s';
        return;
      }
    }
    feedback = 'Cycles $count/$cycles - touch the ${nextSide.toUpperCase()} target';
  }

  @override
  double value() {
    if (tFirst == null) return 0.0;
    final end = tDone ?? lastT;
    return end - tFirst!;
  }

  @override
  Map<String, dynamic> result() {
    final r = super.result();
    if (tDone == null) {
      r['incomplete'] = true; // did not finish 25 cycles in the time limit
      r['value'] = duration ?? 60.0;
    }
    return r;
  }
}

// ---------------------------------------------------------------- coach-timed

/// Coach-timed tests (no pose tracking): the app shows a stopwatch.
abstract class StopwatchTest extends Exercise {
  double? manualValue;

  StopwatchTest({super.heightCm});

  @override
  String get camera => 'none';
  @override
  String get metric => 'time';
  @override
  String get unit => 's';
  @override
  bool get higherIsBetter => false;
  @override
  double? get duration => null;

  @override
  void process(BodyPose pose, double t) {
    feedback = "Use the stopwatch: Start on 'Go', Stop at the finish line";
  }

  @override
  double value() => orNum(manualValue, 0.0);
}

class Dash50m extends StopwatchTest {
  Dash50m({super.heightCm});
  @override
  String get key => 'dash_50m';
  @override
  String get name => '50 m Dash';
}

class Run600m extends StopwatchTest {
  Run600m({super.heightCm});
  @override
  String get key => 'run_600m';
  @override
  String get name => '600 m Run/Walk';
}
