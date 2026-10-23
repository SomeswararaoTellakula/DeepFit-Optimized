// The Dart engine must count exactly like the Python engine on the server.
// Fixtures come from tools/make_fixtures.py (run against exercise_engine.py).
//
//   flutter test test/engine_parity_test.dart

import 'dart:convert';
import 'dart:io';

import 'package:deepfit_mobile/engine/registry.dart';
import 'package:flutter_test/flutter_test.dart';

double d(Object? v) => (v as num).toDouble();

List<List<double>> lm(List raw) => [for (final p in raw) [d(p[0]), d(p[1]), d(p[2])]];

void main() {
  final data = jsonDecode(File('test/fixtures/engine_cases.json').readAsStringSync()) as Map<String, dynamic>;
  final t0 = d(data['t0']);
  final cases = (data['cases'] as List).cast<Map<String, dynamic>>();

  test('engine clock offset matches the server', () => expect(t0, engineT0));

  for (final c in cases) {
    test('parity: ${c['name']}', () {
      final ex = createExercise(c['key'] as String, heightCm: d(c['height_cm']))!;
      final inputs = c['inputs'] as Map<String, dynamic>?;
      if (inputs != null && ex is GrowthMeasures) {
        ex.configure(
            heightCm: d(inputs['height_cm']),
            weightKg: d(inputs['weight_kg']),
            chairCm: d(inputs['chair_cm']),
            age: inputs['age'],
            sex: inputs['sex']);
      }
      if (c['pattern'] != null && ex is CoachabilityChallenge) {
        ex.pattern = (c['pattern'] as List).cast<String>();
        ex.code = c['code'] as String;
      }
      final w = d(c['w']), h = d(c['h']);
      final exp = c['expect'] as Map<String, dynamic>;
      final perFrame = exp['per_frame'] as List;
      final feedback = <List<Object>>[];
      final events = <List<Object>>[];
      String? lastFb;
      var lastId = 0;
      final frames = c['frames'] as List;
      for (var i = 0; i < perFrame.length; i++) {
        final f = frames[i] as List;
        ex.update(f[1] == null ? null : BodyPose(lm(f[1] as List), w, h), t0 + d(f[0]));
        final e = perFrame[i] as List;
        expect(pyRound(ex.value(), 4), closeTo(d(e[0]), 1e-3), reason: 'value at frame $i');
        expect(ex.count, e[1], reason: 'count at frame $i');
        expect(ex.finished ? 1 : 0, e[2], reason: 'finished at frame $i');
        if (e[3] == null) {
          expect(ex.mirrorValue, isNull, reason: 'mirror at frame $i');
        } else {
          expect(ex.mirrorValue, closeTo(d(e[3]), 2e-3), reason: 'mirror at frame $i');
        }
        if (ex.feedback != lastFb) {
          feedback.add([i, ex.feedback]);
          lastFb = ex.feedback;
        }
        for (final ev in ex.events) {
          if (ev.id > lastId) {
            events.add([i, ev.kind, ev.text]);
            lastId = ev.id;
          }
        }
      }
      expect(feedback, [for (final x in exp['feedback'] as List) [x[0], x[1]]], reason: 'feedback texts');
      expect(events, [for (final x in exp['events'] as List) [x[0], x[1], x[2]]], reason: 'events (speech / captions)');

      final fin = exp['final'] as Map<String, dynamic>;
      final r = ex.result();
      expect(d(r['value']), closeTo(d(fin['value']), 1e-2));
      expect(r['unit'], fin['unit']);
      expect(r['repetitions'], fin['repetitions']);
      expect(r['invalid_reps'], fin['invalid_reps']);
      expect(r['form_score'], fin['form_score']);
      expect(r['form_faults'], fin['form_faults']);
      expect(r['incomplete'], fin['incomplete']);
      if (fin['coachability'] != null) {
        final a = r['coachability'] as Map<String, dynamic>, b = fin['coachability'] as Map<String, dynamic>;
        expect([for (final x in a['errors_per_try'] as List) d(x)], [for (final x in b['errors_per_try'] as List) d(x)]);
        expect(d(a['score']), closeTo(d(b['score']), 1e-9));
        expect(a['percentile'], b['percentile']);
        expect(a['reduction_pct'], b['reduction_pct']);
        expect(a['slope'] == null ? null : d(a['slope']), b['slope'] == null ? null : d(b['slope']));
        expect(a['note'], b['note']);
        expect(a['tips'], b['tips']);
        expect(a['tries_completed'], b['tries_completed']);
      }
      if (fin['maturity'] != null) {
        final a = r['maturity'] as Map<String, dynamic>, b = fin['maturity'] as Map<String, dynamic>;
        expect(a.keys.toSet(), b.keys.toSet());
        for (final k in b.keys) {
          if (b[k] is num) {
            expect(d(a[k]), closeTo(d(b[k]), 1e-9), reason: 'maturity.$k');
          } else {
            expect(a[k], b[k], reason: 'maturity.$k');
          }
        }
      } else {
        expect(r['maturity'], isNull);
      }
    });
  }

  final fx = data['functions'] as Map<String, dynamic>;
  test('alignment distance', () {
    for (final a in fx['align'] as List) {
      expect(align((a[0] as List).cast<String>(), (a[1] as List).cast<String>()).dist, a[2]);
    }
  });
  test('coachability score', () {
    for (final a in fx['coach_score'] as List) {
      final s = coachabilityScore([for (final x in a[0] as List) d(x)], 5);
      final e = a[1] as Map<String, dynamic>;
      expect(s.score, closeTo(d(e['score']), 1e-9));
      expect(s.reductionPct, e['reduction_pct']);
      expect(s.slope == null ? null : s.slope, e['slope'] == null ? null : d(e['slope']));
      expect(s.note, e['note']);
    }
  });
  test('starter percentile', () {
    for (final a in fx['percentile'] as List) {
      expect(starterPercentile(d(a[0])), a[1], reason: 'score ${a[0]}');
    }
  });
  test('maturity offset', () {
    for (final a in fx['maturity'] as List) {
      final m = maturityOffset(d(a[0]), a[1], d(a[2]), d(a[3]), d(a[4]));
      final e = a[5] as Map<String, dynamic>;
      for (final k in e.keys) {
        if (e[k] is num) {
          expect(d(m[k]), closeTo(d(e[k]), 1e-9), reason: k);
        } else {
          expect(m[k], e[k], reason: k);
        }
      }
    }
  });
  test('offline benchmark rating', () {
    for (final a in fx['evaluate'] as List) {
      final got = evaluateBenchmark(d(a[1]), (a[2] as Map).cast<String, dynamic>());
      final e = a[3] as Map<String, dynamic>;
      expect(got['rating'], e['rating'], reason: '${a[0]} ${a[1]}');
      expect(got['met'], e['met']);
      expect(got['percent_of_target'], e['percent_of_target']);
    }
  });
  test('python-style formatting', () {
    expect(pyRound(2.5), 2.0);
    expect(pyRound(3.5), 4.0);
    expect(pyRound(2.675, 2), 2.67);
    expect(fmtFixed(-0.3, 0), '-0');
    expect(fmtSigned0(0.0), '+0');
    expect(fmtSigned0(-4.6), '-5');
    expect(fmtG(2.0), '2');
    expect(fmtG(1.5), '1.5');
    expect(fmtPercent0(0.4), '40%');
    expect(sumOf(List.filled(10, 0.1)), 1.0); // Python 3.12+ compensated sum
  });
}
