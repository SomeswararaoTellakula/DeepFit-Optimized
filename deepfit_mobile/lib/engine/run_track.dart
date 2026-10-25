import 'dart:math' as math;

/// GPS run maths - a line-by-line copy of `run_check.py` on the server (clean_points, smooth_xy,
/// distance_track, crossing_time), so the phone stops at the same 600 m the server will compute.
/// If you change a number here, change it there too.

const double kEarthR = 6371008.8;
const double kMaxAccuracyM = 25.0;
const double kMaxPointSpeed = 12.0;
const double kSmoothS = 1.0;
const double kMinMoveM = 1.5;

class GpsFix {
  final double t; // seconds since "Go"
  final double lat, lon, acc;
  final double? spd;
  final bool mocked;
  const GpsFix(this.t, this.lat, this.lon, this.acc, {this.spd, this.mocked = false});
  Map<String, dynamic> toJson() => {
        't': double.parse(t.toStringAsFixed(2)),
        'lat': lat,
        'lon': lon,
        'acc': double.parse(acc.toStringAsFixed(1)),
        if (spd != null) 'spd': double.parse(spd!.toStringAsFixed(2)),
        'mocked': mocked,
      };
}

double haversine(double lat1, double lon1, double lat2, double lon2) {
  double r(double d) => d * math.pi / 180;
  final h = math.pow(math.sin((r(lat2) - r(lat1)) / 2), 2) +
      math.cos(r(lat1)) * math.cos(r(lat2)) * math.pow(math.sin((r(lon2) - r(lon1)) / 2), 2);
  return 2 * kEarthR * math.asin(math.min(1.0, math.sqrt(h)));
}

List<GpsFix> cleanPoints(List<GpsFix> points) {
  final pts = points.where((p) => p.acc <= kMaxAccuracyM).toList()..sort((a, b) => a.t.compareTo(b.t));
  final out = <GpsFix>[];
  for (final p in pts) {
    if (out.isNotEmpty) {
      final last = out.last;
      final d = haversine(last.lat, last.lon, p.lat, p.lon), dt = p.t - last.t;
      if (dt <= 0) continue;
      if (d / dt > kMaxPointSpeed && d > 2 * math.max(p.acc, last.acc)) continue;
    }
    out.add(p);
  }
  return out;
}

/// [(t, x, y)] in local metres, each averaged with the fixes within +-kSmoothS s (weight 1/accuracy^2).
List<List<double>> smoothXY(List<GpsFix> pts) {
  if (pts.isEmpty) return [];
  final lat0 = pts.first.lat, lon0 = pts.first.lon;
  final kx = math.pi / 180 * kEarthR * math.cos(lat0 * math.pi / 180), ky = math.pi / 180 * kEarthR;
  final raw = [
    for (final p in pts) [p.t, (p.lon - lon0) * kx, (p.lat - lat0) * ky, 1 / math.pow(math.max(1.0, p.acc), 2)]
  ];
  final out = <List<double>>[];
  var j0 = 0;
  for (final r in raw) {
    final t = r[0];
    while (raw[j0][0] < t - kSmoothS) {
      j0++;
    }
    var sw = 0.0, sx = 0.0, sy = 0.0;
    for (var j = j0; j < raw.length && raw[j][0] <= t + kSmoothS; j++) {
      final w = raw[j][3];
      sw += w;
      sx += w * raw[j][1];
      sy += w * raw[j][2];
    }
    out.add([t, sx / sw, sy / sw]);
  }
  return out;
}

/// Cumulative distance [(t, metres)] from the smoothed positions.
List<List<double>> distanceTrack(List<GpsFix> pts) {
  final xy = smoothXY(pts);
  if (xy.isEmpty) return [];
  final out = <List<double>>[
    [xy.first[0], 0.0]
  ];
  var ax = xy.first[1], ay = xy.first[2], total = 0.0;
  for (final p in xy.skip(1)) {
    final d = math.sqrt(math.pow(p[1] - ax, 2) + math.pow(p[2] - ay, 2));
    if (d >= kMinMoveM) {
      total += d;
      ax = p[1];
      ay = p[2];
    }
    out.add([p[0], total]);
  }
  return out;
}

double? crossingTime(List<List<double>> track, double target) {
  for (var i = 0; i + 1 < track.length; i++) {
    final t0 = track[i][0], d0 = track[i][1], t1 = track[i + 1][0], d1 = track[i + 1][1];
    if (d0 < target && target <= d1) return d1 > d0 ? t0 + (t1 - t0) * (target - d0) / (d1 - d0) : t1;
  }
  return null;
}

/// Foot strikes from the phone's motion sensor (gravity removed). A running step is a sharp jolt
/// (several m/s^2); peaks are counted with a rising threshold and at most 4.5 steps a second.
class StepDetector {
  final List<double> steps = []; // seconds since "Go"
  double _smooth = 0, _peakAvg = 6.0, _lastStep = -1, _cur = 0;
  bool _above = false;

  void add(double t, double x, double y, double z) {
    final m = math.sqrt(x * x + y * y + z * z);
    _smooth = 0.6 * _smooth + 0.4 * m; // light low-pass: removes buzz, keeps the foot strike
    final thr = math.max(2.5, 0.45 * _peakAvg);
    if (!_above && _smooth > thr) {
      _above = true;
      _cur = _smooth;
    } else if (_above) {
      if (_smooth > _cur) _cur = _smooth;
      if (_smooth < 0.5 * thr) {
        _above = false;
        if (t - _lastStep >= 0.22) {
          steps.add(double.parse(t.toStringAsFixed(3)));
          _lastStep = t;
          _peakAvg = 0.8 * _peakAvg + 0.2 * _cur;
        }
      }
    }
  }
}
