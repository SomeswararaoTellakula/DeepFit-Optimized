import 'dart:async';
import 'dart:io' show Platform;

import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart' show defaultTargetPlatform, TargetPlatform;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:geolocator/geolocator.dart';
import 'package:sensors_plus/sensors_plus.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../app.dart';
import '../engine/registry.dart' show evaluateBenchmark;
import '../engine/run_track.dart';
import '../services/api.dart';
import '../services/app_state.dart';
import '../services/camera_session.dart';
import '../services/outbox.dart';
import '../services/speech.dart';
import '../widgets/common.dart';
import 'result_screen.dart';

/// 600 m Run/Walk timed by the phone the athlete carries: GPS for distance + the motion sensor for
/// steps. Nobody presses Stop or types a time. The face is checked at the start and again within 30 s
/// of the finish. The raw track goes to the server, which recomputes the time (run_check.py) and
/// flags anything that doesn't look like a person running (car, bike, fake GPS, wrong face).
class GpsRunScreen extends StatefulWidget {
  final TestInfo info;
  final double targetM;
  const GpsRunScreen({super.key, required this.info, this.targetM = 600});
  @override
  State<GpsRunScreen> createState() => _GpsRunScreenState();
}

enum _Phase { face, gps, countdown, running, finishFace, saving }

class _GpsRunScreenState extends State<GpsRunScreen> {
  late final AppState _state;
  final _speech = Speech();
  CameraSession? _cam;
  _Phase _phase = _Phase.face;
  bool _checking = false;
  String? _msg;
  String? _startSnap, _precheckToken;

  StreamSubscription<Position>? _gpsSub;
  StreamSubscription<UserAccelerometerEvent>? _accSub;
  Timer? _ticker;
  double? _accuracy;
  int _goodFixes = 0;
  DateTime? _t0;
  final List<GpsFix> _fixes = [];
  final _steps = StepDetector();
  double _distance = 0;
  double? _finishT; // seconds since Go when the phone counted 600 m
  int _nextCall = 100;
  int _count = 0;
  bool _mocked = false;

  @override
  void initState() {
    super.initState();
    _state = AppScope.read(context);
    _speech.init();
    WakelockPlus.enable();
    if (_state.requireFace) {
      _openCamera();
    } else {
      _phase = _Phase.gps;
      _startGps();
    }
  }

  @override
  void dispose() {
    _gpsSub?.cancel();
    _accSub?.cancel();
    _ticker?.cancel();
    _cam?.close();
    _speech.stop();
    WakelockPlus.disable();
    super.dispose();
  }

  double get _now => _t0 == null ? 0 : DateTime.now().difference(_t0!).inMilliseconds / 1000;

  // ------------------------------------------------------------------ face (start and finish)
  Future<void> _openCamera() async {
    final cam = CameraSession(detectPose: false);
    _cam = cam;
    final ok = await cam.open(front: true);
    if (!mounted) return;
    setState(() => _msg = ok ? 'Look at the camera, then press "Check face".' : cam.error);
  }

  Future<void> _checkStartFace() async {
    final cam = _cam;
    if (cam == null || _checking) return;
    setState(() => _checking = true);
    final jpg = await cam.grabJpegBase64();
    if (!mounted) return;
    if (jpg == null) {
      setState(() {
        _checking = false;
        _msg = 'Could not read the camera - try again.';
      });
      return;
    }
    try {
      final r = await _state.api.post('/identity/verify', {'frame': jpg}, timeout: const Duration(seconds: 10));
      if (r['is_match'] == true) {
        _startSnap = jpg;
        _precheckToken = r['precheck_token'] as String?;
        _msg = 'Verified ✓';
      } else {
        _msg = '✗ ${r['message'] ?? 'Face does not match the registered athlete'}';
      }
    } on ApiException catch (e) {
      if (e.offline) {
        _startSnap = jpg; // checked by the server at upload
        _msg = 'Offline - the face is checked when you sync';
      } else {
        _msg = '✗ ${e.message}';
      }
    }
    if (_startSnap != null) {
      await cam.close();
      _cam = null;
      _phase = _Phase.gps;
      _startGps();
    }
    if (mounted) setState(() => _checking = false);
  }

  Future<void> _takeFinishPhoto() async {
    final cam = _cam;
    if (cam == null || _checking) return;
    setState(() => _checking = true);
    final jpg = await cam.grabJpegBase64();
    final t = _now;
    if (!mounted) return;
    if (jpg == null) {
      setState(() {
        _checking = false;
        _msg = 'Could not read the camera - try again quickly.';
      });
      return;
    }
    await _stopSensors();
    await cam.close();
    _cam = null;
    await _save(finishJpg: jpg, finishFaceT: t);
  }

  // ------------------------------------------------------------------ GPS + steps
  Future<void> _startGps() async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      setState(() => _msg = 'Turn on Location (GPS) in the phone settings, then come back.');
      return;
    }
    var perm = await Geolocator.checkPermission();
    if (perm == LocationPermission.denied) perm = await Geolocator.requestPermission();
    if (perm == LocationPermission.denied || perm == LocationPermission.deniedForever) {
      setState(() => _msg = 'DeepFit needs Location permission to measure the run. You can still use the coach stopwatch.');
      return;
    }
    final LocationSettings settings = defaultTargetPlatform == TargetPlatform.android
        ? AndroidSettings(accuracy: LocationAccuracy.best, distanceFilter: 0, intervalDuration: const Duration(seconds: 1))
        : AppleSettings(
            accuracy: LocationAccuracy.best,
            activityType: ActivityType.fitness,
            distanceFilter: 0,
            pauseLocationUpdatesAutomatically: false);
    _gpsSub = Geolocator.getPositionStream(locationSettings: settings).listen(_onFix, onError: (e) {
      if (mounted) setState(() => _msg = 'GPS error: $e');
    });
    setState(() => _msg = 'Waiting for a good GPS signal - stand in the open, away from buildings and trees.');
  }

  void _onFix(Position p) {
    _accuracy = p.accuracy;
    if (p.isMocked) _mocked = true;
    if (_phase == _Phase.gps) {
      _goodFixes = p.accuracy <= 15 ? _goodFixes + 1 : 0;
      setState(() {});
      return;
    }
    if (_phase != _Phase.running && _phase != _Phase.finishFace) return;
    _fixes.add(GpsFix(_now, p.latitude, p.longitude, p.accuracy, spd: p.speed >= 0 ? p.speed : null, mocked: p.isMocked));
    if (_phase != _Phase.running) return;
    final track = distanceTrack(cleanPoints(_fixes));
    _distance = track.isEmpty ? 0 : track.last[1];
    if (_distance >= _nextCall && _nextCall < widget.targetM) {
      _speech.say('$_nextCall metres', interrupt: true);
      _nextCall += 100;
    }
    if (_distance >= widget.targetM) {
      _finishT = crossingTime(track, widget.targetM) ?? _now;
      _finish();
    }
    if (mounted) setState(() {});
  }

  Future<void> _go() async {
    setState(() => _phase = _Phase.countdown);
    for (var s = 3; s > 0; s--) {
      if (!mounted) return;
      setState(() => _count = s);
      _speech.say('$s', interrupt: true);
      await Future.delayed(const Duration(seconds: 1));
    }
    if (!mounted) return;
    HapticFeedback.heavyImpact();
    _speech.say('Go!', interrupt: true);
    _t0 = DateTime.now();
    _fixes.clear();
    _accSub = userAccelerometerEventStream(samplingPeriod: SensorInterval.gameInterval)
        .listen((e) => _steps.add(_now, e.x, e.y, e.z));
    _ticker = Timer.periodic(const Duration(milliseconds: 200), (_) {
      if (mounted) setState(() {});
    });
    setState(() => _phase = _Phase.running);
  }

  Future<void> _finish() async {
    _ticker?.cancel();
    HapticFeedback.heavyImpact();
    _speech.say('Finish! Hold the phone up to your face for the photo.', interrupt: true);
    setState(() {
      _phase = _Phase.finishFace;
      _msg = 'Photo within 30 seconds - look at the camera.';
    });
    // GPS keeps recording a few more seconds (the server needs fixes just after the finish line)
    if (_state.requireFace) {
      await _openCamera();
      if (mounted) setState(() => _msg = 'Finish photo within 30 seconds - look at the camera.');
    } else {
      await Future.delayed(const Duration(seconds: 4));
      await _stopSensors();
      await _save();
    }
  }

  Future<void> _stopSensors() async {
    await _gpsSub?.cancel();
    await _accSub?.cancel();
    _gpsSub = null;
    _accSub = null;
  }

  Future<void> _abandon() async {
    await _stopSensors();
    if (mounted) Navigator.of(context).pop();
  }

  // ------------------------------------------------------------------ save (the server recomputes)
  Future<void> _save({String? finishJpg, double? finishFaceT}) async {
    setState(() => _phase = _Phase.saving);
    final secs = _finishT ?? _now;
    final id = Outbox.newId();
    final body = <String, dynamic>{
      'client_id': id,
      'exercise': widget.info.key,
      'mode': _state.mode,
      'height_cm': _state.heightCm,
      'captured_at': DateTime.now().toUtc().toIso8601String(),
      'gps_run': {
        'target_m': widget.targetM,
        'points': [for (final f in _fixes) f.toJson()],
        'steps': _steps.steps,
        'finish_face_t': finishFaceT,
        'phone_time': double.parse(secs.toStringAsFixed(2)),
      },
      'snapshots': [
        if (_startSnap != null) {'t': 0.0, 'jpg': _startSnap},
        if (finishJpg != null) {'t': finishFaceT, 'jpg': finishJpg},
      ],
      'precheck_token': _precheckToken,
      'client_result': {'value': double.parse(secs.toStringAsFixed(2))},
      'device': {'platform': Platform.operatingSystem, 'app': appVersion},
    };
    final local = <String, dynamic>{
      'value': double.parse(secs.toStringAsFixed(1)),
      'unit': 's',
      'timing': 'gps',
      'coach_timed': false,
      'benchmark': evaluateBenchmark(secs, widget.info.targetFor(_state.mode)),
    };
    await _state.addToOutbox(OutboxItem(
        id: id, kind: 'result', exercise: widget.info.key, name: widget.info.name, created: DateTime.now(), body: body, local: local));
    if (!mounted) return;
    Navigator.of(context).pushReplacement(MaterialPageRoute(
        builder: (_) => ResultScreen(info: widget.info, mode: _state.mode, outboxId: id, local: local)));
  }

  // ------------------------------------------------------------------ UI
  String _clock(double s) => '${(s ~/ 60)}:${(s % 60).toStringAsFixed(1).padLeft(4, '0')}';

  @override
  Widget build(BuildContext context) {
    final controller = _cam?.controller;
    final big = _state.mode == 'blind' || _state.mode == 'deaf';
    return Scaffold(
      appBar: AppBar(title: Text('${widget.info.name} - phone GPS')),
      body: SafeArea(
        child: ListView(padding: const EdgeInsets.all(16), children: [
          if (_phase == _Phase.face || _phase == _Phase.finishFace) ...[
            SectionTitle(_phase == _Phase.face ? '1. Face check' : 'Finish photo'),
            Panel(
              child: Column(children: [
                if (controller != null && controller.value.isInitialized)
                  SizedBox(height: 300, child: Center(child: CameraPreview(controller))),
                if (_msg != null) Padding(padding: const EdgeInsets.all(8), child: Text(_msg!, textAlign: TextAlign.center)),
                if (_phase == _Phase.finishFace && _finishT != null)
                  Text('Time ${_clock(_finishT!)}', style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w900)),
                FilledButton.icon(
                  onPressed: _checking ? null : (_phase == _Phase.face ? _checkStartFace : _takeFinishPhoto),
                  icon: const Icon(Icons.face),
                  label: Text(_checking ? 'Checking…' : (_phase == _Phase.face ? 'Check face' : 'Take finish photo')),
                ),
              ]),
            ),
          ],
          if (_phase == _Phase.gps) ...[
            const SectionTitle('2. GPS'),
            Panel(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(_msg ?? ''),
                const SizedBox(height: 8),
                Text(_accuracy == null ? 'No GPS fix yet…' : 'GPS accuracy: ±${_accuracy!.toStringAsFixed(0)} m',
                    style: TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.w800,
                        color: (_accuracy ?? 99) <= 15 ? DeepFitColors.green : DeepFitColors.muted)),
                const SizedBox(height: 8),
                const Text('Carry the phone in a pocket or armband (screen stays on). Run outdoors. '
                    'The phone stops by itself at 600 m - nobody presses Stop.',
                    style: TextStyle(color: DeepFitColors.muted)),
                if (_mocked)
                  const Text('⚠ A fake-location app is active - the result will be flagged.',
                      style: TextStyle(color: DeepFitColors.red)),
              ]),
            ),
            SizedBox(
              height: 72,
              child: FilledButton(
                onPressed: _goodFixes >= 3 ? _go : null,
                child: Text(_goodFixes >= 3 ? 'Ready - start the countdown' : 'Waiting for GPS…',
                    style: const TextStyle(fontSize: 20)),
              ),
            ),
          ],
          if (_phase == _Phase.countdown)
            Center(child: Text('$_count', style: const TextStyle(fontSize: 160, fontWeight: FontWeight.w900))),
          if (_phase == _Phase.running) ...[
            Panel(
              child: Column(children: [
                Text('${_distance.clamp(0, widget.targetM).toStringAsFixed(0)} m',
                    style: TextStyle(fontSize: big ? 96 : 72, fontWeight: FontWeight.w900)),
                LinearProgressIndicator(value: (_distance / widget.targetM).clamp(0.0, 1.0), minHeight: 14),
                const SizedBox(height: 12),
                Text(_clock(_now), style: const TextStyle(fontSize: 40, fontWeight: FontWeight.w800)),
                Text('${_steps.steps.length} steps · GPS ±${(_accuracy ?? 0).toStringAsFixed(0)} m',
                    style: const TextStyle(color: DeepFitColors.muted)),
              ]),
            ),
            const SizedBox(height: 24),
            // long press only: a phone in a pocket must not stop the run by accident
            OutlinedButton(
              onPressed: null,
              onLongPress: _abandon,
              child: const Text('Hold to cancel the run'),
            ),
          ],
          if (_phase == _Phase.saving) const Center(child: Padding(padding: EdgeInsets.all(32), child: CircularProgressIndicator())),
        ]),
      ),
    );
  }
}
