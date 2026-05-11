"""Парсер вивантажень з 1С (УТП/УНФ).

Читає Excel-файли, експортовані з 1С через "Вивести список" або зі звітів.
Формати трохи відрізняються між конфігураціями (УТП 1.3, УНФ 1.6, Бухгалтерія),
тому використовуємо гнучкі аліаси колонок.

Три типи вивантажень:
- kasa         : Реєстр касових ордерів (ПКО + ВКО)
- realizacii   : Реалізації товарів і послуг (потрібні для прив'язки приходів)
- zamovlennia  : Замовлення покупців (альтернативна основа для приходу)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

# Аліаси колонок для кас.ордерів. Ключі — нормалізовані (lowercase без пробілів).
KASA_ALIASES: dict[str, str] = {
    "дата": "date",
    "датадокумента": "date",
    "номер": "doc_number",
    "номердокумента": "doc_number",
    "виддокумента": "doc_type",
    "видоперації": "doc_type",
    "видоперации": "doc_type",
    "операція": "doc_type",
    "операция": "doc_type",
    "тип": "doc_type",
    "сума": "amount",
    "суммадокумента": "amount",
    "сумма": "amount",
    "сумаоперації": "amount",
    "сумаоперації(грн)": "amount",
    "контрагент": "counterparty",
    "корреспондент": "counterparty",
    "получатель": "counterparty",
    "отримувач": "counterparty",
    "платник": "counterparty",
    "єдрпоу": "edrpou",
    "окпо": "edrpou",
    "підрозділ": "podrozdil",
    "подразделение": "podrozdil",
    "підрозділорганізації": "podrozdil",
    # Усі варіанти нормалізуються прибиранням розділових знаків:
    # "Банковский счет, касса" → "банковскийсчеткасса"
    # "Касса/Счет"             → "кассасчет"
    "банковскийсчеткасса": "kasa_schet",
    "кассасчет": "kasa_schet",
    "касарахунок": "kasa_schet",
    "каса": "kasa_schet",
    "касса": "kasa_schet",
    "счет": "kasa_schet",
    "рахунок": "kasa_schet",
    "стаття": "stattia",
    "статьядвиженияденежныхсредств": "stattia",
    "статтярухугрошовихкоштів": "stattia",
    "статтязатрат": "stattia",
    "статьязатрат": "stattia",
    "документоснова": "dok_osnova",
    "документпідстава": "dok_osnova",
    "документоснование": "dok_osnova",
    "основа": "dok_osnova",
    "основание": "dok_osnova",
    "коментар": "comment",
    "комментарий": "comment",
    "призначенняплатежу": "comment",
}

REALIZACII_ALIASES: dict[str, str] = {
    "дата": "date",
    "номер": "doc_number",
    "сума": "amount",
    "сумма": "amount",
    "контрагент": "counterparty",
    "покупець": "counterparty",
    "покупатель": "counterparty",
    "єдрпоу": "edrpou",
    "окпо": "edrpou",
    "підрозділ": "podrozdil",
    "подразделение": "podrozdil",
}

ZAMOVLENNIA_ALIASES = REALIZACII_ALIASES.copy()


@dataclass
class Load1CResult:
    df: pd.DataFrame
    unmapped_columns: list[str]


def _normalize_col(name: str) -> str:
    """Прибрати пробіли, розділові знаки, дужки, привести до lowercase.

    'Банковский счет, касса' → 'банковскийсчеткасса'
    'Касса/Счет'             → 'кассасчет'
    'Вид операції'            → 'видоперації'
    """
    if name is None:
        return ""
    s = str(name).strip().lower()
    # Прибираємо всі розділові знаки, дужки, лапки, пробіли — залишається тільки текст.
    s = re.sub(r"[\s_:\"'`,;.\-/\\()\[\]{}]+", "", s)
    return s


def _parse_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "-"}:
        return None
    s = s.replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _parse_date(value: object) -> pd.Timestamp | None:
    if value is None or str(value).strip() == "":
        return None
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


def _classify_doc_type(value: str) -> str:
    """ПКО / ВКО / unknown — з тексту назви документа.

    Покриває і УТП (ПКО/ВКО), і УНФ (Поступление/Списание/Расход денег,
    а також "Перемещение денег" — переказ між касами, з банку у готівку).

    Повертає внутрішню абстракцію ПКО (=прихід у касу/рахунок) /
    ВКО (=видаток з каси/рахунку).
    """
    s = str(value).lower()
    if any(k in s for k in ["прибутковий", "приходный", "пко", "приход", "поступление", "поступлення", "надходження"]):
        return "ПКО"
    if any(k in s for k in ["видатковий", "расходный", "вко", "расход", "списание", "списання"]):
        return "ВКО"
    # Перемещение денег — для конкретної каси у звіті це або прихід, або видаток.
    # У парсері звіту ми визначаємо напрямок за тим, в якій колонці сума (Поступление/Расход),
    # тому тут повертаємо ВКО за замовчуванням — реальний напрямок встановлюється там.
    if any(k in s for k in ["перемещение", "перемещ", "переміщення", "перемі"]):
        return "ВКО"
    return "?"


def _read_excel_or_csv(path: Path) -> pd.DataFrame:
    """Прочитати файл — Excel або CSV — як DataFrame з усіма колонками як рядок."""
    if not path.exists():
        raise FileNotFoundError(f"Файл не знайдений: {path}")
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, dtype=str).fillna("")
    # CSV — пробуємо utf-8 і cp1251.
    for enc in ["utf-8-sig", "utf-8", "cp1251"]:
        for delim in [";", ",", "\t"]:
            try:
                df = pd.read_csv(path, encoding=enc, delimiter=delim, dtype=str)
                if df.shape[1] >= 2:
                    return df.fillna("")
            except Exception:  # noqa: BLE001
                continue
    raise RuntimeError(f"Не зміг прочитати {path}")


def _apply_aliases(
    raw_df: pd.DataFrame, aliases: dict[str, str]
) -> tuple[dict[str, str], list[str]]:
    """Зіставити колонки за аліасами. Повертає (col_map, unmapped)."""
    col_map: dict[str, str] = {}
    unmapped: list[str] = []
    for col in raw_df.columns:
        target = aliases.get(_normalize_col(col))
        if target and target not in col_map.values():
            col_map[col] = target
        else:
            unmapped.append(col)
    return col_map, unmapped


def load_1c_kasa(path: str | Path) -> Load1CResult:
    """Прочитати журнал касових/банківських документів з 1С.

    Підтримує:
    - УТП/Бухгалтерія — Прибуткові і Видаткові касові ордери (ПКО/ВКО).
    - УНФ 1.6 — документи Поступление денег / Списание денег / Расход денег
      з реквізитом 'Банковский счет, касса' (мапиться у поле kasa_schet).

    Очікувані колонки (різні написання): Дата, Номер, Вид операції/документа,
    Сума, Контрагент, ЄДРПОУ, Підрозділ, Каса/Рахунок (УНФ), Стаття,
    Документ-основа, Коментар.

    Returns:
        DataFrame з колонками:
        date, doc_number, doc_type ('ПКО'=прихід / 'ВКО'=видаток / '?'),
        amount, counterparty, edrpou, podrozdil, kasa_schet, stattia,
        dok_osnova, comment, raw.
    """
    path = Path(path)
    raw_df = _read_excel_or_csv(path)
    col_map, unmapped = _apply_aliases(raw_df, KASA_ALIASES)

    if "date" not in col_map.values() or "amount" not in col_map.values():
        raise RuntimeError(
            f"У вивантаженні каси нема колонок 'Дата' або 'Сума'. "
            f"Знайдені: {list(raw_df.columns)}. "
            f"Перевір що це не .mxl а .xlsx."
        )

    rows: list[dict] = []
    for _, row in raw_df.iterrows():
        norm: dict = {
            "date": None,
            "doc_number": "",
            "doc_type": "?",
            "amount": None,
            "counterparty": "",
            "edrpou": "",
            "podrozdil": "",
            "kasa_schet": "",  # для УНФ — назва каси/рахунку з довідника "Банковский счет, касса"
            "stattia": "",
            "dok_osnova": "",
            "comment": "",
            "raw": dict(row),
        }
        for src_col, tgt in col_map.items():
            value = row[src_col]
            if tgt == "date":
                norm["date"] = _parse_date(value)
            elif tgt == "amount":
                norm["amount"] = _parse_decimal(value)
            elif tgt == "doc_type":
                norm["doc_type"] = _classify_doc_type(str(value))
            else:
                norm[tgt] = str(value).strip()

        # Якщо doc_type ще '?', спробуємо вгадати з номера або коментаря.
        if norm["doc_type"] == "?":
            hint = f"{norm['doc_number']} {norm['comment']}".lower()
            norm["doc_type"] = _classify_doc_type(hint)

        rows.append(norm)

    out_df = pd.DataFrame(rows)
    out_df = out_df[out_df["date"].notna() & out_df["amount"].notna()].reset_index(drop=True)

    return Load1CResult(df=out_df, unmapped_columns=unmapped)


def load_1c_dvizhenie_report(path: str | Path) -> Load1CResult:
    """Прочитати звіт УНФ "Движение денег" (ієрархічний формат, не журнал).

    Цей звіт має структуру:
        | Банковский счет, касса             | Нач.остаток | Поступление | Расход | Кон.остаток |
        | (sub-header "Документ движения")    |             |             |        |             |
        | Касса Аня ФОП                       | 92439.73    | 128557.06   | 121690 | 99306.79    |
        |   Поступление в кассу 4345 от 19.09 | 92439.73    | 1476        |        | 93915.73    |
        |   Расход из кассы 1918 от 21.09     | 99901.64    |             | 1500   | 98401.64    |
        |   Перемещение денег 894 от 19.09    | 112021.64   |             | 12000  | 100021.64   |

    З цього звіту можна витягти лише: дату, номер, суму і тип документа.
    Контрагент/ЄДРПОУ/підрозділ/основа — їх у звіті НЕМАЄ.

    Тому матчинг з банком буде тільки по date+amount (без fuzzy по контрагенту).
    Для повноцінної звірки потрібен журнал документів — див. load_1c_kasa().

    Перемещение денег — внутрішні операції між касами, ігноруються.
    """
    path = Path(path)
    raw_df = _read_excel_or_csv(path)

    if "Банковский счет, касса" not in raw_df.columns and "Каса/Рахунок" not in raw_df.columns:
        # Спробуємо знайти першу колонку схожу на header.
        first_col = list(raw_df.columns)[0]
    else:
        first_col = next(
            (c for c in raw_df.columns if "касса" in str(c).lower() or "каса" in str(c).lower()),
            list(raw_df.columns)[0],
        )

    postup_col = next((c for c in raw_df.columns if "оступл" in str(c).lower() or "адхо" in str(c).lower()), None)
    rashod_col = next((c for c in raw_df.columns if "асход" in str(c).lower() or "идаток" in str(c).lower() or "пис" in str(c).lower()), None)

    if not postup_col or not rashod_col:
        raise RuntimeError(
            f"У звіті 'Движение денег' нема колонок Поступление/Расход. "
            f"Знайдені: {list(raw_df.columns)}"
        )

    # Регулярка для розбору рядка документа: "Тип ... NN от DD.MM.YYYY"
    doc_re = re.compile(
        r"^(.+?)\s+(\d+)\s+(?:от|вiд|від)\s+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4})",
        re.IGNORECASE,
    )

    current_kasa = ""
    rows: list[dict] = []
    unmapped: list[str] = []

    for _, row in raw_df.iterrows():
        first_val = str(row[first_col]).strip()
        if not first_val or first_val.lower() in {"документ движения", "документ руху"}:
            continue

        # Якщо у рядку нема ключових слів типу документа — це назва каси (group header).
        low = first_val.lower()
        is_doc = any(k in low for k in ["поступление", "поступлення", "расход", "видаток", "списание", "списання", "перемещение", "переміщення"])
        if not is_doc:
            current_kasa = first_val
            continue

        m = doc_re.match(first_val)
        if not m:
            continue
        type_text, doc_number, date_str = m.groups()

        date = _parse_date(date_str)
        if date is None:
            continue

        # Для звіту "Движение денег": напрямок визначається тим, в якій колонці є сума.
        # Поступление = ПКО (прихід у касу/рахунок), Расход = ВКО (видаток).
        # Це коректно і для "Перемещение денег" — воно показано як видаток з тієї каси,
        # з якої гроші вийшли (а в іншій касі — як прихід).
        amount_in = _parse_decimal(row[postup_col])
        amount_out = _parse_decimal(row[rashod_col])

        if amount_in is not None and amount_in > 0:
            doc_type = "ПКО"
            amount = amount_in
        elif amount_out is not None and amount_out > 0:
            doc_type = "ВКО"
            amount = amount_out
        else:
            continue

        rows.append(
            {
                "date": date,
                "doc_number": doc_number,
                "doc_type": doc_type,
                "amount": amount,
                "counterparty": "",
                "edrpou": "",
                "podrozdil": "",
                "kasa_schet": current_kasa,
                "stattia": "",
                "dok_osnova": "",
                "comment": first_val,
                "raw": dict(row),
            }
        )

    out_df = pd.DataFrame(rows)
    return Load1CResult(df=out_df, unmapped_columns=unmapped)


def load_1c_realizacii(path: str | Path) -> Load1CResult:
    """Прочитати журнал Реалізацій з 1С.

    Returns:
        DataFrame з колонками: date, doc_number, amount, counterparty,
        edrpou, podrozdil, raw.
    """
    path = Path(path)
    raw_df = _read_excel_or_csv(path)
    col_map, unmapped = _apply_aliases(raw_df, REALIZACII_ALIASES)

    if "date" not in col_map.values() or "amount" not in col_map.values():
        raise RuntimeError(
            f"У реалізаціях нема 'Дата' або 'Сума'. Колонки: {list(raw_df.columns)}"
        )

    rows: list[dict] = []
    for _, row in raw_df.iterrows():
        norm: dict = {
            "date": None,
            "doc_number": "",
            "amount": None,
            "counterparty": "",
            "edrpou": "",
            "podrozdil": "",
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
        rows.append(norm)

    out_df = pd.DataFrame(rows)
    out_df = out_df[out_df["date"].notna() & out_df["amount"].notna()].reset_index(drop=True)
    return Load1CResult(df=out_df, unmapped_columns=unmapped)


def load_1c_zamovlennia(path: str | Path) -> Load1CResult:
    """Прочитати журнал Замовлень покупців з 1С.

    Returns те саме що load_1c_realizacii (структура однакова).
    """
    return load_1c_realizacii(path)
