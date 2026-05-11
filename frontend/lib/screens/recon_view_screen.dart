/// ReconViewScreen — детальний перегляд однієї звірки.
/// Чотири вкладки: Збіги (exact+fuzzy), Пересорт, До проведення (bank_only), Питання (cash_only).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/models.dart';
import '../providers/providers.dart';
import '../theme/app_theme.dart';

final _rowsProvider =
    FutureProvider.family.autoDispose<List<MatchRow>, ({String sessionId, String? kind})>((ref, args) async {
  return ref.read(reconRepoProvider).rows(args.sessionId, kind: args.kind);
});

class ReconViewScreen extends ConsumerStatefulWidget {
  const ReconViewScreen({super.key, required this.sessionId});
  final String sessionId;

  @override
  ConsumerState<ReconViewScreen> createState() => _ReconViewScreenState();
}

class _ReconViewScreenState extends ConsumerState<ReconViewScreen> with TickerProviderStateMixin {
  late final TabController _tabs;

  final _kinds = const [
    (label: 'Збіги', kind: null, subset: ['exact', 'fuzzy']),
    (label: 'Пересорт', kind: 'peresort', subset: ['peresort']),
    (label: 'До проведення', kind: 'bank_only', subset: ['bank_only']),
    // «Питання» — сумнівні: amount_only (слабкий збіг по сумі) + cash_only
    // ВКО/ПКО які не знайшли пари у банку. Переміщення між внутрішніми
    // касами автоматично ховаємо — вони не йдуть у банк, тому не предмет звірки.
    (label: 'Питання', kind: null, subset: ['amount_only', 'cash_only']),
  ];

  @override
  void initState() {
    super.initState();
    _tabs = TabController(length: _kinds.length, vsync: this);
  }

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }

  @override
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Звірка'),
        actions: [
          IconButton(
            tooltip: 'Перерахувати — заново зматчити цю сесію з поточними даними',
            icon: _busy
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.refresh),
            onPressed: _busy ? null : _rerun,
          ),
          const SizedBox(width: 8),
        ],
        bottom: TabBar(
          controller: _tabs,
          tabs: _kinds.map((k) => Tab(text: k.label)).toList(),
        ),
      ),
      body: TabBarView(
        controller: _tabs,
        children: _kinds.map((k) => _TabContent(sessionId: widget.sessionId, kind: k.kind, subset: k.subset)).toList(),
      ),
    );
  }

  Future<void> _rerun() async {
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(reconRepoProvider).rerun(widget.sessionId);
      // Інвалідуємо рядки і список сесій щоб дашборд оновився.
      ref.invalidate(_rowsProvider);
      ref.invalidate(reconSessionsProvider);
      if (!context.mounted) return;
      messenger.showSnackBar(const SnackBar(
        content: Text('Сесію перераховано'),
        duration: Duration(seconds: 2),
      ));
    } catch (e) {
      if (!context.mounted) return;
      messenger.showSnackBar(SnackBar(
        content: Text('Помилка перерахунку: $e'),
        backgroundColor: AppColors.danger,
      ));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

class _TabContent extends ConsumerWidget {
  const _TabContent({required this.sessionId, required this.kind, required this.subset});
  final String sessionId;
  final String? kind;
  final List<String> subset;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Завантажуємо всі рядки сесії і фільтруємо за subset (бо вкладка «Збіги» = exact + fuzzy).
    final rowsAsync = ref.watch(_rowsProvider((sessionId: sessionId, kind: null)));
    return rowsAsync.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text('$e')),
      data: (rows) {
        final filtered = rows.where((r) {
          if (!subset.contains(r.kind)) return false;
          // У вкладці «Питання» ховаємо cash_only-Перемещение — це внутрішні
          // переміщення між касами, до банку не йдуть, у звірці тільки шум.
          if (r.kind == 'cash_only') {
            final opType = (r.cashOp ?? {})['op_type']?.toString() ?? '';
            if (opType.toLowerCase().contains('перемещ') ||
                opType.toLowerCase().contains('переміщ')) {
              return false;
            }
          }
          return true;
        }).toList();
        if (filtered.isEmpty) {
          return const Center(
            child: Padding(
              padding: EdgeInsets.all(40),
              child: Text('Тут порожньо', style: TextStyle(color: AppColors.muted)),
            ),
          );
        }
        return Padding(
          padding: const EdgeInsets.all(16),
          child: Card(
            child: SingleChildScrollView(
              child: ConstrainedBox(
                constraints: const BoxConstraints(minWidth: double.infinity),
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: DataTable(
                    columnSpacing: 24,
                    horizontalMargin: 16,
                    columns: _columnsFor(subset),
                    rows: filtered.map((r) => _rowFor(r, subset, context)).toList(),
                  ),
                ),
              ),
            ),
          ),
        );
      },
    );
  }

  DataColumn _col(String text, String tooltip, {bool numeric = false}) {
    return DataColumn(
      numeric: numeric,
      label: Tooltip(
        message: tooltip,
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Text(text, style: const TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(width: 4),
          const Icon(Icons.help_outline, size: 12, color: AppColors.muted),
        ]),
      ),
    );
  }

  List<DataColumn> _columnsFor(List<String> subset) {
    if (subset.contains('cash_only')) {
      // КАСОВА сторона без пари у банку — є документ у 1С але банк не знає.
      return [
        _col('Дата', 'Дата касового документа у 1С.'),
        _col('Тип', 'Тип документа: ПКО (прихід), ВКО (видаток), Перемещение.'),
        _col('Сума', 'Сума касового документа.', numeric: true),
        _col('Документ', 'Номер документа в 1С.'),
        _col('Каса', 'ID каси (перші 6 символів).'),
        _col('Примітки', 'Підказки від алгоритму чому цей рядок не зматчився.'),
      ];
    }
    if (subset.contains('bank_only')) {
      // БАНКІВСЬКА сторона без пари у касі — є рух у банку але у 1С ПКО/ВКО нема.
      return [
        _col('Дата', 'Дата проведення банк-операції у виписці Privat.'),
        _col('Тип', 'IN — гроші прийшли, OUT — гроші пішли.'),
        _col('Сума', 'Сума у виписці Privat.', numeric: true),
        _col('Контрагент', 'Назва контрагента з виписки банку.'),
        _col('Призначення', 'Призначення платежу з виписки.'),
        _col('Примітки', 'Що саме алгоритм шукав і чому не знайшов пару.'),
      ];
    }
    // exact + fuzzy + peresort — обидві сторони
    return [
      _col('Дата банк', 'Дата проведення у виписці Privat.'),
      _col('Дата 1С', 'Дата касового документа в 1С.'),
      _col('Тип 1С', 'Тип документа у 1С: ПКО / ВКО / Перемещение.'),
      _col('Сума', 'Сума операції (співпадає у банку і касі).', numeric: true),
      _col('Контрагент банк', 'Контрагент з виписки Privat.'),
      _col('Документ 1С', 'Номер ПКО/ВКО в 1С.'),
      _col('Збіг', 'точний = сума+дата+рахунок ідеальні. нечіткий = сума ок, дата чи назва різна. пересорт = сума і дата ок але каса/рахунок інші, ніж очікувалось.'),
      _col('Δ дн.', 'Різниця між датою банку і датою 1С у днях.', numeric: true),
      _col('Примітки', 'Деталі від алгоритму: схожість назв, чи знайдено пересорт, тощо.'),
    ];
  }

  DataRow _rowFor(MatchRow r, List<String> subset, BuildContext context) {
    String fmtDate(dynamic v) => v == null ? '' : v.toString().substring(0, 10);
    String fmtAmt(dynamic v) => v == null ? '' : v.toString();

    void showDetails() {
      showDialog(
        context: context,
        builder: (_) => _MatchRowDetailsDialog(row: r),
      );
    }

    if (subset.contains('cash_only')) {
      final c = r.cashOp ?? {};
      return DataRow(
        onSelectChanged: (_) => showDetails(),
        cells: [
          DataCell(Text(fmtDate(c['op_date']))),
          DataCell(Text(c['op_type']?.toString() ?? '')),
          DataCell(Text(fmtAmt(c['amount']))),
          DataCell(Text('№${c['doc_number'] ?? ''}')),
          DataCell(Text(c['cash_account_id']?.toString().substring(0, 6) ?? '')),
          DataCell(Tooltip(
          message: r.notes ?? '',
          child: Text(r.notes ?? '', overflow: TextOverflow.ellipsis),
        )),
        ],
      );
    }
    if (subset.contains('bank_only')) {
      final b = r.bankOp ?? {};
      return DataRow(
        onSelectChanged: (_) => showDetails(),
        cells: [
          DataCell(Text(fmtDate(b['op_date']))),
          DataCell(Text(b['direction']?.toString() ?? '')),
          DataCell(Text(fmtAmt(b['amount']))),
          DataCell(Text(b['counterparty']?.toString() ?? '', overflow: TextOverflow.ellipsis)),
          DataCell(Text(b['purpose']?.toString() ?? '', overflow: TextOverflow.ellipsis)),
          DataCell(Tooltip(
          message: r.notes ?? '',
          child: Text(r.notes ?? '', overflow: TextOverflow.ellipsis),
        )),
        ],
      );
    }
    final b = r.bankOp ?? {};
    final c = r.cashOp ?? {};
    final kindLabel = switch (r.kind) {
      'exact' => 'точний',
      'fuzzy' => 'нечіткий',
      'peresort' => 'пересорт',
      _ => r.kind,
    };
    return DataRow(
      onSelectChanged: (_) => showDetails(),
      cells: [
        DataCell(Text(fmtDate(b['op_date']))),
        DataCell(Text(fmtDate(c['op_date']))),
        DataCell(Text(c['op_type']?.toString() ?? b['direction']?.toString() ?? '')),
        DataCell(Text(fmtAmt(b['amount']))),
        DataCell(SizedBox(width: 200, child: Text(b['counterparty']?.toString() ?? '', overflow: TextOverflow.ellipsis))),
        DataCell(Text('№${c['doc_number'] ?? ''}')),
        DataCell(_KindBadge(label: kindLabel, color: _kindColor(r.kind))),
        DataCell(Text('${r.dateDiffDays}')),
        DataCell(SizedBox(width: 240, child: Text(r.notes ?? '', overflow: TextOverflow.ellipsis))),
      ],
    );
  }

  Color _kindColor(String kind) => switch (kind) {
        'exact' => AppColors.lime,
        'fuzzy' => AppColors.sea,
        'amount_only' => AppColors.warn,
        'peresort' => AppColors.danger,
        'bank_only' => AppColors.warn,
        _ => AppColors.muted,
      };
}

class _KindBadge extends StatelessWidget {
  const _KindBadge({required this.label, required this.color});
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(label, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: color)),
    );
  }
}

class _MatchRowDetailsDialog extends ConsumerWidget {
  const _MatchRowDetailsDialog({required this.row});
  final MatchRow row;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final b = row.bankOp;
    final c = row.cashOp;

    // Резолвимо UUID → ім'я каси/банку, щоб юзер бачив реальні назви.
    final cashes = ref.watch(cashAccountsProvider).maybeWhen(
        data: (l) => {for (final c in l) c.id: c.name1c},
        orElse: () => <String, String>{});
    final banks = ref.watch(bankAccountsProvider).maybeWhen(
        data: (l) => {for (final b in l) b.id: '${b.label} • ${b.iban}'},
        orElse: () => <String, String>{});

    // Якщо це пересорт — покажемо «очікувано на касу: X».
    String? expectedCashName;
    if (row.expectedCashAccountId != null) {
      expectedCashName = cashes[row.expectedCashAccountId] ?? row.expectedCashAccountId;
    }

    // Збагачуємо bankOp і cashOp перед показом — замінюємо id на читабельні поля.
    Map<String, dynamic>? enrich(Map<String, dynamic>? src, Map<String, String> lookup, String idField) {
      if (src == null) return null;
      final out = <String, dynamic>{};
      src.forEach((k, v) {
        if (k == idField && v is String) {
          out['Каса/рахунок'] = lookup[v] ?? v;
        } else {
          out[k] = v;
        }
      });
      return out;
    }

    final bEnriched = enrich(b, banks, 'bank_account_id');
    final cEnriched = enrich(c, cashes, 'cash_account_id');

    return AlertDialog(
      title: Text('Рядок звірки — ${_kindLabel(row.kind)}'),
      content: SizedBox(
        width: 720,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (row.kind == 'peresort' && expectedCashName != null)
                Container(
                  margin: const EdgeInsets.only(bottom: 12),
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: AppColors.danger.withValues(alpha: 0.08),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('⚠ Пересорт',
                          style: TextStyle(fontWeight: FontWeight.w700, color: AppColors.danger)),
                      const SizedBox(height: 4),
                      Text('Очікували що проведуть на касу: $expectedCashName',
                          style: const TextStyle(fontSize: 12)),
                      if (c?['cash_account_id'] is String)
                        Text('Фактично провели на касу: ${cashes[c!["cash_account_id"]] ?? c["cash_account_id"]}',
                            style: const TextStyle(fontSize: 12)),
                    ],
                  ),
                ),
              _section(
                'Банк (Privat)',
                AppColors.sea,
                bEnriched,
                empty: 'Немає пари у банку (документ існує лише в 1С).',
              ),
              const SizedBox(height: 16),
              _section(
                '1С (Каса)',
                AppColors.lime,
                cEnriched,
                empty: 'Немає пари у 1С (банк-операція не проведена як ПКО/ВКО).',
              ),
              if (row.notes != null && row.notes!.isNotEmpty) ...[
                const SizedBox(height: 16),
                const Text('Примітки алгоритму:',
                    style: TextStyle(fontWeight: FontWeight.w600, fontSize: 12, color: AppColors.muted)),
                const SizedBox(height: 4),
                SelectableText(row.notes!, style: const TextStyle(fontSize: 12)),
              ],
            ],
          ),
        ),
      ),
      actions: [
        // Підтвердити / Відхилити — для будь-якого рядка крім bank_only
        // (для bank_only «підтвердити» не має сенсу — нема пари).
        if (row.kind != 'bank_only' && row.kind != 'cash_only') ...[
          TextButton(
            onPressed: () async {
              final messenger = ScaffoldMessenger.of(context);
              try {
                await ref.read(reconRepoProvider).setRowStatus(row.id, 'rejected');
                ref.invalidate(_rowsProvider);
                if (context.mounted) Navigator.pop(context);
                messenger.showSnackBar(const SnackBar(content: Text('Рядок відхилено')));
              } catch (e) {
                messenger.showSnackBar(SnackBar(content: Text('Помилка: $e')));
              }
            },
            child: const Text('Відхилити', style: TextStyle(color: AppColors.danger)),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.lime),
            onPressed: () async {
              final messenger = ScaffoldMessenger.of(context);
              try {
                await ref.read(reconRepoProvider).setRowStatus(row.id, 'approved');
                ref.invalidate(_rowsProvider);
                if (context.mounted) Navigator.pop(context);
                messenger.showSnackBar(const SnackBar(content: Text('Рядок підтверджено')));
              } catch (e) {
                messenger.showSnackBar(SnackBar(content: Text('Помилка: $e')));
              }
            },
            child: const Text('Підтвердити'),
          ),
        ],
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Закрити')),
      ],
    );
  }

  String _kindLabel(String k) => switch (k) {
        'exact' => 'точний збіг',
        'fuzzy' => 'нечіткий збіг',
        'peresort' => 'пересорт',
        'bank_only' => 'тільки в банку (до проведення)',
        'cash_only' => 'тільки в касі',
        _ => k,
      };

  Widget _section(String title, Color color, Map<String, dynamic>? data, {required String empty}) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.06),
        border: Border(left: BorderSide(color: color, width: 3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: TextStyle(fontWeight: FontWeight.w700, color: color)),
          const SizedBox(height: 8),
          if (data == null || data.isEmpty)
            Text(empty, style: const TextStyle(color: AppColors.muted, fontStyle: FontStyle.italic))
          else
            ...data.entries.map((e) => Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SizedBox(
                        width: 150,
                        child: Text('${e.key}:',
                            style: const TextStyle(fontSize: 12, color: AppColors.muted)),
                      ),
                      Expanded(
                        child: SelectableText(
                          e.value?.toString() ?? '—',
                          style: const TextStyle(fontSize: 12, fontFamily: 'monospace'),
                        ),
                      ),
                    ],
                  ),
                )),
        ],
      ),
    );
  }
}
