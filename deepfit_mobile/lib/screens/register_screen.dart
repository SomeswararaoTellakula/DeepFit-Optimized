import 'dart:convert';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

import '../app.dart';
import '../services/api.dart';
import '../services/app_state.dart';
import '../services/camera_session.dart';
import '../widgets/common.dart';

/// Registration. The face photo taken here is what every test is verified against.
class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key});
  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final _name = TextEditingController();
  final _age = TextEditingController();
  final _place = TextEditingController();
  final _phone = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  String _gender = 'Male';
  CameraSession? _cam;
  bool _camOpen = false;
  String? _photo; // base64 JPEG
  bool _busy = false;

  @override
  void dispose() {
    _cam?.close();
    for (final c in [_name, _age, _place, _phone, _email, _password]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _openCamera() async {
    final cam = CameraSession(detectPose: false);
    _cam = cam;
    final ok = await cam.open(front: true);
    if (!mounted) return;
    if (!ok) {
      toast(context, cam.error ?? 'Camera unavailable');
      return;
    }
    setState(() => _camOpen = true);
  }

  Future<void> _capture() async {
    final b64 = await _cam?.grabJpegBase64();
    if (!mounted) return;
    if (b64 == null) {
      toast(context, 'Could not take the photo - try again.');
      return;
    }
    await _cam?.close();
    setState(() {
      _photo = b64;
      _camOpen = false;
      _cam = null;
    });
  }

  Future<void> _submit() async {
    final age = int.tryParse(_age.text.trim());
    if ([_name, _place, _phone, _email, _password].any((c) => c.text.trim().isEmpty) || age == null) {
      toast(context, 'Please fill in every field.');
      return;
    }
    if (_photo == null) {
      toast(context, 'Take your face photo - it is used to check that you are the one doing each test.');
      return;
    }
    setState(() => _busy = true);
    final state = AppScope.read(context);
    try {
      await state.register({
        'name': _name.text.trim(),
        'age': age,
        'gender': _gender,
        'place': _place.text.trim(),
        'phone': _phone.text.trim(),
        'email': _email.text.trim(),
        'password': _password.text,
        'photo': 'data:image/jpeg;base64,$_photo',
      });
      if (mounted) Navigator.of(context).popUntil((r) => r.isFirst);
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final controller = _cam?.controller;
    return Scaffold(
      appBar: AppBar(title: const Text('Register athlete')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            TextField(controller: _name, textCapitalization: TextCapitalization.words, decoration: deco('Full name')),
            const SizedBox(height: 12),
            TextField(controller: _age, keyboardType: TextInputType.number, decoration: deco('Age (years)')),
            const SizedBox(height: 12),
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'Male', label: Text('Male')),
                ButtonSegment(value: 'Female', label: Text('Female')),
                ButtonSegment(value: 'Other', label: Text('Other')),
              ],
              selected: {_gender},
              onSelectionChanged: (s) => setState(() => _gender = s.first),
            ),
            const SizedBox(height: 12),
            TextField(controller: _place, decoration: deco('Place (village / town / district)')),
            const SizedBox(height: 12),
            TextField(controller: _phone, keyboardType: TextInputType.phone, decoration: deco('Phone number')),
            const SizedBox(height: 12),
            TextField(controller: _email, keyboardType: TextInputType.emailAddress, decoration: deco('Email')),
            const SizedBox(height: 12),
            TextField(controller: _password, obscureText: true, decoration: deco('Password (6+ characters)')),
            const SectionTitle('Face photo'),
            Panel(
              child: Column(children: [
                if (_camOpen && controller != null && controller.value.isInitialized)
                  ClipRRect(
                    borderRadius: BorderRadius.circular(12),
                    child: SizedBox(height: 320, child: Center(child: CameraPreview(controller))),
                  )
                else if (_photo != null)
                  ClipRRect(
                    borderRadius: BorderRadius.circular(12),
                    child: Image.memory(base64Decode(_photo!), height: 260, fit: BoxFit.contain),
                  )
                else
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 24),
                    child: Text('Face the camera in good light. Only you in the picture, no cap or sunglasses.',
                        textAlign: TextAlign.center, style: TextStyle(color: DeepFitColors.muted)),
                  ),
                const SizedBox(height: 12),
                if (_camOpen)
                  FilledButton.icon(onPressed: _capture, icon: const Icon(Icons.camera_alt), label: const Text('Take photo'))
                else
                  OutlinedButton.icon(
                    onPressed: _openCamera,
                    icon: const Icon(Icons.face),
                    label: Text(_photo == null ? 'Open camera' : 'Retake photo'),
                  ),
              ]),
            ),
            const SizedBox(height: 20),
            FilledButton(onPressed: _busy ? null : _submit, child: Text(_busy ? 'Checking photo…' : 'Create account')),
            const SizedBox(height: 8),
            const Text(
                'The server checks that the photo shows exactly one clear face. Your photo is only used to confirm '
                'that the registered athlete is the one doing each test.',
                style: TextStyle(color: DeepFitColors.muted, fontSize: 12)),
          ],
        ),
      ),
    );
  }
}
