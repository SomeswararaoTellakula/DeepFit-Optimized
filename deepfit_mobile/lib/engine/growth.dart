// Growth Measures (sitting height by camera) + the Mirwald maturity estimate.
// A line-by-line copy of growth.py and potential.maturity_offset.

import 'exercise.dart';
import 'pose.dart';
import 'py.dart';

const eyeRatio = 0.936; // eye height / standing height
const holdSeconds = 1.5; // seconds to hold each position still

/// Typical age at peak height velocity (the server can override these with env settings).
const Map<String, double> meanAphv = {'M': 13.8, 'F': 11.8};

String sexOf(Object? g) {
  final s = (g ?? '').toString().trim().toUpperCase();
  return (s.startsWith('F') || s.startsWith('W') || s.startsWith('G')) ? 'F' : 'M';
}

/// Mirwald et al. (2002) maturity offset: years from peak height velocity.
Map<String, dynamic> maturityOffset(double age, Object? sex, double heightCm, double sittingCm, double weightKg) {
  final s = sexOf(sex);
  final h = heightCm, sh = sittingCm, w = weightKg;
  final ll = h - sh;
  final wh = w / h * 100;
  final double off;
  if (s == 'M') {
    off = -9.236 + 0.0002708 * ll * sh - 0.001663 * age * ll + 0.007216 * age * sh + 0.02292 * wh;
  } else {
    off = (-9.376 + 0.0001882 * ll * sh + 0.0022 * age * ll + 0.005841 * age * sh - 0.002658 * age * w + 0.07693 * wh);
  }
  final aphv = age - off;
  final delta = aphv - meanAphv[s]!; // + = later than average (late developer)
  final status = delta >= 1.0 ? 'late' : (delta <= -1.0 ? 'early' : 'on time');
  final valid = 8 <= age && age <= 17.5;
  return {
    'maturity_offset': pyRound(off, 2),
    'predicted_aphv': pyRound(aphv, 2),
    'mean_aphv': meanAphv[s],
    'years_vs_average': pyRound(delta, 2),
    'status': status,
    'sitting_height_cm': pyRound(sh, 1),
    'leg_length_cm': pyRound(ll, 1),
    'sitting_ratio': pyRound(sh / h, 3),
    'valid_age': valid,
    'note': valid
        ? 'Estimate (Mirwald 2002 equation). Most reliable for ages 8-16; treat as ±1 year.'
        : 'Outside the 8-17 age range the equation is not reliable - shown for reference only.',
  };
}

class GrowthMeasures extends Exercise {
  final Map<String, dynamic> inputs = {};
  String phase = 'stand';
  final List<List<double>> buf = []; // (t, value)
  double? standPx;
  double? floorY;
  double? cmPerPx;
  double? standHipY;
  Map<String, dynamic>? measure;

  GrowthMeasures({super.heightCm}) {
    inputs.addAll({'height_cm': heightCm, 'weight_kg': null, 'chair_cm': 45.0, 'age': null, 'sex': 'M'});
    feedback = 'Stand straight, side-on, on the marked spot';
  }

  @override
  String get key => 'growth_measures';
  @override
  String get name => 'Growth Measures (sitting height)';
  @override
  String get metric => 'maturity_offset';
  @override
  String get unit => 'yrs';
  @override
  double? get duration => 180.0;

  void configure({double? heightCm, double? weightKg, double? chairCm, Object? age, Object? sex}) {
    if (heightCm != null) inputs['height_cm'] = heightCm;
    if (weightKg != null) inputs['weight_kg'] = weightKg;
    if (chairCm != null) inputs['chair_cm'] = chairCm;
    if (age != null) inputs['age'] = age;
    if (sex != null) inputs['sex'] = sex;
  }

  (double, double)? _eyeFloor(BodyPose pose) {
    final eyes = [for (final i in [L.lEye, L.rEye]) if (pose.vis([i])) pose.p(i).y];
    final feet = [
      for (final i in [L.lHeel, L.rHeel, L.lFoot, L.rFoot, L.lAnkle, L.rAnkle])
        if (pose.vis([i])) pose.p(i).y
    ];
    if (eyes.isEmpty || feet.isEmpty) return null;
    return (minOf(eyes), maxOf(feet));
  }

  double? _stable(double t, double val) {
    buf.add([t, val]);
    while (buf.isNotEmpty && t - buf.first[0] > holdSeconds) {
      buf.removeAt(0);
    }
    final vals = buf.map((b) => b[1]).toList();
    final mean = sumOf(vals) / vals.length;
    if (t - buf.first[0] >= holdSeconds * 0.9 && maxOf(vals) - minOf(vals) < 0.02 * (mean.abs() > 1 ? mean.abs() : 1.0)) {
      return mean;
    }
    return null;
  }

  @override
  void process(BodyPose pose, double t) {
    if (phase == 'done') return;
    final ef = _eyeFloor(pose);
    if (ef == null) {
      feedback = 'Eyes and feet must be visible - step back or move the camera';
      buf.clear();
      return;
    }
    final (eyeY, fY) = ef;
    if (phase == 'stand') {
      final v = _stable(t, fY - eyeY);
      feedback = 'Stand still… measuring standing height';
      if (truthy(v)) {
        final h = (inputs['height_cm'] as num).toDouble();
        standPx = v;
        floorY = fY;
        standHipY = pose.vis([L.lHip, L.rHip]) ? pose.mid(L.lHip, L.rHip).y : null;
        cmPerPx = eyeRatio * h / v!;
        phase = 'sit';
        buf.clear();
        feedback = 'Now sit on the chair on the same spot, back straight';
        event('step', 'Now sit on the chair, on the same spot. Back straight, look ahead.');
      }
      return;
    }
    if (phase == 'sit') {
      final hipY = pose.vis([L.lHip, L.rHip]) ? pose.mid(L.lHip, L.rHip).y : null;
      final seated = hipY != null && standHipY != null && hipY - standHipY! > 0.12 * standPx!;
      if (!seated) {
        buf.clear();
        feedback = 'Sit down on the chair (same spot)';
        return;
      }
      final v = _stable(t, floorY! - eyeY);
      feedback = 'Sit tall and still… measuring sitting height';
      if (truthy(v)) _compute(v!);
    }
  }

  void _compute(double seatedPx) {
    final h = (inputs['height_cm'] as num).toDouble();
    final seatedEyeCm = seatedPx * cmPerPx!;
    final sh = seatedEyeCm - (inputs['chair_cm'] as num).toDouble() + (1 - eyeRatio) * h;
    final ratio = sh / h;
    if (!(0.44 <= ratio && ratio <= 0.60)) {
      // outside human range: camera moved, wrong chair height, or slouching
      phase = 'stand';
      buf.clear();
      fault('implausible',
          'Sitting height came out ${fmtPercent0(ratio)} of height - check the chair height and that the camera did not move. Stand up to start again.');
      return;
    }
    final m = <String, dynamic>{'height_cm': pyRound(h, 1), 'sitting_height_cm': pyRound(sh, 1)};
    final w = inputs['weight_kg'], age = inputs['age'];
    if (_truthyObj(w) && _truthyObj(age)) {
      m.addAll(maturityOffset((age as num).toDouble() + 0.5, inputs['sex'], h, sh, (w as num).toDouble()));
    }
    measure = m;
    phase = 'done';
    finished = true;
    final off = m['maturity_offset'] as double?;
    feedback = 'Sitting height ${fmtFixed(sh, 0)} cm. ' +
        (off != null
            ? 'About ${fmtFixed(off.abs(), 1)} years ${off < 0 ? 'before' : 'after'} the growth spurt (${m['status']} developer).'
            : 'Enter weight and age to get the maturity estimate.');
    event('end', feedback);
  }

  static bool _truthyObj(Object? v) => v != null && !(v is num && v == 0);

  @override
  double value() => orNum((measure?['maturity_offset'] as double?), 0.0);

  @override
  Map<String, dynamic> result() {
    final r = super.result();
    r['repetitions'] = null;
    r['form_score'] = null;
    r['maturity'] = measure;
    r['inputs'] = {for (final k in ['height_cm', 'weight_kg', 'chair_cm']) k: inputs[k]};
    if (measure == null) r['incomplete'] = true;
    return r;
  }
}
