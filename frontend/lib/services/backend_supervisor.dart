/// BackendSupervisor — запускає embedded бекенд `recon_backend.exe` як subprocess,
/// чекає поки `/health` відповість, моніторить життя процесу і вбиває при close.
///
/// Шукає бінарник у такій послідовності:
/// 1. ENV `KASA_RECON_BACKEND_EXE` — для повного override (debug).
/// 2. Поряд з kasa_recon.exe у `recon_backend/recon_backend.exe` (release zip).
/// 3. Локально для розробки: `backend/.venv/bin/python -m recon_backend.launcher`
///    (працює на Mac/Linux під час `flutter run`).
///
/// Якщо нічого не знайдено — fallback на «зовнішній бекенд» (припускаємо що
/// юзер сам запустив `uvicorn` на localhost:8765 — для розробки).
library;

import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

class BackendSupervisor {
  BackendSupervisor({this.host = '127.0.0.1', this.port = 8765});

  final String host;
  final int port;

  Process? _process;
  bool _started = false;

  String get baseUrl => 'http://$host:$port';

  /// Запускає бекенд (якщо ще не запущений) і чекає поки `/health` поверне 200.
  ///
  /// timeout — скільки максимально чекати на готовність (типово 30 с).
  /// Кидає `BackendStartException` якщо не вдалось.
  Future<void> ensureRunning({Duration timeout = const Duration(seconds: 30)}) async {
    if (_started) return;

    // 1. Може бекенд вже працює (юзер сам запустив uvicorn для розробки)?
    if (await _healthy()) {
      debugPrint('Backend вже відповідає на $baseUrl — використовуємо існуючий.');
      _started = true;
      return;
    }

    // 2. Спробуємо знайти і запустити локальний бінарник / dev script.
    final cmd = await _resolveBackendCommand();
    if (cmd == null) {
      throw BackendStartException(
        'Не знайдено embedded бекенд (`recon_backend.exe`) і не запущено зовнішній.\n'
        'Перевір що `recon_backend.exe` лежить поряд з kasa_recon.exe, '
        'або запусти dev-сервер: `cd backend && .venv/bin/uvicorn recon_backend.main:app --port $port`',
      );
    }

    debugPrint('Запускаю бекенд: ${cmd.executable} ${cmd.arguments.join(' ')}');
    try {
      _process = await Process.start(
        cmd.executable,
        cmd.arguments,
        workingDirectory: cmd.workingDirectory,
        mode: ProcessStartMode.detachedWithStdio,
      );
    } catch (e) {
      throw BackendStartException('Не вдалось запустити бекенд: $e');
    }

    // Async-моніторинг — якщо процес вмер передчасно, помітимо це.
    unawaited(_process!.exitCode.then((code) {
      debugPrint('Backend subprocess завершився з кодом $code');
      _process = null;
      _started = false;
    }));

    // Поглинаємо stdout/stderr щоб не блокувати pipe.
    _process!.stdout.listen((b) {}, onError: (_) {});
    _process!.stderr.listen((b) {}, onError: (_) {});

    // 3. Чекаємо поки health стане ok.
    final deadline = DateTime.now().add(timeout);
    while (DateTime.now().isBefore(deadline)) {
      if (await _healthy()) {
        _started = true;
        debugPrint('Backend живий на $baseUrl');
        return;
      }
      await Future<void>.delayed(const Duration(milliseconds: 400));
      if (_process == null) {
        // Підпроцес впав — нема сенсу чекати.
        throw BackendStartException(
          'Backend subprocess впав одразу після запуску. Перевір логи у %LOCALAPPDATA%\\KasaRecon\\backend.log',
        );
      }
    }
    await stop();
    throw BackendStartException(
      'Backend не відповів на $baseUrl/health протягом ${timeout.inSeconds}c. Перевір логи.',
    );
  }

  /// Зупинити subprocess (викликається при закритті додатку).
  Future<void> stop() async {
    final p = _process;
    if (p == null) return;
    try {
      p.kill(ProcessSignal.sigterm);
      // Чекаємо до 3 секунд на graceful exit, потім жорстко.
      await p.exitCode.timeout(const Duration(seconds: 3), onTimeout: () {
        p.kill(ProcessSignal.sigkill);
        return -1;
      });
    } catch (e) {
      debugPrint('Помилка при зупинці бекенду: $e');
    }
    _process = null;
    _started = false;
  }

  Future<bool> _healthy() async {
    try {
      final r = await http
          .get(Uri.parse('$baseUrl/health'))
          .timeout(const Duration(seconds: 2));
      return r.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<_BackendCommand?> _resolveBackendCommand() async {
    // 1. ENV override.
    final envExe = Platform.environment['KASA_RECON_BACKEND_EXE'];
    if (envExe != null && File(envExe).existsSync()) {
      return _BackendCommand(executable: envExe, arguments: const []);
    }

    // 2. Embedded bundle: поряд з виконуваним файлом фронтенду.
    //    На Windows: <app>/recon_backend/recon_backend.exe
    //    На macOS:   <app>.app/Contents/MacOS/recon_backend (поки не пакуємо)
    final exeDir = File(Platform.resolvedExecutable).parent;
    final bundled = Platform.isWindows
        ? File('${exeDir.path}/recon_backend/recon_backend.exe')
        : File('${exeDir.path}/recon_backend');
    if (bundled.existsSync()) {
      return _BackendCommand(executable: bundled.path, arguments: const []);
    }

    // 3. Dev fallback: викликати локальний venv-Python через -m recon_backend.launcher.
    //    Працює коли flutter run з кореня репо.
    final repoRoot = Directory.current;
    final pyMac = File('${repoRoot.path}/backend/.venv/bin/python');
    final pyWin = File('${repoRoot.path}/backend/.venv/Scripts/python.exe');
    final py = pyWin.existsSync() ? pyWin : (pyMac.existsSync() ? pyMac : null);
    if (py != null) {
      return _BackendCommand(
        executable: py.path,
        arguments: const ['-m', 'recon_backend.launcher'],
        workingDirectory: '${repoRoot.path}/backend',
      );
    }

    return null;
  }
}

class _BackendCommand {
  _BackendCommand({required this.executable, required this.arguments, this.workingDirectory});
  final String executable;
  final List<String> arguments;
  final String? workingDirectory;
}

class BackendStartException implements Exception {
  BackendStartException(this.message);
  final String message;

  @override
  String toString() => 'BackendStartException: $message';
}
