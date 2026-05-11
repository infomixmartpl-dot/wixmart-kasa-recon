"""Алгоритм співставлення банк ↔ каса 1С.

Стратегія у 3 кроки:

1. **Точне співставлення** (greedy): для кожної операції з банку шукаємо
   касовий ордер з тією самою датою, сумою і напрямком (in→ПКО, out→ВКО).
   Якщо знайдено — пара заматчена, обидві позначаються.

2. **Нечітке співставлення** (fuzzy): для незаматчених — шукаємо в межах
   ±N днів з тією ж сумою і схожим контрагентом (rapidfuzz).

3. **Залишки**:
   - У банку → потрапляють у "До проведення" (треба створити ПКО/ВКО).
   - У 1С → потрапляють у "Тільки в касі" (внутрішні операції? помилки?).

Окремо: коли пара знайдена, але підрозділ у ПКО не відповідає очікуваному
(за правилом рахунок Privat → підрозділ), пара йде в "Пересорт".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Optional

import pandas as pd
from rapidfuzz import fuzz


@dataclass
class MatchResult:
    """Результат однієї одиниці звірки."""

    kind: str  # 'exact_match' | 'fuzzy_match' | 'bank_only' | 'cash_only' | 'mismatch_podrozdil'
    bank_row: Optional[dict] = None
    cash_row: Optional[dict] = None
    score: float = 0.0  # 0..100, ступінь впевненості
    date_diff_days: int = 0
    amount_diff: Decimal = Decimal("0")
    counterparty_similarity: float = 0.0
    expected_podrozdil: str = ""
    notes: list[str] = field(default_factory=list)


def _direction_to_doc_type(direction: str) -> str:
    """in/out (банк) → ПКО/ВКО (1С)."""
    return "ПКО" if direction == "in" else "ВКО"


def _amount_close(a: Decimal, b: Decimal, tolerance: Decimal = Decimal("0.01")) -> bool:
    return abs(a - b) <= tolerance


def _date_diff_days(d1: pd.Timestamp, d2: pd.Timestamp) -> int:
    return abs((d1 - d2).days)


def _counterparty_similarity(name1: str, name2: str) -> float:
    """Схожість двох імен 0..100. Стійка до перестановки слів і регістру."""
    if not name1 or not name2:
        return 0.0
    return float(fuzz.token_set_ratio(name1.lower(), name2.lower()))


def _purpose_similarity(purpose: str, hint: str) -> float:
    """Схожість призначення платежу і коментаря/документа-основи."""
    if not purpose or not hint:
        return 0.0
    return float(fuzz.partial_ratio(purpose.lower(), hint.lower()))


def reconcile(
    bank_df: pd.DataFrame,
    cash_df: pd.DataFrame,
    *,
    expected_podrozdil_fn: Callable[[dict], str] | None = None,
    fuzzy_date_window_days: int = 2,
    fuzzy_name_threshold: float = 85.0,
) -> list[MatchResult]:
    """Зіставити банк і касу 1С.

    Args:
        bank_df: DataFrame від parse_privat.load_privat_statement.
        cash_df: DataFrame від parse_1c.load_1c_kasa.
        expected_podrozdil_fn: функція що по рядку банку повертає очікуваний підрозділ
            (наприклад, по картці Privat → підрозділ із pidrozdily.xlsx).
            Якщо None — перевірку підрозділу не робимо.
        fuzzy_date_window_days: дозволена різниця у днях для нечіткого матчу.
        fuzzy_name_threshold: мінімальна схожість контрагента (0-100) для fuzzy.

    Returns:
        Список MatchResult — для кожної операції банку АБО для непов'язаних
        касових ордерів. Загальна кількість = bank.rows + cash_only.rows.
    """
    results: list[MatchResult] = []
    bank_matched: set[int] = set()
    cash_matched: set[int] = set()

    # === Крок 1: точні матчі ===
    for bi, brow in bank_df.iterrows():
        if bi in bank_matched:
            continue
        b_date = brow["date"]
        b_amount = brow["amount"]
        b_doc_type = _direction_to_doc_type(brow["direction"])

        for ci, crow in cash_df.iterrows():
            if ci in cash_matched:
                continue
            if crow["doc_type"] != b_doc_type:
                continue
            if crow["date"] != b_date:
                continue
            if not _amount_close(crow["amount"], b_amount):
                continue
            # Точний матч.
            bank_matched.add(bi)
            cash_matched.add(ci)
            sim = _counterparty_similarity(brow["counterparty"], crow["counterparty"])
            expected = expected_podrozdil_fn(brow.to_dict()) if expected_podrozdil_fn else ""
            kind = "exact_match"
            notes: list[str] = []
            if expected and crow["podrozdil"] and expected != crow["podrozdil"]:
                kind = "mismatch_podrozdil"
                notes.append(
                    f"Підрозділ у 1С '{crow['podrozdil']}', а має бути '{expected}'"
                )
            results.append(
                MatchResult(
                    kind=kind,
                    bank_row=brow.to_dict(),
                    cash_row=crow.to_dict(),
                    score=100.0,
                    date_diff_days=0,
                    amount_diff=Decimal("0"),
                    counterparty_similarity=sim,
                    expected_podrozdil=expected,
                    notes=notes,
                )
            )
            break

    # === Крок 2: нечіткі матчі для незаматчених рядків банку ===
    for bi, brow in bank_df.iterrows():
        if bi in bank_matched:
            continue
        b_date = brow["date"]
        b_amount = brow["amount"]
        b_doc_type = _direction_to_doc_type(brow["direction"])
        b_name = brow["counterparty"]
        b_purpose = brow["purpose"]

        best_ci: int | None = None
        best_score: float = 0.0
        best_sim: float = 0.0
        best_date_diff: int = 0

        for ci, crow in cash_df.iterrows():
            if ci in cash_matched:
                continue
            if crow["doc_type"] != b_doc_type and crow["doc_type"] != "?":
                continue
            if not _amount_close(crow["amount"], b_amount):
                continue
            date_diff = _date_diff_days(crow["date"], b_date)
            if date_diff > fuzzy_date_window_days:
                continue
            sim_name = _counterparty_similarity(b_name, crow["counterparty"])
            # Якщо ім'я не схоже, спробуємо за призначенням платежу і коментарем.
            sim_purpose = _purpose_similarity(b_purpose, crow["comment"] + " " + crow["dok_osnova"])
            best_sim_row = max(sim_name, sim_purpose)

            # Спецкейс для звіту "Движение денег": якщо в касі НЕМА контрагента,
            # дозволяємо матч по даті ±N + сумі. Скор нижчий — щоб видно було що
            # це менш надійний збіг.
            cash_has_counterparty = bool(crow["counterparty"]) or bool(crow.get("dok_osnova"))
            if not cash_has_counterparty:
                # Дата+сума збіглись — приймаємо. Скор = 60 (середній) мінус штраф за дні.
                row_score = 60 - date_diff * 10
                if row_score > best_score:
                    best_ci = ci
                    best_score = row_score
                    best_sim = 0.0  # контрагента нема — схожість невизначена
                    best_date_diff = date_diff
                continue

            # Загальний скор: схожість мінус штраф за різницю дат.
            row_score = best_sim_row - date_diff * 5
            if best_sim_row >= fuzzy_name_threshold and row_score > best_score:
                best_ci = ci
                best_score = row_score
                best_sim = best_sim_row
                best_date_diff = date_diff

        if best_ci is not None:
            bank_matched.add(bi)
            cash_matched.add(best_ci)
            crow = cash_df.loc[best_ci]
            expected = expected_podrozdil_fn(brow.to_dict()) if expected_podrozdil_fn else ""
            kind = "fuzzy_match"
            notes: list[str] = [f"Нечіткий збіг: схожість контрагента {best_sim:.0f}%"]
            if best_date_diff > 0:
                notes.append(f"Різниця дат {best_date_diff} дн.")
            if expected and crow["podrozdil"] and expected != crow["podrozdil"]:
                kind = "mismatch_podrozdil"
                notes.append(
                    f"Підрозділ у 1С '{crow['podrozdil']}', а має бути '{expected}'"
                )
            results.append(
                MatchResult(
                    kind=kind,
                    bank_row=brow.to_dict(),
                    cash_row=crow.to_dict(),
                    score=best_score,
                    date_diff_days=best_date_diff,
                    amount_diff=Decimal("0"),
                    counterparty_similarity=best_sim,
                    expected_podrozdil=expected,
                    notes=notes,
                )
            )

    # === Крок 3: незаматчений банк — "До проведення" ===
    for bi, brow in bank_df.iterrows():
        if bi in bank_matched:
            continue
        results.append(
            MatchResult(
                kind="bank_only",
                bank_row=brow.to_dict(),
                cash_row=None,
                score=0.0,
                notes=["Нема в касі 1С — треба створити документ"],
            )
        )

    # === Крок 4: незаматчена каса — "Тільки в касі" ===
    for ci, crow in cash_df.iterrows():
        if ci in cash_matched:
            continue
        results.append(
            MatchResult(
                kind="cash_only",
                bank_row=None,
                cash_row=crow.to_dict(),
                score=0.0,
                notes=["Нема в банку — перевір чи це внутрішня операція"],
            )
        )

    return results


def find_realization_basis(
    bank_row: dict,
    realizacii_df: pd.DataFrame,
    *,
    date_window_days: int = 30,
    name_threshold: float = 85.0,
) -> dict | None:
    """Знайти Реалізацію в 1С яка може бути основою для приходу.

    Критерії:
    - Той самий контрагент (точно або схоже за rapidfuzz).
    - Дата Реалізації ≤ дата приходу.
    - Сума Реалізації ≥ сума приходу (часткова оплата дозволена).
    - У межах date_window_days.

    Returns:
        Словник з полями Реалізації або None.
    """
    if realizacii_df.empty:
        return None
    b_date = bank_row["date"]
    b_amount = bank_row["amount"]
    b_name = bank_row["counterparty"]

    best: dict | None = None
    best_score: float = 0.0

    for _, rrow in realizacii_df.iterrows():
        if rrow["date"] > b_date:
            continue
        if (b_date - rrow["date"]).days > date_window_days:
            continue
        if rrow["amount"] < b_amount:
            continue
        sim = _counterparty_similarity(b_name, rrow["counterparty"])
        if sim < name_threshold:
            continue
        # Більший score — точніший збіг сум і менша різниця дат.
        amount_match = 100 - float(abs(rrow["amount"] - b_amount)) / float(rrow["amount"]) * 100
        date_proximity = 100 - (b_date - rrow["date"]).days * 2
        score = sim * 0.5 + amount_match * 0.3 + date_proximity * 0.2
        if score > best_score:
            best_score = score
            best = rrow.to_dict()
            best["_match_score"] = score
            best["_name_similarity"] = sim

    return best
