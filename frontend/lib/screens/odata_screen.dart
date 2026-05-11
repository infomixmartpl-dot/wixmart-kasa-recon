/// OdataScreen — інструменти роботи з 1С OData:
/// - перевірка з'єднання
/// - перелік EntitySet (щоб юзер бачив що доступне)
/// - синк каси/підрозділів
/// - синк документів за період
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../providers/providers.dart';
import '../theme/app_theme.dart';

class OdataScreen extends ConsumerStatefulWidget {
  const OdataScreen({super.key});
  @override
  ConsumerState<OdataScreen> createState() => _OdataScreenState();
}

class _OdataScreenState extends ConsumerState<OdataScreen> {
  Map<String, dynamic>? _testResult;
  Map<String, dynamic>? _discoverResult;
  Map<String, dynamic>? _syncResult;
  String? _error;
  bool _busy = false;

  DateTime _periodFrom = DateTime(DateTime.now().year, DateTime.now().month, 1);
  DateTime _periodTo = DateTime.now();

  // Налаштовувані списки документів (defaults підходять для УНФ 1.6 для України).
  final _inDocuments = TextEditingController(
    text: 'Document_ПоступлениеВКассу, Document_ПоступлениеНаСчет',
  );
  final _outDocuments = TextEditingController(
    text: 'Document_РасходИзКассы, Document_РасходСоСчета',
  );
  final _transferDocuments = TextEditingController(text: 'Document_ПеремещениеДС');

  @override
  void dispose() {
    _inDocuments.dispose();
    _outDocuments.dispose();
    _transferDocuments.dispose();
    super.dispose();
  }

  List<String> _parseList(TextEditingController c) =>
      c.text.split(',').map((s) => s.trim()).where((s) => s.isNotEmpty).toList();

  @override
  Widget build(BuildContext context) {
    final fop = ref.watch(selectedFopProvider);
    if (fop == null) return const SizedBox.shrink();

    return Scaffold(
      appBar: AppBar(title: const Text('1С OData')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Картка №1 — Тест з'єднання
            _SectionCard(
              icon: Icons.wifi_tethering,
              title: 'Тест з\'єднання',
              description: 'Перевіряє чи OData доступний з кредами які ти ввів у формі ФОПа.',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      FilledButton.icon(
                        icon: const Icon(Icons.play_arrow),
                        label: const Text('Перевірити з\'єднання'),
                        onPressed: _busy ? null : _runTest,
                      ),
                      OutlinedButton.icon(
                        icon: const Icon(Icons.list),
                        label: const Text('Перерахувати EntitySet'),
                        onPressed: _busy ? null : _runDiscover,
                      ),
                    ],
                  ),
                  if (_testResult != null) ...[
                    const SizedBox(height: 12),
                    _ResultBox(data: _testResult!, success: _testResult!['ok'] == true),
                  ],
                  if (_discoverResult != null) ...[
                    const SizedBox(height: 12),
                    _DiscoverResultBox(data: _discoverResult!),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 16),

            // Картка №2 — Синк довідників
            _SectionCard(
              icon: Icons.account_tree_outlined,
              title: 'Завантажити довідники',
              description:
                  'Затягне каси і підрозділи з 1С у локальну БД. Запускай ОДИН раз (або коли в 1С додали нову касу).',
              child: FilledButton.icon(
                style: FilledButton.styleFrom(backgroundColor: AppColors.sea),
                icon: const Icon(Icons.download),
                label: const Text('Синхронізувати каси + підрозділи'),
                onPressed: _busy ? null : _syncCatalogs,
              ),
            ),
            const SizedBox(height: 16),

            // Картка №3 — Синк документів за період
            _SectionCard(
              icon: Icons.event_note,
              title: 'Завантажити документи за період',
              description: 'Затягне Поступление, Расход і Перемещение денег за вказаний період.',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: _DateField(
                          label: 'Період з',
                          value: _periodFrom,
                          onPick: (d) => setState(() => _periodFrom = d),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: _DateField(
                          label: 'Період по',
                          value: _periodTo,
                          onPick: (d) => setState(() => _periodTo = d),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  ExpansionTile(
                    tilePadding: EdgeInsets.zero,
                    title: const Text('Назви EntitySet (через кому, для нестандартних конфігурацій)',
                        style: TextStyle(fontSize: 12, color: AppColors.muted)),
                    children: [
                      TextField(
                        controller: _inDocuments,
                        decoration: const InputDecoration(
                          labelText: 'Прихід (через кому)',
                          helperText: 'Готівка + Безготівка',
                        ),
                        maxLines: 2,
                      ),
                      const SizedBox(height: 8),
                      TextField(
                        controller: _outDocuments,
                        decoration: const InputDecoration(
                          labelText: 'Розхід (через кому)',
                        ),
                        maxLines: 2,
                      ),
                      const SizedBox(height: 8),
                      TextField(
                        controller: _transferDocuments,
                        decoration: const InputDecoration(
                          labelText: 'Переміщення',
                        ),
                      ),
                      const SizedBox(height: 8),
                      const Text(
                        'Defaults підходять для УНФ 1.6 для України. Якщо «Перерахувати EntitySet» показує інші назви — вставляй сюди через кому.',
                        style: TextStyle(fontSize: 11, color: AppColors.muted),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  FilledButton.icon(
                    icon: const Icon(Icons.download),
                    label: const Text('Синхронізувати документи'),
                    onPressed: _busy ? null : _syncCash,
                  ),
                  if (_syncResult != null) ...[
                    const SizedBox(height: 12),
                    _ResultBox(data: _syncResult!, success: true),
                  ],
                ],
              ),
            ),

            if (_error != null) ...[
              const SizedBox(height: 16),
              Card(
                color: AppColors.danger.withValues(alpha: 0.08),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Row(
                    children: [
                      const Icon(Icons.error_outline, color: AppColors.danger),
                      const SizedBox(width: 8),
                      Expanded(child: SelectableText(_error!, style: const TextStyle(color: AppColors.danger))),
                    ],
                  ),
                ),
              ),
            ],

            if (_busy) const Padding(
              padding: EdgeInsets.only(top: 16),
              child: LinearProgressIndicator(),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _runTest() async {
    final fop = ref.read(selectedFopProvider)!;
    setState(() {
      _busy = true;
      _error = null;
      _testResult = null;
    });
    try {
      final r = await ref.read(odataRepoProvider).test(fop.id);
      setState(() => _testResult = r);
    } catch (e) {
      setState(() => _error = '$e');
    } finally {
      setState(() => _busy = false);
    }
  }

  Future<void> _runDiscover() async {
    final fop = ref.read(selectedFopProvider)!;
    setState(() {
      _busy = true;
      _error = null;
      _discoverResult = null;
    });
    try {
      _discoverResult = await ref.read(odataRepoProvider).discover(fop.id);
    } catch (e) {
      _error = '$e';
    } finally {
      setState(() => _busy = false);
    }
  }

  Future<void> _syncCatalogs() async {
    final fop = ref.read(selectedFopProvider)!;
    setState(() {
      _busy = true;
      _error = null;
      _syncResult = null;
    });
    try {
      _syncResult = await ref.read(odataRepoProvider).syncCatalogs(fop.id);
      // Оновити списки в інших екранах.
      ref.invalidate(cashAccountsProvider);
      ref.invalidate(bankAccountsProvider);
    } catch (e) {
      _error = '$e';
    } finally {
      setState(() => _busy = false);
    }
  }

  Future<void> _syncCash() async {
    final fop = ref.read(selectedFopProvider)!;
    setState(() {
      _busy = true;
      _error = null;
      _syncResult = null;
    });
    try {
      _syncResult = await ref.read(odataRepoProvider).syncCash(
            fopId: fop.id,
            periodFrom: _periodFrom,
            periodTo: _periodTo,
            inDocuments: _parseList(_inDocuments),
            outDocuments: _parseList(_outDocuments),
            transferDocuments: _parseList(_transferDocuments),
          );
    } catch (e) {
      _error = '$e';
    } finally {
      setState(() => _busy = false);
    }
  }
}

class _SectionCard extends StatelessWidget {
  const _SectionCard({
    required this.icon,
    required this.title,
    required this.description,
    required this.child,
  });

  final IconData icon;
  final String title;
  final String description;
  final Widget child;

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
            const SizedBox(height: 16),
            child,
          ],
        ),
      ),
    );
  }
}

class _ResultBox extends StatelessWidget {
  const _ResultBox({required this.data, required this.success});
  final Map<String, dynamic> data;
  final bool success;

  @override
  Widget build(BuildContext context) {
    final lines = data.entries.map((e) => '${e.key}: ${e.value}').toList();
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: (success ? AppColors.lime : AppColors.danger).withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(success ? Icons.check_circle : Icons.error_outline,
                  color: success ? AppColors.lime : AppColors.danger, size: 18),
              const SizedBox(width: 6),
              Text(success ? 'Готово' : 'Помилка',
                  style: TextStyle(fontWeight: FontWeight.w700, color: success ? AppColors.lime : AppColors.danger)),
            ],
          ),
          const SizedBox(height: 6),
          SelectableText(lines.join('\n'),
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
        ],
      ),
    );
  }
}

class _DiscoverResultBox extends StatelessWidget {
  const _DiscoverResultBox({required this.data});
  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    final cats = (data['catalogs'] as List?)?.cast<String>() ?? [];
    final docs = (data['documents'] as List?)?.cast<String>() ?? [];
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Знайдено: ${data['total'] ?? 0} EntitySet',
              style: const TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          if (docs.isNotEmpty) ...[
            Text('Документи (${docs.length}):', style: const TextStyle(fontSize: 12, color: AppColors.muted)),
            const SizedBox(height: 4),
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 200),
              child: SingleChildScrollView(
                child: SelectableText(docs.join('\n'),
                    style: const TextStyle(fontFamily: 'monospace', fontSize: 11)),
              ),
            ),
            const SizedBox(height: 8),
          ],
          if (cats.isNotEmpty) ...[
            Text('Довідники (${cats.length}):', style: const TextStyle(fontSize: 12, color: AppColors.muted)),
            const SizedBox(height: 4),
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 200),
              child: SingleChildScrollView(
                child: SelectableText(cats.join('\n'),
                    style: const TextStyle(fontFamily: 'monospace', fontSize: 11)),
              ),
            ),
          ],
        ],
      ),
    );
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
