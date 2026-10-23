import 'package:flutter/material.dart';

import '../app.dart';
import '../services/app_state.dart';
import '../services/outbox.dart';
import '../widgets/common.dart';

/// Height & weight measured with a tape and a scale (used to turn pixels into cm).
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

  @override
  void dispose() {
    _h.dispose();
    _w.dispose();
    super.dispose();
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
      body: {'height_cm': h, 'weight_kg': w, 'client_id': id},
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Height & Weight')),
      body: SafeArea(
        child: ListView(padding: const EdgeInsets.all(16), children: [
          const Panel(
            child: Text('Measure standing height with a tape (no shoes, heels against a wall) and weight with a scale. '
                'Your height is used to convert jump heights and reach into centimetres.'),
          ),
          const SizedBox(height: 12),
          TextField(controller: _h, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: deco('Height', suffix: 'cm')),
          const SizedBox(height: 12),
          TextField(controller: _w, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: deco('Weight', suffix: 'kg')),
          const SizedBox(height: 16),
          FilledButton(onPressed: _busy ? null : _save, child: Text(_busy ? 'Saving…' : 'Save')),
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
