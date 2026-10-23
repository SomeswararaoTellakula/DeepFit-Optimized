import 'package:flutter/material.dart';

import '../app.dart';
import '../services/app_state.dart';
import '../services/speech.dart';
import '../widgets/common.dart';
import 'height_weight_screen.dart';
import 'lr_check_screen.dart';
import 'stopwatch_screen.dart';
import 'test_run_screen.dart';

/// Same layout for every test: what to set up, how it is counted, mode, start.
class TestIntroScreen extends StatefulWidget {
  final String testKey;
  const TestIntroScreen({super.key, required this.testKey});
  @override
  State<TestIntroScreen> createState() => _TestIntroScreenState();
}

class _TestIntroScreenState extends State<TestIntroScreen> {
  final _speech = Speech();
  final _height = TextEditingController();
  final _weight = TextEditingController();
  final _chair = TextEditingController(text: '45');
  double _loadKg = 0;                       // dumbbell curls: weight in each hand (0 = no weight / bottle)
  bool _spoke = false;

  @override
  void initState() {
    super.initState();
    final state = AppScope.read(context);
    _height.text = state.heightCm.toStringAsFixed(0);
  }

  @override
  void dispose() {
    _speech.stop();
    _height.dispose();
    _weight.dispose();
    _chair.dispose();
    super.dispose();
  }

  String _spokenIntro(TestInfo t, String mode) {
    final parts = <String>[t.name, ...t.setup, t.counting];
    if (mode == 'blind') parts.addAll(t.blindAdaptation);
    parts.add(mode == 'blind' ? 'Double tap the big button at the bottom to start.' : 'Press start when you are ready.');
    return parts.where((s) => s.trim().isNotEmpty).join('. ');
  }

  void _start(TestInfo t) {
    final state = AppScope.read(context);
    _speech.stop();
    Widget screen;
    if (t.kind == 'height_weight') {
      screen = const HeightWeightScreen();
    } else if (t.kind == 'stopwatch') {
      screen = StopwatchScreen(info: t);
    } else {
      Map<String, double>? growth;
      if (t.key == 'growth_measures') {
        final h = double.tryParse(_height.text.trim()), w = double.tryParse(_weight.text.trim());
        final c = double.tryParse(_chair.text.trim());
        if (h == null || w == null || c == null || h < 100 || h > 230 || w < 15 || w > 200 || c < 25 || c > 80) {
          toast(context, 'Enter standing height (100-230 cm), weight (15-200 kg) and chair height (25-80 cm).');
          return;
        }
        growth = {'height_cm': h, 'weight_kg': w, 'chair_cm': c};
      }
      screen = TestRunScreen(info: t, mode: state.mode, front: state.frontCamera, growthInputs: growth,
          loadKg: t.key == 'dumbbell_curls' && _loadKg > 0 ? _loadKg : null);
    }
    Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => screen));
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final t = state.test(widget.testKey);
    if (t == null) {
      return Scaffold(appBar: AppBar(), body: const Center(child: Text('Test not found - refresh the test list.')));
    }
    final mode = state.mode;
    if (!_spoke && mode == 'blind') {
      _spoke = true;
      _speech.say(_spokenIntro(t, mode));
    }
    final target = t.targetFor(mode);
    return Scaffold(
      appBar: AppBar(title: Text(t.name)),
      body: SafeArea(
        child: Column(children: [
          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Row(children: [
                  Text(t.icon, style: const TextStyle(fontSize: 44)),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Wrap(spacing: 8, runSpacing: 6, children: [
                      if (t.kheloIndia) const Chip(label: Text('Khelo India')),
                      Chip(label: Text(t.kind == 'camera' ? 'Camera: ${t.camera == 'side' ? 'side-on' : 'facing'}' : 'Coach / manual')),
                      if (t.duration != null) Chip(label: Text('${t.duration!.round()} s max')),
                      if (target != null)
                        Chip(
                            label: Text(
                                'Target ${target['higher_is_better'] == true ? '≥' : '≤'} ${fmtValue(target['target'])} ${target['unit']}')),
                    ]),
                  ),
                ]),
                const SizedBox(height: 8),
                const ModeSelector(),
                const SectionTitle('Set up'),
                Panel(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    for (final (i, s) in t.setup.indexed)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 4),
                        child: Text('${i + 1}. $s', style: const TextStyle(fontSize: 15)),
                      ),
                  ]),
                ),
                if (t.counting.isNotEmpty) ...[
                  const SectionTitle('How it is counted'),
                  Panel(child: Text(t.counting, style: const TextStyle(fontSize: 15))),
                ],
                if (t.formCues.isNotEmpty) ...[
                  const SectionTitle('Tips'),
                  Panel(child: Text(t.formCues.map((c) => '• $c').join('\n'))),
                ],
                if (mode != 'standard' && (mode == 'blind' ? t.blindAdaptation : t.deafAdaptation).isNotEmpty) ...[
                  SectionTitle(mode == 'blind' ? 'Blind mode' : 'Deaf mode'),
                  Panel(
                    borderColor: DeepFitColors.cyan,
                    child: Text((mode == 'blind' ? t.blindAdaptation : t.deafAdaptation).map((c) => '• $c').join('\n')),
                  ),
                ],
                if (t.key == 'growth_measures') ...[
                  const SectionTitle('Your measurements'),
                  Panel(
                    child: Column(children: [
                      TextField(controller: _height, keyboardType: TextInputType.number, decoration: deco('Standing height', suffix: 'cm')),
                      const SizedBox(height: 10),
                      TextField(controller: _weight, keyboardType: TextInputType.number, decoration: deco('Weight', suffix: 'kg')),
                      const SizedBox(height: 10),
                      TextField(controller: _chair, keyboardType: TextInputType.number, decoration: deco('Chair seat height', suffix: 'cm')),
                    ]),
                  ),
                ],
                if (t.key == 'dumbbell_curls') ...[
                  const SectionTitle('Dumbbell weight (each hand)'),
                  Panel(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Wrap(spacing: 8, runSpacing: 6, children: [
                        for (final kg in const [0.0, 1.0, 2.0, 3.0, 5.0, 7.5, 10.0])
                          ChoiceChip(
                            label: Text(kg == 0 ? 'No weight / bottle' : '${fmtValue(kg)} kg'),
                            selected: _loadKg == kg,
                            onSelected: (_) => setState(() => _loadKg = kg),
                          ),
                      ]),
                      const SizedBox(height: 8),
                      const Text(
                          'The camera can\'t read the number on a dumbbell, so pick it here. The server then measures how the '
                          'weight moved - elbow angle, lifting speed, body swing - and estimates your strength (1-rep max).',
                          style: TextStyle(color: DeepFitColors.muted, fontSize: 13)),
                    ]),
                  ),
                ],
                if (t.key == 'coachability' && state.lrSwapOverride == null)
                  Panel(
                    borderColor: DeepFitColors.amber,
                    child: Row(children: [
                      const Expanded(
                        child: Text('This test uses LEFT and RIGHT. Do the 10-second left/right camera check once on this phone.'),
                      ),
                      TextButton(
                        onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const LrCheckScreen())),
                        child: const Text('Check'),
                      ),
                    ]),
                  ),
                if (t.kind == 'camera') ...[
                  const SectionTitle('Camera'),
                  SegmentedButton<bool>(
                    segments: const [
                      ButtonSegment(value: true, label: Text('Front (selfie)'), icon: Icon(Icons.camera_front)),
                      ButtonSegment(value: false, label: Text('Back (helper films)'), icon: Icon(Icons.camera_rear)),
                    ],
                    selected: {state.frontCamera},
                    onSelectionChanged: (s) => state.setFrontCamera(s.first),
                  ),
                  const SizedBox(height: 6),
                  const Text('Stand the phone upright (portrait) and keep it still.',
                      style: TextStyle(color: DeepFitColors.muted, fontSize: 13)),
                ],
                if (state.requireFace && t.kind != 'height_weight')
                  const Padding(
                    padding: EdgeInsets.only(top: 12),
                    child: Text('🔒 Your face is checked against your registration photo before and during the test.',
                        style: TextStyle(color: DeepFitColors.muted, fontSize: 13)),
                  ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: SizedBox(
              width: double.infinity,
              height: mode == 'blind' ? 96 : 56,
              child: Semantics(
                button: true,
                label: 'Start ${t.name}',
                child: FilledButton(
                  onPressed: () => _start(t),
                  child: Text(t.kind == 'height_weight' ? 'Enter measurements' : 'Start test',
                      style: TextStyle(fontSize: mode == 'blind' ? 26 : 18)),
                ),
              ),
            ),
          ),
        ]),
      ),
    );
  }
}
