// key -> new exercise, plus the offline benchmark rating (copy of benchmarks.evaluate).

import 'coachability.dart';
import 'exercise.dart';
import 'exercises.dart';
import 'growth.dart';
import 'py.dart';

export 'coachability.dart';
export 'exercise.dart';
export 'exercises.dart';
export 'growth.dart';
export 'pose.dart';
export 'py.dart';

/// Engine clock offset - the server re-runs uploads with the same one.
const double engineT0 = 1000.0;

Exercise? createExercise(String key, {double heightCm = 165.0}) {
  switch (key) {
    case 'situps':
      return SitUps(heightCm: heightCm);
    case 'partial_curlup':
      return PartialCurlUp(heightCm: heightCm);
    case 'pushups':
      return PushUps(heightCm: heightCm);
    case 'pushups_modified':
      return ModifiedPushUps(heightCm: heightCm);
    case 'plank':
      return Plank(heightCm: heightCm);
    case 'squats':
      return Squats(heightCm: heightCm);
    case 'jumping_jacks':
      return JumpingJacks(heightCm: heightCm);
    case 'dumbbell_curls':
      return DumbbellCurls(heightCm: heightCm);
    case 'vertical_jump':
      return VerticalJump(heightCm: heightCm);
    case 'broad_jump':
      return BroadJump(heightCm: heightCm);
    case 'sit_and_reach':
      return SitAndReach(heightCm: heightCm);
    case 'flamingo_balance':
      return FlamingoBalance(heightCm: heightCm);
    case 'plate_tapping':
      return PlateTapping(heightCm: heightCm);
    case 'dash_50m':
      return Dash50m(heightCm: heightCm);
    case 'run_600m':
      return Run600m(heightCm: heightCm);
    case 'growth_measures':
      return GrowthMeasures(heightCm: heightCm);
    case 'coachability':
      return CoachabilityChallenge(heightCm: heightCm);
  }
  return null;
}

/// Offline rating against the target the server sent (benchmarks.evaluate).
/// [target] = {"target", "unit", "higher_is_better", "scoring", "age_band"}.
Map<String, dynamic> evaluateBenchmark(double value, Map<String, dynamic>? target) {
  if (target == null) return {'available': false};
  final tgt = (target['target'] as num).toDouble();
  final higher = target['higher_is_better'] == true;
  String rating;
  bool met;
  int? pct;
  if (target['scoring'] == 'diff') {
    final delta = value - tgt;
    rating = delta < -5 ? 'Needs work' : (delta < 0 ? 'Fair' : (delta < 10 ? 'Good' : 'Excellent'));
    met = delta >= 0;
    pct = null;
  } else {
    double ratio;
    if (value <= 0 && higher) {
      ratio = 0.0;
    } else if (!higher) {
      ratio = value > 0 ? tgt / value : (target['unit'] == 'falls' ? 2.0 : 0.0);
    } else {
      ratio = tgt != 0 ? value / tgt : 0.0;
    }
    met = ratio >= 1.0;
    rating = ratio < 0.75 ? 'Needs work' : (ratio < 1.0 ? 'Fair' : (ratio < 1.5 ? 'Good' : 'Excellent'));
    pct = pyRoundInt(100 * ratio);
  }
  return {
    'available': true,
    'target': tgt,
    'unit': target['unit'],
    'higher_is_better': higher,
    'met': met,
    'rating': rating,
    'percent_of_target': pct,
    'age_band': target['age_band'],
  };
}
