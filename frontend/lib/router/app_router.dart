/// Маршрути додатку.
library;

import 'package:go_router/go_router.dart';

import '../screens/accounts_screen.dart';
import '../screens/dashboard_screen.dart';
import '../screens/home_screen.dart';
import '../screens/recon_view_screen.dart';
import '../screens/upload_screen.dart';
import '../widgets/app_shell.dart';

final appRouter = GoRouter(
  initialLocation: '/',
  routes: [
    // Стартовий екран — вибір ФОПа. БЕЗ shell.
    GoRoute(path: '/', builder: (_, __) => const HomeScreen()),

    // Решта — у спільному shell з navrail.
    ShellRoute(
      builder: (context, state, child) => AppShell(child: child),
      routes: [
        GoRoute(path: '/dashboard', builder: (_, __) => const DashboardScreen()),
        GoRoute(path: '/accounts', builder: (_, __) => const AccountsScreen()),
        GoRoute(path: '/upload', builder: (_, __) => const UploadScreen()),
        GoRoute(
          path: '/recon/:sessionId',
          builder: (_, state) => ReconViewScreen(sessionId: state.pathParameters['sessionId']!),
        ),
      ],
    ),
  ],
);
