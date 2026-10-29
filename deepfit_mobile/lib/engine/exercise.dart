// Base class for every test - a copy of class Exercise / RepState in exercise_engine.py.

import 'pose.dart';
import 'py.dart';

class EngineEvent {
  final int id;
  final String kind; // rep | fault | tick | start | end | ready | step | try | go | move | tip | tap
  final String text;
  const EngineEvent(this.id, this.kind, this.text);
}

abstract class Exercise {
  // --- what the test is (the long texts - setup, adaptations - come from the server catalog)
  String get key;
  String get name;
  String get metric => 'reps';
  String get unit => 'reps';
  bool get higherIsBetter => true;
  double? get duration => 180.0; // seconds (3 min for every test); null = ends by itself / coach-timed
  String get camera => 'side'; // side | front | none

  // --- live state
  final double heightCm;
  int count = 0; // valid reps
  int invalid = 0; // reps rejected for form
  final Map<String, int> faults = {};
  String feedback = 'Get into position';
  final List<EngineEvent> events = []; // last 20, like deque(maxlen=20)
  bool finished = false;
  double? startedAt;
  double lastT = 0.0;
  bool poseSeen = false;
  int _eventId = 0;
  double? mirrorValue; // audio mirror 0..1 (null = no tone)
  String mirrorLabel = '';
  final List<double> _mirrorHist = [];
  Smoother sm = Smoother(); // median filter for every signal a threshold is applied to
  final Map<String, List<double>> _bones = {};
  int _badRun = 0;
  static const boneResetFrames = 8; // this many 'stretched bone' frames in a row = moved nearer/further, not a glitch

  Exercise({double heightCm = 165.0}) : heightCm = heightCm == 0 ? 165.0 : heightCm;

  int get lastEventId => _eventId;

  /// False when a body segment suddenly looks much longer or shorter than it has been - one landmark was
  /// put in the wrong place for a frame (bones can't stretch). Such frames are skipped, not counted.
  bool bonesOk(BodyPose pose, List<List<int>> pairs, {double lo = 0.65, double hi = 1.5}) {
    final lens = <MapEntry<String, double>>[
      for (final p in pairs)
        if (pose.vis([p[0], p[1]])) MapEntry('${p[0]}-${p[1]}', pose.dist(p[0], p[1])) // only points the model is sure of
    ];
    var bad = false;
    for (final e in lens) {
      final d = _bones[e.key];
      if (d != null && d.length >= 8) {
        final m = medianOf(d);
        if (m > 0 && !(lo * m <= e.value && e.value <= hi * m)) bad = true;
      }
    }
    _badRun = bad ? _badRun + 1 : 0;
    if (bad && _badRun >= boneResetFrames) {
      // not a glitch: the athlete really moved nearer / further - learn the bone lengths again
      _bones.clear();
      _badRun = 0;
      bad = false;
    }
    if (!bad) {
      for (final e in lens) {
        final d = _bones.putIfAbsent(e.key, () => <double>[]);
        d.add(e.value);
        if (d.length > 45) d.removeAt(0);
      }
    }
    return !bad;
  }

  void event(String kind, String text) {
    _eventId += 1;
    events.add(EngineEvent(_eventId, kind, text));
    if (events.length > 20) events.removeAt(0);
  }

  void fault(String name, String text) {
    faults[name] = (faults[name] ?? 0) + 1;
    feedback = text;
    event('fault', text);
  }

  void rep([String? text]) {
    count += 1;
    feedback = text ?? 'Rep $count!';
    event('rep', '$count');
  }

  void update(BodyPose? pose, double t) {
    lastT = t;
    startedAt ??= t;
    if (pose == null) {
      feedback = 'No person detected - step into the camera view';
      mirrorValue = null;
      return;
    }
    poseSeen = true;
    process(pose, t);
    final m = mirror(pose, t);
    if (m == null) {
      mirrorValue = null;
    } else {
      _mirrorHist.add(clamp01(m));
      if (_mirrorHist.length > 3) _mirrorHist.removeAt(0);
      mirrorValue = pyRound(sumOf(_mirrorHist) / _mirrorHist.length, 3);
    }
  }

  /// Audio-mirror signal for this exercise; subclasses override. null = no tone.
  double? mirror(BodyPose pose, double t) => null;

  void process(BodyPose pose, double t);

  double value() => count.toDouble();

  int get formPercentage {
    final total = count + invalid;
    return total > 0 ? pyRoundInt(100 * count / total) : (count > 0 ? 100 : 0);
  }

  /// Same keys as Python's result() - shown on the result screen and sent to the server.
  Map<String, dynamic> result() => {
        'value': pyRound(value(), 2),
        'unit': unit,
        'metric': metric,
        'higher_is_better': higherIsBetter,
        'repetitions': metric == 'reps' ? count : null,
        'invalid_reps': invalid,
        'form_score': formPercentage,
        'form_faults': Map<String, int>.from(faults),
      };
}

/// Median of each signal over the last ~0.22 s (at least 3 frames) - a copy of Smoother in exercise_engine.py.
/// Pose models jitter and now and then put a landmark in the wrong place for a frame or two; a median removes
/// that without lagging behind real movement.
class Smoother {
  final double window;
  final int minN;
  final Map<String, List<List<double>>> _buf = {};

  Smoother({this.window = 0.22, this.minN = 3});

  double call(String key, double v, double t) {
    final d = _buf.putIfAbsent(key, () => <List<double>>[]);
    d.add([t, v]);
    if (d.length > 64) d.removeAt(0);
    while (d.length > minN && t - d.first[0] > window) {
      d.removeAt(0);
    }
    return medianOf(d.map((e) => e[1]));
  }
}

/// Two-threshold rep counter with a little debouncing (frames in a row) and a minimum time between stage
/// changes (a real movement can't flip down/up faster than minGap).
class RepState {
  String? stage;
  String? prev;
  final int frames;
  final double minGap;
  String? _pending;
  int _n = 0;
  double _tChange = -1e9;

  RepState([this.frames = 2, this.minGap = 0.0]);

  /// Feed 'down'/'up'/null each frame; returns the new stage when it changes.
  /// [prev] tells which stage it came from (null at the very start).
  String? see(String? s, [double? t]) {
    if (s == null || s == stage) {
      _pending = null;
      _n = 0;
      return null;
    }
    if (s == _pending) {
      _n += 1;
    } else {
      _pending = s;
      _n = 1;
    }
    if (_n >= frames && (t == null || stage == null || t - _tChange >= minGap)) {
      prev = stage;
      stage = s;
      _pending = null;
      _n = 0;
      if (t != null) _tChange = t;
      return s;
    }
    return null;
  }
}
