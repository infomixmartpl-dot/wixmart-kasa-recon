/// AccountsScreen — два списки поряд: банк-рахунки і каси 1С.
/// Дозволяє додати/видалити, а також намапити банк → касу (для виявлення пересорту).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/models.dart';
import '../providers/providers.dart';
import '../theme/app_theme.dart';

class AccountsScreen extends ConsumerWidget {
  const AccountsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final fop = ref.watch(selectedFopProvider);
    if (fop == null) return const SizedBox.shrink();
    final banksAsync = ref.watch(bankAccountsProvider);
    final cashesAsync = ref.watch(cashAccountsProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Рахунки і каси'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () {
              ref.invalidate(bankAccountsProvider);
              ref.invalidate(cashAccountsProvider);
            },
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Колонка: банк-рахунки
            Expanded(
              child: _SectionCard(
                title: 'Банк-рахунки Privat',
                description: 'IBAN-и в Privat24 Business. Один рахунок = одна окрема виписка.',
                onAdd: () async {
                  final cashes = cashesAsync.maybeWhen(data: (l) => l, orElse: () => <CashAccount>[]);
                  final created = await showDialog<bool>(
                    context: context,
                    builder: (_) => _CreateBankDialog(fopId: fop.id, cashes: cashes),
                  );
                  if (created == true) ref.invalidate(bankAccountsProvider);
                },
                child: banksAsync.when(
                  loading: () => const Padding(padding: EdgeInsets.all(20), child: Center(child: CircularProgressIndicator())),
                  error: (e, _) => Text('$e'),
                  data: (banks) {
                    if (banks.isEmpty) {
                      return const Padding(
                        padding: EdgeInsets.all(20),
                        child: Text('Поки немає жодного банк-рахунку.', style: TextStyle(color: AppColors.muted)),
                      );
                    }
                    final cashes = cashesAsync.maybeWhen(data: (l) => l, orElse: () => <CashAccount>[]);
                    return ListView.builder(
                      itemCount: banks.length,
                      itemBuilder: (_, i) {
                        final b = banks[i];
                        final mapped = cashes.where((c) => c.id == b.expectedCashAccountId).toList();
                        final mappedName = mapped.isEmpty ? null : mapped.first.name1c;
                        return ListTile(
                          contentPadding: EdgeInsets.zero,
                          leading: const Icon(Icons.credit_card, color: AppColors.sea),
                          title: Text(b.label, style: const TextStyle(fontWeight: FontWeight.w600)),
                          subtitle: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(b.iban, style: const TextStyle(fontSize: 12, color: AppColors.muted)),
                              Text(
                                mappedName == null ? '↳ нема каси, не виявимо пересорт' : '↳ мапиться на: $mappedName',
                                style: TextStyle(fontSize: 11, color: mappedName == null ? AppColors.warn : AppColors.lime),
                              ),
                            ],
                          ),
                          trailing: IconButton(
                            icon: const Icon(Icons.delete_outline, size: 18),
                            onPressed: () async {
                              await ref.read(bankAccountRepoProvider).delete(b.id);
                              ref.invalidate(bankAccountsProvider);
                            },
                          ),
                        );
                      },
                    );
                  },
                ),
              ),
            ),
            const SizedBox(width: 16),
            // Колонка: каси 1С
            Expanded(
              child: _SectionCard(
                title: 'Каси 1С (УНФ)',
                description: 'Об\'єкти довідника «Банковский счет, касса». Сюди мапяться банк-рахунки.',
                onAdd: () async {
                  final created = await showDialog<bool>(
                    context: context,
                    builder: (_) => _CreateCashDialog(fopId: fop.id),
                  );
                  if (created == true) ref.invalidate(cashAccountsProvider);
                },
                child: cashesAsync.when(
                  loading: () => const Padding(padding: EdgeInsets.all(20), child: Center(child: CircularProgressIndicator())),
                  error: (e, _) => Text('$e'),
                  data: (cashes) {
                    if (cashes.isEmpty) {
                      return const Padding(
                        padding: EdgeInsets.all(20),
                        child: Text('Поки немає жодної каси.', style: TextStyle(color: AppColors.muted)),
                      );
                    }
                    return ListView.builder(
                      itemCount: cashes.length,
                      itemBuilder: (_, i) {
                        final c = cashes[i];
                        return ListTile(
                          contentPadding: EdgeInsets.zero,
                          leading: Icon(
                            c.kind == 'cash' ? Icons.payments_outlined : Icons.account_balance_outlined,
                            color: AppColors.sea,
                          ),
                          title: Text(c.name1c, style: const TextStyle(fontWeight: FontWeight.w600)),
                          subtitle: Text('тип: ${c.kind}',
                              style: const TextStyle(fontSize: 11, color: AppColors.muted)),
                          trailing: IconButton(
                            icon: const Icon(Icons.delete_outline, size: 18),
                            onPressed: () async {
                              await ref.read(cashAccountRepoProvider).delete(c.id);
                              ref.invalidate(cashAccountsProvider);
                            },
                          ),
                        );
                      },
                    );
                  },
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionCard extends StatelessWidget {
  const _SectionCard({required this.title, required this.description, required this.onAdd, required this.child});
  final String title;
  final String description;
  final VoidCallback onAdd;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(child: Text(title, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16))),
                FilledButton.icon(
                  style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10)),
                  icon: const Icon(Icons.add, size: 16),
                  label: const Text('Додати'),
                  onPressed: onAdd,
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(description, style: const TextStyle(color: AppColors.muted, fontSize: 12)),
            const Divider(height: 24),
            Expanded(child: child),
          ],
        ),
      ),
    );
  }
}

class _CreateBankDialog extends ConsumerStatefulWidget {
  const _CreateBankDialog({required this.fopId, required this.cashes});
  final String fopId;
  final List<CashAccount> cashes;
  @override
  ConsumerState<_CreateBankDialog> createState() => _CreateBankDialogState();
}

class _CreateBankDialogState extends ConsumerState<_CreateBankDialog> {
  final _iban = TextEditingController();
  final _label = TextEditingController();
  String? _cashId;
  bool _busy = false;
  String? _err;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Новий банк-рахунок'),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(controller: _label, decoration: const InputDecoration(labelText: 'Назва (наприклад «Privat ФОП Аня»)')),
            const SizedBox(height: 8),
            TextField(controller: _iban, decoration: const InputDecoration(labelText: 'IBAN (UAxxxxxxxx...)')),
            const SizedBox(height: 8),
            DropdownButtonFormField<String>(
              value: _cashId,
              decoration: const InputDecoration(labelText: 'Мапиться на касу 1С (для виявлення пересорту)'),
              items: [
                const DropdownMenuItem(value: null, child: Text('(не вибрано)')),
                ...widget.cashes.map((c) => DropdownMenuItem(value: c.id, child: Text(c.name1c))),
              ],
              onChanged: (v) => setState(() => _cashId = v),
            ),
            if (_err != null) ...[
              const SizedBox(height: 8),
              Text(_err!, style: const TextStyle(color: AppColors.danger)),
            ],
          ],
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
    if (_iban.text.trim().isEmpty || _label.text.trim().isEmpty) {
      setState(() => _err = 'IBAN і Назва обов\'язкові');
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(bankAccountRepoProvider).create(
            fopId: widget.fopId,
            iban: _iban.text.trim(),
            label: _label.text.trim(),
            expectedCashAccountId: _cashId,
          );
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      setState(() {
        _busy = false;
        _err = '$e';
      });
    }
  }
}

class _CreateCashDialog extends ConsumerStatefulWidget {
  const _CreateCashDialog({required this.fopId});
  final String fopId;
  @override
  ConsumerState<_CreateCashDialog> createState() => _CreateCashDialogState();
}

class _CreateCashDialogState extends ConsumerState<_CreateCashDialog> {
  final _name = TextEditingController();
  String _kind = 'bank';
  bool _busy = false;
  String? _err;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Нова каса 1С'),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(controller: _name, decoration: const InputDecoration(labelText: 'Назва в 1С (точно як у довіднику)')),
            const SizedBox(height: 8),
            DropdownButtonFormField<String>(
              value: _kind,
              decoration: const InputDecoration(labelText: 'Тип'),
              items: const [
                DropdownMenuItem(value: 'bank', child: Text('Банк-рахунок')),
                DropdownMenuItem(value: 'cash', child: Text('Готівка')),
                DropdownMenuItem(value: 'terminal', child: Text('Термінал')),
              ],
              onChanged: (v) => setState(() => _kind = v ?? 'bank'),
            ),
            if (_err != null) ...[
              const SizedBox(height: 8),
              Text(_err!, style: const TextStyle(color: AppColors.danger)),
            ],
          ],
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
      setState(() => _err = 'Назва обов\'язкова');
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(cashAccountRepoProvider).create(
            fopId: widget.fopId,
            name1c: _name.text.trim(),
            kind: _kind,
          );
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      setState(() {
        _busy = false;
        _err = '$e';
      });
    }
  }
}
