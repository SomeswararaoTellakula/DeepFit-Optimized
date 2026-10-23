import 'package:flutter/material.dart';

import '../app.dart';
import '../services/api.dart';
import '../services/app_state.dart';
import '../widgets/common.dart';
import 'register_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _server = TextEditingController();
  bool _busy = false;
  bool _showServer = false;
  String? _serverStatus;

  @override
  void initState() {
    super.initState();
    final state = AppScope.read(context);
    _server.text = state.serverUrl;
    _showServer = state.serverUrl.isEmpty;
  }

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _server.dispose();
    super.dispose();
  }

  Future<bool> _saveServer() async {
    final state = AppScope.read(context);
    if (_server.text.trim().isEmpty) {
      setState(() => _serverStatus = 'Enter the address of the DeepFit server first.');
      return false;
    }
    await state.setServer(_server.text);
    try {
      final r = await state.ping();
      setState(() => _serverStatus = '✓ Connected to ${r['server'] ?? 'DeepFit'} (face check ${r['require_face'] == true ? 'on' : 'off'})');
      return true;
    } on ApiException catch (e) {
      setState(() => _serverStatus = '✗ ${e.message}');
      return false;
    }
  }

  Future<void> _login() async {
    if (_busy) return;
    setState(() => _busy = true);
    final state = AppScope.read(context);
    try {
      if (_showServer || state.serverUrl.isEmpty) {
        if (!await _saveServer()) return;
      }
      await state.login(_email.text.trim(), _password.text);
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            const SizedBox(height: 24),
            const Text('DeepFit', style: TextStyle(fontSize: 40, fontWeight: FontWeight.w900, color: DeepFitColors.cyan)),
            const Text('AI sports talent assessment - works offline, verified by face and skeleton.',
                style: TextStyle(color: DeepFitColors.muted, fontSize: 15)),
            const SizedBox(height: 32),
            TextField(
              controller: _email,
              keyboardType: TextInputType.emailAddress,
              autofillHints: const [AutofillHints.email],
              decoration: deco('Email'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _password,
              obscureText: true,
              autofillHints: const [AutofillHints.password],
              decoration: deco('Password'),
              onSubmitted: (_) => _login(),
            ),
            const SizedBox(height: 20),
            FilledButton(onPressed: _busy ? null : _login, child: Text(_busy ? 'Signing in…' : 'Sign in')),
            const SizedBox(height: 12),
            OutlinedButton(
              onPressed: _busy
                  ? null
                  : () async {
                      if (_showServer && !await _saveServer()) return;
                      if (!context.mounted) return;
                      Navigator.of(context).push(MaterialPageRoute(builder: (_) => const RegisterScreen()));
                    },
              child: const Text('New athlete? Register'),
            ),
            const SizedBox(height: 28),
            InkWell(
              onTap: () => setState(() => _showServer = !_showServer),
              child: Row(children: [
                const Icon(Icons.dns, size: 18, color: DeepFitColors.muted),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(state.serverUrl.isEmpty ? 'Server: not set' : 'Server: ${state.serverUrl}',
                      style: const TextStyle(color: DeepFitColors.muted)),
                ),
                Icon(_showServer ? Icons.expand_less : Icons.expand_more, color: DeepFitColors.muted),
              ]),
            ),
            if (_showServer) ...[
              const SizedBox(height: 12),
              TextField(
                controller: _server,
                keyboardType: TextInputType.url,
                decoration: deco('DeepFit server address', hint: 'http://192.168.1.5:7860'),
              ),
              const SizedBox(height: 8),
              const Text(
                'The address of the computer running the DeepFit website (python app.py). '
                'On the same Wi-Fi use its local IP and port 7860.',
                style: TextStyle(color: DeepFitColors.muted, fontSize: 13),
              ),
              const SizedBox(height: 8),
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                    onPressed: _saveServer, icon: const Icon(Icons.wifi_tethering), label: const Text('Test connection')),
              ),
              if (_serverStatus != null) Text(_serverStatus!),
            ],
          ],
        ),
      ),
    );
  }
}
