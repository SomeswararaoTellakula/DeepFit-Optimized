import 'dart:async';
import 'dart:io' show Platform;

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../app.dart';
import '../engine/registry.dart' show evaluateBenchmark;
import '../services/api.dart';
import '../services/app_state.dart';
import '../services/camera_session.dart';
import '../services/outbox.dart';
import '../services/speech.dart';
import '../widgets/common.dart';
import 'result_screen.dart';

/// Coach-timed tests (50 m dash, 600 m run): face check of the athlete, then a stopwatch.
class StopwatchScreen extends StatefulWidget {
  final TestInfo info;
  const StopwatchScreen({super.key, required this.info});
  @override
  State<StopwatchScreen> createState() => _StopwatchScreenState();
}

class _StopwatchScreenState extends State<StopwatchScreen> {
  late final AppState _state;
  CameraSession? _cam;
  final _speech = Speech();
  final _watch = Stopwatch();
  final _manual = TextEditingController();
  Timer? _ticker;
  bool _verified = false;
  bool _checking = false;
  String? _faceMsg;
  String? _snap;
  String? _precheckToken;

  @override
  void initState() {
    super.initState();
    _state = AppScope.read(context);
    WakelockPlus.enable();
    _verified = !_state.requireFace;
    if (!_verified) _openCamera();
  }

  Future<void> _openCamera() async {
    final cam = CameraSession(detectPose: false);
    _cam = cam;
    final ok = await cam.open(front: true);
    if (!mounted) return;
    setState(() => _faceMsg = ok ? 'The athlete looks at the camera, then press "Check face".' : cam.error);
  }

  @override
  void dispose() {
    _ticker?.cancel();
    _cam?.close();
    _manual.dispose();
    _speech.stop();
    WakelockPlus.disable();
    super.dispose();
  }

  Future<void> _checkFace() async {
    final cam = _cam;
    if (cam == null || _checking) return;
    setState(() => _checking = true);
    final jpg = await cam.grabJpegBase64();
    if (!mounted) return;
    if (jpg == null) {
      setState(() {
        _checking = false;
        _faceMsg = 'Could not read the camera - try again.';
      });
      return;
    }
    try {
      final r = await _state.api.post('/identity/verify', {'frame': jpg}, timeout: const Duration(seconds: 10));
      if (r['is_match'] == true) {
        _snap = jpg;
        _precheckToken = r['precheck_token'] as String?;
        _verified = true;
        _faceMsg = 'Verified ✓';
        await cam.close();
        _cam = null;
      } else {
        _faceMsg = '✗ ${r['message'] ?? 'Face does not match the registered athlete'}';
      }
    } on ApiException catch (e) {
      if (e.offline) {
        _snap = jpg; // checked by the server when the result is uploaded
        _verified = true;
        _faceMsg = 'Offline - the face is checked when you sync';
        await cam.close();
        _cam = null;
      } else {
        _faceMsg = '✗ ${e.message}';
      }
    }
    if (mounted) setState(() => _checking = false);
  }

  void _startStop() {
    HapticFeedback.mediumImpact();
    if (_watch.isRunning) {
      _watch.stop();
      _ticker?.cancel();
      _manual.text = (_watch.elapsedMilliseconds / 1000).toStringAsFixed(2);
    } else {
      _watch
        ..reset()
        ..start();
      _speech.say('Go!', interrupt: true);
      _ticker = Timer.periodic(const Duration(milliseconds: 50), (_) {
        if (mounted) setState(() {});
      });
    }
    setState(() {});
  }

  Future<void> _save() async {
    final v = double.tryParse(_manual.text.trim().replaceAll(',', '.'));
    if (v == null || v < 1 || v > 3600) {
      toast(context, 'Enter a time between 1 and 3600 seconds.');
      return;
    }
    final id = Outbox.newId();
    final body = <String, dynamic>{
      'client_id': id,
      'exercise': widget.info.key,
      'mode': _state.mode,
      'manual_value': v,
      'captured_at': DateTime.now().toUtc().toIso8601String(),
      'snapshots': [
        if (_snap != null) {'t': 0.0, 'jpg': _snap}
      ],
      'precheck_token': _precheckToken,
      'client_result': {'value': v},
      'device': {'platform': Platform.operatingSystem, 'app': appVersion},
    };
    final local = <String, dynamic>{
      'value': v,
      'unit': 's',
      'coach_timed': true,
      'benchmark': evaluateBenchmark(v, widget.info.targetFor(_state.mode)),
    };
    await _state.addToOutbox(OutboxItem(
        id: id, kind: 'result', exercise: widget.info.key, name: widget.info.name, created: DateTime.now(), body: body, local: local));
    if (!mounted) return;
    Navigator.of(context).pushReplacement(MaterialPageRoute(
        builder: (_) => ResultScreen(info: widget.info, mode: _state.mode, outboxId: id, local: local)));
  }

  @override
  Widget build(BuildContext context) {
    final controller = _cam?.controller;
    final secs = _watch.elapsedMilliseconds / 1000;
    return Scaffold(
      appBar: AppBar(title: Text(widget.info.name)),
      body: SafeArea(
        child: ListView(padding: const EdgeInsets.all(16), children: [
          if (!_verified) ...[
            const SectionTitle('1. Face check'),
            Panel(
              child: Column(children: [
                if (controller != null && controller.value.isInitialized)
                  SizedBox(height: 300, child: Center(child: CameraPreview(controller))),
                if (_faceMsg != null) Padding(padding: const EdgeInsets.all(8), child: Text(_faceMsg!, textAlign: TextAlign.center)),
                FilledButton.icon(
                  onPressed: _checking ? null : _checkFace,
                  icon: const Icon(Icons.face),
                  label: Text(_checking ? 'Checking…' : 'Check face'),
                ),
              ]),
            ),
          ] else ...[
            Panel(child: Text(_faceMsg ?? 'Ready', style: const TextStyle(color: DeepFitColors.green))),
            const SectionTitle('2. Time the run'),
            Panel(
              child: Column(children: [
                Text(secs.toStringAsFixed(2),
                    style: const TextStyle(fontSize: 72, fontWeight: FontWeight.w900, fontFeatures: [FontFeature.tabularFigures()])),
                const Text('seconds', style: TextStyle(color: DeepFitColors.muted)),
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  height: 72,
                  child: FilledButton(
                    style: FilledButton.styleFrom(backgroundColor: _watch.isRunning ? DeepFitColors.red : DeepFitColors.green),
                    onPressed: _startStop,
                    child: Text(_watch.isRunning ? 'STOP' : 'START on "Go"', style: const TextStyle(fontSize: 24)),
                  ),
                ),
              ]),
            ),
            const SectionTitle('3. Result'),
            TextField(
              controller: _manual,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: deco('Time', suffix: 's', hint: 'or type the coach\'s time'),
            ),
            const SizedBox(height: 12),
            FilledButton(onPressed: _watch.isRunning ? null : _save, child: const Text('Save result')),
          ],
        ]),
      ),
    );
  }
}
