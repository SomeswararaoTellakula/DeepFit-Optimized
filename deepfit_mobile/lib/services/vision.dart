// Camera frames -> body landmarks (Google ML Kit pose, 33 BlazePose points), plus
// copying a frame to a JPEG for the face check.
//
// Coordinates:
//   * "canonical" landmarks go to the engine and to the server: normalised 0..1 in the
//     UPRIGHT frame, as a real (not mirrored) camera sees the athlete, with left/right
//     labels meaning the athlete's own left/right - exactly like the website's webcam.
//   * "display" points are for drawing on top of the camera preview (which is mirrored
//     for the front camera).
//
// The app is locked to portrait, so Android frames need the sensor rotation and iOS
// frames arrive upright.

import 'dart:io' show Platform;
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' show Offset, Size;

import 'package:camera/camera.dart';
import 'package:google_mlkit_pose_detection/google_mlkit_pose_detection.dart';
import 'package:image/image.dart' as img;

import '../engine/pose.dart' show L;

class VisionFrame {
  final List<List<double>>? canonical; // 33 x [x, y, visibility] or null (nobody detected)
  final List<Offset>? display; // 33 points, 0..1 of the preview box
  final List<double>? likelihood;
  final double width, height; // upright frame size in pixels
  const VisionFrame(this.canonical, this.display, this.likelihood, this.width, this.height);
}

/// A copy of one camera frame that can be sent to a background isolate.
class RawFrame {
  final Uint8List bytes;
  final int width, height, bytesPerRow;
  final bool bgra; // iOS: BGRA8888, Android: NV21
  final int rotation; // clockwise degrees to make it upright
  const RawFrame(this.bytes, this.width, this.height, this.bytesPerRow, this.bgra, this.rotation);
}

class PoseVision {
  final PoseDetector _detector =
      PoseDetector(options: PoseDetectorOptions(mode: PoseDetectionMode.stream, model: PoseDetectionModel.base));
  bool mirroredStream; // frames come mirrored (iOS front camera): un-mirror + swap left/right
  bool _closed = false;

  PoseVision({this.mirroredStream = false});

  /// Clockwise rotation that makes a frame upright (portrait app).
  static int rotationFor(CameraDescription cam) {
    if (Platform.isIOS) return 0;
    return cam.sensorOrientation % 360; // portraitUp: no device-rotation compensation
  }

  /// The preview widget mirrors the front camera on Android (iOS preview = the stream).
  static bool previewMirrored(CameraDescription cam) =>
      Platform.isAndroid && cam.lensDirection == CameraLensDirection.front;

  static Uint8List _yuv420ToNv21(CameraImage image) {
    final w = image.width, h = image.height;
    final yP = image.planes[0], uP = image.planes[1], vP = image.planes[2];
    final out = Uint8List(w * h + 2 * (w ~/ 2) * (h ~/ 2));
    var o = 0;
    for (var row = 0; row < h; row++) {
      out.setRange(o, o + w, yP.bytes, row * yP.bytesPerRow);
      o += w;
    }
    final uStride = uP.bytesPerPixel ?? 1, vStride = vP.bytesPerPixel ?? 1;
    for (var row = 0; row < h ~/ 2; row++) {
      for (var col = 0; col < w ~/ 2; col++) {
        out[o++] = vP.bytes[row * vP.bytesPerRow + col * vStride];
        out[o++] = uP.bytes[row * uP.bytesPerRow + col * uStride];
      }
    }
    return out;
  }

  InputImage? _inputImage(CameraImage image, CameraDescription cam) {
    final rotation = InputImageRotationValue.fromRawValue(Platform.isIOS ? cam.sensorOrientation : rotationFor(cam));
    if (rotation == null) return null;
    if (Platform.isIOS) {
      if (image.planes.isEmpty) return null;
      final p = image.planes.first;
      return InputImage.fromBytes(
        bytes: p.bytes,
        metadata: InputImageMetadata(
            size: Size(image.width.toDouble(), image.height.toDouble()),
            rotation: rotation,
            format: InputImageFormat.bgra8888,
            bytesPerRow: p.bytesPerRow),
      );
    }
    // Android: ML Kit wants NV21 in one plane
    final Uint8List bytes;
    final int bytesPerRow;
    if (image.planes.length == 1) {
      bytes = image.planes.first.bytes;
      bytesPerRow = image.planes.first.bytesPerRow;
    } else if (image.planes.length == 3) {
      bytes = _yuv420ToNv21(image);
      bytesPerRow = image.width;
    } else {
      return null;
    }
    return InputImage.fromBytes(
      bytes: bytes,
      metadata: InputImageMetadata(
          size: Size(image.width.toDouble(), image.height.toDouble()),
          rotation: rotation,
          format: InputImageFormat.nv21,
          bytesPerRow: bytesPerRow),
    );
  }

  /// Upright frame size in pixels.
  static Size uprightSize(CameraImage image, CameraDescription cam) {
    final r = rotationFor(cam);
    return (r == 90 || r == 270)
        ? Size(image.height.toDouble(), image.width.toDouble())
        : Size(image.width.toDouble(), image.height.toDouble());
  }

  Future<VisionFrame?> process(CameraImage image, CameraDescription cam) async {
    if (_closed) return null;
    final input = _inputImage(image, cam);
    final size = uprightSize(image, cam);
    if (input == null) return VisionFrame(null, null, null, size.width, size.height);
    final poses = await _detector.processImage(input);
    if (poses.isEmpty) return VisionFrame(null, null, null, size.width, size.height);
    final lms = poses.first.landmarks;
    final raw = <List<double>>[];
    for (final type in PoseLandmarkType.values) {
      final p = lms[type];
      if (p == null) {
        raw.add([0.0, 0.0, 0.0]);
      } else {
        raw.add([p.x / size.width, p.y / size.height, p.likelihood]);
      }
    }
    if (raw.length != 33) return VisionFrame(null, null, null, size.width, size.height);
    final mirrorPreview = previewMirrored(cam);
    final display = [for (final p in raw) Offset(mirrorPreview ? 1 - p[0] : p[0], p[1])];
    final likelihood = [for (final p in raw) p[2]];
    // canonical: un-mirror a mirrored stream, round like the upload
    final canonical = List<List<double>>.generate(33, (i) {
      final src = mirroredStream ? raw[L.mirrorPartner[i]] : raw[i];
      final x = mirroredStream ? 1 - src[0] : src[0];
      return [_r(x, 4), _r(src[1], 4), _r(src[2], 3)];
    });
    return VisionFrame(canonical, display, likelihood, size.width, size.height);
  }

  /// Engine x (canonical, 0..1) -> x on the preview (0..1), for drawing engine targets.
  double displayX(double canonicalX, CameraDescription cam) {
    final raw = mirroredStream ? 1 - canonicalX : canonicalX;
    return previewMirrored(cam) ? 1 - raw : raw;
  }

  RawFrame? copyFrame(CameraImage image, CameraDescription cam) {
    final rot = rotationFor(cam);
    if (image.format.group == ImageFormatGroup.bgra8888 && image.planes.isNotEmpty) {
      final p = image.planes.first;
      return RawFrame(Uint8List.fromList(p.bytes), image.width, image.height, p.bytesPerRow, true, rot);
    }
    if (image.planes.length == 1) {
      final p = image.planes.first;
      return RawFrame(Uint8List.fromList(p.bytes), image.width, image.height, p.bytesPerRow, false, rot);
    }
    if (image.planes.length == 3) {
      return RawFrame(_yuv420ToNv21(image), image.width, image.height, image.width, false, rot);
    }
    return null;
  }

  Future<void> close() async {
    if (_closed) return;
    _closed = true;
    await _detector.close();
  }

  static double _r(double v, int n) {
    final m = math.pow(10, n).toDouble();
    return (v * m).roundToDouble() / m;
  }
}

int _byte(int v) => v < 0 ? 0 : (v > 255 ? 255 : v);

/// Runs in a background isolate: camera frame -> upright JPEG (max 640 px) for the face check.
/// Small JPEG (max 640 px) for face checks and snapshots.
Uint8List encodeJpegFrame(RawFrame f) => _encodeJpeg(f, 640, 80);

/// Sharp JPEG (max 1920 px) for measuring photos: height sheets, scale display, dumbbell number.
Uint8List encodeJpegFrameLarge(RawFrame f) => _encodeJpeg(f, 1920, 90);

Uint8List _encodeJpeg(RawFrame f, int maxSide, int quality) {
  final w = f.width, h = f.height;
  final rgb = Uint8List(w * h * 3);
  final b = f.bytes;
  var o = 0;
  if (f.bgra) {
    for (var y = 0; y < h; y++) {
      var i = y * f.bytesPerRow;
      for (var x = 0; x < w; x++) {
        rgb[o++] = b[i + 2];
        rgb[o++] = b[i + 1];
        rgb[o++] = b[i];
        i += 4;
      }
    }
  } else {
    var stride = f.bytesPerRow;
    if (b.length < stride * h + stride * (h ~/ 2)) stride = w; // tightly packed
    final ySize = stride * h;
    for (var y = 0; y < h; y++) {
      final yRow = y * stride, uvRow = ySize + (y >> 1) * stride;
      for (var x = 0; x < w; x++) {
        final yy = b[yRow + x];
        final uvi = uvRow + (x & ~1);
        final v = (uvi < b.length ? b[uvi] : 128) - 128;
        final u = (uvi + 1 < b.length ? b[uvi + 1] : 128) - 128;
        rgb[o++] = _byte((yy + 1.370705 * v).round());
        rgb[o++] = _byte((yy - 0.337633 * u - 0.698001 * v).round());
        rgb[o++] = _byte((yy + 1.732446 * u).round());
      }
    }
  }
  var im = img.Image.fromBytes(width: w, height: h, bytes: rgb.buffer, numChannels: 3);
  if (f.rotation != 0) im = img.copyRotate(im, angle: f.rotation);
  final longSide = math.max(im.width, im.height);
  if (longSide > maxSide) im = img.copyResize(im, width: (im.width * maxSide / longSide).round());
  return Uint8List.fromList(img.encodeJpg(im, quality: quality));
}
