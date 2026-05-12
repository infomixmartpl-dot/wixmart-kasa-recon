/// Dart моделі дзеркалять Pydantic схеми з backend/recon_backend/api/schemas.py.
///
/// Намагаємось НЕ використовувати code-gen (json_serializable) — за рахунок
/// невеликого розміру моделей пишемо fromJson/toJson вручну. Це додає кілька
/// рядків на модель, але прибирає dependency на build_runner.
library;

class Fop {
  Fop({
    required this.id,
    required this.name,
    this.edrpou,
    this.odataBaseUrl,
    this.odataUsername,
    this.odataPassword,
    this.privatToken,
  });

  final String id;
  final String name;
  final String? edrpou;
  final String? odataBaseUrl;
  final String? odataUsername;
  final String? odataPassword;
  final String? privatToken;

  factory Fop.fromJson(Map<String, dynamic> j) => Fop(
        id: j['id'] as String,
        name: j['name'] as String,
        edrpou: j['edrpou'] as String?,
        odataBaseUrl: j['odata_base_url'] as String?,
        odataUsername: j['odata_username'] as String?,
        odataPassword: j['odata_password'] as String?,
        privatToken: j['privat_token'] as String?,
      );
}

class BankAccount {
  BankAccount({
    required this.id,
    required this.fopId,
    required this.iban,
    required this.label,
    this.currency = 'UAH',
    this.expectedCashAccountId,
  });

  final String id;
  final String fopId;
  final String iban;
  final String label;
  final String currency;
  final String? expectedCashAccountId;

  factory BankAccount.fromJson(Map<String, dynamic> j) => BankAccount(
        id: j['id'] as String,
        fopId: j['fop_id'] as String,
        iban: j['iban'] as String,
        label: j['label'] as String,
        currency: (j['currency'] as String?) ?? 'UAH',
        expectedCashAccountId: j['expected_cash_account_id'] as String?,
      );
}

class CashAccount {
  CashAccount({
    required this.id,
    required this.fopId,
    required this.name1c,
    this.kind = 'bank',
    this.odataRef,
  });

  final String id;
  final String fopId;
  final String name1c;
  final String kind;
  final String? odataRef;

  factory CashAccount.fromJson(Map<String, dynamic> j) => CashAccount(
        id: j['id'] as String,
        fopId: j['fop_id'] as String,
        name1c: j['name_1c'] as String,
        kind: (j['kind'] as String?) ?? 'bank',
        odataRef: j['odata_ref'] as String?,
      );
}

class Pidrozdil {
  Pidrozdil({
    required this.id,
    required this.fopId,
    required this.name1c,
    this.instagramHandle,
  });

  final String id;
  final String fopId;
  final String name1c;
  final String? instagramHandle;

  factory Pidrozdil.fromJson(Map<String, dynamic> j) => Pidrozdil(
        id: j['id'] as String,
        fopId: j['fop_id'] as String,
        name1c: j['name_1c'] as String,
        instagramHandle: j['instagram_handle'] as String?,
      );
}

class ReconSession {
  ReconSession({
    required this.id,
    required this.fopId,
    required this.periodFrom,
    required this.periodTo,
    required this.status,
    required this.dateWindowDays,
    required this.fuzzyNameThreshold,
    required this.createdAt,
    this.postedAt,
    this.totalBankOps = 0,
    this.totalCashOps = 0,
    this.matchedExact = 0,
    this.matchedFuzzy = 0,
    this.peresort = 0,
    this.bankOnly = 0,
    this.cashOnly = 0,
  });

  final String id;
  final String fopId;
  final DateTime periodFrom;
  final DateTime periodTo;
  final String status;
  final int dateWindowDays;
  final int fuzzyNameThreshold;
  final DateTime createdAt;
  final DateTime? postedAt;
  final int totalBankOps;
  final int totalCashOps;
  final int matchedExact;
  final int matchedFuzzy;
  final int peresort;
  final int bankOnly;
  final int cashOnly;

  int get totalMatched => matchedExact + matchedFuzzy;
  double get matchRate => totalBankOps == 0 ? 0 : totalMatched / totalBankOps;

  factory ReconSession.fromJson(Map<String, dynamic> j) => ReconSession(
        id: j['id'] as String,
        fopId: j['fop_id'] as String,
        periodFrom: DateTime.parse(j['period_from'] as String),
        periodTo: DateTime.parse(j['period_to'] as String),
        status: j['status'] as String,
        dateWindowDays: (j['date_window_days'] as num).toInt(),
        fuzzyNameThreshold: (j['fuzzy_name_threshold'] as num).toInt(),
        createdAt: DateTime.parse(j['created_at'] as String),
        postedAt: j['posted_at'] == null ? null : DateTime.parse(j['posted_at'] as String),
        totalBankOps: (j['total_bank_ops'] as num?)?.toInt() ?? 0,
        totalCashOps: (j['total_cash_ops'] as num?)?.toInt() ?? 0,
        matchedExact: (j['matched_exact'] as num?)?.toInt() ?? 0,
        matchedFuzzy: (j['matched_fuzzy'] as num?)?.toInt() ?? 0,
        peresort: (j['peresort'] as num?)?.toInt() ?? 0,
        bankOnly: (j['bank_only'] as num?)?.toInt() ?? 0,
        cashOnly: (j['cash_only'] as num?)?.toInt() ?? 0,
      );
}

class MatchRow {
  MatchRow({
    required this.id,
    required this.sessionId,
    required this.kind,
    this.bankOpId,
    this.cashOpId,
    this.expectedCashAccountId,
    this.score = 0,
    this.dateDiffDays = 0,
    this.counterpartySimilarity = 0,
    this.notes,
    this.approved = false,
    this.userStatus,
    this.manual = false,
    this.bankOp,
    this.cashOp,
  });

  final String id;
  final String sessionId;
  final String kind; // exact | fuzzy | amount_only | peresort | bank_only | cash_only
  final String? bankOpId;
  final String? cashOpId;
  final String? expectedCashAccountId;
  final double score;
  final int dateDiffDays;
  final double counterpartySimilarity;
  final String? notes;
  final bool approved;
  final String? userStatus; // approved | rejected | null=pending
  final bool manual;
  final Map<String, dynamic>? bankOp;
  final Map<String, dynamic>? cashOp;

  factory MatchRow.fromJson(Map<String, dynamic> j) => MatchRow(
        id: j['id'] as String,
        sessionId: j['session_id'] as String,
        kind: j['kind'] as String,
        bankOpId: j['bank_op_id'] as String?,
        cashOpId: j['cash_op_id'] as String?,
        expectedCashAccountId: j['expected_cash_account_id'] as String?,
        score: (j['score'] as num?)?.toDouble() ?? 0,
        dateDiffDays: (j['date_diff_days'] as num?)?.toInt() ?? 0,
        counterpartySimilarity:
            (j['counterparty_similarity'] as num?)?.toDouble() ?? 0,
        notes: j['notes'] as String?,
        approved: (j['approved'] as bool?) ?? false,
        userStatus: j['user_status'] as String?,
        manual: (j['manual'] as bool?) ?? false,
        bankOp: j['bank_op_summary'] as Map<String, dynamic>?,
        cashOp: j['cash_op_summary'] as Map<String, dynamic>?,
      );
}

class HealthStatus {
  HealthStatus({required this.status, required this.version, required this.db});
  final String status;
  final String version;
  final String db;

  factory HealthStatus.fromJson(Map<String, dynamic> j) => HealthStatus(
        status: j['status'] as String,
        version: j['version'] as String,
        db: j['db'] as String,
      );
}

class Pidrozdil {
  Pidrozdil({required this.id, required this.name1c, this.instagramHandle, this.odataRef});
  final String id;
  final String name1c;
  final String? instagramHandle;
  final String? odataRef;

  factory Pidrozdil.fromJson(Map<String, dynamic> j) => Pidrozdil(
        id: j['id'] as String,
        name1c: j['name_1c'] as String,
        instagramHandle: j['instagram_handle'] as String?,
        odataRef: j['odata_ref'] as String?,
      );
}

class Stattia {
  Stattia({required this.id, required this.name1c, this.movementType, this.odataRef});
  final String id;
  final String name1c;
  final String? movementType;
  final String? odataRef;

  factory Stattia.fromJson(Map<String, dynamic> j) => Stattia(
        id: j['id'] as String,
        name1c: j['name_1c'] as String,
        movementType: j['movement_type'] as String?,
        odataRef: j['odata_ref'] as String?,
      );
}
