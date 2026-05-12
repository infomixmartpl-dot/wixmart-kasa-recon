/// Riverpod провайдери: API клієнт, репозиторії, активний ФОП.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../api/repositories.dart';
import '../models/models.dart';

/// Центральний HTTP-клієнт. baseUrl задаємо через `setBaseUrl` після старту бекенду.
final apiClientProvider = Provider<ApiClient>((ref) {
  // Embedded: бекенд слухає на 127.0.0.1:8765, запускається BackendSupervisor-ом.
  return ApiClient(baseUrl: 'http://127.0.0.1:8765');
});

final fopRepoProvider = Provider((ref) => FopRepository(ref.read(apiClientProvider)));
final bankAccountRepoProvider = Provider((ref) => BankAccountRepository(ref.read(apiClientProvider)));
final cashAccountRepoProvider = Provider((ref) => CashAccountRepository(ref.read(apiClientProvider)));
final syncRepoProvider = Provider((ref) => SyncRepository(ref.read(apiClientProvider)));
final reconRepoProvider = Provider((ref) => ReconRepository(ref.read(apiClientProvider)));
final odataRepoProvider = Provider((ref) => ODataRepository(ref.read(apiClientProvider)));

/// Список усіх ФОПів — реактивно оновлюється кнопкою «оновити».
final fopsProvider = FutureProvider<List<Fop>>((ref) async {
  return ref.read(fopRepoProvider).list();
});

/// Активний ФОП (з якого працює юзер). null до вибору.
final selectedFopProvider = StateProvider<Fop?>((ref) => null);

/// Банк-рахунки активного ФОПа.
final bankAccountsProvider = FutureProvider.autoDispose<List<BankAccount>>((ref) async {
  final fop = ref.watch(selectedFopProvider);
  if (fop == null) return [];
  return ref.read(bankAccountRepoProvider).listByFop(fop.id);
});

/// Каси 1С активного ФОПа.
final cashAccountsProvider = FutureProvider.autoDispose<List<CashAccount>>((ref) async {
  final fop = ref.watch(selectedFopProvider);
  if (fop == null) return [];
  return ref.read(cashAccountRepoProvider).listByFop(fop.id);
});

/// Сесії звірки активного ФОПа.
final reconSessionsProvider = FutureProvider.autoDispose<List<ReconSession>>((ref) async {
  final fop = ref.watch(selectedFopProvider);
  if (fop == null) return [];
  return ref.read(reconRepoProvider).listSessions(fop.id);
});

/// Підрозділи активного ФОПа (для dropdown у діях 1С).
final pidrozdilyProvider = FutureProvider.autoDispose<List<Pidrozdil>>((ref) async {
  final fop = ref.watch(selectedFopProvider);
  if (fop == null) return [];
  return ref.read(pidrozdilRepoProvider).listByFop(fop.id);
});

/// Статті руху коштів активного ФОПа.
final stattiProvider = FutureProvider.autoDispose<List<Stattia>>((ref) async {
  final fop = ref.watch(selectedFopProvider);
  if (fop == null) return [];
  return ref.read(stattiaRepoProvider).listByFop(fop.id);
});

final pidrozdilRepoProvider = Provider((ref) => PidrozdilRepository(ref.read(apiClientProvider)));
final stattiaRepoProvider = Provider((ref) => StattiaRepository(ref.read(apiClientProvider)));
