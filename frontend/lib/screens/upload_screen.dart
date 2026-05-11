/// UploadScreen — завантажити CSV виписки Privat і XLSX вивантаження УНФ.
library;

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/providers.dart';
import '../theme/app_theme.dart';

class UploadScreen extends ConsumerStatefulWidget {
  const UploadScreen({super.key});
  @override
  ConsumerState<UploadScreen> createState() => _UploadScreenState();
}

class _UploadScreenState extends ConsumerState<UploadScreen> {
  String? _selectedBankId;
  String? _selectedCashId;
  String? _lastResult;
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    final fop = ref.watch(selectedFopProvider);
    if (fop == null) return const SizedBox.shrink();
    final banksAsync = ref.watch(bankAccountsProvider);
    final cashesAsync = ref.watch(cashAccountsProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Завантаження даних')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Виписка Privat
            _UploadCard(
              icon: Icons.credit_card,
              title: 'Виписка ПриватБанк',
              description:
                  'CSV або XLSX експорт з Privat24 Business. У файлі може бути '
                  'декілька IBAN — вибери «Авто-визначити з IBAN у файлі» і парсер '
                  'розкладе кожен рядок на свій банк-рахунок.',
              accountLabel: 'Банк-рахунок',
              accountSelector: banksAsync.when(
                loading: () => const LinearProgressIndicator(),
                error: (e, _) => Text('$e'),
                data: (banks) {
                  if (banks.isEmpty) {
                    return const Padding(
                      padding: EdgeInsets.symmetric(vertical: 8),
                      child: Text('Спочатку додай банк-рахунок у «Рахунки і каси».',
                          style: TextStyle(color: AppColors.warn)),
                    );
                  }
                  return DropdownButtonFormField<String>(
                    value: _selectedBankId,
                    decoration: const InputDecoration(border: OutlineInputBorder()),
                    items: [
                      const DropdownMenuItem(
                        value: '__auto__',
                        child: Text('🔍 Авто-визначити з IBAN у файлі (мульти-IBAN)'),
                      ),
                      ...banks.map((b) => DropdownMenuItem(
                            value: b.id,
                            child: Text('${b.label} • ${b.iban}', overflow: TextOverflow.ellipsis),
                          )),
                    ],
                    onChanged: (v) => setState(() => _selectedBankId = v),
                  );
                },
              ),
              onPick: _selectedBankId == null
                  ? null
                  : () => _pickAndUpload(
                        isPrivat: true,
                        fopId: fop.id,
                        accountId: _selectedBankId == '__auto__' ? '' : _selectedBankId!,
                        allowedExtensions: ['csv', 'xlsx', 'xls'],
                      ),
            ),
            const SizedBox(height: 16),

            // Журнал транзакцій — БАГАТО кас у одному файлі (рекомендується)
            _UploadCard(
              icon: Icons.list_alt,
              title: 'Журнал документів каси — ВСІ каси одним файлом',
              description:
                  'XLSX з колонкою «Касса/Счет». Парсер сам розкладає документи по касах '
                  '(не треба вибирати касу). Рекомендується для першого заливання історії.',
              accountLabel: '',
              accountSelector: const SizedBox.shrink(),
              onPick: () => _pickAndUploadJournal(fopId: fop.id),
            ),
            const SizedBox(height: 16),

            // Вивантаження УНФ
            _UploadCard(
              icon: Icons.account_balance,
              title: 'Вивантаження каси з УНФ — одна каса',
              description:
                  'XLSX — журнал документів або звіт «Движение денег». Програма авто-визначає формат.',
              accountLabel: 'Каса в 1С',
              accountSelector: cashesAsync.when(
                loading: () => const LinearProgressIndicator(),
                error: (e, _) => Text('$e'),
                data: (cashes) {
                  if (cashes.isEmpty) {
                    return const Padding(
                      padding: EdgeInsets.symmetric(vertical: 8),
                      child: Text('Спочатку додай касу у «Рахунки і каси».',
                          style: TextStyle(color: AppColors.warn)),
                    );
                  }
                  return DropdownButtonFormField<String>(
                    value: _selectedCashId,
                    decoration: const InputDecoration(border: OutlineInputBorder()),
                    items: cashes.map((c) => DropdownMenuItem(value: c.id, child: Text(c.name1c))).toList(),
                    onChanged: (v) => setState(() => _selectedCashId = v),
                  );
                },
              ),
              onPick: _selectedCashId == null
                  ? null
                  : () => _pickAndUpload(
                        isPrivat: false,
                        fopId: fop.id,
                        accountId: _selectedCashId!,
                        allowedExtensions: ['xlsx', 'xls'],
                      ),
            ),
            const SizedBox(height: 16),

            if (_busy) const LinearProgressIndicator(),

            if (_lastResult != null)
              Card(
                color: AppColors.lime.withValues(alpha: 0.08),
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Row(
                    children: [
                      const Icon(Icons.check_circle, color: AppColors.lime),
                      const SizedBox(width: 8),
                      Expanded(child: Text(_lastResult!)),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _pickAndUpload({
    required bool isPrivat,
    required String fopId,
    required String accountId,
    required List<String> allowedExtensions,
  }) async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: allowedExtensions,
    );
    if (result == null || result.files.isEmpty) return;
    final file = result.files.first;
    if (file.path == null) return;

    setState(() {
      _busy = true;
      _lastResult = null;
    });
    try {
      final r = isPrivat
          ? await ref.read(syncRepoProvider).uploadPrivat(
                fopId: fopId,
                bankAccountId: accountId,
                filePath: file.path!,
                filename: file.name,
              )
          : await ref.read(syncRepoProvider).uploadCash(
                fopId: fopId,
                cashAccountId: accountId,
                filePath: file.path!,
                filename: file.name,
              );
      setState(() {
        _busy = false;
        _lastResult =
            '${isPrivat ? 'Виписка' : 'Вивантаження каси'} «${file.name}»: '
            'додано ${r['added']}, дублів ${r['duplicates']}, всього ${r['total_parsed']}'
            '${r['source'] != null ? ' (${r['source']})' : ''}';
      });
    } catch (e) {
      setState(() {
        _busy = false;
        _lastResult = '✗ Помилка: $e';
      });
    }
  }

  Future<void> _pickAndUploadJournal({required String fopId}) async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['xlsx', 'xls'],
    );
    if (result == null || result.files.isEmpty) return;
    final file = result.files.first;
    if (file.path == null) return;

    setState(() {
      _busy = true;
      _lastResult = null;
    });
    try {
      final r = await ref.read(syncRepoProvider).uploadCashJournal(
            fopId: fopId,
            filePath: file.path!,
            filename: file.name,
          );
      final unmapped = (r['unmapped_cash_accounts'] as Map?) ?? {};
      final unmappedNote = unmapped.isEmpty
          ? ''
          : ' • не знайдено кас у БД: ${unmapped.length} '
              '(${unmapped.entries.take(3).map((e) => "${e.key}=${e.value}").join(", ")}${unmapped.length > 3 ? "..." : ""})';
      setState(() {
        _busy = false;
        _lastResult =
            'Журнал «${file.name}»: '
            'додано ${r['added']}, дублів ${r['duplicates']}, '
            'всього розпарсено ${r['total_parsed']}$unmappedNote';
      });
      ref.invalidate(cashAccountsProvider);
    } catch (e) {
      setState(() {
        _busy = false;
        _lastResult = '✗ Помилка: $e';
      });
    }
  }
}

class _UploadCard extends StatelessWidget {
  const _UploadCard({
    required this.icon,
    required this.title,
    required this.description,
    required this.accountLabel,
    required this.accountSelector,
    required this.onPick,
  });

  final IconData icon;
  final String title;
  final String description;
  final String accountLabel;
  final Widget accountSelector;
  final VoidCallback? onPick;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Container(
                  width: 36,
                  height: 36,
                  decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(8)),
                  child: Icon(icon, color: AppColors.sea, size: 18),
                ),
                const SizedBox(width: 12),
                Expanded(child: Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700))),
              ],
            ),
            const SizedBox(height: 4),
            Text(description, style: const TextStyle(color: AppColors.muted, fontSize: 12)),
            const SizedBox(height: 12),
            Text(accountLabel, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12, color: AppColors.muted)),
            const SizedBox(height: 4),
            accountSelector,
            const SizedBox(height: 16),
            FilledButton.icon(
              icon: const Icon(Icons.upload_file),
              label: const Text('Вибрати файл і завантажити'),
              onPressed: onPick,
            ),
          ],
        ),
      ),
    );
  }
}
