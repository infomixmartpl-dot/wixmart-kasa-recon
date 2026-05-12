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

/// Фільтр звірки по касі. null = всі каси.
final _cashFilterProvider = StateProvider<String?>((ref) => null);

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

  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    final filterCashId = ref.watch(_cashFilterProvider);
    final cashesAsync = ref.watch(cashAccountsProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Звірка'),
        actions: [
          // Dropdown фільтр по касі — обмежує перегляд однією касою.
          cashesAsync.maybeWhen(
            data: (cashes) {
              // Тільки каси які намапленні з банк-рахунків — інші не релевантні.
              final banksAsync = ref.watch(bankAccountsProvider);
              final mapped = banksAsync.maybeWhen(
                data: (banks) => banks
                    .where((b) => b.expectedCashAccountId != null)
                    .map((b) => b.expectedCashAccountId!)
                    .toSet(),
                orElse: () => <String>{},
              );
              final available = cashes.where((c) => mapped.contains(c.id)).toList();
              if (available.isEmpty) return const SizedBox.shrink();
              return Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                child: DropdownButton<String?>(
                  value: filterCashId,
                  hint: const Text('Каса: всі', style: TextStyle(fontSize: 12)),
                  underline: const SizedBox.shrink(),
                  items: [
                    const DropdownMenuItem<String?>(value: null, child: Text('Каса: всі')),
                    ...available.map((c) => DropdownMenuItem<String?>(
                          value: c.id,
                          child: Text(c.name1c, style: const TextStyle(fontSize: 13)),
                        )),
                  ],
                  onChanged: (v) => ref.read(_cashFilterProvider.notifier).state = v,
                ),
              );
            },
            orElse: () => const SizedBox.shrink(),
          ),
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
    // Завантажуємо всі рядки сесії і фільтруємо за subset.
    final rowsAsync = ref.watch(_rowsProvider((sessionId: sessionId, kind: null)));
    final filterCashId = ref.watch(_cashFilterProvider);
    return rowsAsync.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text('$e')),
      data: (rows) {
        // expected_cash_account_ids — каси куди мапляться банк-рахунки.
        final bankExpected = ref.watch(bankAccountsProvider).maybeWhen(
          data: (banks) => banks
              .where((b) => b.expectedCashAccountId != null)
              .map((b) => b.expectedCashAccountId!)
              .toSet(),
          orElse: () => <String>{},
        );
        // Якщо фільтр по касі — також треба знати які bank_accounts мапляться
        // на ту касу (щоб відфільтрувати bank_only рядки правильно).
        final banksForFilterCash = ref.watch(bankAccountsProvider).maybeWhen(
          data: (banks) => banks
              .where((b) => b.expectedCashAccountId == filterCashId)
              .map((b) => b.id)
              .toSet(),
          orElse: () => <String>{},
        );

        final filtered = rows.where((r) {
          if (!subset.contains(r.kind)) return false;
          if (r.kind == 'cash_only') {
            final cashAcc = (r.cashOp ?? {})['cash_account_id']?.toString() ?? '';
            if (!bankExpected.contains(cashAcc)) return false;
          }
          // Фільтр по касі: показуємо рядок якщо стосується обраної каси
          // (через cash_op.cash_account_id або через bank_op.bank_account_id
          // що мапиться на цю касу).
          if (filterCashId != null) {
            final cashAcc = (r.cashOp ?? {})['cash_account_id']?.toString();
            final bankAcc = (r.bankOp ?? {})['bank_account_id']?.toString();
            final cashMatch = cashAcc == filterCashId;
            final bankMatch = bankAcc != null && banksForFilterCash.contains(bankAcc);
            if (!cashMatch && !bankMatch) return false;
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
              scrollDirection: Axis.horizontal,
              child: PaginatedDataTable(
                header: Text('${filtered.length} рядків',
                    style: const TextStyle(fontSize: 14, color: AppColors.muted)),
                columnSpacing: 24,
                horizontalMargin: 16,
                rowsPerPage: 50,
                availableRowsPerPage: const [25, 50, 100, 200],
                columns: _columnsFor(subset),
                source: _RowsSource(filtered, subset, context, _rowFor),
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

class _RowsSource extends DataTableSource {
  _RowsSource(this.rows, this.subset, this.context, this.rowBuilder);
  final List<MatchRow> rows;
  final List<String> subset;
  final BuildContext context;
  final DataRow Function(MatchRow r, List<String> subset, BuildContext ctx) rowBuilder;

  @override
  DataRow getRow(int index) => rowBuilder(rows[index], subset, context);

  @override
  int get rowCount => rows.length;

  @override
  bool get isRowCountApproximate => false;

  @override
  int get selectedRowCount => 0;
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
        // bank_only — кнопка «Намапити вручну» (відкриває пошук кандидатів).
        if (row.kind == 'bank_only')
          TextButton.icon(
            icon: const Icon(Icons.link, size: 16),
            label: const Text('Намапити вручну'),
            onPressed: () => _openManualMatchPicker(context, ref),
          ),
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

  Future<void> _openManualMatchPicker(BuildContext context, WidgetRef ref) async {
    final picked = await showDialog<String>(
      context: context,
      builder: (_) => _ManualMatchPicker(bankOp: row.bankOp ?? {}, sessionId: row.sessionId),
    );
    if (picked == null) return;
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(reconRepoProvider).manualMatch(
            sessionId: row.sessionId,
            bankOpId: row.bankOpId!,
            cashOpId: picked,
          );
      ref.invalidate(_rowsProvider);
      if (context.mounted) Navigator.pop(context);
      messenger.showSnackBar(const SnackBar(content: Text('Ручний матч створено')));
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('Помилка: $e')));
    }
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

class _ManualMatchPicker extends ConsumerWidget {
  const _ManualMatchPicker({required this.bankOp, required this.sessionId});
  final Map<String, dynamic> bankOp;
  final String sessionId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Завантажуємо всі рядки сесії — нам потрібні незаматчені каса-операції.
    final rowsAsync = ref.watch(_rowsProvider((sessionId: sessionId, kind: null)));
    final cashes = ref.watch(cashAccountsProvider).maybeWhen(
        data: (l) => {for (final c in l) c.id: c.name1c},
        orElse: () => <String, String>{});

    // Множина expected cash_account_id — каси які мапляться з банк-рахунків.
    // Кандидати на цих касах піднімаються нагору списку і підсвічуються.
    final expectedCashes = ref.watch(bankAccountsProvider).maybeWhen(
      data: (banks) => banks
          .where((b) => b.expectedCashAccountId != null)
          .map((b) => b.expectedCashAccountId!)
          .toSet(),
      orElse: () => <String>{},
    );
    // Конкретна expected_cash для banку який зараз матчимо.
    final myBankAccId = bankOp['bank_account_id']?.toString();
    final myExpectedCash = ref.watch(bankAccountsProvider).maybeWhen(
      data: (banks) {
        final b = banks.where((x) => x.id == myBankAccId).toList();
        return b.isEmpty ? null : b.first.expectedCashAccountId;
      },
      orElse: () => null,
    );

    final targetAmount = double.tryParse(bankOp['amount']?.toString() ?? '0') ?? 0;

    return AlertDialog(
      title: Text('Знайти пару для ${bankOp['amount']} грн'),
      content: SizedBox(
        width: 760,
        height: 520,
        child: rowsAsync.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Text('$e'),
          data: (rows) {
            final candidates = rows.where((r) {
              if (r.kind != 'cash_only' && r.kind != 'amount_only') return false;
              if (r.cashOp == null) return false;
              return true;
            }).toList();

            // Сортування: ПРІОРИТЕТ — каси з мапінгу bank→cash.
            // Спочатку моя expected_cash, потім інші expected, потім решта.
            // Усередині кожної групи — за близькістю суми.
            candidates.sort((a, b) {
              final ac = a.cashOp?['cash_account_id']?.toString();
              final bc = b.cashOp?['cash_account_id']?.toString();
              int priority(String? cashId) {
                if (cashId == null) return 3;
                if (cashId == myExpectedCash) return 0;
                if (expectedCashes.contains(cashId)) return 1;
                return 2;
              }
              final pa = priority(ac);
              final pb = priority(bc);
              if (pa != pb) return pa.compareTo(pb);
              final ap = double.tryParse(a.cashOp?['amount']?.toString() ?? '0') ?? 0;
              final bp = double.tryParse(b.cashOp?['amount']?.toString() ?? '0') ?? 0;
              return (ap - targetAmount).abs().compareTo((bp - targetAmount).abs());
            });

            if (candidates.isEmpty) {
              return const Center(
                child: Text('Немає кандидатів — всі каси за період вже зматчено',
                    style: TextStyle(color: AppColors.muted)),
              );
            }
            return ListView.builder(
              itemCount: candidates.length,
              itemBuilder: (_, i) {
                final r = candidates[i];
                final c = r.cashOp ?? {};
                final amount = c['amount']?.toString() ?? '';
                final date = (c['op_date']?.toString() ?? '').substring(0, 10);
                final cashAccId = c['cash_account_id']?.toString();
                final cashName = cashes[cashAccId] ?? '';
                final isMyExpected = cashAccId == myExpectedCash;
                final isExpected = cashAccId != null && expectedCashes.contains(cashAccId);
                return Container(
                  color: isMyExpected
                      ? AppColors.lime.withValues(alpha: 0.10)
                      : (isExpected ? AppColors.sea.withValues(alpha: 0.05) : null),
                  child: ListTile(
                    dense: true,
                    title: Text(
                        '$date • $amount грн • ${c['op_type'] ?? ''} №${c['doc_number'] ?? ''}'),
                    subtitle: Row(
                      children: [
                        if (isMyExpected)
                          Container(
                            margin: const EdgeInsets.only(right: 6),
                            padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
                            decoration: BoxDecoration(
                              color: AppColors.lime,
                              borderRadius: BorderRadius.circular(3),
                            ),
                            child: const Text('ВАША КАСА',
                                style: TextStyle(fontSize: 9, color: Colors.white, fontWeight: FontWeight.w700)),
                          ),
                        Expanded(
                          child: Text(
                              '${c['counterparty'] ?? ''}  •  каса: $cashName',
                              overflow: TextOverflow.ellipsis),
                        ),
                      ],
                    ),
                    trailing: FilledButton(
                      onPressed: () => Navigator.pop(context, r.cashOpId),
                      child: const Text('Вибрати'),
                    ),
                  ),
                );
              },
            );
          },
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Скасувати')),
      ],
    );
  }
}
