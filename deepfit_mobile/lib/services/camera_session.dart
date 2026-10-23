// Opens the camera, streams frames through body tracking and can grab a frame as a
// JPEG (registration photo, face checks). One per screen.

import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;

import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart';

import 'vision.dart';

class CameraSession {
  CameraController? controller;
  CameraDescription? description;
  final PoseVision vision;
  final bool detectPose;
  void Function(VisionFrame frame)? onFrame;
  Completer<RawFrame?>? _grab;
  bool _busy = false;
  bool _closed = false;
  String? error;

  CameraSession({required this.detectPose, bool mirroredStream = false})
      : vision = PoseVision(mirroredStream: mirroredStream);

  bool get ready => controller?.value.isInitialized == true && !_closed;

  Future<bool> open({required bool front}) async {
    try {
      final cams = await availableCameras();
      if (cams.isEmpty) {
        error = 'No camera found on this phone.';
        return false;
      }
      final want = front ? CameraLensDirection.front : CameraLensDirection.back;
      description = cams.firstWhere((c) => c.lensDirection == want, orElse: () => cams.first);
      final c = CameraController(description!, ResolutionPreset.medium,
          enableAudio: false,
          imageFormatGroup: Platform.isAndroid ? ImageFormatGroup.nv21 : ImageFormatGroup.bgra8888);
      controller = c;
      await c.initialize();
      if (_closed) return false;
      await c.startImageStream(_onImage);
      return true;
    } on CameraException catch (e) {
      error = (e.code == 'CameraAccessDenied' || e.code == 'CameraAccessDeniedWithoutPrompt')
          ? 'Camera permission is off. Allow the camera for DeepFit in your phone settings.'
          : 'Camera error: ${e.description ?? e.code}';
      return false;
    } catch (e) {
      error = 'Camera error: $e';
      return false;
    }
  }

  bool get front => description?.lensDirection == CameraLensDirection.front;

  Future<void> _onImage(CameraImage image) async {
    final grab = _grab;
    if (grab != null && !grab.isCompleted && description != null) {
      _grab = null;
      grab.complete(vision.copyFrame(image, description!)); // copy now: the buffer is reused
    }
    if (!detectPose || _busy || _closed || description == null) return;
    _busy = true;
    try {
      final f = await vision.process(image, description!);
      if (f != null && !_closed) onFrame?.call(f);
    } catch (e) {
      debugPrint('pose error: $e');
    } finally {
      _busy = false;
    }
  }

  /// The next camera frame as a base64 JPEG (upright, max 640 px), or null.
  Future<String?> grabJpegBase64({Duration timeout = const Duration(seconds: 3)}) async {
    if (!ready) return null;
    final c = Completer<RawFrame?>();
    _grab = c;
    final raw = await c.future.timeout(timeout, onTimeout: () => null);
    if (raw == null) return null;
    final bytes = await compute(encodeJpegFrame, raw);
    return base64Encode(bytes);
  }

  Future<void> close() async {
    if (_closed) return;
    _closed = true;
    final c = controller;
    controller = null;
    try {
      if (c != null && c.value.isStreamingImages) await c.stopImageStream();
    } catch (_) {}
    try {
      await c?.dispose();
    } catch (_) {}
    try {
      await vision.close();
    } catch (_) {}
  }
}
