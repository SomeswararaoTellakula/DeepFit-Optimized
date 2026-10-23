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
  final rs = RepState();

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

  @override
  void process(BodyPose pose, double t) {
    final side = pose.bestSide([L.lShoulder, L.lHip, L.lKnee], [L.rShoulder, L.rHip, L.rKnee]);
    if (side == null) {
      feedback = 'Turn side-on so your shoulder, hip and knee are visible';
      return;
    }
    final elev = elevation(pose.p(side[1]), pose.p(side[0]));
    final st = rs.see(elev < downElev ? 'down' : (elev > upElev ? 'up' : null));
    if (st == 'up') {
      feedback = 'Good - now lie back down';
    } else if (st == 'down') {
      if (rs.prev == 'up') {
        rep();
      } else {
        feedback = 'Sit up!';
      }
    }
  }
}

class PartialCurlUp extends Exercise {
  static const downElev = 12.0, upElev = 25.0; // torso lift above the floor, degrees
  final rs = RepState();
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
    final elev = elevation(pose.p(side[1]), pose.p(side[0]));
    maxElev = math.max(maxElev, elev);
    final st = rs.see(elev < downElev ? 'down' : (elev > upElev ? 'up' : null));
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
  bool get kneeVariant => false;
  final rs = RepState();
  bool badLineInRep = false;

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
    final sh = pose.p(side[0]), el = pose.p(side[1]), wr = pose.p(side[2]), hp = pose.p(side[3]), en = pose.p(side[4]);
    final elbow = angle(sh, el, wr);
    final body = angle(sh, hp, en);
    if (body < straight) badLineInRep = true;
    final st = rs.see(elbow < down ? 'down' : (elbow > up ? 'up' : null));
    if (st == 'down') {
      feedback = 'Push up!';
    } else if (st == 'up' && rs.prev != 'down') {
      badLineInRep = false;
      feedback = 'Lower your chest';
    } else if (st == 'up') {
      if (badLineInRep) {
        invalid += 1;
        fault('body_line', 'Not counted - keep your body straight');
      } else {
        rep();
      }
      badLineInRep = false;
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
    final dt = _prevT == null ? 0.0 : math.min(0.5, t - _prevT!);
    _prevT = t;
    final side = pose.bestSide([L.lShoulder, L.lHip, L.lAnkle], [L.rShoulder, L.rHip, L.rAnkle]);
    var good = false;
    if (side != null) {
      final sh = pose.p(side[0]), hp = pose.p(side[1]), an = pose.p(side[2]);
      good = angle(sh, hp, an) >= straight && elevation(an, sh) <= maxTorsoElev;
    }
    if (good) {
      brokenSince = null;
      if (!holding) {
        holding = true;
        event('start', 'Holding');
      }
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
        finished = true;
        feedback = 'Plank ended at ${hold.toInt()} s';
        event('end', feedback);
      }
    } else {
      feedback = side != null ? 'Get into a straight plank to start the clock' : 'Turn side-on - shoulder, hip and ankle visible';
    }
  }

  @override
  double value() => hold;
}

class Squats extends Exercise {
  static const down = 100.0, up = 160.0, maxLean = 55.0;
  final rs = RepState();
  bool leanBad = false;

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
    final sh = pose.p(side[0]), hp = pose.p(side[1]), kn = pose.p(side[2]), an = pose.p(side[3]);
    final knee = angle(hp, kn, an);
    final lean = 90 - elevation(hp, sh);
    if (knee < 130 && lean > maxLean) leanBad = true;
    final st = rs.see(knee < down ? 'down' : (knee > up ? 'up' : null));
    if (st == 'down') {
      feedback = 'Drive up!';
    } else if (st == 'up' && rs.prev != 'down') {
      leanBad = false;
      feedback = 'Squat down';
    } else if (st == 'up') {
      if (leanBad) {
        invalid += 1;
        fault('lean', 'Not counted - keep your chest up');
      } else {
        rep();
      }
      leanBad = false;
    }
  }
}

// ---------------------------------------------------------------- front-view

class JumpingJacks extends Exercise {
  final rs = RepState();
  bool _wasOpen = false;

  JumpingJacks({super.heightCm});

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
    final shw = math.max(pose.dist(L.lShoulder, L.rShoulder), 1.0);
    final feet = (pose.p(L.lAnkle).x - pose.p(L.rAnkle).x).abs();
    final shY = math.min(pose.p(L.lShoulder).y, pose.p(L.rShoulder).y);
    final handsUp = pose.p(L.lWrist).y < shY && pose.p(L.rWrist).y < shY;
    final handsDown = pose.p(L.lWrist).y > shY + 0.3 * shw && pose.p(L.rWrist).y > shY + 0.3 * shw;
    String? st;
    if (handsUp && feet > 1.3 * shw) {
      st = rs.see('open');
    } else if (handsDown && feet < 1.0 * shw) {
      st = rs.see('closed');
    } else {
      st = rs.see(null);
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
  final Map<String, String> state = {'left': 'down', 'right': 'down'};
  final Map<String, int> counts = {'left': 0, 'right': 0};

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
      final a = angle(pose.p(s), pose.p(e), pose.p(w));
      if (state[arm] == 'down' && a < up) {
        state[arm] = 'up';
        counts[arm] = counts[arm]! + 1;
        count += 1;
        feedback = '${arm[0].toUpperCase()}${arm.substring(1)} ${counts[arm]}';
        event('rep', '$arm ${counts[arm]}');
      } else if (state[arm] == 'up' && a > down) {
        state[arm] = 'down';
      }
    }
    if (!seen) feedback = 'Face the camera - shoulders, elbows and wrists visible';
  }
}

// ---------------------------------------------------------------- jumps

class _Stand {
  final double hipY, ankX, ankY, bodyPx, lAnkY, rAnkY;
  const _Stand(this.hipY, this.ankX, this.ankY, this.bodyPx, this.lAnkY, this.rAnkY);
}

class _JumpBaseline {
  final _Stand avg;
  final double cmPerPx;
  const _JumpBaseline(this.avg, this.cmPerPx);
}

/// Shared calibration: stand still, measure body size in pixels to convert to cm.
abstract class _JumpBase extends Exercise {
  static const attemptsMax = 3;
  final List<_Stand> calib = []; // deque(maxlen=20)
  _JumpBaseline? base;
  bool airborne = false;
  final List<double> attempts = [];
  double peakRise = 0.0;
  int landFrames = 0;

  _JumpBase({super.heightCm});

  @override
  double? get duration => 90.0;

  _Stand? _standing(BodyPose pose) {
    if (!pose.vis([L.nose, L.lHip, L.rHip, L.lAnkle, L.rAnkle])) return null;
    final hip = pose.mid(L.lHip, L.rHip);
    final ank = pose.mid(L.lAnkle, L.rAnkle);
    final nose = pose.p(L.nose);
    return _Stand(hip.y, ank.x, ank.y, ank.y - nose.y, pose.p(L.lAnkle).y, pose.p(L.rAnkle).y);
  }

  bool _calibrate(_Stand cur) {
    calib.add(cur);
    if (calib.length > 20) calib.removeAt(0);
    if (calib.length < 12) {
      feedback = 'Stand still for calibration…';
      return false;
    }
    final hips = calib.map((c) => c.hipY);
    final xs = calib.map((c) => c.ankX);
    if (maxOf(hips) - minOf(hips) > 0.02 * cur.bodyPx || maxOf(xs) - minOf(xs) > 0.03 * cur.bodyPx) {
      feedback = 'Stand still for calibration…';
      return false;
    }
    final n = calib.length;
    double avg(double Function(_Stand) f) => sumOf(calib.map(f)) / n;
    final a = _Stand(avg((c) => c.hipY), avg((c) => c.ankX), avg((c) => c.ankY), avg((c) => c.bodyPx),
        avg((c) => c.lAnkY), avg((c) => c.rAnkY));
    // nose is ~0.92 of standing height; ankle ~0.04 above the floor
    base = _JumpBaseline(a, (heightCm * 0.88) / math.max(a.bodyPx, 1.0));
    calib.clear();
    feedback = 'Ready - jump! (attempt ${attempts.length + 1} of $attemptsMax)';
    event('ready', feedback);
    return true;
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
    final rise = (base!.avg.hipY - cur.hipY) * base!.cmPerPx;
    if (!airborne && rise > 6) {
      airborne = true;
      peakRise = rise;
      feedback = 'Up!';
    } else if (airborne) {
      peakRise = math.max(peakRise, rise);
      if (rise < 3) {
        landFrames += 1;
        if (landFrames >= 3) {
          airborne = false;
          landFrames = 0;
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
      _calibrate(cur);
      return;
    }
    final cpp = base!.cmPerPx;
    final moved = (cur.ankX - base!.avg.ankX).abs() * cpp;
    // take-off = BOTH feet off the floor (walking only lifts one foot at a time)
    final lifted = math.min(base!.avg.lAnkY - cur.lAnkY, base!.avg.rAnkY - cur.rAnkY) * cpp;
    if (!airborne && lifted > 4) {
      airborne = true;
      feedback = 'Jump!';
    } else if (airborne) {
      final onFloor = (cur.ankY - base!.avg.ankY).abs() * cpp < 4;
      if (onFloor && moved > 20) {
        landFrames += 1;
        if (landFrames >= 4) {
          airborne = false;
          landFrames = 0;
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
      } else {
        landFrames = 0;
      }
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
  double? get duration => 45.0;

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
    if (angle(hp, kn, an) < straightLeg) {
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
    if (window.isNotEmpty && t - window.first[0] >= holdTime * 0.9 && maxOf(vals) - minOf(vals) < 3) {
      final held = sumOf(vals) / vals.length;
      if (best == null || held > best! + 0.5) {
        best = held;
        event('rep', '${fmtFixed(held, 0)} centimetres');
      }
      feedback = 'Held ${fmtSigned0(held)} cm - best ${fmtSigned0(best!)} cm';
    } else {
      feedback = 'Reach… ${fmtSigned0(reach)} cm';
    }
  }

  @override
  double value() => best ?? 0.0;
}

class FlamingoBalance extends Exercise {
  static const lift = 0.06, downTime = 0.3;
  double balanceTime = 0.0;
  bool balancing = false;
  double? downSince;
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
    final dt = _prevT == null ? 0.0 : math.min(0.5, t - _prevT!);
    _prevT = t;
    if (!pose.vis([L.lAnkle, L.rAnkle, L.nose])) {
      feedback = 'Whole body must be visible';
      return;
    }
    final body = math.max(pose.mid(L.lAnkle, L.rAnkle).y - pose.p(L.nose).y, 1.0);
    final lifted = (pose.p(L.lAnkle).y - pose.p(L.rAnkle).y).abs() / body > lift;
    if (lifted) {
      downSince = null;
      if (!balancing) {
        balancing = true;
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
  static const cycles = 25;
  Map<String, PlateTarget>? targets;
  String nextSide = 'left';
  int touches = 0;
  double? tFirst;
  double? tDone;

  PlateTapping({super.heightCm});

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
    final hands = [
      for (final i in [L.lWrist, L.rWrist, L.lIndex, L.rIndex])
        if (pose.vis([i])) pose.p(i)
    ];
    final tg = targets![nextSide]!;
    if (hands.any((h) => hypot(h.x - tg.x, h.y - tg.y) < tg.r)) {
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
