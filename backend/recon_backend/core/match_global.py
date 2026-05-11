"""Глобальний алгоритм матчингу — всі банк-операції ↔ всі каси одночасно.

Відмінність від попереднього `match.py` (попарний):
1. Працює на рівні ФОПа — отримує ВСІ банк-операції з усіх рахунків + ВСІ касові
   документи з усіх кас за період.
2. Виявляє **пересорт між касами**: якщо банк-операція з рахунку А зматчилась у
   касовому документі каси Б (а не очікуваної каси А) — позначаємо як `peresort`.
3. Дата-вікно за замовчуванням **14 днів** (за вказівкою юзера — буває по тижні
   не проводять, а потім провід пачкою).
4. Якщо в касовому документі немає контрагента (звіт «Движение денег») —
   матч робиться по даті ±N + сумі з нижчим скором.

Усі типи даних — звичайні dataclasses (без залежності від SQLAlchemy), щоб ядро
залишалось portable і тестованим окремо від БД.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from rapidfuzz import fuzz

_WORD_RE = re.compile(r"[А-Яа-яA-Za-zЇїІіЄєҐґ']+")


@dataclass(frozen=True)
class BankOpData:
    """Banker-side операція для матчингу. Поля копіюються з моделі BankOp."""

    id: str
    op_date: date
    amount: Decimal
    direction: str  # "in" | "out"
    bank_account_id: str
    counterparty: str = ""
    edrpou: str = ""
    purpose: str = ""


@dataclass(frozen=True)
class CashOpData:
    """1С-side документ для матчингу. Копія з CashOp."""

    id: str
    op_date: date
    amount: Decimal
    op_type: str  # "ПКО" | "ВКО" | "Перемещение"
    cash_account_id: str
    counterparty: str = ""
    edrpou: str = ""
    pidrozdil_id: str = ""
    dok_osnova: str = ""
    comment: str = ""


@dataclass
class MatchOutcome:
    """Результат для одного рядка звірки. Іде в БД як MatchRow."""

    kind: str  # "exact" | "fuzzy" | "peresort_exact" | "peresort_fuzzy" | "bank_only" | "cash_only"
    bank_op_id: str | None = None
    cash_op_id: str | None = None
    expected_cash_account_id: str | None = None  # для peresort — куди мало піти
    actual_cash_account_id: str | None = None    # де реально провели
    score: float = 0.0
    date_diff_days: int = 0
    counterparty_similarity: float = 0.0
    notes: list[str] = field(default_factory=list)


# ─── Допоміжні функції ─────────────────────────────────────────────────


def _direction_to_op_types(direction: str) -> tuple[str, ...]:
    """Мапінг direction → можливі op_types у 1С.

    - in (прихід на банк): тільки ПКО (приходний касовий ордер). Прихід
      клієнта НЕ є переміщенням — це нова грошова операція.
    - out (списання з банку): ВКО (видаток) АБО Перемещение (зняття готівки
      з банкомату оформляється як перемещение банк→каса).
    """
    if direction == "in":
        return ("ПКО",)
    return ("ВКО", "Перемещение")


def _amount_close(a: Decimal, b: Decimal, tolerance: Decimal = Decimal("1.00")) -> bool:
    """Сума «близька» у межах толерансу.

    За замовч. 1 грн — бо в обліку бувало округляли копійки. Для exact-кроку
    окремо викликається з tolerance=0.01.
    """
    return abs(a - b) <= tolerance


def _date_diff(d1: date, d2: date) -> int:
    return abs((d1 - d2).days)


def _name_sim(a: str, b: str) -> float:
    """Найкраща схожість двох строк — макс з token_set_ratio і partial_ratio.

    - token_set_ratio: ігнорує порядок слів, дублікати — добре для імен.
    - partial_ratio: знаходить найкращу підстроку — добре коли одне поле
      містить інше з зайвим текстом.
    """
    if not a or not b:
        return 0.0
    al, bl = a.lower(), b.lower()
    return float(max(
        fuzz.token_set_ratio(al, bl),
        fuzz.partial_ratio(al, bl),
    ))


def _purpose_sim(purpose: str, hint: str) -> float:
    """Те саме що _name_sim — лишаю окрему функцію для семантики."""
    return _name_sim(purpose, hint)


def _significant_words(text: str, min_len: int = 4) -> set[str]:
    """Слова довжиною ≥min_len з тексту, нормалізовані lower-case."""
    if not text:
        return set()
    return {w.lower() for w in _WORD_RE.findall(text) if len(w) >= min_len}


def _shared_significant_words(a: str, b: str, min_len: int = 4) -> set[str]:
    """Спільні значущі слова (≥min_len букв) між двома рядками.

    Призначено для пошуку прізвищ: 'ПИСАРЕНКО' є і в банк-purpose,
    і у каса-counterparty → це майже точно один і той же платіж.
    """
    return _significant_words(a, min_len) & _significant_words(b, min_len)


def _similar_word_pairs(a: str, b: str, min_len: int = 5, threshold: float = 75.0) -> set[tuple[str, str]]:
    """Знайти пари слів з обох рядків які схожі на ≥threshold %.

    Ловить варіанти прізвищ з різними закінченнями: «Рубанська» (банк)
    vs «Рубанський» (1С) — корінь однаковий, fuzz.ratio ~84.
    Або «Левченко» vs «Левч.» — abbreviation.
    """
    a_words = [w.lower() for w in _WORD_RE.findall(a) if len(w) >= min_len]
    b_words = [w.lower() for w in _WORD_RE.findall(b) if len(w) >= min_len]
    matches: set[tuple[str, str]] = set()
    for aw in a_words:
        for bw in b_words:
            if aw == bw:
                continue  # точні збіги ловить _shared_significant_words
            if fuzz.ratio(aw, bw) >= threshold:
                matches.add((aw, bw))
    return matches


# ─── Головна функція ───────────────────────────────────────────────────


def reconcile_global(
    bank_ops: list[BankOpData],
    cash_ops: list[CashOpData],
    bank_to_cash_mapping: dict[str, str | None] | None = None,
    *,
    date_window_days: int = 14,
    name_threshold: float = 70.0,
    blind_date_window_days: int = 7,
) -> list[MatchOutcome]:
    """Глобальна звірка ФОПа.

    Args:
        bank_ops: усі банк-операції ФОПа за період.
        cash_ops: усі касові документи ФОПа за період.
        bank_to_cash_mapping: словник bank_account_id → cash_account_id|None.
            Це мапінг «з якого банку → у яку касу 1С має проводитись».
            Використовується для виявлення пересорту:
            - Якщо банк-операція з рахунку A зматчилась з касою A → exact.
            - Якщо з касою Б (а очікувалась A) → peresort.
        date_window_days: дозволена різниця дат у fuzzy-матчингу (за замовч. 14).
        name_threshold: мінімальна схожість контрагента у fuzzy (0-100).
        blind_date_window_days: дата-вікно для «сліпого» матчингу — коли в касі
            нема контрагента (формат звіту). Менше, щоб мало false positive.

    Returns:
        Список MatchOutcome.
        - Один outcome для кожної заматченої пари (kind=exact|fuzzy|peresort_*).
        - Один outcome для кожної незаматченої банк-операції (kind=bank_only).
        - Один outcome для кожного незаматченого касового документа (kind=cash_only).
    """
    bank_to_cash_mapping = bank_to_cash_mapping or {}

    results: list[MatchOutcome] = []
    bank_matched: set[str] = set()
    cash_matched: set[str] = set()

    # Індексуємо касові операції по (cash_account_id, op_type) для швидкого пошуку.
    cash_by_account_and_type: dict[tuple[str, str], list[CashOpData]] = {}
    for cop in cash_ops:
        key = (cop.cash_account_id, cop.op_type)
        cash_by_account_and_type.setdefault(key, []).append(cop)

    def _candidates(bop: BankOpData) -> list[CashOpData]:
        """Усі каса-операції потрібного типу (для приходу — ПКО, для видатку — ВКО+Перемещение)."""
        out: list[CashOpData] = []
        for op_type in _direction_to_op_types(bop.direction):
            # Спершу очікувана каса (за мапінгом), потім решта — для рангу пересорту.
            expected_cash = bank_to_cash_mapping.get(bop.bank_account_id)
            if expected_cash:
                out.extend(cash_by_account_and_type.get((expected_cash, op_type), []))
            for (cash_acc, ot), ops in cash_by_account_and_type.items():
                if ot != op_type:
                    continue
                if cash_acc == expected_cash:
                    continue
                out.extend(ops)
        return out

    # ─── Крок 1: точні матчі (дата+сума копійка в копійку) у правильній касі ───
    strict_tolerance = Decimal("0.01")
    for bop in bank_ops:
        if bop.id in bank_matched:
            continue
        expected_cash = bank_to_cash_mapping.get(bop.bank_account_id)
        if not expected_cash:
            continue
        for op_type in _direction_to_op_types(bop.direction):
            ops = cash_by_account_and_type.get((expected_cash, op_type), [])
            for cop in ops:
                if cop.id in cash_matched:
                    continue
                if cop.op_date != bop.op_date:
                    continue
                if not _amount_close(cop.amount, bop.amount, tolerance=strict_tolerance):
                    continue
                # Точний збіг у правильній касі.
                bank_matched.add(bop.id)
                cash_matched.add(cop.id)
                results.append(MatchOutcome(
                    kind="exact",
                    bank_op_id=bop.id,
                    cash_op_id=cop.id,
                    expected_cash_account_id=expected_cash,
                    actual_cash_account_id=cop.cash_account_id,
                    score=100.0,
                    counterparty_similarity=_name_sim(bop.counterparty, cop.counterparty),
                ))
                break
            if bop.id in bank_matched:
                break

    # ─── Крок 2: точні матчі (дата+сума копійка в копійку) у будь-якій касі = peresort ───
    for bop in bank_ops:
        if bop.id in bank_matched:
            continue
        expected_cash = bank_to_cash_mapping.get(bop.bank_account_id)
        for cop in _candidates(bop):
            if cop.id in cash_matched:
                continue
            if cop.op_date != bop.op_date:
                continue
            if not _amount_close(cop.amount, bop.amount, tolerance=strict_tolerance):
                continue
            bank_matched.add(bop.id)
            cash_matched.add(cop.id)
            is_peresort = expected_cash and cop.cash_account_id != expected_cash
            kind = "peresort_exact" if is_peresort else "exact"
            note = []
            if is_peresort:
                note.append(f"Провели в касу {cop.cash_account_id}, мало б у {expected_cash}")
            results.append(MatchOutcome(
                kind=kind,
                bank_op_id=bop.id,
                cash_op_id=cop.id,
                expected_cash_account_id=expected_cash,
                actual_cash_account_id=cop.cash_account_id,
                score=95.0 if is_peresort else 100.0,
                counterparty_similarity=_name_sim(bop.counterparty, cop.counterparty),
                notes=note,
            ))
            break

    # ─── Крок 3: fuzzy матчі (дата ±N + контрагент) у будь-якій касі ───
    for bop in bank_ops:
        if bop.id in bank_matched:
            continue
        expected_cash = bank_to_cash_mapping.get(bop.bank_account_id)
        best_cop: CashOpData | None = None
        best_score: float = 0.0
        best_sim: float = 0.0
        best_dd: int = 0
        best_shared: set[str] = set()

        for cop in _candidates(bop):
            if cop.id in cash_matched:
                continue
            if not _amount_close(cop.amount, bop.amount):
                continue
            dd = _date_diff(cop.op_date, bop.op_date)
            if dd > date_window_days:
                continue

            # Розширений fuzzy: шукаємо схожість прізвища/контрагента у БУДЬ-ЯКОМУ
            # з полів обох сторін. У призначенні платежу банку часто пишуть
            # прізвище клієнта; в касі прізвище може бути в counterparty,
            # dok_osnova або comment.
            cash_name_pool = " ".join(filter(None, [
                cop.counterparty, cop.dok_osnova, cop.comment,
            ]))
            bank_name_pool = " ".join(filter(None, [
                bop.counterparty, bop.purpose,
            ]))
            cash_has_name = bool(cash_name_pool.strip())

            if cash_has_name:
                # ШВИДКА перевірка: чи є спільні значущі слова (прізвище)?
                # Якщо так — це майже точно один платіж, дозволяємо матч навіть
                # при низькому ratio (бо ratio може бути низьким через зайвий
                # текст у purpose типу 'Платник: ІПН3496012433 ...').
                shared = _shared_significant_words(bank_name_pool, cash_name_pool)
                # ТАКОЖ: різні форми прізвища (Рубанська/Рубанський, Левченко/Левч.).
                # Шукаємо пари слів з ratio ≥75%.
                similar_pairs = _similar_word_pairs(bank_name_pool, cash_name_pool)
                # Об'єднуємо в один індикатор «знайдено спільне прізвище».
                if similar_pairs:
                    shared = shared | {f"{a}~{b}" for a, b in similar_pairs}
                # Беремо МАКСИМАЛЬНУ схожість серед усіх крос-перевірок:
                #   bank.counterparty ↔ cash.counterparty
                #   bank.counterparty ↔ cash.(dok_osnova/comment)
                #   bank.purpose       ↔ cash.counterparty
                #   bank.purpose       ↔ cash.(dok_osnova/comment)
                sim_c2c = _name_sim(bop.counterparty, cop.counterparty)
                sim_c2d = _purpose_sim(bop.counterparty, f"{cop.dok_osnova} {cop.comment}")
                sim_p2c = _purpose_sim(bop.purpose, cop.counterparty)
                sim_p2d = _purpose_sim(bop.purpose, f"{cop.dok_osnova} {cop.comment}")
                # Загальний крос-pool теж — щоб точно нічого не упустити.
                sim_pool = _name_sim(bank_name_pool, cash_name_pool)
                sim_row = max(sim_c2c, sim_c2d, sim_p2c, sim_p2d, sim_pool)
                # Pass якщо: схожість ≥ поріг АБО є спільне прізвище.
                if sim_row < name_threshold and not shared:
                    continue
                # Якщо знайдене спільне слово — бонус +20 до скору щоб
                # такі матчі мали пріоритет.
                row_score = sim_row - dd * 1.5
                if shared:
                    row_score = max(row_score, 70.0) + len(shared) * 10 - dd * 1.5
            else:
                # Сліпий матчинг (звіт без контрагента) — менший вікно і нижчий скор.
                if dd > blind_date_window_days:
                    continue
                sim_row = 0.0
                row_score = 60.0 - dd * 3

            if row_score > best_score:
                best_cop = cop
                best_score = row_score
                best_sim = sim_row
                best_dd = dd
                best_shared = shared if cash_has_name else set()

        if best_cop is not None:
            bank_matched.add(bop.id)
            cash_matched.add(best_cop.id)
            is_peresort = expected_cash and best_cop.cash_account_id != expected_cash
            kind = "peresort_fuzzy" if is_peresort else "fuzzy"
            notes = []
            if best_shared:
                notes.append(f"Спільні слова: {', '.join(sorted(best_shared))}")
            if best_sim:
                notes.append(f"Нечіткий збіг {best_sim:.0f}%")
            elif not best_shared:
                notes.append("Сліпий збіг — контрагент у касі відсутній")
            if best_dd > 0:
                notes.append(f"Різниця дат {best_dd} дн.")
            if is_peresort:
                notes.append(f"Пересорт: провели у {best_cop.cash_account_id}, мало б у {expected_cash}")
            results.append(MatchOutcome(
                kind=kind,
                bank_op_id=bop.id,
                cash_op_id=best_cop.id,
                expected_cash_account_id=expected_cash,
                actual_cash_account_id=best_cop.cash_account_id,
                score=round(best_score, 2),
                date_diff_days=best_dd,
                counterparty_similarity=best_sim,
                notes=notes,
            ))

    # ─── Крок 4: amount_only — fallback по сумі+даті БЕЗ перевірки прізвища ───
    # Юзер: «спочатку потрібно щоб була окрема група яка матчится в кінці по сумам».
    # Сюди потрапляють залишки коли і прізвища не співпали і слова не співпали,
    # але сума однакова і дата близько. Слабкі матчі — для ручної перевірки.
    for bop in bank_ops:
        if bop.id in bank_matched:
            continue
        expected_cash = bank_to_cash_mapping.get(bop.bank_account_id)
        best_cop: CashOpData | None = None
        best_dd: int = 9999
        for cop in _candidates(bop):
            if cop.id in cash_matched:
                continue
            if not _amount_close(cop.amount, bop.amount, tolerance=Decimal("1.00")):
                continue
            dd = _date_diff(cop.op_date, bop.op_date)
            if dd > date_window_days:
                continue
            # Беремо найближчий по даті.
            if dd < best_dd:
                best_cop = cop
                best_dd = dd
        if best_cop is not None:
            bank_matched.add(bop.id)
            cash_matched.add(best_cop.id)
            results.append(MatchOutcome(
                kind="amount_only",
                bank_op_id=bop.id,
                cash_op_id=best_cop.id,
                actual_cash_account_id=best_cop.cash_account_id,
                expected_cash_account_id=expected_cash,
                score=50.0 - best_dd,
                date_diff_days=best_dd,
                notes=[
                    "Слабкий збіг — лише сума+дата, прізвище не співпало.",
                    "Перевір вручну: можливо це не та сама операція.",
                ],
            ))

    # ─── Крок 5: незаматчені банк → bank_only ───
    for bop in bank_ops:
        if bop.id in bank_matched:
            continue
        results.append(MatchOutcome(
            kind="bank_only",
            bank_op_id=bop.id,
            notes=["Нема пари в жодній касі — треба провести в 1С"],
        ))

    # ─── Крок 6: незаматчені каси → cash_only ───
    for cop in cash_ops:
        if cop.id in cash_matched:
            continue
        results.append(MatchOutcome(
            kind="cash_only",
            cash_op_id=cop.id,
            actual_cash_account_id=cop.cash_account_id,
            notes=["Нема пари в жодному рахунку Privat — внутрішня операція або помилка"],
        ))

    return results
