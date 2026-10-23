import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

import '../app.dart';
import '../services/app_state.dart';

class Panel extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry padding;
  final Color? color;
  final Color? borderColor;
  const Panel({super.key, required this.child, this.padding = const EdgeInsets.all(16), this.color, this.borderColor});

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.symmetric(vertical: 6),
        padding: padding,
        decoration: BoxDecoration(
          color: color ?? DeepFitColors.panel,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: borderColor ?? Colors.white10),
        ),
        child: child,
      );
}

InputDecoration deco(String label, {String? hint, String? suffix}) =>
    InputDecoration(labelText: label, hintText: hint, suffixText: suffix, border: const OutlineInputBorder());

void toast(BuildContext context, String msg) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(msg)));
}

class SectionTitle extends StatelessWidget {
  final String text;
  const SectionTitle(this.text, {super.key});
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 16, 4, 4),
        child: Text(text.toUpperCase(),
            style: const TextStyle(color: DeepFitColors.muted, fontWeight: FontWeight.w700, letterSpacing: 1.1, fontSize: 12)),
      );
}

class RatingChip extends StatelessWidget {
  final String? rating;
  const RatingChip(this.rating, {super.key});
  @override
  Widget build(BuildContext context) {
    if (rating == null) return const SizedBox.shrink();
    final c = DeepFitColors.rating(rating);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: c.withAlpha(40), borderRadius: BorderRadius.circular(20), border: Border.all(color: c)),
      child: Text(rating!, style: TextStyle(color: c, fontSize: 12, fontWeight: FontWeight.w700)),
    );
  }
}

/// Standard / Blind / Deaf - changes how a test talks to the athlete and which benchmark is used.
class ModeSelector extends StatelessWidget {
  const ModeSelector({super.key});
  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    return SegmentedButton<String>(
      segments: const [
        ButtonSegment(value: 'standard', label: Text('Standard'), icon: Icon(Icons.person)),
        ButtonSegment(value: 'blind', label: Text('Blind'), icon: Icon(Icons.hearing)),
        ButtonSegment(value: 'deaf', label: Text('Deaf'), icon: Icon(Icons.visibility)),
      ],
      selected: {state.mode},
      showSelectedIcon: false,
      onSelectionChanged: (s) => state.setMode(s.first),
    );
  }
}

String fmtValue(Object? v) {
  if (v is! num) return '-';
  final d = v.toDouble();
  if (d == d.roundToDouble()) return d.toInt().toString();
  return d.toStringAsFixed(1);
}

Future<void> openLink(BuildContext context, String url) async {
  final ok = await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
  if (!ok && context.mounted) toast(context, 'Could not open the link.');
}

/// QR code + buttons for a Talent Passport link.
Future<void> showPassportSheet(BuildContext context, String url, {String title = 'Talent Passport'}) {
  return showModalBottomSheet(
    context: context,
    backgroundColor: DeepFitColors.panel,
    showDragHandle: true,
    builder: (ctx) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          const Text('A scout scans this code to see the verified result, the face-check evidence and a skeleton-only replay.',
              textAlign: TextAlign.center, style: TextStyle(color: DeepFitColors.muted)),
          const SizedBox(height: 16),
          Container(
            color: Colors.white,
            padding: const EdgeInsets.all(10),
            child: QrImageView(data: url, size: 200, backgroundColor: Colors.white),
          ),
          const SizedBox(height: 16),
          Row(children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: () {
                  Clipboard.setData(ClipboardData(text: url));
                  toast(ctx, 'Link copied');
                },
                icon: const Icon(Icons.copy),
                label: const Text('Copy link'),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: FilledButton.icon(
                onPressed: () => openLink(ctx, url),
                icon: const Icon(Icons.open_in_new),
                label: const Text('Open'),
              ),
            ),
          ]),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: TextButton.icon(
              onPressed: () => openLink(ctx, '$url/card'),
              icon: const Icon(Icons.print),
              label: const Text('Printable card (save as PDF)'),
            ),
          ),
          if (url.contains('://192.168.') || url.contains('://10.') || url.contains('localhost'))
            const Padding(
              padding: EdgeInsets.only(top: 10),
              child: Text('This link uses a local network address - it opens only on the same Wi-Fi as the server.',
                  textAlign: TextAlign.center, style: TextStyle(color: DeepFitColors.amber, fontSize: 12)),
            ),
        ]),
      ),
    ),
  );
}

/// "3 results waiting to upload" + Sync now.
class PendingBanner extends StatelessWidget {
  const PendingBanner({super.key});
  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    if (state.pending == 0) return const SizedBox.shrink();
    return Panel(
      borderColor: DeepFitColors.amber,
      child: Row(children: [
        const Icon(Icons.cloud_upload, color: DeepFitColors.amber),
        const SizedBox(width: 12),
        Expanded(
          child: Text(
              '${state.pending} result${state.pending == 1 ? '' : 's'} saved on this phone, waiting to upload.'
              '${state.online ? '' : ' (offline)'}'),
        ),
        TextButton(
          onPressed: state.syncing ? null : () => state.syncAll(),
          child: Text(state.syncing ? 'Uploading…' : 'Sync now'),
        ),
      ]),
    );
  }
}
