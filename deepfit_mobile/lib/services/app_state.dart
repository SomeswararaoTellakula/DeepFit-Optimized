// Everything the screens share: server address, login, cached test catalog, settings,
// and the upload queue.

import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'outbox.dart';

const appVersion = '1.0.0';
const testModes = ['standard', 'blind', 'deaf'];

/// One test from the server catalog (/api/v1/hub).
class TestInfo {
  final Map<String, dynamic> raw;
  const TestInfo(this.raw);

  String get key => raw['key'] as String;
  String get name => (raw['name'] ?? key) as String;
  String get icon => (raw['icon'] ?? '🏃') as String;
  String get category => (raw['category'] ?? '') as String;
  String get camera => (raw['camera'] ?? 'side') as String;
  String get kind => (raw['kind'] ?? (camera == 'none' ? 'stopwatch' : 'camera')) as String;
  String get unit => (raw['unit'] ?? '') as String;
  bool get higherIsBetter => raw['higher_is_better'] != false;
  bool get kheloIndia => raw['khelo_india'] == true;
  double? get duration => (raw['duration'] as num?)?.toDouble();
  String get counting => (raw['counting'] ?? '') as String;
  List<String> _list(String k) => [for (final x in (raw[k] as List? ?? const [])) x.toString()];
  List<String> get setup => _list('setup');
  List<String> get formCues => _list('form_cues');
  List<String> get blindAdaptation => _list('blind_adaptation');
  List<String> get deafAdaptation => _list('deaf_adaptation');
  Map<String, dynamic>? get last => (raw['last'] as Map?)?.cast<String, dynamic>();

  Map<String, dynamic>? targetFor(String mode) {
    final t = (raw['targets'] as Map?)?.cast<String, dynamic>();
    if (t == null) return null;
    return ((t[mode] ?? t['standard']) as Map?)?.cast<String, dynamic>();
  }
}

class SyncOutcome {
  final String status; // saved | rejected | failed | offline | auth
  final String? message;
  final Map<String, dynamic>? result; // server result (value, benchmark, passport_url, ...)
  final bool sameAsPhone;
  const SyncOutcome(this.status, {this.message, this.result, this.sameAsPhone = true});
}

class AppState extends ChangeNotifier {
  late SharedPreferences _prefs;
  final Outbox outbox = Outbox();
  late Api api;

  Map<String, dynamic>? athlete;
  Map<String, dynamic>? hub;
  String mode = 'standard';
  bool frontCamera = true;
  bool voice = true; // spoken counts in standard mode
  bool? lrSwapOverride; // null = automatic; set by the left/right check
  int pending = 0;
  bool online = false;
  String? lastError;
  bool _syncing = false;
  final Map<String, SyncOutcome> outcomes = {}; // outbox id -> what the server said

  bool get loggedIn => api.token != null && athlete != null;
  bool get syncing => _syncing;
  String get serverUrl => api.baseUrl;
  bool get requireFace => hub?['require_face'] != false;
  double get faceHiddenSeconds => ((hub?['face_hidden_seconds'] ?? 15) as num).toDouble();
  double get heightCm => ((hub?['height_cm'] ?? 165) as num).toDouble();
  String get firstName => ((athlete?['name'] ?? 'Athlete') as String).split(' ').first;

  /// iOS delivers the front camera mirrored (and left/right labels swapped); Android does not.
  bool mirroredStream(bool front) => lrSwapOverride ?? (Platform.isIOS && front);

  List<TestInfo> get tests => [for (final t in (hub?['tests'] as List? ?? const [])) TestInfo((t as Map).cast<String, dynamic>())];

  TestInfo? test(String key) {
    for (final t in tests) {
      if (t.key == key) return t;
    }
    return null;
  }

  Future<void> load() async {
    _prefs = await SharedPreferences.getInstance();
    api = Api(_prefs.getString('server') ?? '', token: _prefs.getString('token'));
    athlete = _json(_prefs.getString('athlete'));
    hub = _json(_prefs.getString('hub'));
    mode = _prefs.getString('mode') ?? 'standard';
    frontCamera = _prefs.getBool('front') ?? true;
    voice = _prefs.getBool('voice') ?? true;
    lrSwapOverride = _prefs.containsKey('lr_swap') ? _prefs.getBool('lr_swap') : null;
    pending = await outbox.count();
    if (loggedIn) unawaited(refresh());
  }

  static Map<String, dynamic>? _json(String? s) {
    if (s == null) return null;
    try {
      return (jsonDecode(s) as Map).cast<String, dynamic>();
    } catch (_) {
      return null;
    }
  }

  Future<void> setServer(String url) async {
    api.baseUrl = Api.normalizeUrl(url);
    await _prefs.setString('server', api.baseUrl);
    notifyListeners();
  }

  Future<Map<String, dynamic>> ping() => api.get('/ping', timeout: const Duration(seconds: 6));

  Future<void> _signedIn(Map<String, dynamic> r) async {
    api.token = r['token'] as String;
    athlete = (r['athlete'] as Map).cast<String, dynamic>();
    await _prefs.setString('token', api.token!);
    await _prefs.setString('athlete', jsonEncode(athlete));
    await refresh();
  }

  Future<void> login(String email, String password) async {
    final r = await api.post('/auth/login', {'email': email, 'password': password});
    await _signedIn(r);
  }

  Future<void> register(Map<String, dynamic> form) async {
    final r = await api.post('/auth/register', form, timeout: const Duration(seconds: 40));
    await _signedIn(r);
  }

  Future<void> logout() async {
    api.token = null;
    athlete = null;
    hub = null;
    await _prefs.remove('token');
    await _prefs.remove('athlete');
    await _prefs.remove('hub');
    notifyListeners();
  }

  Future<void> setMode(String m) async {
    if (!testModes.contains(m)) return;
    mode = m;
    await _prefs.setString('mode', m);
    notifyListeners();
    unawaited(refresh());
  }

  Future<void> setFrontCamera(bool v) async {
    frontCamera = v;
    await _prefs.setBool('front', v);
    notifyListeners();
  }

  Future<void> setVoice(bool v) async {
    voice = v;
    await _prefs.setBool('voice', v);
    notifyListeners();
  }

  Future<void> setLrSwap(bool? v) async {
    lrSwapOverride = v;
    if (v == null) {
      await _prefs.remove('lr_swap');
    } else {
      await _prefs.setBool('lr_swap', v);
    }
    notifyListeners();
  }

  /// Reload the catalog + progress and upload anything waiting.
  Future<void> refresh() async {
    if (!loggedIn) return;
    try {
      final h = await api.get('/hub', query: {'mode': mode});
      hub = h;
      athlete = (h['athlete'] as Map?)?.cast<String, dynamic>() ?? athlete;
      await _prefs.setString('hub', jsonEncode(h));
      await _prefs.setString('athlete', jsonEncode(athlete));
      online = true;
      lastError = null;
    } on ApiException catch (e) {
      online = !e.offline;
      lastError = e.message;
      if (e.auth) {
        await logout();
        return;
      }
    }
    notifyListeners();
    if (online) unawaited(syncAll());
  }

  Future<void> addToOutbox(OutboxItem item) async {
    await outbox.add(item);
    pending = await outbox.count();
    notifyListeners();
  }

  Future<SyncOutcome> syncOne(String id) async {
    final item = await outbox.get(id);
    if (item == null) return outcomes[id] ?? const SyncOutcome('failed', message: 'Already uploaded.');
    final out = await _upload(item);
    pending = await outbox.count();
    notifyListeners();
    return out;
  }

  Future<void> syncAll() async {
    if (_syncing || !loggedIn) return;
    _syncing = true;
    notifyListeners();
    try {
      for (final item in await outbox.list()) {
        if (item.error != null) continue; // refused before - the athlete decides (retake / delete)
        final o = await _upload(item);
        if (o.status == 'offline' || o.status == 'auth') break;
      }
    } finally {
      _syncing = false;
      pending = await outbox.count();
      notifyListeners();
    }
  }

  Future<SyncOutcome> _upload(OutboxItem item) async {
    try {
      final path = item.kind == 'height_weight' ? '/height_weight' : '/results';
      final r = await api.post(path, item.body, timeout: const Duration(seconds: 120), compress: true);
      online = true;
      final status = (r['status'] ?? 'saved') as String;
      final outcome = SyncOutcome(status,
          message: r['message'] as String?,
          result: (r['result'] as Map?)?.cast<String, dynamic>() ?? (item.kind == 'height_weight' ? r : null),
          sameAsPhone: r['same_as_phone'] != false);
      outcomes[item.id] = outcome;
      await outbox.remove(item.id);
      if (item.kind == 'height_weight' && r['height_cm'] != null && hub != null) {
        hub!['height_cm'] = r['height_cm'];
      }
      unawaited(refresh());
      return outcome;
    } on ApiException catch (e) {
      if (e.offline) {
        online = false;
        return SyncOutcome('offline', message: e.message);
      }
      if (e.auth) return SyncOutcome('auth', message: e.message);
      // the server refused this upload (bad data): keep it with the reason
      item.error = e.message;
      await outbox.update(item);
      final o = SyncOutcome('failed', message: e.message);
      outcomes[item.id] = o;
      return o;
    }
  }

  Future<void> discard(String id) async {
    await outbox.remove(id);
    pending = await outbox.count();
    notifyListeners();
  }
}

/// Gives every screen access to the AppState and rebuilds them when it changes.
class AppScope extends InheritedNotifier<AppState> {
  const AppScope({super.key, required AppState state, required super.child}) : super(notifier: state);

  static AppState of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<AppScope>()!.notifier!;

  /// Read without subscribing to changes (for callbacks).
  static AppState read(BuildContext context) =>
      (context.getElementForInheritedWidgetOfExactType<AppScope>()!.widget as AppScope).notifier!;
}
