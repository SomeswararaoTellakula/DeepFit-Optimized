import 'package:deepfit_mobile/services/api.dart';
import 'package:deepfit_mobile/services/tones.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('server address is normalised', () {
    expect(Api.normalizeUrl(' 192.168.1.5:7860/ '), 'http://192.168.1.5:7860');
    expect(Api.normalizeUrl('https://deepfit.example.org'), 'https://deepfit.example.org');
  });

  test('audio mirror tones are valid WAV files', () {
    final wav = wavTone(440, 100);
    expect(String.fromCharCodes(wav.sublist(0, 4)), 'RIFF');
    expect(String.fromCharCodes(wav.sublist(8, 12)), 'WAVE');
    expect(wav.length, 44 + 2 * (22050 * 100 ~/ 1000));
  });
}
