import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

import '../app.dart';
import '../engine/pose.dart' show L;
import '../services/app_state.dart';
import '../services/camera_session.dart';
import '../services/speech.dart';
import '../services/vision.dart';
import '../widgets/pose_painter.dart';

/// 10-second check: "raise your LEFT hand". Some phones deliver the selfie camera
/// mirrored, which would swap left and right in the Coachability Challenge.
class LrCheckScreen extends StatefulWidget {
  const LrCheckScreen({super.key});
  @override
  State<LrCheckScreen> createState() => _LrCheckScreenState();
}

class _LrCheckScreenState extends State<LrCheckScreen> {
  late final AppState _state;
  late final CameraSession _cam;
  final _speech = Speech();
  VisionFrame? _frame;
  int _leftUp = 0, _rightUp = 0;
  String _msg = 'Stand 2 m away facing the phone, then raise your LEFT hand above your head.';
  bool _done = false;

  @override
  void initState() {
    super.initState();
    _state = AppScope.read(context);
    _cam = CameraSession(detectPose: true, mirroredStream: _state.mirroredStream(true));
    _cam.onFrame = _onFrame;
    _cam.open(front: true).then((ok) {
      if (!mounted) return;
      setState(() => _msg = ok ? _msg : (_cam.error ?? 'Camera unavailable'));
      if (ok) _speech.say('Stand facing the phone and raise your left hand above your head.');
    });
  }

  @override
  void dispose() {
    _cam.close();
    _speech.stop();
    super.dispose();
  }

  void _onFrame(VisionFrame f) {
    if (!mounted || _done) return;
    _frame = f;
    final lm = f.canonical;
    if (lm != null && lm[L.nose][2] > 0.5 && lm[L.lWrist][2] > 0.5 && lm[L.rWrist][2] > 0.5) {
      final nose = lm[L.nose][1];
      final leftUp = lm[L.lWrist][1] < nose && lm[L.rWrist][1] > nose;
      final rightUp = lm[L.rWrist][1] < nose && lm[L.lWrist][1] > nose;
      _leftUp = leftUp ? _leftUp + 1 : 0;
      _rightUp = rightUp ? _rightUp + 1 : 0;
      if (_leftUp >= 10) {
        _finish(swap: _state.mirroredStream(true));
      } else if (_rightUp >= 10) {
        _finish(swap: !_state.mirroredStream(true));
      }
    }
    setState(() {});
  }

  Future<void> _finish({required bool swap}) async {
    _done = true;
    final changed = swap != _state.mirroredStream(true);
    await _state.setLrSwap(swap);
    _msg = changed
        ? '✓ Fixed: this phone\'s selfie camera is mirrored, left and right are now corrected.'
        : '✓ Left and right are correct on this phone.';
    _speech.say(changed ? 'Fixed. Left and right are now correct.' : 'Left and right are correct.');
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final c = _cam.controller;
    return Scaffold(
      appBar: AppBar(title: const Text('Left / right check')),
      body: SafeArea(
        child: Column(children: [
          Expanded(
            child: c != null && c.value.isInitialized
                ? Center(child: CameraPreview(c, child: CustomPaint(painter: PosePainter(_frame?.display, _frame?.likelihood))))
                : const Center(child: CircularProgressIndicator()),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(children: [
              Text(_msg, textAlign: TextAlign.center, style: const TextStyle(fontSize: 18)),
              const SizedBox(height: 12),
              if (_done)
                FilledButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Done'))
              else
                TextButton(
                  onPressed: () async {
                    await _state.setLrSwap(null);
                    if (context.mounted) Navigator.of(context).pop();
                  },
                  child: const Text('Skip (use automatic)', style: TextStyle(color: DeepFitColors.muted)),
                ),
            ]),
          ),
        ]),
      ),
    );
  }
}
