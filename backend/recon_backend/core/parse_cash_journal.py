"""Парсер для «Список транзакцій» — повний журнал документів каси з УНФ.

Формат файлу (експорт з УНФ через «Документи руху грошей → Вывести список»):
    Дата | Номер | Сумма | Контрагент | Подотчетник | Касса ККМ |
    Структурная единица | Корреспонденция | Касса/Счет | Операция

Особливості:
- Сума зі знаком: `+` = прихід (ПКО), `-` = розхід (ВКО).
- Колонка «Касса/Счет» — назва каси/рахунку (мапиться на `cash_accounts.name_1c`).
- Колонка «Операция» — текстовий опис («От покупателя», «Поставщику», «На расходы»,
  «Перемещение» тощо). Використовуємо для класифікації переміщень.
- Один файл — багато кас. На відміну від `load_1c_kasa` парсер НЕ
  прив'язує до однієї `cash_account_id` — парсер мапить кожен рядок.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as date_cls
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class CashJournalRow:
    op_date: date_cls
    doc_number: str
    amount: Decimal  # абсолютна (без знаку)
    op_type: str  # "ПКО" | "ВКО" | "Перемещение"
    cash_account_name: str  # з колонки «Касса/Счет», для мапінгу
    counterparty: str
    operation: str  # текстовий опис типу
    comment: str
    structural_unit: str  # «Структурная единица»


@dataclass
class CashJournalResult:
    rows: list[CashJournalRow]
    skipped_no_date: int = 0
    skipped_no_amount: int = 0
    skipped_no_cash: int = 0


def _parse_date(v: Any) -> date_cls | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, date_cls):
        return v if not hasattr(v, "date") else v.date()
    s = str(v).strip()
    if not s:
        return None
    # 31.08.2019, 31/08/2019, 2019-08-31
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            from datetime import datetime as _dt
            return _dt.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(v: Any) -> Decimal | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)):
        try:
            return Decimal(str(v))
        except Exception:
            return None
    s = str(v).strip().replace(" ", "").replace(",", ".").replace("\xa0", "")
    if not s:
        return None
    try:
        return Decimal(s)
    except Exception:
        return None


def _classify_op_type(amount: Decimal, operation: str, comment: str = "") -> str:
    """Класифікувати тип операції за сумою і назвою.

    - «Перемещение» / «переміщ» в операції → завжди Перемещение.
    - Знак суми: `+` = ПКО, `-` = ВКО.
    """
    op_lower = (operation or "").lower()
    com_lower = (comment or "").lower()
    if any(k in op_lower for k in ("перемещ", "переміщ", "перевод")):
        return "Перемещение"
    if any(k in com_lower for k in ("перемещ", "переміщ")):
        return "Перемещение"
    return "ПКО" if amount >= 0 else "ВКО"


def load_cash_journal(path: Path) -> CashJournalResult:
    """Прочитати xlsx журнал документів каси.

    Тільки рядки з валідною датою + сумою + Касса/Счет потрапляють у результат.
    """
    df = pd.read_excel(path, dtype=object)
    df.columns = [str(c).strip() for c in df.columns]

    # Знайти потрібні колонки за нормалізованим іменем.
    def find_col(*candidates: str) -> str | None:
        for col in df.columns:
            norm = str(col).strip().lower().replace("ё", "е")
            for cand in candidates:
                if cand in norm:
                    return col
        return None

    col_date = find_col("дата")
    col_number = find_col("номер")
    col_amount = find_col("сумма", "сума")
    col_counter = find_col("контрагент")
    col_cash = find_col("касса/счет", "каса/рахун", "касса", "каса", "счет", "рахун")
    col_operation = find_col("операц")
    col_unit = find_col("структурн")

    if not (col_date and col_amount and col_cash):
        raise RuntimeError(
            f"Файл не схожий на журнал транзакцій. Знайдено колонки: {list(df.columns)}. "
            f"Очікую щонайменше: Дата, Сумма, Касса/Счет."
        )

    rows: list[CashJournalRow] = []
    skipped_no_date = 0
    skipped_no_amount = 0
    skipped_no_cash = 0

    for _, raw in df.iterrows():
        op_date = _parse_date(raw[col_date])
        if op_date is None:
            skipped_no_date += 1
            continue
        amount_signed = _parse_amount(raw[col_amount])
        if amount_signed is None:
            skipped_no_amount += 1
            continue
        cash_name = str(raw[col_cash] or "").strip()
        if not cash_name:
            skipped_no_cash += 1
            continue

        operation = str(raw[col_operation] or "").strip() if col_operation else ""
        op_type = _classify_op_type(amount_signed, operation)

        rows.append(CashJournalRow(
            op_date=op_date,
            doc_number=str(raw[col_number] or "").strip() if col_number else "",
            amount=abs(amount_signed),  # завжди позитивна для нас
            op_type=op_type,
            cash_account_name=cash_name,
            counterparty=str(raw[col_counter] or "").strip() if col_counter else "",
            operation=operation,
            comment="",
            structural_unit=str(raw[col_unit] or "").strip() if col_unit else "",
        ))

    logger.info(
        "Журнал транзакцій: %d рядків валідні, %d без дати, %d без суми, %d без каси",
        len(rows), skipped_no_date, skipped_no_amount, skipped_no_cash,
    )
    return CashJournalResult(
        rows=rows,
        skipped_no_date=skipped_no_date,
        skipped_no_amount=skipped_no_amount,
        skipped_no_cash=skipped_no_cash,
    )
