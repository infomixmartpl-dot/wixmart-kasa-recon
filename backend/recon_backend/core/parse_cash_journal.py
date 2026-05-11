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

    Auto-detect формату:
    - «Список transaction»: Дата + Касса/Счет + Сумма + Операция.
    - «Перемещения денег»: Дата + Откуда + Куда + Сумма.
    - «Движение денег» (звіт-tree): Банковский счет, касса + Поступление + Расход.
    """
    df = pd.read_excel(path, dtype=object)
    df.columns = [str(c).strip() for c in df.columns]

    # Auto-detect tree-формату звіту «Движение денег».
    # ВАЖЛИВО: з цього звіту беремо ТІЛЬКИ переміщення. Бо у ПКО/ВКО з нього
    # нема прізвищ клієнтів — а ці типи зазвичай вже залиті з «Список transaction»
    # (з прізвищами). Інакше були б дублі + втрата контрагентів.
    cols_lower = {str(c).lower() for c in df.columns}
    if any("оступл" in c for c in cols_lower) and any("асход" in c for c in cols_lower):
        return _load_dvizhenie_report_tree(df, only_transfers=True)

    # Знайти потрібні колонки за нормалізованим іменем.
    # ВАЖЛИВО: кандидати ідуть від більш специфічних → до менш специфічних.
    # Для КОЖНОГО кандидата окремо пройти всі колонки — щоб НЕ вибрати
    # 'Касса ККМ' замість 'Касса/Счет' лише тому що 'касса' матчить першу.
    def find_col(*candidates: str) -> str | None:
        for cand in candidates:
            for col in df.columns:
                norm = str(col).strip().lower().replace("ё", "е")
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

    # Журнал «Перемещения денег» з УНФ — інший формат:
    # Дата | Номер | Откуда | Куда | Сумма документа.
    # Замість «Касса/Счет» — окремі поля «Откуда» (відправник) і «Куда».
    col_from = find_col("откуда", "звідки", "відправник", "источник", "источн")
    col_to = find_col("куда", "куди", "получатель", "одержувач", "приёмник", "получ")
    is_transfer_journal = col_from is not None and col_cash is None

    if not col_date or not col_amount:
        raise RuntimeError(
            f"Файл не схожий на журнал. Знайдено колонки: {list(df.columns)}. "
            f"Очікую щонайменше: Дата, Сумма."
        )
    if not col_cash and not col_from:
        raise RuntimeError(
            f"Файл не має ні «Касса/Счет», ні «Откуда». Колонки: {list(df.columns)}."
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
        # Журнал переміщень: cash_account = «Откуда» (відправник).
        # Стандартний журнал: cash_account = «Касса/Счет».
        if is_transfer_journal:
            raw_cash = raw[col_from]
        else:
            raw_cash = raw[col_cash]
        if pd.isna(raw_cash):
            skipped_no_cash += 1
            continue
        cash_name = str(raw_cash).strip()
        if not cash_name or cash_name.lower() == "nan":
            skipped_no_cash += 1
            continue

        operation = str(raw[col_operation] or "").strip() if col_operation else ""
        if is_transfer_journal:
            op_type = "Перемещение"
            # У comment ховаємо «Куда» — інформативно при ручному перегляді.
            to_name = ""
            if col_to is not None and not pd.isna(raw[col_to]):
                to_name = str(raw[col_to]).strip()
            comment = f"Куди: {to_name}" if to_name else ""
        else:
            op_type = _classify_op_type(amount_signed, operation)
            comment = ""

        rows.append(CashJournalRow(
            op_date=op_date,
            doc_number=str(raw[col_number] or "").strip() if col_number else "",
            amount=abs(amount_signed),  # завжди позитивна для нас
            op_type=op_type,
            cash_account_name=cash_name,
            counterparty=str(raw[col_counter] or "").strip() if col_counter else "",
            operation=operation or ("Переміщення" if is_transfer_journal else ""),
            comment=comment,
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


def _load_dvizhenie_report_tree(df: pd.DataFrame, *, only_transfers: bool = False) -> CashJournalResult:
    """Парсер звіту «Движение денег» (tree-формат).

    only_transfers=True — повертати ТІЛЬКИ переміщення (ПКО/ВКО ігноруються).
        Корисно коли ПКО/ВКО вже залиті з іншого джерела з прізвищами,
        а з цього звіту треба тільки переміщення яких не вистачає.

    Структура:
        Банковский счет, касса / Документ движения | Поступление | Расход | Чистый
        Касса Аня ФОП                              | 92439.73    | 121690  | (header)
          Поступление в кассу 4345 от 19.09.2022   | 1476        |         | ...
          Расход из кассы 1918 от 21.09.2022       |             | 1500    | ...
          Перемещение денег 894 от 19.09.2022      |             | 12000   | ...
    """
    import re as _re

    # Знайти колонки.
    first_col = list(df.columns)[0]  # «Банковский счет, касса» / «Документ движения»
    postup_col = next((c for c in df.columns if "оступл" in str(c).lower()), None)
    rashod_col = next((c for c in df.columns if "асход" in str(c).lower()), None)

    if not postup_col or not rashod_col:
        raise RuntimeError(
            f"У звіті 'Движение денег' нема колонок Поступление/Расход. "
            f"Знайдені: {list(df.columns)}"
        )

    doc_re = _re.compile(
        r"^(.+?)\s+(\d+)\s+(?:от|вiд|від)\s+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4})",
        _re.IGNORECASE,
    )

    rows: list[CashJournalRow] = []
    skipped_no_date = 0
    skipped_no_amount = 0
    skipped_no_cash = 0
    current_kasa = ""

    for _, raw in df.iterrows():
        first_val_raw = raw[first_col]
        if pd.isna(first_val_raw):
            continue
        first_val = str(first_val_raw).strip()
        if not first_val or first_val.lower() in {"документ движения", "документ руху", "nan"}:
            continue

        low = first_val.lower()
        is_doc = any(k in low for k in [
            "поступление", "поступлення", "расход", "видаток",
            "списание", "списання", "перемещение", "переміщення",
        ])
        if not is_doc:
            # Це заголовок каси.
            current_kasa = first_val
            continue

        is_transfer = "перемещ" in low or "переміщ" in low
        # only_transfers=True — пропускаємо ПКО/ВКО, бо вони мають кращу
        # версію у іншому файлі (з прізвищами клієнтів).
        if only_transfers and not is_transfer:
            continue

        m = doc_re.match(first_val)
        if not m:
            continue
        type_text, doc_number, date_str = m.groups()
        op_date = _parse_date(date_str)
        if op_date is None:
            skipped_no_date += 1
            continue
        if not current_kasa:
            skipped_no_cash += 1
            continue

        amount_in = _parse_amount(raw[postup_col])
        amount_out = _parse_amount(raw[rashod_col])

        if amount_in is not None and amount_in > 0:
            # Для переміщень: amount у Поступление = каса-одержувач.
            # Для звичайних ПКО — це прихід. У БД пишемо op_type=Перемещение
            # якщо це переміщення, інакше ПКО.
            op_type = "Перемещение" if is_transfer else "ПКО"
            amount = amount_in
        elif amount_out is not None and amount_out > 0:
            op_type = "Перемещение" if is_transfer else "ВКО"
            amount = amount_out
        else:
            skipped_no_amount += 1
            continue

        # Документ-номер з префіксом «ПЕРЕМ-» / «ПКО-» / «ВКО-» щоб не
        # колідувати з номерами з «Список transaction» (НФНФ-XXXXXX).
        # Краще створити унікальний ключ ніж випадково перетертися дублем.
        prefix = "ПЕРЕМ" if is_transfer else type_text.upper().replace(" ", "")[:5]
        unique_doc = f"{prefix}-{doc_number}"

        rows.append(CashJournalRow(
            op_date=op_date,
            doc_number=unique_doc,
            amount=amount,
            op_type=op_type,
            cash_account_name=current_kasa,
            counterparty="",
            operation=type_text.strip(),
            comment=first_val,  # повний рядок для детального перегляду
            structural_unit="",
        ))

    logger.info(
        "Звіт 'Движение денег': %d рядків, %d без дати, %d без суми, %d без каси",
        len(rows), skipped_no_date, skipped_no_amount, skipped_no_cash,
    )
    return CashJournalResult(
        rows=rows,
        skipped_no_date=skipped_no_date,
        skipped_no_amount=skipped_no_amount,
        skipped_no_cash=skipped_no_cash,
    )
