// Talks to the DeepFit server (the Flask website) through its /api/v1 endpoints.

import 'dart:async';
import 'dart:convert';
import 'dart:io' show SocketException, gzip;

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  final String message;
  final int? status;
  final bool auth; // the login expired - sign in again
  final bool offline; // the server could not be reached
  const ApiException(this.message, {this.status, this.auth = false, this.offline = false});
  @override
  String toString() => message;
}

class Api {
  String baseUrl;
  String? token;
  final http.Client _client = http.Client();

  Api(String baseUrl, {this.token}) : baseUrl = normalizeUrl(baseUrl);

  /// "192.168.1.5:7860" -> "http://192.168.1.5:7860"
  static String normalizeUrl(String raw) {
    var s = raw.trim();
    if (s.isEmpty) return s;
    if (!s.startsWith('http://') && !s.startsWith('https://')) s = 'http://$s';
    while (s.endsWith('/')) {
      s = s.substring(0, s.length - 1);
    }
    return s;
  }

  bool get configured => baseUrl.isNotEmpty;

  Uri _uri(String path, [Map<String, String>? query]) {
    final u = Uri.parse('$baseUrl/api/v1$path');
    return query == null ? u : u.replace(queryParameters: query);
  }

  Map<String, String> _headers({bool gzipped = false}) => {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
        if (gzipped) 'Content-Encoding': 'gzip',
      };

  Future<Map<String, dynamic>> get(String path,
      {Map<String, String>? query, Duration timeout = const Duration(seconds: 15)}) async {
    if (!configured) throw const ApiException('Set the server address first.', offline: true);
    try {
      final r = await _client.get(_uri(path, query), headers: _headers()).timeout(timeout);
      return _decode(r);
    } on ApiException {
      rethrow;
    } on TimeoutException {
      throw const ApiException('The server did not answer in time.', offline: true);
    } on SocketException {
      throw const ApiException('Cannot reach the DeepFit server.', offline: true);
    } on http.ClientException {
      throw const ApiException('Cannot reach the DeepFit server.', offline: true);
    }
  }

  Future<Map<String, dynamic>> post(String path, Map<String, dynamic> body,
      {Duration timeout = const Duration(seconds: 20), bool compress = false}) async {
    if (!configured) throw const ApiException('Set the server address first.', offline: true);
    try {
      final raw = utf8.encode(jsonEncode(body));
      final r = await _client
          .post(_uri(path), headers: _headers(gzipped: compress), body: compress ? gzip.encode(raw) : raw)
          .timeout(timeout);
      return _decode(r);
    } on ApiException {
      rethrow;
    } on TimeoutException {
      throw const ApiException('The server did not answer in time.', offline: true);
    } on SocketException {
      throw const ApiException('Cannot reach the DeepFit server.', offline: true);
    } on http.ClientException {
      throw const ApiException('Cannot reach the DeepFit server.', offline: true);
    }
  }

  Map<String, dynamic> _decode(http.Response r) {
    Map<String, dynamic> data;
    try {
      final d = jsonDecode(utf8.decode(r.bodyBytes));
      data = d is Map<String, dynamic> ? d : <String, dynamic>{};
    } catch (_) {
      // not JSON: an old server without the phone API, or a proxy error page
      throw ApiException(
          r.statusCode == 404
              ? 'This DeepFit server has no phone API yet - update the server files.'
              : 'Server error (${r.statusCode}).',
          status: r.statusCode);
    }
    if (r.statusCode >= 400 || data['ok'] == false) {
      throw ApiException((data['error'] ?? 'Server error (${r.statusCode}).').toString(),
          status: r.statusCode, auth: r.statusCode == 401 || data['auth'] == true);
    }
    return data;
  }
}
