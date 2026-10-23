// Run once after `flutter create .` (tool/setup.sh does both). Adds the camera
// permission texts, network access to a DeepFit server on the local Wi-Fi, and the
// iOS version ML Kit needs. Safe to run again - it only adds what is missing.
//
//   dart run tool/patch_platforms.dart

import 'dart:io';

void main() {
  _android();
  _ios();
  stdout.writeln('Platform files patched.');
}

void _android() {
  final f = File('android/app/src/main/AndroidManifest.xml');
  if (!f.existsSync()) {
    stdout.writeln('No android/ folder - skipped (run flutter create . first).');
    return;
  }
  var s = f.readAsStringSync();
  for (final perm in ['android.permission.INTERNET', 'android.permission.CAMERA']) {
    if (!s.contains(perm)) {
      s = s.replaceFirst('<application', '<uses-permission android:name="$perm"/>\n    <application');
    }
  }
  // http:// to the server on the local network (use https in production)
  if (!s.contains('usesCleartextTraffic')) {
    s = s.replaceFirst('<application', '<application\n        android:usesCleartextTraffic="true"');
  }
  // open Talent Passport links in the browser
  const intent = '<intent><action android:name="android.intent.action.VIEW"/><data android:scheme="https"/></intent>';
  if (!s.contains('android.intent.action.VIEW"/><data android:scheme="https"')) {
    if (s.contains('<queries>')) {
      s = s.replaceFirst('<queries>', '<queries>\n        $intent');
    } else {
      s = s.replaceFirst('</manifest>', '    <queries>\n        $intent\n    </queries>\n</manifest>');
    }
  }
  f.writeAsStringSync(s);
  stdout.writeln('Android manifest: camera, internet, local http, browser links.');

  for (final name in ['android/app/build.gradle.kts', 'android/app/build.gradle']) {
    final g = File(name);
    if (!g.existsSync()) continue;
    var t = g.readAsStringSync();
    // ML Kit + camera need Android 5.0 (API 21) or newer
    final m = RegExp(r'minSdk(Version)?\s*=?\s*(\d+)').firstMatch(t);
    if (m != null && int.parse(m.group(2)!) < 21) {
      t = t.replaceFirst(m.group(0)!, m.group(0)!.replaceFirst(m.group(2)!, '21'));
      g.writeAsStringSync(t);
      stdout.writeln('$name: minSdk raised to 21.');
    }
  }
}

void _ios() {
  final plist = File('ios/Runner/Info.plist');
  if (!plist.existsSync()) {
    stdout.writeln('No ios/ folder - skipped.');
    return;
  }
  var s = plist.readAsStringSync();
  final adds = <String, String>{
    'NSCameraUsageDescription':
        '<key>NSCameraUsageDescription</key>\n\t<string>DeepFit uses the camera to track your body during fitness tests and to check that you are the registered athlete.</string>',
    'NSAppTransportSecurity':
        '<key>NSAppTransportSecurity</key>\n\t<dict>\n\t\t<key>NSAllowsArbitraryLoads</key>\n\t\t<true/>\n\t\t<key>NSAllowsLocalNetworking</key>\n\t\t<true/>\n\t</dict>',
    'NSLocalNetworkUsageDescription':
        '<key>NSLocalNetworkUsageDescription</key>\n\t<string>DeepFit connects to the DeepFit server on your Wi-Fi to upload results.</string>',
  };
  final end = s.lastIndexOf('</dict>');
  if (end > 0) {
    final extra = StringBuffer();
    adds.forEach((key, xml) {
      if (!s.contains('<key>$key</key>')) extra.write('\t$xml\n');
    });
    s = s.substring(0, end) + extra.toString() + s.substring(end);
    plist.writeAsStringSync(s);
  }
  stdout.writeln('iOS Info.plist: camera text, local network.');

  final pod = File('ios/Podfile');
  if (pod.existsSync()) {
    var p = pod.readAsStringSync();
    p = p.replaceFirst(RegExp(r"#?\s*platform :ios, '[\d.]+'"), "platform :ios, '15.5'");
    if (!p.contains("platform :ios")) p = "platform :ios, '15.5'\n$p";
    if (!p.contains("IPHONEOS_DEPLOYMENT_TARGET'] = '15.5'")) {
      p = p.replaceFirst('flutter_additional_ios_build_settings(target)',
          "flutter_additional_ios_build_settings(target)\n    target.build_configurations.each do |config|\n      config.build_settings['IPHONEOS_DEPLOYMENT_TARGET'] = '15.5'\n    end");
    }
    pod.writeAsStringSync(p);
    stdout.writeln("iOS Podfile: platform 15.5 (ML Kit needs it).");
  }
  final proj = File('ios/Runner.xcodeproj/project.pbxproj');
  if (proj.existsSync()) {
    final t = proj.readAsStringSync().replaceAllMapped(
        RegExp(r'IPHONEOS_DEPLOYMENT_TARGET = (\d+)\.(\d+);'),
        (m) => int.parse(m.group(1)!) < 15 || (int.parse(m.group(1)!) == 15 && int.parse(m.group(2)!) < 5)
            ? 'IPHONEOS_DEPLOYMENT_TARGET = 15.5;'
            : m.group(0)!);
    proj.writeAsStringSync(t);
  }
}
