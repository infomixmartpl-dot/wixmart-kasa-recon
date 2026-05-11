"""Парсер виписки ПриватБанку.

Читає CSV/XLS файл, експортований з Privat24 Business.
Повертає DataFrame зі стандартизованими колонками для подальшого матчингу.

Стандартні колонки на виході:
- date            : datetime  — дата операції
- amount          : Decimal   — сума (завжди додатня; знак у direction)
- direction       : str       — 'in' (прихід) або 'out' (видаток)
- currency        : str       — UAH, USD, EUR ...
- counterparty    : str       — назва контрагента (платник для in, отримувач для out)
- edrpou          : str       — ЄДРПОУ/ІПН якщо є
- purpose         : str       — призначення платежу
- account         : str       — номер рахунку/картки куди зайшло (для розпізнавання підрозділу)
- raw             : dict      — оригінальний рядок виписки (для діагностики)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

# Можливі назви колонок у різних версіях експорту Privat24 Business.
# Зліва — нормалізована назва (lowercase, без пробілів),
# справа — наше внутрішнє ім'я.
COLUMN_ALIASES: dict[str, str] = {
    # Дата
    "дата": "date",
    "датаоперації": "date",
    "датапроводки": "date",
    "дата_проведения": "date",
    "date": "date",
    # Сума
    "сума": "amount",
    "сумаввалютікартки": "amount",
    "сумаввалютікартки(uah)": "amount",
    "сумаввалютіоперації": "amount",
    "amount": "amount",
    # Валюта
    "валюта": "currency",
    "currency": "currency",
    "валютаоперації": "currency",
    # Контрагент (платник для приходу, отримувач для видатку)
    "контрагент": "counterparty",
    "корреспондент": "counterparty",
    "кореспондент": "counterparty",   # укр з одним 'р' — як у виписці Privat юр.особи
    "найменуванняплатника": "counterparty",
    "найменуванняотримувача": "counterparty",
    "назвадругоїсторони": "counterparty",
    "counterparty": "counterparty",
    # ЄДРПОУ — поле edrpou = другої сторони (контрагент). our_edrpou = наш ФОП.
    "єдрпоукореспондента": "edrpou",
    "єдрпоуконтрагента": "edrpou",
    "okpo": "edrpou",
    "code": "edrpou",
    "єдрпоу": "our_edrpou",
    "ідентифікаційнийкод": "our_edrpou",
    # Призначення платежу
    "призначенняплатежу": "purpose",
    "призначення": "purpose",
    "опис": "purpose",
    "описоперації": "purpose",         # 'Опис операції' з ї на кінці
    "purpose": "purpose",
    "description": "purpose",
    # Картка/рахунок (наш або кореспондента)
    "картка": "account",
    "номеркартки": "account",
    "рахунок": "account",
    "номеррахунку": "account",
    "iban": "account",
    "рахуноккореспондента": "account_correspondent",  # рахунок другої сторони
    "ibanкореспондента": "account_correspondent",
    "account": "account",
}

ENCODINGS_TRY = ["utf-8-sig", "utf-8", "cp1251", "windows-1251"]
DELIMITERS_TRY = [";", ",", "\t", "|"]


@dataclass
class PrivatParseResult:
    df: pd.DataFrame
    unmapped_columns: list[str]
    encoding_used: str
    delimiter_used: str


def _normalize_col(name: str) -> str:
    """Прибрати пробіли, розділові знаки, дужки, привести до lowercase.

    Узгоджено з parse_1c._normalize_col.
    'ЄДРПОУ кореспондента' → 'єдрпоукореспондента'
    'Опис операції'         → 'описоперації'
    """
    if name is None:
        return ""
    s = str(name).strip().lower()
    s = re.sub(r"[\s_:\"'`,;.\-/\\()\[\]{}]+", "", s)
    return s


def _try_read_csv(path: Path) -> tuple[pd.DataFrame, str, str]:
    """Перебрати кодування і розділювачі, поки CSV не зчитається з ≥2 колонками."""
    last_err: Exception | None = None
    for enc in ENCODINGS_TRY:
        for delim in DELIMITERS_TRY:
            try:
                df = pd.read_csv(path, encoding=enc, delimiter=delim, dtype=str)
                if df.shape[1] >= 2:
                    return df, enc, delim
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
    raise RuntimeError(
        f"Не вдалось прочитати CSV {path.name}. "
        f"Спробував кодування {ENCODINGS_TRY} і розділювачі {DELIMITERS_TRY}. "
        f"Остання помилка: {last_err}"
    )


def _parse_decimal(value: object) -> Decimal | None:
    """Перетворити '1 234,56' / '1234.56' / '-100,00' на Decimal. None якщо порожньо."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "-"}:
        return None
    # Прибрати пробіли (нерозривні теж) і замінити кому на крапку.
    s = s.replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _parse_date(value: object) -> pd.Timestamp | None:
    """Парсити дату у будь-якому з типових форматів."""
    if value is None or str(value).strip() == "":
        return None
    # Спочатку явні формати, потім pandas автоматичний (з dayfirst).
    formats = ["%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]
    for fmt in formats:
        try:
            return pd.to_datetime(str(value).strip(), format=fmt)
        except (ValueError, TypeError):
            continue
    try:
        return pd.to_datetime(str(value).strip(), dayfirst=True)
    except (ValueError, TypeError):
        return None


def load_privat_statement(path: str | Path) -> PrivatParseResult:
    """Прочитати виписку Privat24 Business і повернути нормалізований DataFrame.

    Підтримує .csv (з різними кодуваннями і розділювачами) та .xlsx/.xls.

    Args:
        path: шлях до файлу виписки.

    Returns:
        PrivatParseResult з:
          - df: DataFrame з колонками date, amount, direction, currency,
            counterparty, edrpou, purpose, account, raw
          - unmapped_columns: список колонок які не вдалось розпізнати
            (вони залишились у raw, але не в основному DataFrame)
          - encoding_used / delimiter_used: для діагностики

    Raises:
        FileNotFoundError: файлу нема.
        RuntimeError: не вдалось прочитати або не знайдено критичних колонок.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Виписка не знайдена: {path}")

    if path.suffix.lower() in {".xlsx", ".xls"}:
        raw_df = pd.read_excel(path, dtype=str)
        encoding_used = "binary-excel"
        delimiter_used = "n/a"
    else:
        raw_df, encoding_used, delimiter_used = _try_read_csv(path)

    raw_df = raw_df.fillna("")

    # Мапимо колонки.
    col_map: dict[str, str] = {}
    unmapped: list[str] = []
    for col in raw_df.columns:
        target = COLUMN_ALIASES.get(_normalize_col(col))
        if target:
            # Якщо вже мапили цю target з іншої колонки — пропускаємо (беремо першу).
            if target not in col_map.values():
                col_map[col] = target
            else:
                unmapped.append(col)
        else:
            unmapped.append(col)

    if "date" not in col_map.values() or "amount" not in col_map.values():
        raise RuntimeError(
            f"У виписці не знайдено колонок 'дата' або 'сума'. "
            f"Знайдені колонки: {list(raw_df.columns)}. "
            f"Додай аліаси у COLUMN_ALIASES у parse_privat.py."
        )

    # Будуємо нормалізований DataFrame.
    out_rows: list[dict] = []
    for _, row in raw_df.iterrows():
        norm: dict = {
            "date": None,
            "amount": None,
            "direction": None,
            "currency": "UAH",
            "counterparty": "",
            "edrpou": "",
            "our_edrpou": "",
            "purpose": "",
            "account_correspondent": "",
            "account": "",
            "raw": dict(row),
        }
        for src_col, tgt in col_map.items():
            value = row[src_col]
            if tgt == "date":
                norm["date"] = _parse_date(value)
            elif tgt == "amount":
                norm["amount"] = _parse_decimal(value)
            else:
                norm[tgt] = str(value).strip()

        # Розрахунок напрямку: знак суми.
        if norm["amount"] is not None:
            if norm["amount"] < 0:
                norm["direction"] = "out"
                norm["amount"] = -norm["amount"]
            else:
                norm["direction"] = "in"

        out_rows.append(norm)

    out_df = pd.DataFrame(out_rows)

    # Викидаємо порожні рядки (без дати або суми).
    out_df = out_df[out_df["date"].notna() & out_df["amount"].notna()].reset_index(drop=True)

    return PrivatParseResult(
        df=out_df,
        unmapped_columns=unmapped,
        encoding_used=encoding_used,
        delimiter_used=delimiter_used,
    )


def filter_by_month(df: pd.DataFrame, year: int, month: int) -> pd.DataFrame:
    """Залишити тільки операції за вказаний рік-місяць."""
    mask = (df["date"].dt.year == year) & (df["date"].dt.month == month)
    return df[mask].reset_index(drop=True)
