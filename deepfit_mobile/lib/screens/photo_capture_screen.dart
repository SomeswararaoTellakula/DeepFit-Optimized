import 'dart:async';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

import '../app.dart';
import '../services/camera_session.dart';
import '../services/speech.dart';
import '../widgets/common.dart';

/// Takes 1-3 sharp photos (optionally after a spoken self-timer) and returns them as base64 JPEGs.
/// Used for: the height sheets on the wall, the scale display, the number on a dumbbell.
class PhotoCaptureScreen extends StatefulWidget {
  final String title;
  final String hint;
  final int shots;
  final int timerSeconds; // 0 = take the photo on tap
  final bool front;
  const PhotoCaptureScreen(
      {super.key, required this.title, required this.hint, this.shots = 1, this.timerSeconds = 0, this.front = false});
  @override
  State<PhotoCaptureScreen> createState() => _PhotoCaptureScreenState();
}

class _PhotoCaptureScreenState extends State<PhotoCaptureScreen> {
  final _speech = Speech();
  CameraSession? _cam;
  late bool _front = widget.front;
  bool _opening = true;
  bool _busy = false;
  int? _count;
  String? _error;
  final _photos = <String>[];

  @override
  void initState() {
    super.initState();
    _speech.init();
    _open();
  }

  Future<void> _open() async {
    setState(() {
      _opening = true;
      _error = null;
    });
    await _cam?.close();
    final cam = CameraSession(detectPose: false, preset: ResolutionPreset.veryHigh);
    _cam = cam;
    final ok = await cam.open(front: _front);
    if (!mounted) return;
    setState(() {
      _opening = false;
      _error = ok ? null : cam.error;
    });
  }

  @override
  void dispose() {
    _speech.stop();
    _cam?.close();
    super.dispose();
  }

  Future<void> _shoot() async {
    final cam = _cam;
    if (cam == null || !cam.ready || _busy) return;
    setState(() => _busy = true);
    for (var s = widget.timerSeconds; s > 0; s--) {
      if (!mounted) return;
      setState(() => _count = s);
      if (s <= 5 || s == widget.timerSeconds) _speech.say('$s', interrupt: true);
      await Future.delayed(const Duration(seconds: 1));
    }
    if (!mounted) return;
    setState(() => _count = null);
    if (widget.timerSeconds > 0) _speech.say('Hold still', interrupt: true);
    _photos.clear();
    for (var i = 0; i < widget.shots; i++) {
      final b64 = await cam.grabJpegBase64(large: true, timeout: const Duration(seconds: 4));
      if (b64 != null) _photos.add(b64);
      if (i < widget.shots - 1) await Future.delayed(const Duration(milliseconds: 700));
    }
    if (!mounted) return;
    if (_photos.isEmpty) {
      setState(() => _busy = false);
      toast(context, 'No picture from the camera - try again.');
      return;
    }
    _speech.say('Done', interrupt: true);
    Navigator.of(context).pop(List<String>.from(_photos));
  }

  @override
  Widget build(BuildContext context) {
    final c = _cam?.controller;
    final ready = !_opening && _error == null && c != null && c.value.isInitialized;
    return Scaffold(
      appBar: AppBar(title: Text(widget.title), actions: [
        IconButton(
          tooltip: 'Switch camera',
          icon: const Icon(Icons.cameraswitch),
          onPressed: _busy
              ? null
              : () {
                  _front = !_front;
                  _open();
                },
        ),
      ]),
      body: SafeArea(
        child: Column(children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
            child: Text(widget.hint, style: const TextStyle(color: DeepFitColors.muted)),
          ),
          Expanded(
            child: Stack(alignment: Alignment.center, children: [
              if (ready)
                Center(child: AspectRatio(aspectRatio: 1 / c.value.aspectRatio, child: CameraPreview(c)))
              else if (_error != null)
                Padding(padding: const EdgeInsets.all(24), child: Text(_error!, textAlign: TextAlign.center))
              else
                const CircularProgressIndicator(),
              if (_count != null)
                Text('$_count',
                    style: const TextStyle(fontSize: 120, fontWeight: FontWeight.w900, color: Colors.white, shadows: [
                      Shadow(blurRadius: 24, color: Colors.black),
                    ])),
            ]),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: SizedBox(
              width: double.infinity,
              height: 64,
              child: FilledButton.icon(
                icon: Icon(widget.timerSeconds > 0 ? Icons.timer : Icons.photo_camera),
                label: Text(
                    _busy
                        ? (_count != null ? 'Get in place…' : 'Taking photo…')
                        : widget.timerSeconds > 0
                            ? 'Start ${widget.timerSeconds} s timer'
                            : 'Take photo',
                    style: const TextStyle(fontSize: 18)),
                onPressed: ready && !_busy ? _shoot : null,
              ),
            ),
          ),
        ]),
      ),
    );
  }
}
