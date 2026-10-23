import 'dart:async';
import 'dart:io' show Platform;

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../app.dart';
import '../engine/registry.dart';
import '../services/api.dart';
import '../services/app_state.dart';
import '../services/camera_session.dart';
import '../services/outbox.dart';
import '../services/speech.dart';
import '../services/tones.dart';
import '../services/vision.dart';
import '../widgets/common.dart';
import '../widgets/pose_painter.dart';
import 'result_screen.dart';

enum _Phase { opening, ready, verifying, countdown, running, finishing, failed }

const _snapEvery = 3.0; // seconds between face snapshots during a test
const _countdownSeconds = 3;
final _guidance = RegExp(r'visible|turn|step|stand still|lift|sit side|face the', caseSensitive: false);

/// Runs one camera test on the phone: body tracking, counting, voice / tones / flashes,
/// face checks, then hands the recording to the upload queue.
class TestRunScreen extends StatefulWidget {
  final TestInfo info;
  final String mode;
  final bool front;
  final Map<String, double>? growthInputs;
  final double? loadKg;                    // dumbbell curls: weight in each hand
  final Map<String, dynamic>? loadDetect;  // how that weight was found (read off the dumbbell / estimated / picked)
  const TestRunScreen(
      {super.key, required this.info, required this.mode, required this.front, this.growthInputs, this.loadKg, this.loadDetect});
  @override
  State<TestRunScreen> createState() => _TestRunScreenState();
}

class _TestRunScreenState extends State<TestRunScreen> with WidgetsBindingObserver {
  late final AppState _state;
  late final CameraSession _cam;
  late final Exercise _ex;
  final _speech = Speech();
  final _tones = Tones();
  _Phase _phase = _Phase.opening;
  String? _error;
  VisionFrame? _frame;
  Size _frameSize = const Size(480, 640);

  // recording
  final _clock = Stopwatch();
  final List<List<Object?>> _frames = [];
  final List<Map<String, Object>> _snaps = [];
  double _nextSnapAt = 0;
  bool _snapBusy = false;
  String? _precheckToken;
  bool _offlineCheck = false;

  // live identity (online only - the server re-checks every snapshot anyway)
  int _strikes = 0;
  double _lastFaceSeen = 0;
  bool _liveBusy = false;
  String _identity = '';

  // feedback to the athlete
  int _lastEventId = 0;
  int _countdown = 0;
  Timer? _countdownTimer;
  String _caption = '';
  Color? _flash;
  Timer? _flashTimer;
  final Set<int> _announced = {};
  String _lastFeedback = '';
  DateTime _lastGuidance = DateTime(2000);
  bool _mirrorOn = false;
  bool _mirrorSeen = false;

  bool get _blind => widget.mode == 'blind';
  bool get _deaf => widget.mode == 'deaf';
  bool get _talk => !_deaf && (_blind || _state.voice);
  double? get _duration => _ex.duration;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _state = AppScope.read(context);
    final ex = createExercise(widget.info.key, heightCm: _state.heightCm) ?? SitUps(heightCm: _state.heightCm);
    final g = widget.growthInputs;
    if (ex is GrowthMeasures && g != null) {
      ex.configure(
          heightCm: g['height_cm'], weightKg: g['weight_kg'], chairCm: g['chair_cm'],
          age: _state.athlete?['age'], sex: _state.athlete?['gender']);
    }
    _ex = ex;
    _mirrorOn = _blind;
    _cam = CameraSession(detectPose: true, mirroredStream: _state.mirroredStream(widget.front));
    _cam.onFrame = _onFrame;
    WakelockPlus.enable();
    _speech.init();
    _tones.init();
    _open();
  }

  Future<void> _open() async {
    final ok = await _cam.open(front: widget.front);
    if (!mounted) return;
    if (!ok) {
      setState(() {
        _phase = _Phase.failed;
        _error = _cam.error;
      });
      _say(_cam.error ?? 'Camera unavailable', interrupt: true);
      return;
    }
    setState(() => _phase = _Phase.ready);
    _say(_blind ? 'Camera ready. Get into position, then double tap anywhere to start.' : 'Get into position, then press start.');
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState s) {
    // the camera stops when the app goes to the background: end the test with what we have
    if (s == AppLifecycleState.paused && _phase == _Phase.running) _finish();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _countdownTimer?.cancel();
    _flashTimer?.cancel();
    _cam.close();
    _tones.dispose();
    _speech.stop();
    WakelockPlus.disable();
    super.dispose();
  }

  // ------------------------------------------------------------------ helpers

  void _say(String text, {bool interrupt = false}) {
    if (_talk) _speech.say(text, interrupt: interrupt);
  }

  void _beep(int freq, int ms) {
    if (_blind) _tones.beep(freq, ms);
  }

  void _flashKind(bool ok) {
    if (_deaf || _blind) {
      ok ? HapticFeedback.mediumImpact() : HapticFeedback.heavyImpact();
    }
    if (!_deaf) return;
    _flashTimer?.cancel();
    setState(() => _flash = ok ? DeepFitColors.green : DeepFitColors.red);
    _flashTimer = Timer(Duration(milliseconds: ok ? 350 : 900), () {
      if (mounted) setState(() => _flash = null);
    });
  }

  double get _elapsed => _clock.elapsedMicroseconds / 1e6;

  // ------------------------------------------------------------------ start: face check + countdown

  Future<void> _start() async {
    if (_phase != _Phase.ready) return;
    HapticFeedback.selectionClick();
    if (!_state.requireFace) {
      _beginCountdown();
      return;
    }
    setState(() {
      _phase = _Phase.verifying;
      _identity = 'Checking your face…';
    });
    _say('Look at the camera for a face check.', interrupt: true);
    final jpg = await _cam.grabJpegBase64();
    if (!mounted) return;
    if (jpg == null) {
      setState(() {
        _phase = _Phase.ready;
        _identity = 'Could not read the camera - try again';
      });
      return;
    }
    _snaps.add({'t': -1.0, 'jpg': jpg}); // start snapshot (used by the server if this test is uploaded later)
    try {
      final r = await _state.api.post('/identity/verify', {'frame': jpg}, timeout: const Duration(seconds: 10));
      if (!mounted) return;
      if (r['is_match'] == true) {
        _precheckToken = r['precheck_token'] as String?;
        _identity = 'Verified ✓';
        _say('Face verified.');
        _beginCountdown();
      } else {
        final msg = (r['message'] ?? 'Face does not match the registered athlete') as String;
        _snaps.clear();
        setState(() {
          _phase = _Phase.ready;
          _identity = '✗ $msg';
        });
        _say('$msg. Only the registered athlete can take the test.', interrupt: true);
        _flashKind(false);
      }
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.offline) {
        // no internet: run the test now, the server checks the face snapshots when it syncs
        _offlineCheck = true;
        _identity = 'Offline - face checked when you sync';
        _beginCountdown();
      } else {
        setState(() {
          _phase = _Phase.ready;
          _identity = '✗ ${e.message}';
        });
        _say(e.message, interrupt: true);
      }
    }
  }

  void _beginCountdown() {
    setState(() {
      _phase = _Phase.countdown;
      _countdown = _countdownSeconds;
    });
    _say('$_countdown', interrupt: true);
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) return t.cancel();
      _countdown -= 1;
      if (_countdown <= 0) {
        t.cancel();
        _go();
      } else {
        setState(() {});
        _say('$_countdown', interrupt: true);
        _beep(700, 60);
      }
    });
  }

  void _go() {
    _clock
      ..reset()
      ..start();
    _nextSnapAt = 0;
    _lastFaceSeen = 0;
    setState(() => _phase = _Phase.running);
    if (_ex is! CoachabilityChallenge) {
      _say('Go!', interrupt: true);
      _beep(1000, 250);
    }
    _flashKind(true);
  }

  // ------------------------------------------------------------------ every frame

  void _onFrame(VisionFrame f) {
    if (!mounted) return;
    _frame = f;
    _frameSize = Size(f.width, f.height);
    if (_phase == _Phase.running) _feed(f);
    setState(() {});
  }

  void _feed(VisionFrame f) {
    final t = (_elapsed * 10000).roundToDouble() / 10000;
    final dur = _duration;
    if (dur != null && t > dur + 0.25) {
      _finish();
      return;
    }
    final lm = f.canonical;
    _ex.update(lm == null ? null : BodyPose(lm, f.width, f.height), engineT0 + t);
    _frames.add([t, lm]);
    _handleEvents();
    _guide();
    _timeLeft(t);
    if (_ex.mirrorValue != null) _mirrorSeen = true;
    _tones.mirror(_mirrorOn ? _ex.mirrorValue : null, speaking: _speech.speaking);
    if (t >= _nextSnapAt) {
      _nextSnapAt = t + _snapEvery;
      _snapshot(t);
    }
    if (_ex.finished || (dur != null && t >= dur)) _finish();
  }

  void _handleEvents() {
    for (final ev in _ex.events) {
      if (ev.id <= _lastEventId) continue;
      _lastEventId = ev.id;
      _caption = ev.text;
      switch (ev.kind) {
        case 'rep':
          _say(ev.text, interrupt: true);
          _beep(1100, 90);
          _flashKind(true);
        case 'fault':
          _say(ev.text, interrupt: true);
          _beep(250, 250);
          _flashKind(false);
        case 'tap':
          _beep(ev.text == 'left' ? 700 : 900, 60);
          _flashKind(true);
        case 'move':
          final ok = ev.text.startsWith('✓');
          _beep(ok ? 1200 : 300, 90);
          _flashKind(ok);
        case 'go':
          _say('Go!', interrupt: true);
          _beep(1000, 250);
          _flashKind(true);
        case 'tip':
          _say(ev.text, interrupt: true);
        default:
          _say(ev.text);
      }
    }
  }

  /// Position guidance is spoken at most every 5 s, and only when it changes.
  void _guide() {
    final fb = _ex.feedback;
    if (fb != _lastFeedback &&
        DateTime.now().difference(_lastGuidance).inSeconds >= 5 &&
        _guidance.hasMatch(fb)) {
      _lastGuidance = DateTime.now();
      _say(fb);
    }
    _lastFeedback = fb;
  }

  void _timeLeft(double t) {
    final dur = _duration;
    if (dur == null) return;
    final rem = dur - t;
    for (final mark in const [30, 10]) {
      if (rem <= mark && rem > mark - 2 && dur > mark + 5 && _announced.add(mark)) _say('$mark seconds left');
    }
  }

  Future<void> _snapshot(double t) async {
    if (_snapBusy) return;
    _snapBusy = true;
    try {
      final jpg = await _cam.grabJpegBase64();
      if (jpg == null || !mounted || _phase != _Phase.running) return;
      _snaps.add({'t': t, 'jpg': jpg});
      if (_state.requireFace && !_offlineCheck) _liveCheck(jpg, t);
    } finally {
      _snapBusy = false;
    }
  }

  /// Same rules as the website: 3 mismatches in a row (or the face hidden too long) stop the test.
  Future<void> _liveCheck(String jpg, double t) async {
    if (_liveBusy) return;
    _liveBusy = true;
    try {
      final r = await _state.api.post('/identity/verify', {'frame': jpg, 'live': true}, timeout: const Duration(seconds: 8));
      if (!mounted || _phase != _Phase.running) return;
      final reason = r['reason'];
      if (r['is_match'] == true) {
        _strikes = 0;
        _lastFaceSeen = t;
        _identity = 'Verified ✓ (live)';
      } else if (reason == 'mismatch') {
        _strikes += 1;
        _lastFaceSeen = t;
        _identity = 'MISMATCH $_strikes/3';
        _say('Face does not match', interrupt: true);
      } else if (reason == 'no_face' && _state.faceHiddenSeconds > 0 && t - _lastFaceSeen > _state.faceHiddenSeconds) {
        _strikes += 1;
        _lastFaceSeen = t;
        _identity = 'Face hidden $_strikes/3';
      }
      if (_strikes >= 3) _finish(identityFailed: true);
    } on ApiException {
      // offline mid-test: the server checks the snapshots when the result is uploaded
    } finally {
      _liveBusy = false;
    }
  }

  // ------------------------------------------------------------------ finish

  Future<void> _finish({bool identityFailed = false}) async {
    if (_phase == _Phase.finishing) return;
    final wasRunning = _phase == _Phase.running;
    setState(() => _phase = _Phase.finishing);
    _clock.stop();
    _countdownTimer?.cancel();
    await _tones.silence();
    if (identityFailed) {
      _say('Test stopped. A different person was detected.', interrupt: true);
      await _cam.close();
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Test stopped'),
          content: const Text('A different person was detected. Only the registered athlete can take the test - nothing was saved.'),
          actions: [TextButton(onPressed: () => Navigator.of(c).pop(), child: const Text('OK'))],
        ),
      );
      if (mounted) Navigator.of(context).pop();
      return;
    }
    if (!wasRunning || _frames.isEmpty) {
      await _cam.close();
      if (mounted) Navigator.of(context).pop();
      return;
    }
    // one last face snapshot so the end of the test is covered too
    if (_state.requireFace) {
      final jpg = await _cam.grabJpegBase64(timeout: const Duration(seconds: 1));
      if (jpg != null) _snaps.add({'t': (_frames.last[0] as double), 'jpg': jpg});
    }
    await _cam.close();
    final result = _ex.result();
    final ex = _ex;
    final id = Outbox.newId();
    final body = <String, dynamic>{
      'client_id': id,
      'exercise': widget.info.key,
      'mode': widget.mode,
      'captured_at': DateTime.now().toUtc().toIso8601String(),
      'frame_size': {'w': _frameSize.width.round(), 'h': _frameSize.height.round()},
      'frames': _frames,
      'snapshots': _snaps,
      'client_result': {'value': result['value']},
      'precheck_token': _precheckToken,
      'height_cm': _state.heightCm,
      'device': {
        'platform': Platform.operatingSystem,
        'os': Platform.operatingSystemVersion,
        'app': appVersion,
        'camera': widget.front ? 'front' : 'back',
      },
      if (ex is GrowthMeasures) 'inputs': widget.growthInputs,
      if (widget.loadKg != null) 'load_kg': widget.loadKg,
      if (widget.loadKg != null && widget.loadDetect != null) 'load_detect': widget.loadDetect,
      if (ex is CoachabilityChallenge) 'pattern': ex.pattern,
      if (ex is CoachabilityChallenge) 'pattern_code': ex.code,
    };
    final rating = evaluateBenchmark((result['value'] as num).toDouble(), widget.info.targetFor(widget.mode));
    final local = <String, dynamic>{...result, 'benchmark': rating, 'exercise_name': widget.info.name};
    await _state.addToOutbox(OutboxItem(
        id: id,
        kind: 'result',
        exercise: widget.info.key,
        name: widget.info.name,
        created: DateTime.now(),
        body: body,
        local: local));
    _say('Test finished.');
    if (!mounted) return;
    Navigator.of(context).pushReplacement(MaterialPageRoute(
        builder: (_) => ResultScreen(info: widget.info, mode: widget.mode, outboxId: id, local: local)));
  }

  // ------------------------------------------------------------------ UI

  @override
  Widget build(BuildContext context) {
    final controller = _cam.controller;
    final ex = _ex;
    final running = _phase == _Phase.running;
    final dur = _duration;
    final t = _elapsed;
    final timerText = dur == null ? _fmtClock(t) : _fmtClock(running ? (dur - t).clamp(0, dur).toDouble() : dur);

    Widget preview = const Center(child: CircularProgressIndicator());
    if (_phase == _Phase.failed) {
      preview = Center(
        child: Padding(padding: const EdgeInsets.all(24), child: Text(_error ?? 'Camera unavailable', textAlign: TextAlign.center)),
      );
    } else if (controller != null && controller.value.isInitialized && _cam.description != null) {
      final desc = _cam.description!;
      final targets = <(Offset, double, bool)>[];
      if (ex is PlateTapping && ex.targets != null && _frame != null) {
        ex.targets!.forEach((side, tg) {
          targets.add((
            Offset(_cam.vision.displayX(tg.x / _frameSize.width, desc), tg.y / _frameSize.height),
            tg.r / _frameSize.width,
            side == ex.nextSide,
          ));
        });
      }
      preview = Center(
        child: CameraPreview(
          controller,
          child: CustomPaint(painter: PosePainter(_frame?.display, _frame?.likelihood, targets: targets)),
        ),
      );
    }

    final body = Stack(children: [
      Positioned.fill(child: preview),
      if (_flash != null)
        Positioned.fill(
          child: IgnorePointer(
            child: Container(
              decoration: BoxDecoration(
                color: _flash == DeepFitColors.green ? DeepFitColors.green.withAlpha(70) : null,
                border: Border.all(color: _flash!, width: 14),
              ),
            ),
          ),
        ),
      if (_phase == _Phase.countdown)
        Center(
          child: Text('$_countdown',
              style: const TextStyle(fontSize: 160, fontWeight: FontWeight.w900, color: Colors.white, shadows: [Shadow(blurRadius: 20)])),
        ),
      Positioned(
        left: 12,
        top: 12,
        child: _Badge(text: '${widget.info.icon} ${widget.info.name} · ${widget.mode}'),
      ),
      if (_identity.isNotEmpty)
        Positioned(
          right: 12,
          top: 12,
          child: _Badge(
              text: _identity,
              color: _identity.startsWith('✗') || _identity.startsWith('MIS') || _identity.startsWith('Face hidden')
                  ? DeepFitColors.red
                  : DeepFitColors.green),
        ),
      if (_deaf && _caption.isNotEmpty)
        Positioned(
          left: 12,
          right: 12,
          bottom: 12,
          child: Container(
            padding: const EdgeInsets.all(12),
            color: Colors.black87,
            child: Text(_caption, textAlign: TextAlign.center, style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w800)),
          ),
        ),
    ]);

    final panel = Container(
      color: DeepFitColors.panel,
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(_valueText(ex), style: const TextStyle(fontSize: 46, fontWeight: FontWeight.w900, color: DeepFitColors.cyan)),
          const SizedBox(width: 6),
          Padding(padding: const EdgeInsets.only(bottom: 10), child: Text(ex.unit, style: const TextStyle(color: DeepFitColors.muted))),
          const Spacer(),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(timerText, style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w800)),
            Text(dur == null ? 'elapsed' : 'left', style: const TextStyle(color: DeepFitColors.muted, fontSize: 12)),
          ]),
        ]),
        if (dur != null)
          LinearProgressIndicator(value: running ? (t / dur).clamp(0, 1).toDouble() : 0.0, minHeight: 4),
        const SizedBox(height: 8),
        Semantics(
          liveRegion: true,
          child: Text(
            _phase == _Phase.ready ? 'Get into position, then start.' : ex.feedback,
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: _deaf ? 22 : 17, fontWeight: FontWeight.w600),
          ),
        ),
        if (ex is CoachabilityChallenge) _CoachPanel(ex: ex),
        if (ex is GrowthMeasures && running) _GrowthPanel(ex: ex),
        if (_mirrorSeen || _blind) _meter(ex),
        const SizedBox(height: 10),
        _mainButton(),
      ]),
    );

    final scaffold = PopScope(
      // while a test runs, "back" must not throw the recording away - use Stop & save
      canPop: _phase != _Phase.running && _phase != _Phase.finishing,
      child: Scaffold(
        backgroundColor: Colors.black,
        body: SafeArea(child: Column(children: [Expanded(child: body), panel])),
      ),
    );
    if (!_blind) return scaffold;
    // blind mode: double tap anywhere starts / stops
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onDoubleTap: () {
        if (_phase == _Phase.ready) {
          _start();
        } else if (_phase == _Phase.running) {
          _finish();
        }
      },
      child: scaffold,
    );
  }

  Widget _meter(Exercise ex) {
    final v = ex.mirrorValue;
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Row(children: [
        const Text('Form', style: TextStyle(color: DeepFitColors.muted)),
        const SizedBox(width: 8),
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: LinearProgressIndicator(
              value: v ?? 0.0,
              minHeight: 12,
              color: (v ?? 0) >= 0.95 ? DeepFitColors.green : DeepFitColors.cyan,
            ),
          ),
        ),
        IconButton(
          tooltip: 'Audio mirror',
          onPressed: () {
            setState(() => _mirrorOn = !_mirrorOn);
            if (!_mirrorOn) _tones.silence();
            _say(_mirrorOn ? 'Audio mirror on. ${ex.mirrorLabel}' : 'Audio mirror off', interrupt: true);
          },
          icon: Icon(_mirrorOn ? Icons.volume_up : Icons.volume_off),
        ),
      ]),
    );
  }

  Widget _mainButton() {
    final h = _blind ? 84.0 : 54.0;
    switch (_phase) {
      case _Phase.ready:
        return SizedBox(
          width: double.infinity,
          height: h,
          child: FilledButton(onPressed: _start, child: Text('Start', style: TextStyle(fontSize: _blind ? 28 : 18))),
        );
      case _Phase.running:
        return SizedBox(
          width: double.infinity,
          height: h,
          child: FilledButton(
            style: FilledButton.styleFrom(backgroundColor: DeepFitColors.red),
            onPressed: () => _finish(),
            child: Text('Stop & save', style: TextStyle(fontSize: _blind ? 28 : 18)),
          ),
        );
      case _Phase.failed:
        return SizedBox(
          width: double.infinity,
          height: h,
          child: OutlinedButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Back')),
        );
      default:
        return SizedBox(height: h, child: const Center(child: CircularProgressIndicator()));
    }
  }

  String _valueText(Exercise ex) {
    if (ex is CoachabilityChallenge) return ex.value().round().toString();
    if (ex is Plank || ex is PlateTapping || ex is SitAndReach) return ex.value().toStringAsFixed(1);
    if (ex is GrowthMeasures) return ex.measure == null ? '—' : ex.value().toStringAsFixed(1);
    final v = ex.value();
    return v == v.roundToDouble() ? v.toInt().toString() : v.toStringAsFixed(1);
  }

  static String _fmtClock(double s) {
    final total = s.floor();
    final m = total ~/ 60, sec = total % 60;
    return '$m:${sec.toString().padLeft(2, '0')}';
  }
}

class _Badge extends StatelessWidget {
  final String text;
  final Color? color;
  const _Badge({required this.text, this.color});
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: Colors.black54,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: color ?? Colors.white24),
        ),
        child: Text(text, style: TextStyle(color: color ?? Colors.white, fontWeight: FontWeight.w700, fontSize: 13)),
      );
}

/// The 5-move pattern as numbered cards; the steps done so far light up.
class _CoachPanel extends StatelessWidget {
  final CoachabilityChallenge ex;
  const _CoachPanel({required this.ex});

  @override
  Widget build(BuildContext context) {
    final doneMoves = ex.phase == 'perform' ? ex.done.map((d) => d.$1).toList() : const <String>[];
    final last = ex.triesDone.isEmpty ? null : ex.triesDone.last;
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Column(children: [
        Text('Pattern ${ex.code} · try ${ex.currentTry == 0 ? 1 : ex.currentTry} of $tries · ${ex.phase}',
            style: const TextStyle(color: DeepFitColors.muted, fontSize: 12)),
        const SizedBox(height: 6),
        Row(children: [
          for (var i = 0; i < ex.pattern.length; i++)
            Expanded(
              child: Container(
                margin: const EdgeInsets.symmetric(horizontal: 2),
                padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 2),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(8),
                  color: i < doneMoves.length
                      ? (doneMoves[i] == ex.pattern[i] ? DeepFitColors.green.withAlpha(90) : DeepFitColors.red.withAlpha(90))
                      : Colors.white10,
                  border: Border.all(color: Colors.white24),
                ),
                child: Column(children: [
                  Text('${i + 1}', style: const TextStyle(fontWeight: FontWeight.w900)),
                  Text(moveLabel(ex.pattern[i]), textAlign: TextAlign.center, style: const TextStyle(fontSize: 10)),
                ]),
              ),
            ),
        ]),
        if (last != null)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text('Try ${last.tryNo}: ${fmtG(last.errors)} errors · ${last.tip}',
                textAlign: TextAlign.center, style: const TextStyle(color: DeepFitColors.amber, fontSize: 13)),
          ),
      ]),
    );
  }
}

class _GrowthPanel extends StatelessWidget {
  final GrowthMeasures ex;
  const _GrowthPanel({required this.ex});
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 8),
        child: Text(ex.phase == 'stand' ? 'STAND' : (ex.phase == 'sit' ? 'SIT' : 'DONE'),
            style: const TextStyle(fontSize: 34, fontWeight: FontWeight.w900, letterSpacing: 4)),
      );
}
