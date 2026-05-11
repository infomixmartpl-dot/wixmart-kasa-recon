/// Спільний layout для основних екранів: ліва панель навігації +
/// перемикач активного ФОПа у верхньому правому куті.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../providers/providers.dart';
import '../theme/app_theme.dart';

class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final fop = ref.watch(selectedFopProvider);
    final loc = GoRouterState.of(context).uri.path;

    return Scaffold(
      body: Row(
        children: [
          // Ліва панель навігації
          Container(
            width: 220,
            color: Colors.white,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Padding(
                  padding: const EdgeInsets.all(20),
                  child: Row(
                    children: [
                      Container(
                        width: 32,
                        height: 32,
                        decoration: BoxDecoration(
                          color: AppColors.sea,
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: const Icon(Icons.balance, color: Colors.white, size: 18),
                      ),
                      const SizedBox(width: 10),
                      const Text('Kasa Recon',
                          style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                    ],
                  ),
                ),
                const Divider(height: 1),
                _NavItem(label: 'Дашборд', icon: Icons.dashboard_outlined, route: '/dashboard', active: loc == '/dashboard'),
                _NavItem(label: 'Рахунки і каси', icon: Icons.account_balance_wallet_outlined, route: '/accounts', active: loc == '/accounts'),
                _NavItem(label: 'Завантаження', icon: Icons.upload_file_outlined, route: '/upload', active: loc == '/upload'),
                const Spacer(),
                if (fop != null)
                  Container(
                    margin: const EdgeInsets.all(12),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AppColors.surface,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('Активний ФОП',
                            style: TextStyle(color: AppColors.muted, fontSize: 11)),
                        const SizedBox(height: 4),
                        Text(fop.name,
                            style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                        if (fop.edrpou != null && fop.edrpou!.isNotEmpty)
                          Text('ЄДРПОУ ${fop.edrpou}',
                              style: const TextStyle(color: AppColors.muted, fontSize: 11)),
                        const SizedBox(height: 6),
                        TextButton(
                          style: TextButton.styleFrom(
                            padding: EdgeInsets.zero,
                            minimumSize: const Size(0, 24),
                            tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                          ),
                          onPressed: () {
                            ref.read(selectedFopProvider.notifier).state = null;
                            context.go('/');
                          },
                          child: const Text('Змінити', style: TextStyle(fontSize: 12)),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
          // Контент
          Expanded(child: child),
        ],
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({required this.label, required this.icon, required this.route, required this.active});

  final String label;
  final IconData icon;
  final String route;
  final bool active;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: () => context.go(route),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
        color: active ? AppColors.surface : null,
        child: Row(
          children: [
            Icon(icon, size: 18, color: active ? AppColors.sea : AppColors.muted),
            const SizedBox(width: 12),
            Text(label,
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: active ? FontWeight.w600 : FontWeight.w400,
                  color: active ? AppColors.text : AppColors.muted,
                )),
          ],
        ),
      ),
    );
  }
}
