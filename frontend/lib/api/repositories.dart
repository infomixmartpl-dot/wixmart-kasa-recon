/// Репозиторії — тонка обгортка над ApiClient, що повертає типізовані моделі.
library;

import '../models/models.dart';
import 'api_client.dart';

class FopRepository {
  FopRepository(this._api);
  final ApiClient _api;

  Future<List<Fop>> list() async {
    final r = await _api.get<List<dynamic>>('/api/fops/');
    return (r.data ?? []).map((e) => Fop.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<Fop> create({
    required String name,
    String? edrpou,
    String? odataBaseUrl,
    String? odataUsername,
    String? odataPassword,
    String? privatToken,
  }) async {
    final r = await _api.post<Map<String, dynamic>>('/api/fops/', data: {
      'name': name,
      'edrpou': edrpou,
      'odata_base_url': odataBaseUrl,
      'odata_username': odataUsername,
      'odata_password': odataPassword,
      'privat_token': privatToken,
    });
    return Fop.fromJson(r.data!);
  }

  Future<void> delete(String id) async {
    await _api.delete('/api/fops/$id');
  }
}

class BankAccountRepository {
  BankAccountRepository(this._api);
  final ApiClient _api;

  Future<List<BankAccount>> listByFop(String fopId) async {
    final r = await _api.get<List<dynamic>>('/api/bank-accounts/', query: {'fop_id': fopId});
    return (r.data ?? []).map((e) => BankAccount.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<BankAccount> create({
    required String fopId,
    required String iban,
    required String label,
    String currency = 'UAH',
    String? expectedCashAccountId,
  }) async {
    final r = await _api.post<Map<String, dynamic>>(
      '/api/bank-accounts/',
      query: {'fop_id': fopId},
      data: {
        'iban': iban,
        'label': label,
        'currency': currency,
        'expected_cash_account_id': expectedCashAccountId,
      },
    );
    return BankAccount.fromJson(r.data!);
  }

  Future<void> delete(String id) async {
    await _api.delete('/api/bank-accounts/$id');
  }
}

class CashAccountRepository {
  CashAccountRepository(this._api);
  final ApiClient _api;

  Future<List<CashAccount>> listByFop(String fopId) async {
    final r = await _api.get<List<dynamic>>('/api/cash-accounts/', query: {'fop_id': fopId});
    return (r.data ?? []).map((e) => CashAccount.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<CashAccount> create({
    required String fopId,
    required String name1c,
    String kind = 'bank',
    String? odataRef,
  }) async {
    final r = await _api.post<Map<String, dynamic>>(
      '/api/cash-accounts/',
      query: {'fop_id': fopId},
      data: {'name_1c': name1c, 'kind': kind, 'odata_ref': odataRef},
    );
    return CashAccount.fromJson(r.data!);
  }

  Future<void> delete(String id) async {
    await _api.delete('/api/cash-accounts/$id');
  }
}

class SyncRepository {
  SyncRepository(this._api);
  final ApiClient _api;

  Future<Map<String, dynamic>> uploadPrivat({
    required String fopId,
    required String bankAccountId,
    required String filePath,
    required String filename,
  }) async {
    final r = await _api.upload<Map<String, dynamic>>(
      '/api/sync/privat-upload',
      fieldName: 'file',
      filePath: filePath,
      filename: filename,
      data: {'fop_id': fopId, 'bank_account_id': bankAccountId},
    );
    return r.data ?? {};
  }

  Future<Map<String, dynamic>> uploadCash({
    required String fopId,
    required String cashAccountId,
    required String filePath,
    required String filename,
  }) async {
    final r = await _api.upload<Map<String, dynamic>>(
      '/api/sync/cash-upload',
      fieldName: 'file',
      filePath: filePath,
      filename: filename,
      data: {'fop_id': fopId, 'cash_account_id': cashAccountId},
    );
    return r.data ?? {};
  }

  /// Завантажити повний журнал документів каси — один файл, всі каси.
  /// Парсер мапить рядки на каси за полем «Касса/Счет».
  Future<Map<String, dynamic>> uploadCashJournal({
    required String fopId,
    required String filePath,
    required String filename,
  }) async {
    final r = await _api.upload<Map<String, dynamic>>(
      '/api/sync/cash-journal-upload',
      fieldName: 'file',
      filePath: filePath,
      filename: filename,
      data: {'fop_id': fopId},
    );
    return r.data ?? {};
  }
}

class ODataRepository {
  ODataRepository(this._api);
  final ApiClient _api;

  Future<Map<String, dynamic>> test(String fopId) async {
    final r = await _api.post<Map<String, dynamic>>('/api/odata/$fopId/test');
    return r.data ?? {};
  }

  Future<Map<String, dynamic>> discover(String fopId) async {
    final r = await _api.post<Map<String, dynamic>>('/api/odata/$fopId/discover');
    return r.data ?? {};
  }

  Future<Map<String, dynamic>> syncCatalogs(
    String fopId, {
    String? catalogKasa,
    String? catalogPidrozdil,
  }) async {
    final r = await _api.post<Map<String, dynamic>>(
      '/api/odata/$fopId/sync-catalogs',
      query: {
        if (catalogKasa != null) 'catalog_kasa': catalogKasa,
        if (catalogPidrozdil != null) 'catalog_pidrozdil': catalogPidrozdil,
      },
    );
    return r.data ?? {};
  }

  Future<Map<String, dynamic>> syncCash({
    required String fopId,
    required DateTime periodFrom,
    required DateTime periodTo,
    List<String>? inDocuments,
    List<String>? outDocuments,
    List<String>? transferDocuments,
  }) async {
    final data = <String, dynamic>{
      'period_from': _isoDate(periodFrom),
      'period_to': _isoDate(periodTo),
    };
    if (inDocuments != null) data['in_documents'] = inDocuments;
    if (outDocuments != null) data['out_documents'] = outDocuments;
    if (transferDocuments != null) data['transfer_documents'] = transferDocuments;

    final r = await _api.post<Map<String, dynamic>>(
      '/api/odata/$fopId/sync-cash',
      data: data,
    );
    return r.data ?? {};
  }
}

class ReconRepository {
  ReconRepository(this._api);
  final ApiClient _api;

  Future<List<ReconSession>> listSessions(String fopId) async {
    final r = await _api.get<List<dynamic>>(
      '/api/recon/sessions',
      query: {'fop_id': fopId},
    );
    return (r.data ?? [])
        .map((e) => ReconSession.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<ReconSession> run({
    required String fopId,
    required DateTime periodFrom,
    required DateTime periodTo,
    int dateWindowDays = 14,
    int fuzzyNameThreshold = 70,
  }) async {
    final r = await _api.post<Map<String, dynamic>>('/api/recon/run', data: {
      'fop_id': fopId,
      'period_from': _isoDate(periodFrom),
      'period_to': _isoDate(periodTo),
      'date_window_days': dateWindowDays,
      'fuzzy_name_threshold': fuzzyNameThreshold,
    });
    return ReconSession.fromJson(r.data!);
  }

  Future<List<MatchRow>> rows(String sessionId, {String? kind}) async {
    final r = await _api.get<List<dynamic>>(
      '/api/recon/$sessionId/rows',
      query: kind == null ? null : {'kind': kind},
    );
    return (r.data ?? []).map((e) => MatchRow.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<void> deleteSession(String id) async {
    await _api.delete('/api/recon/$id');
  }

  /// Перерахувати існуючу сесію — очистити рядки і заново зматчити.
  Future<ReconSession> rerun(String sessionId) async {
    final r = await _api.post<Map<String, dynamic>>('/api/recon/$sessionId/rerun');
    return ReconSession.fromJson(r.data!);
  }

  /// Видалити всі сесії ФОПа.
  Future<int> deleteAllSessions(String fopId) async {
    final r = await _api.delete<Map<String, dynamic>>(
      '/api/recon/sessions/all?fop_id=$fopId',
    );
    return (r.data?['deleted'] as int?) ?? 0;
  }
}

String _isoDate(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
