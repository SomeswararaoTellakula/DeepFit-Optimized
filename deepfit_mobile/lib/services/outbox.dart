// Results waiting to be uploaded. Tests work offline: each finished test is written
// to a file first, then uploaded whenever the server can be reached.

import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:path_provider/path_provider.dart';

class OutboxItem {
  final String id;
  final String kind; // result | height_weight
  final String exercise;
  final String name;
  final DateTime created;
  final Map<String, dynamic> body; // exactly what is POSTed
  final Map<String, dynamic> local; // what the phone showed (value, unit, rating)
  String? error; // the server refused it (kept so the athlete can see why)

  OutboxItem({
    required this.id,
    required this.kind,
    required this.exercise,
    required this.name,
    required this.created,
    required this.body,
    required this.local,
    this.error,
  });

  Map<String, dynamic> toJson() => {
        'id': id,
        'kind': kind,
        'exercise': exercise,
        'name': name,
        'created': created.toIso8601String(),
        'body': body,
        'local': local,
        'error': error,
      };

  factory OutboxItem.fromJson(Map<String, dynamic> j) => OutboxItem(
        id: j['id'] as String,
        kind: (j['kind'] ?? 'result') as String,
        exercise: (j['exercise'] ?? '') as String,
        name: (j['name'] ?? '') as String,
        created: DateTime.tryParse((j['created'] ?? '') as String) ?? DateTime.now(),
        body: (j['body'] as Map).cast<String, dynamic>(),
        local: ((j['local'] ?? const {}) as Map).cast<String, dynamic>(),
        error: j['error'] as String?,
      );
}

class Outbox {
  Directory? _dir;

  Future<Directory> _folder() async {
    if (_dir != null) return _dir!;
    final docs = await getApplicationDocumentsDirectory();
    final d = Directory('${docs.path}/deepfit_outbox');
    if (!await d.exists()) await d.create(recursive: true);
    return _dir = d;
  }

  static String newId() {
    final r = math.Random.secure();
    final rand = List.generate(8, (_) => r.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
    return '${DateTime.now().millisecondsSinceEpoch}-$rand';
  }

  Future<void> add(OutboxItem item) async {
    final d = await _folder();
    final f = File('${d.path}/${item.id}.json');
    final tmp = File('${f.path}.tmp');
    await tmp.writeAsString(jsonEncode(item.toJson()), flush: true);
    await tmp.rename(f.path); // atomic: a crash never leaves half a file
  }

  Future<void> update(OutboxItem item) => add(item);

  Future<List<OutboxItem>> list() async {
    final d = await _folder();
    final items = <OutboxItem>[];
    await for (final e in d.list()) {
      if (e is File && e.path.endsWith('.json')) {
        try {
          items.add(OutboxItem.fromJson(jsonDecode(await e.readAsString()) as Map<String, dynamic>));
        } catch (_) {
          // unreadable file: leave it, it will be visible in the folder for support
        }
      }
    }
    items.sort((a, b) => a.created.compareTo(b.created));
    return items;
  }

  Future<OutboxItem?> get(String id) async {
    final d = await _folder();
    final f = File('${d.path}/$id.json');
    if (!await f.exists()) return null;
    return OutboxItem.fromJson(jsonDecode(await f.readAsString()) as Map<String, dynamic>);
  }

  Future<void> remove(String id) async {
    final d = await _folder();
    final f = File('${d.path}/$id.json');
    if (await f.exists()) await f.delete();
  }

  Future<int> count() async => (await list()).length;
}
