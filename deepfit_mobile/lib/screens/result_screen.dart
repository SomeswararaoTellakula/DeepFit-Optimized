import 'package:flutter/material.dart';

import '../app.dart';
import '../services/app_state.dart';
import '../widgets/common.dart';
import 'test_intro_screen.dart';

/// The result as the phone counted it, then the server's verdict once uploaded
/// (face snapshots checked, score recomputed from the skeleton, Talent Passport signed).
class ResultScreen extends StatefulWidget {
  final TestInfo info;
  final String mode;
  final String outboxId;
  final Map<String, dynamic> local;
  const ResultScreen({super.key, required this.info, required this.mode, required this.outboxId, required this.local});
  @override
  State<ResultScreen> createState() => _ResultScreenState();
}

class _ResultScreenState extends State<ResultScreen> {
  SyncOutcome? _outcome;
  bool _uploading = true;

  @override
  void initState() {
    super.initState();
    _upload();
  }

  Future<void> _upload() async {
    setState(() => _uploading = true);
    final o = await AppScope.read(context).syncOne(widget.outboxId);
    if (!mounted) return;
    setState(() {
      _outcome = o;
      _uploading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final saved = _outcome?.status == 'saved';
    final server = saved ? _outcome!.result : null;
    final r = server ?? widget.local;
    final bench = (r['benchmark'] as Map?)?.cast<String, dynamic>();
    final rating = bench?['rating'] as String?;
    final nextKey = (server?['next_test'] ?? state.hub?['next_test']) as String?;
    final next = nextKey == null ? null : state.test(nextKey);
    final passportUrl = server?['passport_url'] as String?;
    final coach = (r['coachability'] as Map?)?.cast<String, dynamic>();
    final maturity = (r['maturity'] as Map?)?.cast<String, dynamic>();

    return Scaffold(
      appBar: AppBar(title: Text(widget.info.name), automaticallyImplyLeading: false, actions: [
        IconButton(icon: const Icon(Icons.close), onPressed: () => Navigator.of(context).pop()),
      ]),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Panel(
              child: Column(children: [
                Text(widget.info.icon, style: const TextStyle(fontSize: 44)),
                Semantics(
                  liveRegion: true,
                  child: Text('${fmtValue(r['value'])} ${r['unit'] ?? ''}',
                      style: const TextStyle(fontSize: 54, fontWeight: FontWeight.w900, color: DeepFitColors.cyan)),
                ),
                if (coach != null && coach['percentile'] != null)
                  Text('${coach['percentile']}th percentile*', style: const TextStyle(color: DeepFitColors.muted)),
                const SizedBox(height: 6),
                RatingChip(rating),
                if (bench != null && bench['available'] == true)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      'Target for your age group (${bench['age_band'] ?? ''}, ${widget.mode}): '
                      '${bench['higher_is_better'] == true ? '≥' : '≤'} ${fmtValue(bench['target'])} ${bench['unit'] ?? ''}',
                      textAlign: TextAlign.center,
                      style: const TextStyle(color: DeepFitColors.muted, fontSize: 13),
                    ),
                  ),
                if (r['incomplete'] == true)
                  const Padding(
                    padding: EdgeInsets.only(top: 6),
                    child: Text('Not completed within the time limit.', style: TextStyle(color: DeepFitColors.amber)),
                  ),
              ]),
            ),
            _statusPanel(),
            if (coach != null) _coachPanel(coach),
            if (maturity != null) _maturityPanel(maturity),
            if (passportUrl != null)
              Panel(
                borderColor: DeepFitColors.green,
                child: Row(children: [
                  const Icon(Icons.verified, color: DeepFitColors.green),
                  const SizedBox(width: 10),
                  const Expanded(child: Text('Verified result card (Talent Passport) ready.')),
                  FilledButton.icon(
                    onPressed: () => showPassportSheet(context, passportUrl),
                    icon: const Icon(Icons.qr_code_2),
                    label: const Text('QR'),
                  ),
                ]),
              ),
            const SizedBox(height: 12),
            if (next != null)
              FilledButton(
                onPressed: () => Navigator.of(context)
                    .pushReplacement(MaterialPageRoute(builder: (_) => TestIntroScreen(testKey: next.key))),
                child: Text('Next test: ${next.name}'),
              ),
            const SizedBox(height: 8),
            OutlinedButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Back to all tests')),
            const SizedBox(height: 8),
            const Text('* Starter benchmarks and norms - they will be replaced after field testing.',
                style: TextStyle(color: DeepFitColors.muted, fontSize: 12)),
          ],
        ),
      ),
    );
  }

  Widget _statusPanel() {
    if (_uploading) {
      return const Panel(
        child: Row(children: [
          SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 3)),
          SizedBox(width: 12),
          Expanded(child: Text('Uploading - the server checks your face snapshots and recounts from the skeleton…')),
        ]),
      );
    }
    final o = _outcome;
    switch (o?.status) {
      case 'saved':
        final serverValue = o!.result?['value'];
        final phoneValue = widget.local['value'];
        return Panel(
          borderColor: DeepFitColors.green,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('✓ Saved and verified by the server', style: TextStyle(fontWeight: FontWeight.w800, color: DeepFitColors.green)),
            if (!o.sameAsPhone)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text('The server recounted ${fmtValue(serverValue)} (the phone showed ${fmtValue(phoneValue)}). '
                    'The server\'s count is the official one.'),
              ),
          ]),
        );
      case 'rejected':
        return Panel(
          borderColor: DeepFitColors.red,
          child: Text('✗ Not saved: ${o!.message ?? 'the identity check failed.'}',
              style: const TextStyle(color: DeepFitColors.red, fontWeight: FontWeight.w700)),
        );
      case 'failed':
        return Panel(
          borderColor: DeepFitColors.red,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('The server refused this upload: ${o!.message ?? ''}'),
            TextButton(
              onPressed: () async {
                await AppScope.read(context).discard(widget.outboxId);
                if (mounted) Navigator.of(context).pop();
              },
              child: const Text('Delete it'),
            ),
          ]),
        );
      case 'auth':
        return const Panel(child: Text('Saved on this phone. Sign in again to upload it.'));
      default:
        return Panel(
          borderColor: DeepFitColors.amber,
          child: Row(children: [
            const Icon(Icons.cloud_off, color: DeepFitColors.amber),
            const SizedBox(width: 12),
            const Expanded(child: Text('Saved on this phone. It uploads automatically when the server can be reached.')),
            TextButton(onPressed: _upload, child: const Text('Retry')),
          ]),
        );
    }
  }

  Widget _coachPanel(Map<String, dynamic> c) {
    final errs = [for (final e in (c['errors_per_try'] as List? ?? const [])) (e as num).toDouble()];
    final maxE = errs.isEmpty ? 1.0 : errs.reduce((a, b) => a > b ? a : b).clamp(1.0, 99.0);
    final tips = [for (final t in (c['tips'] as List? ?? const [])) t.toString()];
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('Errors per try (lower = learning)', style: TextStyle(fontWeight: FontWeight.w700)),
        const SizedBox(height: 10),
        SizedBox(
          height: 90,
          child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            for (var i = 0; i < errs.length; i++)
              Expanded(
                child: Column(mainAxisAlignment: MainAxisAlignment.end, children: [
                  Text(fmtValue(errs[i]), style: const TextStyle(fontSize: 12)),
                  Container(
                    height: 4 + 60 * errs[i] / maxE,
                    margin: const EdgeInsets.symmetric(horizontal: 6),
                    color: DeepFitColors.cyan,
                  ),
                  Text('${i + 1}', style: const TextStyle(color: DeepFitColors.muted, fontSize: 12)),
                ]),
              ),
          ]),
        ),
        if (c['reduction_pct'] != null) Text('Errors fell ${c['reduction_pct']}%.'),
        if (c['note'] != null) Text(c['note'].toString(), style: const TextStyle(color: DeepFitColors.amber)),
        const SizedBox(height: 6),
        for (final (i, t) in tips.indexed)
          Text('Tip after try ${i + 1}: $t', style: const TextStyle(color: DeepFitColors.muted, fontSize: 13)),
      ]),
    );
  }

  Widget _maturityPanel(Map<String, dynamic> m) {
    final off = m['maturity_offset'] as num?;
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('Growth', style: TextStyle(fontWeight: FontWeight.w700)),
        const SizedBox(height: 6),
        Text('Sitting height ${fmtValue(m['sitting_height_cm'])} cm · leg length ${fmtValue(m['leg_length_cm'])} cm'),
        if (off != null)
          Text('About ${off.abs().toStringAsFixed(1)} years ${off < 0 ? 'before' : 'after'} the growth spurt '
              '(${m['status']} developer).'),
        if (m['note'] != null)
          Text(m['note'].toString(), style: const TextStyle(color: DeepFitColors.muted, fontSize: 12)),
      ]),
    );
  }
}
