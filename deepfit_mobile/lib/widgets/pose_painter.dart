import 'package:flutter/material.dart';

/// Skeleton drawn on top of the camera preview (points are 0..1 of the preview box).
class PosePainter extends CustomPainter {
  final List<Offset>? points;
  final List<double>? likelihood;
  final List<(Offset, double, bool)> targets; // plate-tapping targets: centre, radius (0..1 of width), active
  final Color color;

  PosePainter(this.points, this.likelihood, {this.targets = const [], this.color = const Color(0xFF42C8F5)});

  static const connections = [
    [11, 12], [11, 13], [13, 15], [12, 14], [14, 16], [11, 23], [12, 24], [23, 24], [23, 25], [25, 27],
    [24, 26], [26, 28], [27, 29], [29, 31], [27, 31], [28, 30], [30, 32], [28, 32], [15, 19], [16, 20],
  ];

  @override
  void paint(Canvas canvas, Size size) {
    for (final t in targets) {
      final p = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 4
        ..color = t.$3 ? const Color(0xFF22C55E) : Colors.white54;
      canvas.drawCircle(Offset(t.$1.dx * size.width, t.$1.dy * size.height), t.$2 * size.width, p);
    }
    final pts = points, lk = likelihood;
    if (pts == null || lk == null || pts.length < 33) return;
    final line = Paint()
      ..color = color
      ..strokeWidth = 4
      ..strokeCap = StrokeCap.round;
    Offset at(int i) => Offset(pts[i].dx * size.width, pts[i].dy * size.height);
    for (final c in connections) {
      if (lk[c[0]] < 0.4 || lk[c[1]] < 0.4) continue;
      canvas.drawLine(at(c[0]), at(c[1]), line);
    }
    final dot = Paint()..color = Colors.white;
    for (var i = 11; i < 33; i++) {
      if (lk[i] >= 0.4) canvas.drawCircle(at(i), 4, dot);
    }
    if (lk[0] >= 0.4) {
      canvas.drawCircle(at(0), 6, Paint()..color = color);
    }
  }

  @override
  bool shouldRepaint(covariant PosePainter old) => true;
}
