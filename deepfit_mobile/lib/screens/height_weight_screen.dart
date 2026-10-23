import 'package:flutter/material.dart';

import '../app.dart';
import '../services/api.dart';
import '../services/app_state.dart';
import '../services/outbox.dart';
import '../widgets/common.dart';
import 'photo_capture_screen.dart';

/// Height & weight. Height: measured by the camera with the two DeepFit sheets on the wall (same maths as
/// the website) - or typed from a tape. Weight: read off a photo of the scale display - or typed.
/// Height is also used to turn pixels into cm in the jump and reach tests.
class HeightWeightScreen extends StatefulWidget {
  const HeightWeightScreen({super.key});
  @override
  State<HeightWeightScreen> createState() => _HeightWeightScreenState();
}

class _HeightWeightScreenState extends State<HeightWeightScreen> {
  final _h = TextEditingController();
  final _w = TextEditingController();
  bool _busy = false;
  String? _done;
  String? _working; // what the server is doing right now
  // where the numbers came from (reset to typing when the field is edited by hand)
  String _heightSource = 'tape';
  String _weightSource = 'typed';
  Map<String, dynamic>? _measurement;
  String? _heightNote, _weightNote;
  String _hSet = '', _wSet = '';

  @override
  void initState() {
    super.initState();
    _h.addListener(() {
      if (_heightSource == 'camera' && _h.text != _hSet) setState(() => _heightSource = 'tape');
    });
    _w.addListener(() {
      if (_weightSource == 'scale_photo' && _w.text != _wSet) setState(() => _weightSource = 'typed');
    });
  }

  @override
  void dispose() {
    _h.dispose();
    _w.dispose();
    super.dispose();
  }

  Future<void> _measureHeight() async {
    final state = AppScope.read(context);
    final go = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (c) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('Set up (once)', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
            const SizedBox(height: 8),
            const Text('1. Print the two DeepFit sheets at 100 % - or use two plain A4 sheets on a darker wall.\n'
                '2. FLOOR sheet: cut on the dashed line, stand it on the floor against the wall, tape it flat.\n'
                '3. TOP sheet: tape it anywhere above your head, a bit to the side.\n'
                '4. Prop the phone 2-3 m away at chest height: both sheets, your head and feet in view.\n'
                '5. Start the timer, then stand next to the floor sheet - no shoes or cap, heels, back and head on the wall.'),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              icon: const Icon(Icons.print),
              label: const Text('Open the sheets to print'),
              onPressed: () => openLink(context, '${state.serverUrl}/height/marker'),
            ),
            const SizedBox(height: 8),
            FilledButton(onPressed: () => Navigator.of(c).pop(true), child: const Text('Ready - open the camera')),
          ]),
        ),
      ),
    );
    if (go != true || !mounted) return;
    final photos = await Navigator.of(context).push<List<String>>(MaterialPageRoute(
        builder: (_) => const PhotoCaptureScreen(
              title: 'Height photos',
              hint: 'Both sheets, your head and your feet must be in the picture. After the timer it takes 3 photos - stand still.',
              shots: 3,
              timerSeconds: 10,
            )));
    if (photos == null || photos.isEmpty || !mounted) return;
    setState(() => _working = 'Measuring your height…');
    try {
      final r = await state.api.post('/height_weight/measure', {'photos': photos}, timeout: const Duration(seconds: 90));
      final h = (r['height_cm'] as num).toDouble();
      setState(() {
        _hSet = h.toStringAsFixed(1);
        _h.text = _hSet;
        _heightSource = 'camera';
        _measurement = {'reference': r['reference'], 'spread_cm': r['spread_cm'], 'photos_used': r['photos_used']};
        _heightNote = 'Measured by the camera from ${r['photos_used']} photos'
            '${r['reference'] == 'a4' ? ' (A4 sheets)' : ''} · photos agree within ±${r['spread_cm']} cm · accuracy ≈ ±1 cm';
      });
    } on ApiException catch (e) {
      if (mounted) _problem('Height not measured', e.message);
    } finally {
      if (mounted) setState(() => _working = null);
    }
  }

  Future<void> _readScale() async {
    final state = AppScope.read(context);
    final photos = await Navigator.of(context).push<List<String>>(MaterialPageRoute(
        builder: (_) => const PhotoCaptureScreen(
              title: 'Photo of your scale',
              hint: 'Stand on the scale, wait until the number stops changing, step off, then photograph the display '
                  'close up - fill the screen with the digits, no glare.',
            )));
    if (photos == null || photos.isEmpty || !mounted) return;
    setState(() => _working = 'Reading the scale…');
    try {
      final r = await state.api.post('/vision/scale', {'photo': photos.first}, timeout: const Duration(seconds: 60));
      final kg = (r['kg'] as num).toDouble();
      setState(() {
        _wSet = kg.toStringAsFixed(1);
        _w.text = _wSet;
        _weightSource = 'scale_photo';
        _weightNote = 'Read ${fmtValue(r['reading'])} ${r['unit']} on the display'
            '${r['sure'] == true ? '' : ' - not fully sure, please check the number'}';
      });
    } on ApiException catch (e) {
      if (mounted) _problem('Scale not read', e.message);
    } finally {
      if (mounted) setState(() => _working = null);
    }
  }

  void _problem(String title, String msg) {
    showDialog<void>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(title),
        content: Text(msg),
        actions: [TextButton(onPressed: () => Navigator.of(c).pop(), child: const Text('OK'))],
      ),
    );
  }

  Future<void> _save() async {
    final h = double.tryParse(_h.text.trim().replaceAll(',', '.'));
    final w = double.tryParse(_w.text.trim().replaceAll(',', '.'));
    if (h == null || w == null || h < 100 || h > 230 || w < 15 || w > 200) {
      toast(context, 'Enter height 100-230 cm and weight 15-200 kg.');
      return;
    }
    setState(() => _busy = true);
    final state = AppScope.read(context);
    final id = Outbox.newId();
    await state.addToOutbox(OutboxItem(
      id: id,
      kind: 'height_weight',
      exercise: 'height_weight',
      name: 'Height & Weight',
      created: DateTime.now(),
      body: {
        'height_cm': h,
        'weight_kg': w,
        'client_id': id,
        'height_source': _heightSource,
        'weight_source': _weightSource,
        if (_heightSource == 'camera' && _measurement != null) 'measurement': _measurement,
      },
      local: {'height_cm': h, 'weight_kg': w},
    ));
    final o = await state.syncOne(id);
    if (!mounted) return;
    final bmi = w / ((h / 100) * (h / 100));
    setState(() {
      _busy = false;
      _done = o.status == 'saved'
          ? 'Saved ✓  BMI ${bmi.toStringAsFixed(1)}'
          : 'Saved on this phone (BMI ${bmi.toStringAsFixed(1)}) - uploads when online.';
    });
  }

  Widget _source(String? note, bool fromCamera) => note == null || !fromCamera
      ? const SizedBox.shrink()
      : Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Row(children: [
            const Icon(Icons.check_circle, color: DeepFitColors.green, size: 18),
            const SizedBox(width: 6),
            Expanded(child: Text(note, style: const TextStyle(color: DeepFitColors.muted, fontSize: 13))),
          ]),
        );

  @override
  Widget build(BuildContext context) {
    final online = !_busy && _working == null;
    return Scaffold(
      appBar: AppBar(title: const Text('Height & Weight')),
      body: SafeArea(
        child: ListView(padding: const EdgeInsets.all(16), children: [
          const SectionTitle('Height'),
          Panel(
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              FilledButton.icon(
                icon: const Icon(Icons.straighten),
                label: const Text('Measure with the camera'),
                onPressed: online ? _measureHeight : null,
              ),
              const SizedBox(height: 10),
              TextField(
                  controller: _h,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: deco('Height', suffix: 'cm', hint: 'or type a tape measurement')),
              _source(_heightNote, _heightSource == 'camera'),
            ]),
          ),
          const SectionTitle('Weight'),
          Panel(
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              FilledButton.icon(
                icon: const Icon(Icons.monitor_weight),
                label: const Text('Read my scale (photo)'),
                onPressed: online ? _readScale : null,
              ),
              const SizedBox(height: 10),
              TextField(
                  controller: _w,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: deco('Weight', suffix: 'kg', hint: 'or type it')),
              _source(_weightNote, _weightSource == 'scale_photo'),
            ]),
          ),
          if (_working != null)
            Panel(
              child: Row(children: [
                const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 3)),
                const SizedBox(width: 12),
                Text(_working!),
              ]),
            ),
          const SizedBox(height: 8),
          FilledButton(onPressed: online ? _save : null, child: Text(_busy ? 'Saving…' : 'Save')),
          const SizedBox(height: 8),
          const Text(
              'Camera height uses two sheets on the wall: the floor one marks the floor, the top one lets the server '
              'measure and remove camera tilt. Expected accuracy ≈ ±1 cm. A camera cannot weigh you - it reads your scale.',
              style: TextStyle(color: DeepFitColors.muted, fontSize: 12)),
          if (_done != null) ...[
            const SizedBox(height: 16),
            Panel(borderColor: DeepFitColors.green, child: Text(_done!)),
            OutlinedButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Back to all tests')),
          ],
        ]),
      ),
    );
  }
}
