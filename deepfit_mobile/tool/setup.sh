#!/bin/bash
# One-time setup of the DeepFit phone app (macOS / Linux). Needs Flutter installed.
#   cd deepfit_mobile && bash tool/setup.sh
set -e
cd "$(dirname "$0")/.."
command -v flutter >/dev/null || { echo "Flutter is not installed - see README.md step 1."; exit 1; }
# Adds android/ and ios/ folders. Existing files (lib/, test/, pubspec.yaml) are NOT overwritten.
flutter create . --project-name deepfit_mobile --org in.deepfit --platforms android,ios
dart run tool/patch_platforms.dart
flutter pub get
echo
echo "Checking the code and running the tests (engine must match the server)..."
flutter analyze || true
flutter test
echo
echo "Done. Plug in a phone (USB debugging on) and run:  flutter run"
