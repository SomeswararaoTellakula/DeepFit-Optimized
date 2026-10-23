import 'package:flutter/material.dart';

import '../app.dart';
import '../services/api.dart';
import '../services/app_state.dart';
import '../services/outbox.dart';
import '../widgets/common.dart';
import 'lr_check_screen.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _server = TextEditingController();
  String? _serverMsg;
  List<OutboxItem> _items = [];

  @override
  void initState() {
    super.initState();
    final state = AppScope.read(context);
    _server.text = state.serverUrl;
    _reload();
  }

  @override
  void dispose() {
    _server.dispose();
    super.dispose();
  }

  Future<void> _reload() async {
    final items = await AppScope.read(context).outbox.list();
    if (mounted) setState(() => _items = items);
  }

  Future<void> _testServer() async {
    final state = AppScope.read(context);
    await state.setServer(_server.text);
    try {
      final r = await state.ping();
      setState(() => _serverMsg = '✓ Connected (${r['server']}, phone API v${r['api']})');
      await state.refresh();
    } on ApiException catch (e) {
      setState(() => _serverMsg = '✗ ${e.message}');
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        const SectionTitle('Athlete'),
        Panel(
          child: Text('${state.athlete?['name'] ?? ''} · ${state.athlete?['email'] ?? ''}\n'
              'Age ${state.athlete?['age'] ?? '-'} · ${state.athlete?['gender'] ?? ''} · ${state.athlete?['place'] ?? ''}'),
        ),
        const SectionTitle('Uploads waiting'),
        if (_items.isEmpty)
          const Panel(child: Text('Everything is uploaded.'))
        else ...[
          for (final it in _items)
            Panel(
              borderColor: it.error != null ? DeepFitColors.red : null,
              child: Row(children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(it.name, style: const TextStyle(fontWeight: FontWeight.w700)),
                    Text('${it.created.toLocal().toString().substring(0, 16)} · '
                        '${it.local['value'] != null ? '${fmtValue(it.local['value'])} ${it.local['unit'] ?? ''}' : ''}'),
                    if (it.error != null) Text(it.error!, style: const TextStyle(color: DeepFitColors.red)),
                  ]),
                ),
                IconButton(
                  tooltip: 'Delete',
                  icon: const Icon(Icons.delete_outline),
                  onPressed: () async {
                    await state.discard(it.id);
                    _reload();
                  },
                ),
              ]),
            ),
          FilledButton.icon(
            onPressed: state.syncing
                ? null
                : () async {
                    // items refused before are retried too (e.g. after the server was updated)
                    for (final it in _items.where((i) => i.error != null)) {
                      it.error = null;
                      await state.outbox.update(it);
                    }
                    await state.syncAll();
                    _reload();
                  },
            icon: const Icon(Icons.cloud_upload),
            label: Text(state.syncing ? 'Uploading…' : 'Upload now'),
          ),
        ],
        const SectionTitle('Test settings'),
        Panel(
          child: Column(children: [
            const ModeSelector(),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Spoken counts in Standard mode'),
              subtitle: const Text('Blind mode always speaks; Deaf mode never does.'),
              value: state.voice,
              onChanged: state.setVoice,
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Use the front (selfie) camera'),
              value: state.frontCamera,
              onChanged: state.setFrontCamera,
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Left / right camera check'),
              subtitle: Text(state.lrSwapOverride == null ? 'Not done yet (automatic)' : 'Done on this phone'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const LrCheckScreen())),
            ),
          ]),
        ),
        const SectionTitle('Server'),
        Panel(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            TextField(controller: _server, keyboardType: TextInputType.url, decoration: deco('DeepFit server address')),
            const SizedBox(height: 8),
            TextButton.icon(onPressed: _testServer, icon: const Icon(Icons.wifi_tethering), label: const Text('Save & test')),
            if (_serverMsg != null) Text(_serverMsg!),
          ]),
        ),
        const SectionTitle('Privacy'),
        const Panel(
          child: Text('Videos are never uploaded or stored. The phone sends only the skeleton (33 body points per frame) '
              'and a few small face snapshots, which the server uses for the identity check and then discards.'),
        ),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          onPressed: () async {
            await state.logout();
            if (context.mounted) Navigator.of(context).popUntil((r) => r.isFirst);
          },
          icon: const Icon(Icons.logout),
          label: const Text('Sign out'),
        ),
        const SizedBox(height: 8),
        const Center(child: Text('DeepFit $appVersion', style: TextStyle(color: DeepFitColors.muted))),
      ]),
    );
  }
}
