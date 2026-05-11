/// HomeScreen — вибір активного ФОПа або створення нового.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../models/models.dart';
import '../providers/providers.dart';
import '../theme/app_theme.dart';

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final fopsAsync = ref.watch(fopsProvider);

    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 600),
          child: Padding(
            padding: const EdgeInsets.all(40),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Container(
                      width: 48,
                      height: 48,
                      decoration: BoxDecoration(color: AppColors.sea, borderRadius: BorderRadius.circular(10)),
                      child: const Icon(Icons.balance, color: Colors.white, size: 26),
                    ),
                    const SizedBox(width: 12),
                    const Text('Kasa Recon',
                        style: TextStyle(fontSize: 24, fontWeight: FontWeight.w700)),
                  ],
                ),
                const SizedBox(height: 8),
                const Center(
                  child: Text('Звірка ПриватБанк ↔ Каса 1С',
                      style: TextStyle(color: AppColors.muted)),
                ),
                const SizedBox(height: 36),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Row(
                          children: [
                            const Expanded(
                              child: Text('Обери ФОПа',
                                  style: TextStyle(fontWeight: FontWeight.w600, fontSize: 16)),
                            ),
                            IconButton(
                              icon: const Icon(Icons.refresh, size: 20),
                              onPressed: () => ref.invalidate(fopsProvider),
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        fopsAsync.when(
                          loading: () => const Padding(
                            padding: EdgeInsets.all(20),
                            child: Center(child: CircularProgressIndicator()),
                          ),
                          error: (e, _) => _ErrorBox(message: 'Не вдалось завантажити ФОПів: $e'),
                          data: (fops) {
                            if (fops.isEmpty) {
                              return const Padding(
                                padding: EdgeInsets.symmetric(vertical: 16),
                                child: Text('Поки немає жодного ФОПа. Додай першого нижче.',
                                    style: TextStyle(color: AppColors.muted)),
                              );
                            }
                            return Column(
                              children: fops
                                  .map((f) => _FopRow(
                                        fop: f,
                                        onSelect: () {
                                          ref.read(selectedFopProvider.notifier).state = f;
                                          context.go('/dashboard');
                                        },
                                        onDelete: () async {
                                          await ref.read(fopRepoProvider).delete(f.id);
                                          ref.invalidate(fopsProvider);
                                        },
                                      ))
                                  .toList(),
                            );
                          },
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                FilledButton.icon(
                  icon: const Icon(Icons.add),
                  label: const Text('Додати ФОПа'),
                  onPressed: () async {
                    final created = await showDialog<Fop?>(
                      context: context,
                      builder: (_) => const _CreateFopDialog(),
                    );
                    if (created != null) {
                      ref.invalidate(fopsProvider);
                      ref.read(selectedFopProvider.notifier).state = created;
                      if (context.mounted) context.go('/dashboard');
                    }
                  },
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _FopRow extends StatelessWidget {
  const _FopRow({required this.fop, required this.onSelect, required this.onDelete});
  final Fop fop;
  final VoidCallback onSelect;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onSelect,
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 12),
        child: Row(
          children: [
            const Icon(Icons.business_center_outlined, color: AppColors.sea),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(fop.name, style: const TextStyle(fontWeight: FontWeight.w600)),
                  if (fop.edrpou != null && fop.edrpou!.isNotEmpty)
                    Text('ЄДРПОУ ${fop.edrpou}',
                        style: const TextStyle(color: AppColors.muted, fontSize: 12)),
                ],
              ),
            ),
            IconButton(
              icon: const Icon(Icons.delete_outline, size: 20, color: AppColors.muted),
              onPressed: () async {
                final ok = await showDialog<bool>(
                  context: context,
                  builder: (_) => AlertDialog(
                    title: const Text('Видалити ФОПа?'),
                    content: Text('Усі дані ФОПа «${fop.name}» (рахунки, каси, звірки) теж видаляться.'),
                    actions: [
                      TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Скасувати')),
                      FilledButton(
                        style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
                        onPressed: () => Navigator.pop(context, true),
                        child: const Text('Видалити'),
                      ),
                    ],
                  ),
                );
                if (ok == true) onDelete();
              },
            ),
            const Icon(Icons.chevron_right, color: AppColors.muted),
          ],
        ),
      ),
    );
  }
}

class _CreateFopDialog extends ConsumerStatefulWidget {
  const _CreateFopDialog();
  @override
  ConsumerState<_CreateFopDialog> createState() => _CreateFopDialogState();
}

class _CreateFopDialogState extends ConsumerState<_CreateFopDialog> {
  final _name = TextEditingController();
  final _edrpou = TextEditingController();
  final _odataUrl = TextEditingController();
  final _odataUser = TextEditingController();
  final _odataPass = TextEditingController();
  final _privatToken = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Новий ФОП'),
      content: SizedBox(
        width: 480,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextField(controller: _name, decoration: const InputDecoration(labelText: "Назва (наприклад «ФОП Аня Петренко»)")),
              const SizedBox(height: 8),
              TextField(controller: _edrpou, decoration: const InputDecoration(labelText: 'ЄДРПОУ / ІПН')),
              const SizedBox(height: 16),
              const Text('1С OData (опційно — можна додати потім)',
                  style: TextStyle(color: AppColors.muted, fontSize: 12)),
              const SizedBox(height: 8),
              TextField(controller: _odataUrl, decoration: const InputDecoration(labelText: 'OData base URL')),
              const SizedBox(height: 8),
              Row(children: [
                Expanded(child: TextField(controller: _odataUser, decoration: const InputDecoration(labelText: 'Логін'))),
                const SizedBox(width: 8),
                Expanded(child: TextField(controller: _odataPass, decoration: const InputDecoration(labelText: 'Пароль'), obscureText: true)),
              ]),
              const SizedBox(height: 16),
              const Text('Privat24 Business API (опційно)',
                  style: TextStyle(color: AppColors.muted, fontSize: 12)),
              const SizedBox(height: 8),
              TextField(controller: _privatToken, decoration: const InputDecoration(labelText: 'Token')),
              if (_error != null) ...[
                const SizedBox(height: 8),
                Text(_error!, style: const TextStyle(color: AppColors.danger)),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: _busy ? null : () => Navigator.pop(context), child: const Text('Скасувати')),
        FilledButton(
          onPressed: _busy ? null : _submit,
          child: _busy ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : const Text('Створити'),
        ),
      ],
    );
  }

  Future<void> _submit() async {
    if (_name.text.trim().isEmpty) {
      setState(() => _error = 'Назва обов\'язкова');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final fop = await ref.read(fopRepoProvider).create(
            name: _name.text.trim(),
            edrpou: _edrpou.text.trim().isEmpty ? null : _edrpou.text.trim(),
            odataBaseUrl: _odataUrl.text.trim().isEmpty ? null : _odataUrl.text.trim(),
            odataUsername: _odataUser.text.trim().isEmpty ? null : _odataUser.text.trim(),
            odataPassword: _odataPass.text.trim().isEmpty ? null : _odataPass.text.trim(),
            privatToken: _privatToken.text.trim().isEmpty ? null : _privatToken.text.trim(),
          );
      if (mounted) Navigator.pop(context, fop);
    } catch (e) {
      setState(() {
        _busy = false;
        _error = 'Помилка: $e';
      });
    }
  }
}

class _ErrorBox extends StatelessWidget {
  const _ErrorBox({required this.message});
  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.danger.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline, color: AppColors.danger, size: 20),
          const SizedBox(width: 8),
          Expanded(child: Text(message, style: const TextStyle(color: AppColors.danger))),
        ],
      ),
    );
  }
}
