/// DashboardScreen — список усіх сесій звірки активного ФОПа + кнопка «Нова звірка».
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../models/models.dart';
import '../providers/providers.dart';
import '../theme/app_theme.dart';

class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final fop = ref.watch(selectedFopProvider);
    if (fop == null) {
      // Якщо ФОПа не обрано — повертаємось до Home.
      WidgetsBinding.instance.addPostFrameCallback((_) => context.go('/'));
      return const SizedBox.shrink();
    }

    final sessionsAsync = ref.watch(reconSessionsProvider);

    return Scaffold(
      appBar: AppBar(
        title: Text('Дашборд • ${fop.name}'),
        actions: [
          IconButton(
            tooltip: 'Видалити ВСІ звірки',
            icon: const Icon(Icons.delete_sweep_outlined),
            onPressed: () async {
              final messenger = ScaffoldMessenger.of(context);
              try {
                final count = await ref.read(reconRepoProvider).deleteAllSessions(fop.id);
                if (!context.mounted) return;
                ref.invalidate(reconSessionsProvider);
                messenger.showSnackBar(SnackBar(
                  content: Text('Видалено звірок: $count'),
                  duration: const Duration(seconds: 3),
                ));
              } catch (e) {
                messenger.showSnackBar(SnackBar(
                  content: Text('Помилка: $e'),
                  backgroundColor: AppColors.danger,
                ));
              }
            },
          ),
          IconButton(
            tooltip: 'Оновити',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(reconSessionsProvider),
          ),
          const SizedBox(width: 8),
          FilledButton.icon(
            icon: const Icon(Icons.play_arrow),
            label: const Text('Нова звірка'),
            onPressed: () async {
              final result = await showDialog<bool>(
                context: context,
                builder: (_) => const _RunReconDialog(),
              );
              if (result == true) {
                ref.invalidate(reconSessionsProvider);
              }
            },
          ),
          const SizedBox(width: 16),
        ],
      ),
      body: sessionsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Помилка: $e')),
        data: (sessions) {
          if (sessions.isEmpty) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(40),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.balance, size: 64, color: AppColors.muted),
                    const SizedBox(height: 12),
                    const Text('Поки немає жодної звірки',
                        style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
                    const SizedBox(height: 4),
                    const Text('Спочатку залий виписки і вивантаження каси, потім запусти першу звірку.',
                        style: TextStyle(color: AppColors.muted), textAlign: TextAlign.center),
                    const SizedBox(height: 20),
                    OutlinedButton.icon(
                      icon: const Icon(Icons.upload_file),
                      label: const Text('Перейти до завантаження'),
                      onPressed: () => context.go('/upload'),
                    ),
                  ],
                ),
              ),
            );
          }
          return ListView.builder(
            padding: const EdgeInsets.all(20),
            itemCount: sessions.length,
            itemBuilder: (_, i) => _SessionCard(session: sessions[i]),
          );
        },
      ),
    );
  }
}

class _SessionCard extends ConsumerWidget {
  const _SessionCard({required this.session});
  final ReconSession session;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final df = DateFormat('yyyy-MM-dd');
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: InkWell(
        onTap: () => context.go('/recon/${session.id}'),
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: _statusColor(session.status).withValues(alpha: 0.12),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text(_statusLabel(session.status),
                        style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: _statusColor(session.status))),
                  ),
                  const SizedBox(width: 12),
                  Text('${df.format(session.periodFrom)} … ${df.format(session.periodTo)}',
                      style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
                  const Spacer(),
                  Text('${(session.matchRate * 100).toStringAsFixed(0)}%',
                      style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: AppColors.sea)),
                  const SizedBox(width: 4),
                  const Text('зматчено', style: TextStyle(fontSize: 12, color: AppColors.muted)),
                  IconButton(
                    icon: const Icon(Icons.delete_outline, size: 18, color: AppColors.muted),
                    onPressed: () async {
                      // Без модалки confirm — на Windows 8.1 overlay застрягає.
                      // Замість confirm — SnackBar з «Скасувати» 5 сек.
                      final repo = ref.read(reconRepoProvider);
                      final messenger = ScaffoldMessenger.of(context);
                      try {
                        await repo.deleteSession(session.id);
                        if (!context.mounted) return;
                        ref.invalidate(reconSessionsProvider);
                        messenger.showSnackBar(SnackBar(
                          content: Text('Звірка ${df.format(session.periodFrom)} – ${df.format(session.periodTo)} видалена'),
                          duration: const Duration(seconds: 3),
                        ));
                      } catch (e) {
                        messenger.showSnackBar(SnackBar(
                          content: Text('Помилка видалення: $e'),
                          backgroundColor: AppColors.danger,
                        ));
                      }
                    },
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 16,
                runSpacing: 8,
                children: [
                  _Stat(label: 'Банк операцій', value: '${session.totalBankOps}'),
                  _Stat(label: 'Каса операцій', value: '${session.totalCashOps}'),
                  _Stat(label: 'Точні', value: '${session.matchedExact}', color: AppColors.lime),
                  _Stat(label: 'Нечіткі', value: '${session.matchedFuzzy}', color: AppColors.sea),
                  _Stat(label: 'Пересорт', value: '${session.peresort}', color: AppColors.danger),
                  _Stat(label: 'До проведення', value: '${session.bankOnly}', color: AppColors.warn),
                  _Stat(label: 'Тільки в касі', value: '${session.cashOnly}', color: AppColors.muted),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Color _statusColor(String s) => switch (s) {
        'draft' => AppColors.muted,
        'approved' => AppColors.sea,
        'posted' => AppColors.lime,
        _ => AppColors.muted,
      };

  String _statusLabel(String s) => switch (s) {
        'draft' => 'чорнетка',
        'approved' => 'затверджена',
        'posted' => 'проведена',
        _ => s,
      };
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value, this.color});
  final String label;
  final String value;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontSize: 11, color: AppColors.muted)),
        Text(value, style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: color ?? AppColors.text)),
      ],
    );
  }
}

class _RunReconDialog extends ConsumerStatefulWidget {
  const _RunReconDialog();
  @override
  ConsumerState<_RunReconDialog> createState() => _RunReconDialogState();
}

class _RunReconDialogState extends ConsumerState<_RunReconDialog> {
  DateTime _from = DateTime(DateTime.now().year, DateTime.now().month, 1);
  DateTime _to = DateTime.now();
  int _dateWindow = 14;
  bool _busy = false;
  String? _error;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Запустити нову звірку'),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: _DateField(
                    label: 'Період з',
                    value: _from,
                    onPick: (d) => setState(() => _from = d),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _DateField(
                    label: 'Період по',
                    value: _to,
                    onPick: (d) => setState(() => _to = d),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Text('Вікно дат для нечіткого матчингу: $_dateWindow дн.'),
            Slider(
              value: _dateWindow.toDouble(),
              min: 1,
              max: 30,
              divisions: 29,
              label: '$_dateWindow дн.',
              onChanged: (v) => setState(() => _dateWindow = v.round()),
            ),
            const Text('14 днів — типове, бо буває проводять пачкою через тиждень-два.',
                style: TextStyle(color: AppColors.muted, fontSize: 11)),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(_error!, style: const TextStyle(color: AppColors.danger)),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: _busy ? null : () => Navigator.pop(context, false), child: const Text('Скасувати')),
        FilledButton(
          onPressed: _busy ? null : _submit,
          child: _busy
              ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Text('Запустити'),
        ),
      ],
    );
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final fop = ref.read(selectedFopProvider);
      if (fop == null) throw 'ФОПа не обрано';
      await ref.read(reconRepoProvider).run(
            fopId: fop.id,
            periodFrom: _from,
            periodTo: _to,
            dateWindowDays: _dateWindow,
          );
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      setState(() {
        _busy = false;
        _error = '$e';
      });
    }
  }
}

class _DateField extends StatelessWidget {
  const _DateField({required this.label, required this.value, required this.onPick});
  final String label;
  final DateTime value;
  final ValueChanged<DateTime> onPick;

  @override
  Widget build(BuildContext context) {
    final df = DateFormat('yyyy-MM-dd');
    return InkWell(
      onTap: () async {
        final picked = await showDatePicker(
          context: context,
          initialDate: value,
          firstDate: DateTime(2020),
          lastDate: DateTime(2030),
        );
        if (picked != null) onPick(picked);
      },
      child: InputDecorator(
        decoration: InputDecoration(labelText: label),
        child: Text(df.format(value)),
      ),
    );
  }
}
