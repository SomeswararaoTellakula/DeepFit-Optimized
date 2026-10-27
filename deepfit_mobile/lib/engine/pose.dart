// Body landmarks + geometry. A line-by-line copy of the top of exercise_engine.py.
//
// Landmarks are the 33 BlazePose points (ML Kit on the phone and MediaPipe on the
// website use the same order). Inputs are normalised x/y (0..1 of the upright frame)
// plus a visibility / likelihood score; the engine works in pixels.

import 'dart:math' as math;

import 'py.dart';

/// Landmark indices (same as MediaPipe Pose / ML Kit PoseLandmarkType.index).
abstract final class L {
  static const nose = 0;
  static const lEye = 2, rEye = 5;
  static const lEar = 7, rEar = 8;
  static const lShoulder = 11, rShoulder = 12;
  static const lElbow = 13, rElbow = 14;
  static const lWrist = 15, rWrist = 16;
  static const lIndex = 19, rIndex = 20;
  static const lHip = 23, rHip = 24;
  static const lKnee = 25, rKnee = 26;
  static const lAnkle = 27, rAnkle = 28;
  static const lHeel = 29, rHeel = 30;
  static const lFoot = 31, rFoot = 32;

  /// Left/right partner of every landmark (used to undo a mirrored camera stream).
  static const List<int> mirrorPartner = [
    0, 4, 5, 6, 1, 2, 3, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15, 18, 17, 20, 19, 22, 21,
    24, 23, 26, 25, 28, 27, 30, 29, 32, 31,
  ];
}

const double visMin = 0.5; // minimum landmark visibility

class Vec {
  final double x, y;
  const Vec(this.x, this.y);
}

/// Landmarks in pixel coordinates (x right, y down) with visibility.
class BodyPose {
  final double w, h;
  final List<List<double>> pts;

  BodyPose(List<List<double>> landmarks, this.w, this.h)
      : pts = [for (final lm in landmarks) [lm[0] * w, lm[1] * h, lm[2]]];

  Vec p(int i) => Vec(pts[i][0], pts[i][1]);

  bool vis(List<int> idx) => idx.every((i) => pts[i][2] >= visMin);

  Vec mid(int a, int b) => Vec((pts[a][0] + pts[b][0]) / 2, (pts[a][1] + pts[b][1]) / 2);

  double dist(int a, int b) {
    final p1 = p(a), p2 = p(b);
    return hypot(p2.x - p1.x, p2.y - p1.y);
  }

  /// The body side the camera sees better (for side-on exercises).
  List<int>? bestSide(List<int> left, List<int> right) {
    final lv = sumOf(left.map((i) => pts[i][2]));
    final rv = sumOf(right.map((i) => pts[i][2]));
    final side = lv >= rv ? left : right;
    return vis(side) ? side : null;
  }
}

/// Angle ABC in degrees.
double angle(Vec a, Vec b, Vec c) {
  final v1x = a.x - b.x, v1y = a.y - b.y;
  final v2x = c.x - b.x, v2y = c.y - b.y;
  final n = hypot(v1x, v1y) * hypot(v2x, v2y);
  if (n == 0) return 180.0;
  final cos = math.max(-1.0, math.min(1.0, (v1x * v2x + v1y * v2y) / n));
  return math.acos(cos) * radToDeg;
}

/// Angle of the line a->b above the horizontal, 0..90 degrees.
double elevation(Vec a, Vec b) {
  final dx = b.x - a.x, dy = a.y - b.y;
  return math.atan2(dy.abs(), dx.abs() + 1e-6) * radToDeg;
}

/// 0 at lo, 1 at hi (works for lo > hi too).
double ramp(double x, double lo, double hi) {
  if (hi == lo) return 1.0;
  return math.max(0.0, math.min(1.0, (x - lo) / (hi - lo)));
}
