// Small helpers so the Dart engine produces exactly the same numbers and texts as the
// Python engine on the server (exercise_engine.py). The server re-runs every phone
// result, so both sides must agree.

import 'dart:math' as math;

const double radToDeg = 180.0 / math.pi;

/// Python's round(x, n): exact halves go to the even neighbour (round(2.5) == 2).
double pyRound(double x, [int n = 0]) {
  if (x.isNaN || x.isInfinite) return x;
  final m = math.pow(10, n).toDouble();
  final y = x * m;
  final f = y.floorToDouble();
  final diff = y - f;
  double r;
  if (diff > 0.5) {
    r = f + 1;
  } else if (diff < 0.5) {
    r = f;
  } else {
    r = (f % 2 == 0) ? f : f + 1;
  }
  final out = r / m;
  return out == 0 ? 0.0 : out; // never "-0.0"
}

/// Python int(round(x)).
int pyRoundInt(double x) => pyRound(x).toInt();

/// f"{x:.Nf}" (Python keeps the minus sign: format(-0.3, '.0f') == '-0').
String fmtFixed(double x, int n) {
  final s = pyRound(x.abs(), n).toStringAsFixed(n);
  return x.isNegative ? '-$s' : s;
}

/// f"{x:+.0f}"
String fmtSigned0(double x) {
  final s = pyRound(x.abs()).toStringAsFixed(0);
  return x.isNegative ? '-$s' : '+$s';
}

/// f"{x:g}" for the small numbers the engine prints (errors like 2, 1.5, 0).
String fmtG(double x) {
  if (x == x.roundToDouble()) return x.toInt().toString();
  var s = x.toStringAsFixed(6);
  while (s.endsWith('0')) {
    s = s.substring(0, s.length - 1);
  }
  if (s.endsWith('.')) s = s.substring(0, s.length - 1);
  return s;
}

/// f"{x:.0%}"
String fmtPercent0(double x) => '${fmtFixed(x * 100, 0)}%';

double hypot(double x, double y) => math.sqrt(x * x + y * y);

double clamp01(double x) => x < 0 ? 0.0 : (x > 1 ? 1.0 : x);

/// Python math.erf (power series; accurate to ~1e-12 for |x| < 4, which covers every score 0-100).
double erf(double x) {
  if (x.abs() > 4) return x.isNegative ? -1.0 : 1.0;
  double sum = 0, term = x;
  for (var n = 0; n < 150; n++) {
    final add = term / (2 * n + 1);
    sum += add;
    if (add.abs() < 1e-17) break;
    term *= -x * x / (n + 1);
  }
  return 2 / math.sqrt(math.pi) * sum;
}

/// Python's "a or b" for numbers: None and 0 count as false.
double orNum(double? a, double b) => (a == null || a == 0) ? b : a;

/// Python's "bool(a)" for an optional number.
bool truthy(double? a) => a != null && a != 0;

/// Python 3.12+ sum() of floats (Neumaier-compensated, exactly as CPython does it).
double sumOf(Iterable<double> xs) {
  double s = 0.0, c = 0.0;
  for (final x in xs) {
    final t = s + x;
    if (s.abs() >= x.abs()) {
      c += (s - t) + x;
    } else {
      c += (x - t) + s;
    }
    s = t;
  }
  if (c != 0 && c.isFinite) s += c;
  return s;
}

double maxOf(Iterable<double> xs) => xs.reduce(math.max);
double minOf(Iterable<double> xs) => xs.reduce(math.min);
