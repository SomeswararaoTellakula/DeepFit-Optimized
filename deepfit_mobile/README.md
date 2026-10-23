# DeepFit phone app (Flutter, Android + iOS)

The phone app for DeepFit (SIH 2025, PS 25073). The **website stays exactly as it is** - it
also becomes the app's server: the app talks to the same Flask server (`python app.py`), the
same login and the same MongoDB, through new `/api/v1/...` endpoints (`mobile_api.py`).

## What the app does

| | |
|---|---|
| **All 18 tests** | Same order and targets as the website's All Tests page: Khelo India battery, Coachability Challenge, Growth Measures, coach-timed runs, height & weight. |
| **On-device AI** | Camera + Google ML Kit body tracking (the same 33 BlazePose points as MediaPipe on the website). Reps are counted on the phone by `lib/engine/` - a line-by-line Dart copy of `exercise_engine.py`. |
| **Works offline** | A finished test is saved on the phone first and uploads when the server can be reached (pull down on the home screen or *Settings → Upload now*). |
| **Only the registered athlete** | Face check before the test and a snapshot every 3 s during it. Online: 3 mismatches in a row stop the test, like the website. Offline: the server checks every snapshot at upload and refuses the result if the face doesn't match. |
| **Can't be faked by a modified app** | The phone uploads the skeleton track, not just the score. The server **re-runs the Python engine** on it and saves *its own* number. If the phone said something else, the result card says so. |
| **Talent Passport** | After upload: QR code + link to the signed result page (face evidence + skeleton replay). |
| **Blind mode** | Everything is spoken, big double-tap start/stop, beeps, **audio mirror** (ticks rise and speed up as the body gets closer to the right position, steady tone when perfect). |
| **Deaf mode** | Big countdown, green flash on every rep, red border on faults, large captions, vibration. |
| **Hidden Potential + AI coach** | Same report and chatbot as the website. |
| **Privacy** | No video is uploaded or stored. Face snapshots are only used for the check. |

## Run it (first time)

1. **Install Flutter** (once): <https://docs.flutter.dev/get-started/install> - on a Mac also
   Xcode (for iPhone) and/or Android Studio (for Android). Check with `flutter doctor`.
2. **Start the DeepFit server** on your computer as usual:
   ```
   cd "SIH_FinalApp 2/SIH-7/HeightAndWeightCalculator"
   source venv312/bin/activate
   python app.py
   ```
   Find the computer's Wi-Fi address: `ipconfig getifaddr en0` (Mac), e.g. `192.168.1.5`.
3. **Set up the app** (adds the android/ and ios/ folders, permissions, runs the tests):
   ```
   cd deepfit_mobile
   bash tool/setup.sh
   ```
4. **Run it** on a phone connected by USB (Android: developer options → USB debugging;
   iPhone: open `ios/Runner.xcworkspace` in Xcode once and pick your team under *Signing*):
   ```
   flutter run
   ```
5. In the app, open **Server** on the sign-in screen and enter `http://192.168.1.5:7860`
   (your computer's address; phone and computer on the same Wi-Fi), then sign in with a
   website account or register a new athlete.

> ML Kit does not run in the iOS Simulator on Apple-silicon Macs - use a real iPhone or an
> Android phone / emulator.

## Checks

```
flutter test                                   # engine parity + small unit tests
flutter test test/engine_parity_test.dart      # Dart engine == Python engine (30 recorded movements)
```

If you change a threshold, change it in **both** `exercise_engine.py` (server) and
`lib/engine/` (phone), then regenerate the fixtures: `python3 tool/make_fixtures.py`.

## Publishing (Play Store / App Store)

* Put the server on a public **https** address (set `PUBLIC_BASE_URL` in the server's `.env`
  so QR codes use it), and remove `NSAllowsArbitraryLoads` from `ios/Runner/Info.plist` and
  `usesCleartextTraffic` from the Android manifest.
* Change the app id `in.deepfit.deepfit_mobile` if you own another domain, add an app icon,
  then `flutter build appbundle` (Play Store) / `flutter build ipa` (App Store).
* Store listings need a privacy policy: camera use, face snapshots used only for identity
  checks, skeleton data, results stored on the DeepFit server.

## Layout

```
lib/
  engine/         Dart copy of exercise_engine.py, coachability.py, growth.py (+ offline benchmark rating)
  services/       server API, upload queue, camera + ML Kit, voice, tones
  screens/        sign-in, register, home, test intro, test run, stopwatch, result, Hidden Potential, coach, settings
  widgets/        skeleton painter, shared bits
test/             engine parity test (+ fixtures from tool/make_fixtures.py)
tool/             setup.sh, patch_platforms.dart, make_fixtures.py
```
