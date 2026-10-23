import 'package:flutter/material.dart';

import '../app.dart';
import '../services/api.dart';
import '../services/app_state.dart';

/// The DeepFit AI coach (same chatbot as the website; it can read your own results).
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});
  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final List<(bool, String)> _messages = [
    (false, 'Hi! I am your DeepFit coach. Ask me about your results, what to train next, or how a test works.'),
  ];
  bool _busy = false;

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty || _busy) return;
    _input.clear();
    setState(() {
      _messages.add((true, text));
      _busy = true;
    });
    _toEnd();
    final state = AppScope.read(context);
    try {
      final r = await state.api.post('/chat', {'message': text}, timeout: const Duration(seconds: 90));
      _messages.add((false, (r['response'] ?? '') as String));
    } on ApiException catch (e) {
      _messages.add((false, '⚠️ ${e.message}'));
    }
    if (!mounted) return;
    setState(() => _busy = false);
    _toEnd();
  }

  void _toEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) _scroll.animateTo(_scroll.position.maxScrollExtent, duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('AI coach'), actions: [
        IconButton(
          tooltip: 'New conversation',
          icon: const Icon(Icons.refresh),
          onPressed: () async {
            final state = AppScope.read(context);
            try {
              await state.api.post('/chat/reset', {});
            } on ApiException {
              // offline: the local history is cleared anyway
            }
            if (mounted) setState(() => _messages.removeRange(1, _messages.length));
          },
        ),
      ]),
      body: SafeArea(
        child: Column(children: [
          Expanded(
            child: ListView.builder(
              controller: _scroll,
              padding: const EdgeInsets.all(12),
              itemCount: _messages.length + (_busy ? 1 : 0),
              itemBuilder: (_, i) {
                if (i == _messages.length) {
                  return const Padding(padding: EdgeInsets.all(12), child: Text('Coach is typing…', style: TextStyle(color: DeepFitColors.muted)));
                }
                final (mine, text) = _messages[i];
                return Align(
                  alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
                  child: Container(
                    constraints: const BoxConstraints(maxWidth: 320),
                    margin: const EdgeInsets.symmetric(vertical: 4),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: mine ? DeepFitColors.cyan.withAlpha(60) : DeepFitColors.panel,
                      borderRadius: BorderRadius.circular(14),
                    ),
                    child: SelectableText(text.replaceAll('**', '')),
                  ),
                );
              },
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(8),
            child: Row(children: [
              Expanded(
                child: TextField(
                  controller: _input,
                  minLines: 1,
                  maxLines: 4,
                  textInputAction: TextInputAction.send,
                  onSubmitted: (_) => _send(),
                  decoration: const InputDecoration(hintText: 'Ask the coach…', border: OutlineInputBorder()),
                ),
              ),
              IconButton.filled(onPressed: _busy ? null : _send, icon: const Icon(Icons.send)),
            ]),
          ),
        ]),
      ),
    );
  }
}
