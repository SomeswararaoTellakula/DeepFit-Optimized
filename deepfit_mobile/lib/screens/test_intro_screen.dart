import 'package:flutter/material.dart';

import '../app.dart';
import '../services/api.dart';
import '../services/app_state.dart';
import '../services/speech.dart';
import '../widgets/common.dart';
import 'gps_run_screen.dart';
import 'height_weight_screen.dart';
import 'lr_check_screen.dart';
import 'photo_capture_screen.dart';
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
  Map<String, dynamic>? _loadDetect;        // how the weight was found (read off the dumbbell / estimated)
  String? _detectNote;
  bool _detecting = false;
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

  Future<void> _detectDumbbell() async {
    final state = AppScope.read(context);
    final photos = await Navigator.of(context).push<List<String>>(MaterialPageRoute(
        builder: (_) => const PhotoCaptureScreen(
              title: 'Show your dumbbell',
              hint: 'Hold the dumbbell close with the end that says "5 KG" (or similar) towards the camera, then take the photo.',
              front: true,
            )));
    if (photos == null || photos.isEmpty || !mounted) return;
    setState(() => _detecting = true);
    try {
      final r = await state.api.post('/dumbbell/detect', {'photo': photos.first}, timeout: const Duration(seconds: 60));
      final kg = (r['kg'] as num).toDouble();
      setState(() {
        _loadKg = kg;
        _loadDetect = {
          'source': r['source'], 'kg': kg, 'label_text': r['label_text'], 'model': r['model'], 'sure': r['sure'],
          'object': r['object'],
        };
        _detectNote = r['source'] == 'label'
            ? '✓ Detected ${fmtValue(kg)} kg - read "${r['label_text'] ?? '${fmtValue(kg)} kg'}" on the ${r['object'] ?? 'dumbbell'}'
            : '≈ ${fmtValue(kg)} kg - no number was readable, this is a guess from its look. Tap the right weight if it is wrong.';
      });
      _speech.say(r['source'] == 'label' ? 'Detected ${fmtValue(kg)} kilograms.' : 'About ${fmtValue(kg)} kilograms. Please check.');
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message);
    } finally {
      if (mounted) setState(() => _detecting = false);
    }
  }

  void _start(TestInfo t) {
    final state = AppScope.read(context);
    _speech.stop();
    Widget screen;
    if (t.kind == 'height_weight') {
      screen = const HeightWeightScreen();
    } else if (t.kind == 'stopwatch' && t.key == 'run_600m') {
      _chooseRunTiming(t);
      return;
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
      final load = t.key == 'dumbbell_curls' && _loadKg > 0 ? _loadKg : null;
      final detect = load == null
          ? null
          : (_loadDetect != null && (_loadDetect!['kg'] as num).toDouble() == load ? _loadDetect : {'source': 'typed'});
      screen = TestRunScreen(info: t, mode: state.mode, front: state.frontCamera, growthInputs: growth,
          loadKg: load, loadDetect: detect);
    }
    Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => screen));
  }

  /// 600 m: the phone can time it by itself (GPS + steps, checked by the server) or the coach uses the stopwatch.
  Future<void> _chooseRunTiming(TestInfo t) async {
    final gps = await showModalBottomSheet<bool>(
      context: context,
      builder: (c) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Text('How should the run be timed?', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
            const SizedBox(height: 12),
            FilledButton.icon(
              icon: const Icon(Icons.gps_fixed),
              label: const Text('Phone GPS - the runner carries the phone (outdoors)'),
              onPressed: () => Navigator.of(c).pop(true),
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              icon: const Icon(Icons.timer),
              label: const Text('Coach stopwatch'),
              onPressed: () => Navigator.of(c).pop(false),
            ),
            const SizedBox(height: 8),
            const Text('Phone GPS results are checked by the server for running rhythm, speed and a face photo at the finish.',
                style: TextStyle(color: DeepFitColors.muted, fontSize: 12)),
          ]),
        ),
      ),
    );
    if (gps == null || !mounted) return;
    Navigator.of(context).pushReplacement(MaterialPageRoute(
        builder: (_) => gps ? GpsRunScreen(info: t) : StopwatchScreen(info: t)));
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
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton.icon(
                          icon: const Icon(Icons.photo_camera),
                          label: Text(_detecting ? 'Reading the dumbbell…' : 'Detect my dumbbell'),
                          onPressed: _detecting ? null : _detectDumbbell,
                        ),
                      ),
                      if (_detectNote != null) ...[
                        const SizedBox(height: 8),
                        Text(_detectNote!,
                            style: TextStyle(
                                color: _loadDetect?['source'] == 'label' ? DeepFitColors.green : DeepFitColors.amber,
                                fontWeight: FontWeight.w600)),
                      ],
                      const SizedBox(height: 10),
                      const Text('No number on it, or a water bottle? Pick it:',
                          style: TextStyle(color: DeepFitColors.muted, fontSize: 13)),
                      const SizedBox(height: 6),
                      Wrap(spacing: 8, runSpacing: 6, children: [
                        for (final kg in {0.0, 1.0, 2.0, 3.0, 5.0, 7.5, 10.0, if (_loadKg > 0) _loadKg}.toList()..sort())
                          ChoiceChip(
                            label: Text(kg == 0 ? 'No weight / bottle' : '${fmtValue(kg)} kg'),
                            selected: _loadKg == kg,
                            onSelected: (_) => setState(() => _loadKg = kg),
                          ),
                      ]),
                      const SizedBox(height: 8),
                      const Text(
                          'The server measures how the weight moved - elbow angle, lifting speed, body swing - estimates your '
                          'strength (1-rep max) and checks the weight against the benchmark for your age group.',
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
