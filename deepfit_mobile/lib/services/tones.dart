// Beeps and the AUDIO MIRROR for blind athletes.
//
// Audio mirror (same idea as the website): the closer the body is to the correct
// position, the higher and faster the ticks - like a car's parking sensor. When the
// position is right (>= 95%) it turns into a steady, gently pulsing high tone.
// The tone pauses while the phone is speaking.

import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:path_provider/path_provider.dart';

class Tones {
  final List<AudioPlayer> _ticks = [AudioPlayer(), AudioPlayer(), AudioPlayer()];
  final AudioPlayer _loop = AudioPlayer();
  final Map<String, String> _files = {};
  int _next = 0;
  bool _ready = false;
  bool _loopOn = false;
  DateTime _lastTick = DateTime(2000);

  static const mirrorSteps = 8; // 220 Hz ... 880 Hz

  Future<void> init() async {
    if (_ready) return;
    _ready = true;
    try {
      final dir = await getTemporaryDirectory();
      Future<void> make(String name, double freq, int ms, {bool loop = false}) async {
        final f = File('${dir.path}/deepfit_$name.wav');
        if (!await f.exists()) await f.writeAsBytes(wavTone(freq, ms, loop: loop), flush: true);
        _files[name] = f.path;
      }

      for (var i = 0; i < mirrorSteps; i++) {
        await make('m$i', 220 * math.pow(2, 2 * i / (mirrorSteps - 1)).toDouble(), 70);
      }
      await make('perfect', 880, 1000, loop: true);
      for (final b in const [(250, 250), (300, 90), (700, 60), (900, 60), (1000, 250), (1100, 90), (1200, 90)]) {
        await make('b${b.$1}_${b.$2}', b.$1.toDouble(), b.$2);
      }
      for (final p in _ticks) {
        await p.setReleaseMode(ReleaseMode.stop);
        if (Platform.isAndroid) await p.setPlayerMode(PlayerMode.lowLatency);
      }
      await _loop.setReleaseMode(ReleaseMode.loop);
    } catch (_) {
      // no audio output available: the visual meter still works
    }
  }

  Future<void> _play(String name, double volume) async {
    final path = _files[name];
    if (path == null) return;
    final p = _ticks[_next];
    _next = (_next + 1) % _ticks.length;
    try {
      await p.stop();
      await p.play(DeviceFileSource(path), volume: volume);
    } catch (_) {}
  }

  /// Short beep (only the frequencies listed in init are available).
  Future<void> beep(int freq, int ms) => _play('b${freq}_$ms', 0.6);

  /// Call on every processed frame with the exercise's mirror value (null = silence).
  Future<void> mirror(double? v, {bool speaking = false}) async {
    if (v == null || speaking) {
      await _stopLoop();
      return;
    }
    if (v >= 0.95) {
      if (!_loopOn) {
        _loopOn = true;
        final path = _files['perfect'];
        if (path != null) {
          try {
            await _loop.play(DeviceFileSource(path), volume: 0.35);
          } catch (_) {}
        }
      }
      return;
    }
    await _stopLoop();
    final now = DateTime.now();
    final gapMs = (650 - 450 * v).round(); // closer = faster ticks
    if (now.difference(_lastTick).inMilliseconds < gapMs) return;
    _lastTick = now;
    final step = math.min(mirrorSteps - 1, math.max(0, (v * (mirrorSteps - 1)).round()));
    await _play('m$step', 0.45);
  }

  Future<void> _stopLoop() async {
    if (!_loopOn) return;
    _loopOn = false;
    try {
      await _loop.stop();
    } catch (_) {}
  }

  Future<void> silence() => _stopLoop();

  Future<void> dispose() async {
    await _stopLoop();
    for (final p in [..._ticks, _loop]) {
      try {
        await p.dispose();
      } catch (_) {}
    }
  }
}

/// 16-bit mono PCM WAV with a sine tone. [loop] = no fade, gentle 4 Hz pulse, whole cycles.
Uint8List wavTone(double freq, int ms, {bool loop = false, double volume = 0.6}) {
  const rate = 22050;
  final n = rate * ms ~/ 1000;
  final data = ByteData(44 + n * 2);
  void str(int off, String s) {
    for (var i = 0; i < s.length; i++) {
      data.setUint8(off + i, s.codeUnitAt(i));
    }
  }

  str(0, 'RIFF');
  data.setUint32(4, 36 + n * 2, Endian.little);
  str(8, 'WAVE');
  str(12, 'fmt ');
  data.setUint32(16, 16, Endian.little);
  data.setUint16(20, 1, Endian.little); // PCM
  data.setUint16(22, 1, Endian.little); // mono
  data.setUint32(24, rate, Endian.little);
  data.setUint32(28, rate * 2, Endian.little);
  data.setUint16(32, 2, Endian.little);
  data.setUint16(34, 16, Endian.little);
  str(36, 'data');
  data.setUint32(40, n * 2, Endian.little);
  final fade = math.max(1, math.min(n ~/ 4, rate ~/ 100)); // 10 ms fade in/out (no clicks)
  for (var i = 0; i < n; i++) {
    var env = 1.0;
    if (!loop) {
      if (i < fade) {
        env = i / fade;
      } else if (i > n - fade) {
        env = (n - i) / fade;
      }
    } else {
      env = 0.65 + 0.35 * math.sin(2 * math.pi * 4 * i / rate);
    }
    final s = math.sin(2 * math.pi * freq * i / rate) * env * volume;
    final q = (s * 32767).round();
    data.setInt16(44 + i * 2, q < -32768 ? -32768 : (q > 32767 ? 32767 : q), Endian.little);
  }
  return data.buffer.asUint8List();
}
