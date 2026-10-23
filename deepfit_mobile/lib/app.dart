import 'package:flutter/material.dart';

import 'screens/home_screen.dart';
import 'screens/login_screen.dart';
import 'services/app_state.dart';

class DeepFitColors {
  static const navy = Color(0xFF020B18);
  static const panel = Color(0xFF0B1A2E);
  static const cyan = Color(0xFF42C8F5);
  static const green = Color(0xFF22C55E);
  static const amber = Color(0xFFF59E0B);
  static const red = Color(0xFFEF4444);
  static const muted = Color(0xFF94A3B8);

  static Color rating(String? r) {
    switch (r) {
      case 'Excellent':
        return green;
      case 'Good':
        return cyan;
      case 'Fair':
        return amber;
      case 'Needs work':
        return red;
    }
    if (r != null && r.startsWith('LATE')) return amber;
    return muted;
  }
}

class DeepFitApp extends StatelessWidget {
  final AppState state;
  const DeepFitApp({super.key, required this.state});

  @override
  Widget build(BuildContext context) {
    final scheme = ColorScheme.fromSeed(
      seedColor: DeepFitColors.cyan,
      brightness: Brightness.dark,
      surface: DeepFitColors.panel,
    );
    return AppScope(
      state: state,
      child: MaterialApp(
        title: 'DeepFit',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          useMaterial3: true,
          colorScheme: scheme,
          scaffoldBackgroundColor: DeepFitColors.navy,
          // (component themes like cardTheme changed type across Flutter versions - styled per widget instead)
          filledButtonTheme: FilledButtonThemeData(
            style: FilledButton.styleFrom(minimumSize: const Size(64, 52), textStyle: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
          ),
        ),
        home: const _Root(),
      ),
    );
  }
}

class _Root extends StatelessWidget {
  const _Root();

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    return state.loggedIn ? const HomeScreen() : const LoginScreen();
  }
}
