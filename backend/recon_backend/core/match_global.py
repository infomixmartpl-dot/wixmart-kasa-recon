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

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from rapidfuzz import fuzz


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

    - in (прихід на банк): ПКО (классичний) АБО Перемещение (виручка з POS-
      терміналу часто проводиться як перемещение банк→каса, а не ПКО).
    - out (списання з банку): ВКО (видаток) АБО Перемещение (зняття готівки
      з банкомату — перемещение банк→каса, або переказ на інший рахунок).
    """
    if direction == "in":
        return ("ПКО", "Перемещение")
    return ("ВКО", "Перемещение")


def _amount_close(a: Decimal, b: Decimal, tolerance: Decimal = Decimal("0.01")) -> bool:
    return abs(a - b) <= tolerance


def _date_diff(d1: date, d2: date) -> int:
    return abs((d1 - d2).days)


def _name_sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return float(fuzz.token_set_ratio(a.lower(), b.lower()))


def _purpose_sim(purpose: str, hint: str) -> float:
    if not purpose or not hint:
        return 0.0
    return float(fuzz.partial_ratio(purpose.lower(), hint.lower()))


# ─── Головна функція ───────────────────────────────────────────────────


def reconcile_global(
    bank_ops: list[BankOpData],
    cash_ops: list[CashOpData],
    bank_to_cash_mapping: dict[str, str | None] | None = None,
    *,
    date_window_days: int = 14,
    name_threshold: float = 85.0,
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

    # ─── Крок 1: точні матчі (дата+сума) у правильній касі (за мапінгом) ───
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
                if not _amount_close(cop.amount, bop.amount):
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

    # ─── Крок 2: точні матчі (дата+сума) у будь-якій касі = peresort ───
    for bop in bank_ops:
        if bop.id in bank_matched:
            continue
        expected_cash = bank_to_cash_mapping.get(bop.bank_account_id)
        for cop in _candidates(bop):
            if cop.id in cash_matched:
                continue
            if cop.op_date != bop.op_date:
                continue
            if not _amount_close(cop.amount, bop.amount):
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

        for cop in _candidates(bop):
            if cop.id in cash_matched:
                continue
            if not _amount_close(cop.amount, bop.amount):
                continue
            dd = _date_diff(cop.op_date, bop.op_date)
            if dd > date_window_days:
                continue

            cash_has_name = bool(cop.counterparty) or bool(cop.dok_osnova)
            if cash_has_name:
                # Стандартний fuzzy: схожість імені / призначення з порогом.
                sim_name = _name_sim(bop.counterparty, cop.counterparty)
                sim_purpose = _purpose_sim(bop.purpose, f"{cop.comment} {cop.dok_osnova}")
                sim_row = max(sim_name, sim_purpose)
                if sim_row < name_threshold:
                    continue
                row_score = sim_row - dd * 1.5
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

        if best_cop is not None:
            bank_matched.add(bop.id)
            cash_matched.add(best_cop.id)
            is_peresort = expected_cash and best_cop.cash_account_id != expected_cash
            kind = "peresort_fuzzy" if is_peresort else "fuzzy"
            notes = []
            if best_sim:
                notes.append(f"Нечіткий збіг {best_sim:.0f}%")
            else:
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

    # ─── Крок 4: незаматчені банк → bank_only ───
    for bop in bank_ops:
        if bop.id in bank_matched:
            continue
        results.append(MatchOutcome(
            kind="bank_only",
            bank_op_id=bop.id,
            notes=["Нема пари в жодній касі — треба провести в 1С"],
        ))

    # ─── Крок 5: незаматчені каси → cash_only ───
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
