// Text-to-speech for blind athletes (and spoken counts for everyone else).

import 'dart:io' show Platform;

import 'package:flutter_tts/flutter_tts.dart';

class Speech {
  final FlutterTts _tts = FlutterTts();
  bool speaking = false;
  bool _ready = false;

  Future<void> init() async {
    if (_ready) return;
    _ready = true;
    _tts.setStartHandler(() => speaking = true);
    _tts.setCompletionHandler(() => speaking = false);
    _tts.setCancelHandler(() => speaking = false);
    _tts.setErrorHandler((_) => speaking = false);
    try {
      if (Platform.isIOS) {
        await _tts.setSharedInstance(true);
        // speak even when the ring/silent switch is on, and mix with the tones
        await _tts.setIosAudioCategory(
            IosTextToSpeechAudioCategory.playback, [IosTextToSpeechAudioCategoryOptions.mixWithOthers]);
      }
      final ok = await _tts.isLanguageAvailable('en-IN');
      await _tts.setLanguage(ok == true ? 'en-IN' : 'en-US');
      await _tts.setSpeechRate(0.5);
      await _tts.setVolume(1.0);
      await _tts.awaitSpeakCompletion(false);
    } catch (_) {
      // a phone without a TTS voice still works - captions and tones carry the information
    }
  }

  Future<void> say(String text, {bool interrupt = false}) async {
    if (text.trim().isEmpty) return;
    await init();
    try {
      if (interrupt) await _tts.stop();
      await _tts.speak(text);
    } catch (_) {}
  }

  Future<void> stop() async {
    try {
      await _tts.stop();
    } catch (_) {}
    speaking = false;
  }
}
