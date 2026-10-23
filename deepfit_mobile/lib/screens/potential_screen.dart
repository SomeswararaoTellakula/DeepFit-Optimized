import 'package:flutter/material.dart';

import '../app.dart';
import '../services/api.dart';
import '../services/app_state.dart';
import '../widgets/common.dart';
import 'test_intro_screen.dart';

/// Hidden Potential Index: maturity-adjusted fitness + coachability + growth headroom.
class PotentialScreen extends StatefulWidget {
  const PotentialScreen({super.key});
  @override
  State<PotentialScreen> createState() => _PotentialScreenState();
}

class _PotentialScreenState extends State<PotentialScreen> {
  Map<String, dynamic>? _data;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final state = AppScope.read(context);
    try {
      final r = await state.api.get('/potential', query: {'mode': state.mode});
      if (mounted) setState(() => _data = r);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _error = e.message;
          // offline: show the copy from the last hub refresh
          final hp = state.hub?['hidden_potential'];
          if (hp != null) _data = {'hidden_potential': hp};
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final hp = (_data?['hidden_potential'] as Map?)?.cast<String, dynamic>();
    final rank = (_data?['rank'] as Map?)?.cast<String, dynamic>();
    return Scaffold(
      appBar: AppBar(title: const Text('Hidden Potential')),
      body: hp == null
          ? Center(child: _error == null ? const CircularProgressIndicator() : Text(_error!))
          : ListView(padding: const EdgeInsets.all(16), children: [
              Panel(
                child: Column(children: [
                  SizedBox(
                    width: 150,
                    height: 150,
                    child: Stack(alignment: Alignment.center, children: [
                      SizedBox.expand(
                        child: CircularProgressIndicator(
                          value: ((hp['index'] as num?)?.toDouble() ?? 0) / 100,
                          strokeWidth: 12,
                          backgroundColor: Colors.white10,
                        ),
                      ),
                      Text(hp['index'] == null ? '—' : (hp['index'] as num).round().toString(),
                          style: const TextStyle(fontSize: 48, fontWeight: FontWeight.w900)),
                    ]),
                  ),
                  const SizedBox(height: 12),
                  Text((hp['summary'] ?? '') as String, textAlign: TextAlign.center),
                  if (hp['late_bloomer'] == true)
                    const Padding(padding: EdgeInsets.only(top: 8), child: RatingChip('LATE BLOOMER · HIGH POTENTIAL')),
                  if (hp['complete'] != true && hp['index'] != null)
                    const Padding(
                      padding: EdgeInsets.only(top: 6),
                      child: Text('PROVISIONAL', style: TextStyle(color: DeepFitColors.amber, fontWeight: FontWeight.w800)),
                    ),
                ]),
              ),
              const SectionTitle('What it is made of'),
              _bar('Fitness, adjusted for maturity (30%)', hp['fitness_adjusted'] as num?,
                  sub: hp['biological_age'] == null ? null : 'Biological age ${hp['biological_age']}'),
              _bar('Coachability - learning speed (40%)', hp['coachability'] as num?,
                  sub: hp['coachability_percentile'] == null ? null : '${hp['coachability_percentile']}th percentile*'),
              _bar('Growth still to come (30%)', hp['headroom'] as num?),
              _bar('Fitness today (for comparison)', hp['fitness_today'] as num?),
              if ((hp['missing'] as List? ?? const []).isNotEmpty) ...[
                const SectionTitle('Still missing'),
                for (final m in (hp['missing'] as List))
                  if (m == 'fitness_tests')
                    const Panel(child: Text('Do any fitness test (push-ups, sit and reach, plank, ...).'))
                  else if (state.test(m.toString()) != null)
                    Panel(
                      child: Row(children: [
                        Expanded(child: Text(state.test(m.toString())!.name)),
                        TextButton(
                          onPressed: () => Navigator.of(context)
                              .push(MaterialPageRoute(builder: (_) => TestIntroScreen(testKey: m.toString()))),
                          child: const Text('Take it'),
                        ),
                      ]),
                    ),
              ],
              if (rank != null) ...[
                const SectionTitle('Rank'),
                Panel(
                  child: Text('Among ${rank['group']} (${rank['group_size']}): '
                      '#${rank['by_fitness'] ?? '-'} by today\'s fitness, #${rank['by_potential'] ?? '-'} by potential.'),
                ),
              ],
              const SizedBox(height: 8),
              const Text('* Weights and norms are starter values, to be tuned with real data.',
                  style: TextStyle(color: DeepFitColors.muted, fontSize: 12)),
            ]),
    );
  }

  Widget _bar(String label, num? v, {String? sub}) => Panel(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(label)),
            Text(v == null ? '—' : v.round().toString(), style: const TextStyle(fontWeight: FontWeight.w800)),
          ]),
          const SizedBox(height: 6),
          LinearProgressIndicator(value: v == null ? 0.0 : (v.toDouble() / 100).clamp(0.0, 1.0).toDouble(), minHeight: 8),
          if (sub != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(sub, style: const TextStyle(color: DeepFitColors.muted, fontSize: 12))),
        ]),
      );
}
