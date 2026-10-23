import 'package:flutter/material.dart';

import '../app.dart';
import '../services/app_state.dart';
import '../widgets/common.dart';
import 'chat_screen.dart';
import 'potential_screen.dart';
import 'settings_screen.dart';
import 'test_intro_screen.dart';

/// All tests, progress, the next test, Hidden Potential and the Talent Passport.
class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final tests = state.tests;
    final hp = (state.hub?['hidden_potential'] as Map?)?.cast<String, dynamic>();
    final nextKey = state.hub?['next_test'] as String?;
    final next = nextKey == null ? null : state.test(nextKey);
    final done = (state.hub?['done'] ?? 0) as num, total = (state.hub?['total'] ?? tests.length) as num;
    final passportUrl = state.athlete?['passport_url'] as String?;

    return Scaffold(
      appBar: AppBar(
        title: const Text('DeepFit', style: TextStyle(fontWeight: FontWeight.w900)),
        actions: [
          IconButton(
            tooltip: 'AI coach',
            icon: const Icon(Icons.chat_bubble_outline),
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ChatScreen())),
          ),
          IconButton(
            tooltip: 'Settings',
            icon: Badge(
              isLabelVisible: state.pending > 0,
              label: Text('${state.pending}'),
              child: const Icon(Icons.settings),
            ),
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SettingsScreen())),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: state.refresh,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 32),
          children: [
            Panel(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Hi ${state.firstName}!', style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800)),
                const SizedBox(height: 4),
                Text('${done.toInt()} of ${total.toInt()} tests done', style: const TextStyle(color: DeepFitColors.muted)),
                const SizedBox(height: 8),
                ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: LinearProgressIndicator(value: total > 0 ? done.toDouble() / total.toDouble() : 0.0, minHeight: 8),
                ),
                const SizedBox(height: 14),
                const SizedBox(width: double.infinity, child: ModeSelector()),
                if (!state.online && state.lastError != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 10),
                    child: Text('Offline - tests still work and upload later. (${state.lastError})',
                        style: const TextStyle(color: DeepFitColors.amber, fontSize: 13)),
                  ),
              ]),
            ),
            const PendingBanner(),
            if (next != null)
              Panel(
                borderColor: DeepFitColors.cyan,
                child: Row(children: [
                  Text(next.icon, style: const TextStyle(fontSize: 34)),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      const Text('NEXT TEST', style: TextStyle(color: DeepFitColors.cyan, fontSize: 12, fontWeight: FontWeight.w800)),
                      Text(next.name, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
                    ]),
                  ),
                  FilledButton(onPressed: () => _open(context, next), child: const Text('Start')),
                ]),
              ),
            if (state.test('coachability') != null) _CoachabilityCard(info: state.test('coachability')!),
            if (hp != null) _PotentialCard(hp: hp, passportUrl: passportUrl),
            const SectionTitle('All tests'),
            if (tests.isEmpty)
              Panel(
                child: Column(children: [
                  const Text('The test list will appear once the phone has reached the DeepFit server.'),
                  TextButton(onPressed: state.refresh, child: const Text('Try again')),
                ]),
              ),
            for (final t in tests)
              if (t.key != 'coachability') _TestTile(info: t), // has its own card above
          ],
        ),
      ),
    );
  }

  static void _open(BuildContext context, TestInfo t) {
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => TestIntroScreen(testKey: t.key)));
  }
}

/// Coachability Challenge gets its own button: it measures how fast the athlete LEARNS.
class _CoachabilityCard extends StatelessWidget {
  final TestInfo info;
  const _CoachabilityCard({required this.info});

  @override
  Widget build(BuildContext context) {
    final last = info.last;
    return Panel(
      color: const Color(0xFF1E1145),
      borderColor: const Color(0xFF8B5CF6),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Row(children: [
          Text('🧠', style: TextStyle(fontSize: 32)),
          SizedBox(width: 10),
          Expanded(
            child: Text('Coachability Challenge',
                style: TextStyle(fontSize: 19, fontWeight: FontWeight.w800, color: Color(0xFFC4B5FD))),
          ),
        ]),
        const SizedBox(height: 6),
        const Text('Learn a new 5-move pattern in 5 tries, with one tip after each try. It measures how fast you learn.',
            style: TextStyle(color: DeepFitColors.muted)),
        if (last != null)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Row(children: [
              Text('Last: ${fmtValue(last['value'])} pts  ', style: const TextStyle(fontWeight: FontWeight.w700)),
              RatingChip(last['rating'] as String?),
            ]),
          ),
        const SizedBox(height: 10),
        SizedBox(
          width: double.infinity,
          child: FilledButton.icon(
            style: FilledButton.styleFrom(backgroundColor: const Color(0xFF7C3AED), foregroundColor: Colors.white),
            onPressed: () => HomeScreen._open(context, info),
            icon: Icon(last == null ? Icons.play_arrow : Icons.replay),
            label: Text(last == null ? 'Start Coachability Challenge' : 'Retake Coachability Challenge'),
          ),
        ),
      ]),
    );
  }
}

class _PotentialCard extends StatelessWidget {
  final Map<String, dynamic> hp;
  final String? passportUrl;
  const _PotentialCard({required this.hp, this.passportUrl});

  @override
  Widget build(BuildContext context) {
    final idx = hp['index'] as num?;
    final missing = (hp['missing'] as List? ?? const []).length;
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Expanded(
            child: Text('HIDDEN POTENTIAL INDEX',
                style: TextStyle(color: DeepFitColors.muted, fontSize: 12, fontWeight: FontWeight.w800, letterSpacing: 1)),
          ),
          Text(idx == null ? '—' : idx.round().toString(),
              style: const TextStyle(fontSize: 36, fontWeight: FontWeight.w900, color: DeepFitColors.cyan)),
        ]),
        Text((hp['summary'] ?? '') as String, style: const TextStyle(color: DeepFitColors.muted)),
        if (hp['late_bloomer'] == true)
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: RatingChip('LATE BLOOMER · HIGH POTENTIAL'),
          ),
        if (idx != null && missing > 0)
          const Padding(
            padding: EdgeInsets.only(top: 6),
            child: Text('Provisional - some parts still missing.', style: TextStyle(color: DeepFitColors.amber, fontSize: 12)),
          ),
        const SizedBox(height: 10),
        Wrap(spacing: 10, runSpacing: 8, children: [
          OutlinedButton.icon(
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const PotentialScreen())),
            icon: const Icon(Icons.insights),
            label: const Text('Full report'),
          ),
          if (passportUrl != null)
            OutlinedButton.icon(
              onPressed: () => showPassportSheet(context, passportUrl!, title: 'My Talent Passport'),
              icon: const Icon(Icons.qr_code_2),
              label: const Text('My Talent Passport'),
            ),
        ]),
      ]),
    );
  }
}

class _TestTile extends StatelessWidget {
  final TestInfo info;
  const _TestTile({required this.info});

  @override
  Widget build(BuildContext context) {
    final last = info.last;
    return Panel(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      child: InkWell(
        onTap: () => HomeScreen._open(context, info),
        child: Row(children: [
          Text(info.icon, style: const TextStyle(fontSize: 30)),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(info.name, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
              const SizedBox(height: 2),
              Text(
                last == null
                    ? '${info.kheloIndia ? 'Khelo India · ' : ''}${info.category}'
                    : 'Last: ${fmtValue(last['value'])} ${last['unit'] ?? ''} · ${last['when'] ?? ''}',
                style: const TextStyle(color: DeepFitColors.muted, fontSize: 13),
              ),
            ]),
          ),
          if (last != null) RatingChip(last['rating'] as String?) else const Icon(Icons.chevron_right),
        ]),
      ),
    );
  }
}
