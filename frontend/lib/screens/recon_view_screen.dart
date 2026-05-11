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
    (label: 'Питання', kind: 'cash_only', subset: ['cash_only']),
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
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Звірка'),
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
        final filtered = rows.where((r) => subset.contains(r.kind)).toList();
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
                    rows: filtered.map((r) => _rowFor(r, subset)).toList(),
                  ),
                ),
              ),
            ),
          ),
        );
      },
    );
  }

  List<DataColumn> _columnsFor(List<String> subset) {
    if (subset.contains('cash_only')) {
      return const [
        DataColumn(label: Text('Дата')),
        DataColumn(label: Text('Тип'), numeric: false),
        DataColumn(label: Text('Сума'), numeric: true),
        DataColumn(label: Text('Документ')),
        DataColumn(label: Text('Каса')),
        DataColumn(label: Text('Примітки')),
      ];
    }
    if (subset.contains('bank_only')) {
      return const [
        DataColumn(label: Text('Дата')),
        DataColumn(label: Text('Тип')),
        DataColumn(label: Text('Сума'), numeric: true),
        DataColumn(label: Text('Контрагент')),
        DataColumn(label: Text('Призначення')),
        DataColumn(label: Text('Примітки')),
      ];
    }
    // exact + fuzzy + peresort
    return const [
      DataColumn(label: Text('Дата банк')),
      DataColumn(label: Text('Дата 1С')),
      DataColumn(label: Text('Тип')),
      DataColumn(label: Text('Сума'), numeric: true),
      DataColumn(label: Text('Контрагент банк')),
      DataColumn(label: Text('Документ 1С')),
      DataColumn(label: Text('Збіг')),
      DataColumn(label: Text('Δ дн.'), numeric: true),
      DataColumn(label: Text('Примітки')),
    ];
  }

  DataRow _rowFor(MatchRow r, List<String> subset) {
    String fmtDate(dynamic v) => v == null ? '' : v.toString().substring(0, 10);
    String fmtAmt(dynamic v) => v == null ? '' : v.toString();

    if (subset.contains('cash_only')) {
      final c = r.cashOp ?? {};
      return DataRow(cells: [
        DataCell(Text(fmtDate(c['op_date']))),
        DataCell(Text(c['op_type']?.toString() ?? '')),
        DataCell(Text(fmtAmt(c['amount']))),
        DataCell(Text('№${c['doc_number'] ?? ''}')),
        DataCell(Text(c['cash_account_id']?.toString().substring(0, 6) ?? '')),
        DataCell(Text(r.notes ?? '', overflow: TextOverflow.ellipsis)),
      ]);
    }
    if (subset.contains('bank_only')) {
      final b = r.bankOp ?? {};
      return DataRow(cells: [
        DataCell(Text(fmtDate(b['op_date']))),
        DataCell(Text(b['direction']?.toString() ?? '')),
        DataCell(Text(fmtAmt(b['amount']))),
        DataCell(Text(b['counterparty']?.toString() ?? '', overflow: TextOverflow.ellipsis)),
        DataCell(Text(b['purpose']?.toString() ?? '', overflow: TextOverflow.ellipsis)),
        DataCell(Text(r.notes ?? '', overflow: TextOverflow.ellipsis)),
      ]);
    }
    final b = r.bankOp ?? {};
    final c = r.cashOp ?? {};
    final kindLabel = switch (r.kind) {
      'exact' => 'точний',
      'fuzzy' => 'нечіткий',
      'peresort' => 'пересорт',
      _ => r.kind,
    };
    return DataRow(cells: [
      DataCell(Text(fmtDate(b['op_date']))),
      DataCell(Text(fmtDate(c['op_date']))),
      DataCell(Text(c['op_type']?.toString() ?? b['direction']?.toString() ?? '')),
      DataCell(Text(fmtAmt(b['amount']))),
      DataCell(SizedBox(width: 200, child: Text(b['counterparty']?.toString() ?? '', overflow: TextOverflow.ellipsis))),
      DataCell(Text('№${c['doc_number'] ?? ''}')),
      DataCell(_KindBadge(label: kindLabel, color: _kindColor(r.kind))),
      DataCell(Text('${r.dateDiffDays}')),
      DataCell(SizedBox(width: 240, child: Text(r.notes ?? '', overflow: TextOverflow.ellipsis))),
    ]);
  }

  Color _kindColor(String kind) => switch (kind) {
        'exact' => AppColors.lime,
        'fuzzy' => AppColors.sea,
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
