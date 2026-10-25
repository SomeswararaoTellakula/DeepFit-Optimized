import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:deepfit_mobile/engine/run_track.dart';
import 'package:flutter_test/flutter_test.dart';

/// The phone's GPS maths must give the server's numbers (fixtures written by run_check.py on simulated runs).
void main() {
  final cases = jsonDecode(File('test/fixtures/gps_runs.json').readAsStringSync()) as List;
  for (var i = 0; i < cases.length; i++) {
    test('GPS run $i: same distance and 600 m time as the server', () {
      final c = cases[i] as Map<String, dynamic>;
      final fixes = [
        for (final p in c['points'] as List)
          GpsFix((p['t'] as num).toDouble(), (p['lat'] as num).toDouble(), (p['lon'] as num).toDouble(),
              (p['acc'] as num).toDouble(), mocked: p['mocked'] == true)
      ];
      final kept = cleanPoints(fixes);
      expect(kept.length, c['kept']);
      final track = distanceTrack(kept);
      expect(track.last[1], closeTo((c['total_m'] as num).toDouble(), 0.01));
      final cross = crossingTime(track, 600);
      if (c['cross_s'] == null) {
        expect(cross, isNull);
      } else {
        expect(cross, closeTo((c['cross_s'] as num).toDouble(), 0.01));
      }
    });
  }

  test('step detector: steady running rhythm is counted, stillness is not', () {
    final d = StepDetector();
    for (var i = 0; i < 1000; i++) {
      final t = i / 50, ph = (t * 2.9) % 1;
      final a = 14 * _gauss((ph - 0.1) / 0.06) + 5 * _gauss((ph - 0.35) / 0.1);
      d.add(t, a, 0, 0);
    }
    expect(d.steps.length, inInclusiveRange(55, 60)); // 20 s at 2.9 steps a second
    final still = StepDetector();
    for (var i = 0; i < 1000; i++) {
      still.add(i / 50, 0.3, 0.2, 0.1);
    }
    expect(still.steps, isEmpty);
  });
}

double _gauss(double x) => math.exp(-x * x);
