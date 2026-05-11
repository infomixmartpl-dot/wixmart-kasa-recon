import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'providers/providers.dart';
import 'router/app_router.dart';
import 'services/backend_supervisor.dart';
import 'theme/app_theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ProviderScope(child: _Bootstrap()));
}

/// Сплеш-екран під час старту: запускає embedded бекенд через BackendSupervisor.
/// Коли бекенд відповів на /health — рендериться основний додаток.
class _Bootstrap extends ConsumerStatefulWidget {
  const _Bootstrap();
  @override
  ConsumerState<_Bootstrap> createState() => _BootstrapState();
}

class _BootstrapState extends ConsumerState<_Bootstrap> with WidgetsBindingObserver {
  late final BackendSupervisor _supervisor;
  Future<void>? _bootFuture;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _supervisor = BackendSupervisor();
    _bootFuture = _boot();
  }

  Future<void> _boot() async {
    await _supervisor.ensureRunning();
    // ApiClient читає baseUrl зі supervisor — оновлюємо рантайм.
    final api = ref.read(apiClientProvider);
    api.setBaseUrl(_supervisor.baseUrl);
  }

  Future<void> _retry() async {
    setState(() {
      _bootFuture = _boot();
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // На Windows закриття вікна викликає detached — вбиваємо бекенд.
    if (state == AppLifecycleState.detached) {
      _supervisor.stop();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    unawaited(_supervisor.stop());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Kasa Recon — старт',
      theme: buildLightTheme(),
      debugShowCheckedModeBanner: false,
      home: FutureBuilder<void>(
        future: _bootFuture,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const _SplashScreen(status: 'Запускаю бекенд...');
          }
          if (snapshot.hasError) {
            return _SplashScreen(
              status: 'Не вдалось запустити бекенд',
              error: '${snapshot.error}',
              onRetry: _retry,
            );
          }
          // Бекенд готовий — рендеримо основний додаток.
          return KasaReconApp();
        },
      ),
    );
  }
}

class KasaReconApp extends StatelessWidget {
  KasaReconApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: 'WixMart Kasa Recon',
      theme: buildLightTheme(),
      debugShowCheckedModeBanner: false,
      routerConfig: appRouter,
    );
  }
}

class _SplashScreen extends StatelessWidget {
  const _SplashScreen({required this.status, this.error, this.onRetry});

  final String status;
  final String? error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Container(
                  width: 56,
                  height: 56,
                  decoration: BoxDecoration(
                    color: AppColors.sea,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Icon(Icons.balance, color: Colors.white, size: 30),
                ),
                const SizedBox(height: 16),
                const Text(
                  'Kasa Recon',
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 24),
                if (error == null) ...[
                  const SizedBox(
                    width: 28,
                    height: 28,
                    child: CircularProgressIndicator(strokeWidth: 3),
                  ),
                  const SizedBox(height: 16),
                  Text(status, style: const TextStyle(color: AppColors.muted)),
                ] else ...[
                  const Icon(Icons.error_outline, color: AppColors.danger, size: 32),
                  const SizedBox(height: 12),
                  Text(status,
                      style: const TextStyle(
                          fontSize: 15, fontWeight: FontWeight.w600, color: AppColors.danger)),
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AppColors.surface,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: SelectableText(
                      error!,
                      style: const TextStyle(fontFamily: 'monospace', fontSize: 11),
                    ),
                  ),
                  const SizedBox(height: 16),
                  if (onRetry != null)
                    FilledButton.icon(
                      icon: const Icon(Icons.refresh),
                      label: const Text('Повторити'),
                      onPressed: onRetry,
                    ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
