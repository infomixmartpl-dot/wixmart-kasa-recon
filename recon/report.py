"""Генератор Excel-звіту звірки.

Створює файл `reports/recon-YYYY-MM.xlsx` з листами:

1. **Зведення**         — підсумкові цифри (скільки знайдено, скільки збігів тощо).
2. **До проведення**    — є в банку, нема в касі 1С → треба створити ПКО/ВКО.
                          Колонка `Підтвердити` (1/0) — на наступному кроці експорту в .epf.
3. **Пересорт**         — є в обох, але підрозділ у 1С не співпадає з очікуваним.
4. **Збіги**            — все ок, нічого не робити (для довідки).
5. **Питання**          — касові ордери, для яких нема пари у виписці банку.

Використовується pandas.ExcelWriter з engine='xlsxwriter' для форматування.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from .match import MatchResult
from .proportion import Rozpodil


def _fmt_decimal(d: Decimal | None) -> float:
    if d is None:
        return 0.0
    return float(d)


def _fmt_date(d) -> str:
    if d is None:
        return ""
    return pd.Timestamp(d).strftime("%Y-%m-%d")


def _rozpodil_to_text(r: Rozpodil | None) -> str:
    """Форматує розподіл для колонки в Excel: 'Магазин_А: 100.00 (33%); Магазин_Б: ...'"""
    if r is None or not r.chastky:
        return ""
    parts = [f"{c.pidrozdil}: {c.suma} ({c.vidsotok:.1f}%)" for c in r.chastky]
    return "; ".join(parts)


def _rozpodil_status(r: Rozpodil | None) -> str:
    if r is None:
        return "—"
    return {
        "ok": "ok",
        "no_pravylo": "немає правила",
        "no_oborot": "немає обороту",
        "partial": "часткове",
    }.get(r.status, r.status)


def _build_do_provedennya(
    results: list[MatchResult],
    rozpodily: dict[int, Rozpodil],
    realization_basis: dict[int, dict | None],
) -> pd.DataFrame:
    """Лист 'До проведення' — bank_only."""
    rows: list[dict] = []
    for idx, r in enumerate(results):
        if r.kind != "bank_only":
            continue
        b = r.bank_row or {}
        direction = b.get("direction", "")
        rozp = rozpodily.get(idx)
        basis = realization_basis.get(idx)
        rows.append(
            {
                "№": len(rows) + 1,
                "Дата": _fmt_date(b.get("date")),
                "Тип": "ПКО" if direction == "in" else "ВКО",
                "Сума": _fmt_decimal(b.get("amount")),
                "Валюта": b.get("currency", "UAH"),
                "Контрагент (банк)": b.get("counterparty", ""),
                "ЄДРПОУ": b.get("edrpou", ""),
                "Призначення": b.get("purpose", ""),
                "Картка/рахунок": b.get("account", ""),
                "Запропонована основа (Реалізація)": (
                    f"№{basis.get('doc_number', '')} від {_fmt_date(basis.get('date'))} на {basis.get('amount', '')}"
                    if basis else "—"
                ),
                "Стаття (запропонована)": rozp.pravylo.stattia if rozp and rozp.pravylo else "—",
                "Розподіл по підрозділах": _rozpodil_to_text(rozp),
                "Статус розподілу": _rozpodil_status(rozp),
                "Підтвердити (1/0)": 0,
                "Примітки": "; ".join(r.notes),
                "_internal_idx": idx,
            }
        )
    return pd.DataFrame(rows)


def _build_peresort(results: list[MatchResult]) -> pd.DataFrame:
    """Лист 'Пересорт' — mismatch_podrozdil."""
    rows: list[dict] = []
    for r in results:
        if r.kind != "mismatch_podrozdil":
            continue
        b = r.bank_row or {}
        c = r.cash_row or {}
        rows.append(
            {
                "№": len(rows) + 1,
                "Дата": _fmt_date(b.get("date")),
                "Сума": _fmt_decimal(b.get("amount")),
                "Контрагент (банк)": b.get("counterparty", ""),
                "Картка/рахунок": b.get("account", ""),
                "Підрозділ у 1С зараз": c.get("podrozdil", ""),
                "Має бути": r.expected_podrozdil,
                "Документ 1С": f"{c.get('doc_type', '')} №{c.get('doc_number', '')} від {_fmt_date(c.get('date'))}",
                "Дія": "Перепровести з правильним підрозділом",
                "Підтвердити перепровод (1/0)": 0,
                "Примітки": "; ".join(r.notes),
            }
        )
    return pd.DataFrame(rows)


def _build_zbihy(results: list[MatchResult]) -> pd.DataFrame:
    """Лист 'Збіги' — exact_match + fuzzy_match без проблем."""
    rows: list[dict] = []
    for r in results:
        if r.kind not in ("exact_match", "fuzzy_match"):
            continue
        b = r.bank_row or {}
        c = r.cash_row or {}
        rows.append(
            {
                "№": len(rows) + 1,
                "Дата (банк)": _fmt_date(b.get("date")),
                "Дата (1С)": _fmt_date(c.get("date")),
                "Тип": c.get("doc_type", ""),
                "Сума": _fmt_decimal(b.get("amount")),
                "Контрагент (банк)": b.get("counterparty", ""),
                "Контрагент (1С)": c.get("counterparty", ""),
                "Підрозділ": c.get("podrozdil", ""),
                "Тип збігу": "точний" if r.kind == "exact_match" else "нечіткий",
                "Схожість контрагента, %": round(r.counterparty_similarity, 1),
                "Різниця дат, дн.": r.date_diff_days,
                "Документ 1С": f"№{c.get('doc_number', '')}",
            }
        )
    return pd.DataFrame(rows)


def _build_pytannya(results: list[MatchResult]) -> pd.DataFrame:
    """Лист 'Питання' — cash_only (у касі є, у банку нема)."""
    rows: list[dict] = []
    for r in results:
        if r.kind != "cash_only":
            continue
        c = r.cash_row or {}
        rows.append(
            {
                "№": len(rows) + 1,
                "Дата": _fmt_date(c.get("date")),
                "Тип": c.get("doc_type", ""),
                "Сума": _fmt_decimal(c.get("amount")),
                "Контрагент": c.get("counterparty", ""),
                "Підрозділ": c.get("podrozdil", ""),
                "Стаття": c.get("stattia", ""),
                "Документ 1С": f"№{c.get('doc_number', '')}",
                "Коментар": c.get("comment", ""),
                "Можливі причини": "інкасація з готівки, помилка вводу, ручний ПКО без банку",
            }
        )
    return pd.DataFrame(rows)


def _build_zvedennya(
    results: list[MatchResult],
    bank_total_in: Decimal,
    bank_total_out: Decimal,
    cash_total_in: Decimal,
    cash_total_out: Decimal,
    month_label: str,
) -> pd.DataFrame:
    """Лист 'Зведення' — підсумки."""
    counts: dict[str, int] = {}
    for r in results:
        counts[r.kind] = counts.get(r.kind, 0) + 1

    rows = [
        {"Показник": "Період", "Значення": month_label},
        {"Показник": "Дата формування звіту", "Значення": datetime.now().strftime("%Y-%m-%d %H:%M")},
        {"Показник": "—", "Значення": "—"},
        {"Показник": "Усього операцій у банку", "Значення": sum(
            1 for r in results if r.bank_row is not None
        )},
        {"Показник": "Усього касових ордерів у 1С", "Значення": sum(
            1 for r in results if r.cash_row is not None
        )},
        {"Показник": "—", "Значення": "—"},
        {"Показник": "Точних збігів", "Значення": counts.get("exact_match", 0)},
        {"Показник": "Нечітких збігів", "Значення": counts.get("fuzzy_match", 0)},
        {"Показник": "Пересортів (треба перепровести)", "Значення": counts.get("mismatch_podrozdil", 0)},
        {"Показник": "До проведення (нема в касі)", "Значення": counts.get("bank_only", 0)},
        {"Показник": "Тільки в касі (нема в банку)", "Значення": counts.get("cash_only", 0)},
        {"Показник": "—", "Значення": "—"},
        {"Показник": "Сума приходів у банку (UAH)", "Значення": _fmt_decimal(bank_total_in)},
        {"Показник": "Сума видатків у банку (UAH)", "Значення": _fmt_decimal(bank_total_out)},
        {"Показник": "Сума ПКО в 1С (UAH)", "Значення": _fmt_decimal(cash_total_in)},
        {"Показник": "Сума ВКО в 1С (UAH)", "Значення": _fmt_decimal(cash_total_out)},
        {"Показник": "Різниця ПКО (банк − 1С)", "Значення": _fmt_decimal(bank_total_in - cash_total_in)},
        {"Показник": "Різниця ВКО (банк − 1С)", "Значення": _fmt_decimal(bank_total_out - cash_total_out)},
    ]
    return pd.DataFrame(rows)


def write_excel_report(
    output_path: str | Path,
    results: list[MatchResult],
    *,
    rozpodily: dict[int, Rozpodil] | None = None,
    realization_basis: dict[int, dict | None] | None = None,
    month_label: str = "",
) -> Path:
    """Записати Excel-звіт.

    Args:
        output_path: куди писати .xlsx.
        results: результати reconcile().
        rozpodily: словник {indeх_у_results: Rozpodil} для витрат, у яких рахували розподіл.
        realization_basis: словник {indeх: знайдена Реалізація-основа}.
        month_label: текстова мітка періоду (наприклад "2024-01").

    Returns:
        Path до створеного файлу.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rozpodily = rozpodily or {}
    realization_basis = realization_basis or {}

    # Загальні суми для зведення.
    bank_in = sum(
        (r.bank_row["amount"] for r in results
         if r.bank_row and r.bank_row.get("direction") == "in"),
        Decimal("0"),
    )
    bank_out = sum(
        (r.bank_row["amount"] for r in results
         if r.bank_row and r.bank_row.get("direction") == "out"),
        Decimal("0"),
    )
    cash_in = sum(
        (r.cash_row["amount"] for r in results
         if r.cash_row and r.cash_row.get("doc_type") == "ПКО"),
        Decimal("0"),
    )
    cash_out = sum(
        (r.cash_row["amount"] for r in results
         if r.cash_row and r.cash_row.get("doc_type") == "ВКО"),
        Decimal("0"),
    )

    df_zvedennya = _build_zvedennya(results, bank_in, bank_out, cash_in, cash_out, month_label)
    df_do_provedennya = _build_do_provedennya(results, rozpodily, realization_basis)
    df_peresort = _build_peresort(results)
    df_zbihy = _build_zbihy(results)
    df_pytannya = _build_pytannya(results)

    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
        df_zvedennya.to_excel(writer, sheet_name="Зведення", index=False)
        df_do_provedennya.to_excel(writer, sheet_name="До проведення", index=False)
        df_peresort.to_excel(writer, sheet_name="Пересорт", index=False)
        df_zbihy.to_excel(writer, sheet_name="Збіги", index=False)
        df_pytannya.to_excel(writer, sheet_name="Питання", index=False)

        # Форматування — заголовки жирні, автофільтр, авто-ширина колонок.
        workbook = writer.book
        header_fmt = workbook.add_format({"bold": True, "bg_color": "#D9E1F2", "border": 1})
        money_fmt = workbook.add_format({"num_format": "#,##0.00"})

        for sheet_name, df in [
            ("Зведення", df_zvedennya),
            ("До проведення", df_do_provedennya),
            ("Пересорт", df_peresort),
            ("Збіги", df_zbihy),
            ("Питання", df_pytannya),
        ]:
            ws = writer.sheets[sheet_name]
            if df.empty:
                continue
            # Заголовок.
            for col_idx, col_name in enumerate(df.columns):
                ws.write(0, col_idx, str(col_name), header_fmt)
            # Авто-ширина.
            for col_idx, col_name in enumerate(df.columns):
                series = df[col_name].astype(str)
                max_len = max(series.map(len).max() if len(series) else 0, len(str(col_name)))
                ws.set_column(col_idx, col_idx, min(max_len + 2, 50))
            # Грошові колонки.
            for col_idx, col_name in enumerate(df.columns):
                if "Сума" in str(col_name) or "Значення" in str(col_name):
                    ws.set_column(col_idx, col_idx, 14, money_fmt)
            # Автофільтр + freeze.
            ws.autofilter(0, 0, len(df), len(df.columns) - 1)
            ws.freeze_panes(1, 0)

    return output_path


def read_confirmed_export(report_path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Прочитати звіт після того, як юзер проставив галочки 'Підтвердити'.

    Повертає (do_provedennya_confirmed, peresort_confirmed) — тільки ті рядки,
    де колонка 'Підтвердити (1/0)' = 1.
    """
    report_path = Path(report_path)
    if not report_path.exists():
        raise FileNotFoundError(f"Звіт не знайдено: {report_path}")

    do_provedennya = pd.read_excel(report_path, sheet_name="До проведення", dtype=str).fillna("")
    peresort = pd.read_excel(report_path, sheet_name="Пересорт", dtype=str).fillna("")

    do_conf = do_provedennya[
        do_provedennya.get("Підтвердити (1/0)", "0").astype(str).str.strip().isin(["1", "1.0", "так", "+", "✓"])
    ].reset_index(drop=True)
    pere_conf = peresort[
        peresort.get("Підтвердити перепровод (1/0)", "0").astype(str).str.strip().isin(["1", "1.0", "так", "+", "✓"])
    ].reset_index(drop=True)

    return do_conf, pere_conf
