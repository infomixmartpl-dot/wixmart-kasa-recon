"""Командний рядок для звірки.

Команди:
- `recon`        : виконати звірку за місяць → reports/recon-YYYY-MM.xlsx
- `export`       : зчитати підтверджені рядки звіту → output/import-YYYY-MM.xlsx
- `analyze`      : швидкий аналіз без створення Excel (статистика в консоль)
- `init-config`  : створити шаблонні файли у data/config/

Запуск:
    python -m recon recon --month 2024-01
    python -m recon export --month 2024-01
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import click
import pandas as pd

from .match import MatchResult, find_realization_basis, reconcile
from .parse_1c import load_1c_dvizhenie_report, load_1c_kasa, load_1c_realizacii
from .parse_privat import filter_by_month, load_privat_statement
from .proportion import (
    Rozpodil,
    find_pravylo,
    load_oborot,
    load_pidrozdily,
    load_pravyla,
    rozpodilyty,
)
from .report import read_confirmed_export, write_excel_report

# Корінь проєкту = батько папки `recon/`.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"
OUTPUT_DIR = PROJECT_ROOT / "output"


def _parse_month(month: str) -> tuple[int, int]:
    """'2024-01' → (2024, 1)."""
    try:
        year_s, month_s = month.split("-")
        return int(year_s), int(month_s)
    except (ValueError, AttributeError) as e:
        raise click.BadParameter(f"--month має бути у форматі YYYY-MM (напр. 2024-01): {e}")


def _find_file(folder: Path, prefix: str, month: str) -> Path | None:
    """Знайти файл `<prefix>-<month>.{csv,xlsx,xls}` у папці."""
    for ext in [".csv", ".xlsx", ".xls"]:
        p = folder / f"{prefix}-{month}{ext}"
        if p.exists():
            return p
    return None


def _build_expected_podrozdil_fn(pidrozdily_df: pd.DataFrame):
    """Створити функцію розпізнавання підрозділу за карткою Privat.

    Шукає у `pidrozdily_df` рядок, де `картка_Privat` входить у `account`
    або `account` входить у `картка_Privat` (часткове співпадіння, бо в банку
    можуть бути замасковані картки виду `4***1234`).
    """
    if pidrozdily_df.empty or "картка_Privat" not in pidrozdily_df.columns:
        return lambda _: ""

    pairs: list[tuple[str, str]] = []
    for _, row in pidrozdily_df.iterrows():
        karta = str(row.get("картка_Privat", "")).strip()
        nazva = str(row.get("назва_1С", "")).strip()
        if karta and nazva:
            pairs.append((karta, nazva))

    def fn(bank_row: dict) -> str:
        account = str(bank_row.get("account", "")).strip()
        if not account:
            return ""
        # Видаляємо '*' з обох сторін, шукаємо за останніми 4 цифрами або частковим збігом.
        norm_acc = account.replace("*", "").replace(" ", "")
        for karta, nazva in pairs:
            norm_kar = karta.replace("*", "").replace(" ", "")
            if not norm_kar:
                continue
            if norm_kar in norm_acc or norm_acc in norm_kar:
                return nazva
            # Останні 4 цифри.
            tail_acc = norm_acc[-4:] if len(norm_acc) >= 4 else norm_acc
            tail_kar = norm_kar[-4:] if len(norm_kar) >= 4 else norm_kar
            if tail_acc and tail_acc == tail_kar:
                return nazva
        return ""

    return fn


def _load_data_for_month(month: str) -> dict:
    """Завантажити всі дані за вказаний місяць. Повернути словник з ключами:
    bank_df, cash_df, realizacii_df, pidrozdily_df, oborot_df, pravyla.
    """
    year, mnum = _parse_month(month)

    bank_path = _find_file(DATA_DIR / "bank", "privat", month)
    if not bank_path:
        raise click.UsageError(
            f"Не знайдено виписку: data/bank/privat-{month}.csv (або .xlsx).\n"
            f"Поклади файл туди і запусти знову."
        )

    cash_path = _find_file(DATA_DIR / "1c-export", "kasa", month)
    if not cash_path:
        raise click.UsageError(
            f"Не знайдено вивантаження каси: data/1c-export/kasa-{month}.xlsx.\n"
            f"Вивантаж з 1С 'Реєстр касових ордерів' за {month}."
        )

    realizacii_path = _find_file(DATA_DIR / "1c-export", "realizacii", month)

    click.echo(f"📁 Виписка Privat:  {bank_path.name}")
    click.echo(f"📁 Каса 1С:        {cash_path.name}")
    click.echo(f"📁 Реалізації 1С:  {realizacii_path.name if realizacii_path else '(не задано)'}")

    bank_result = load_privat_statement(bank_path)
    bank_df = filter_by_month(bank_result.df, year, mnum)
    click.echo(
        f"   ↳ банк: {len(bank_df)} операцій за {month} "
        f"(всього у файлі {len(bank_result.df)})"
    )
    if bank_result.unmapped_columns:
        click.echo(
            f"   ⚠️  Не розпізнані колонки у виписці: {bank_result.unmapped_columns}",
            err=True,
        )

    # Auto-detect: чи це звіт "Движение денег" (5 колонок з "Остаток"),
    # чи журнал документів. Звіт містить менше даних (нема контрагента, ЄДРПОУ).
    cash_preview = pd.read_excel(cash_path, dtype=str, nrows=2).fillna("") if str(cash_path).lower().endswith((".xlsx", ".xls")) else None
    is_report = (
        cash_preview is not None
        and any("остаток" in str(c).lower() or "залишок" in str(c).lower() for c in cash_preview.columns)
        and any("поступл" in str(c).lower() or "адхо" in str(c).lower() for c in cash_preview.columns)
    )

    if is_report:
        click.echo("   ⚠️  Це звіт 'Движение денег', не журнал — контрагент і ЄДРПОУ недоступні.")
        click.echo("       Матчинг буде ТІЛЬКИ по даті+сумі (менша точність).")
        cash_result = load_1c_dvizhenie_report(cash_path)
    else:
        cash_result = load_1c_kasa(cash_path)

    cash_df = cash_result.df
    if not cash_df.empty and "date" in cash_df.columns:
        cash_df = cash_df[(cash_df["date"].dt.year == year) & (cash_df["date"].dt.month == mnum)].reset_index(drop=True)
    click.echo(f"   ↳ каса 1С: {len(cash_df)} документів")

    realizacii_df = pd.DataFrame()
    if realizacii_path:
        rr = load_1c_realizacii(realizacii_path)
        realizacii_df = rr.df
        click.echo(f"   ↳ реалізації: {len(realizacii_df)}")

    pidrozdily_df = load_pidrozdily(DATA_DIR / "config" / "pidrozdily.xlsx")
    if pidrozdily_df.empty:
        click.echo("   ⚠️  pidrozdily.xlsx не знайдено або порожній", err=True)

    oborot_df = load_oborot(DATA_DIR / "config" / "oborot-pidrozdil.xlsx")
    if oborot_df.empty:
        click.echo("   ⚠️  oborot-pidrozdil.xlsx не знайдено — розподіл буде неможливий", err=True)

    pravyla = load_pravyla(DATA_DIR / "config" / "pravyla-vytrat.xlsx")
    if not pravyla:
        click.echo("   ⚠️  pravyla-vytrat.xlsx не знайдено — статті витрат не розпізнаються", err=True)

    return {
        "bank_df": bank_df,
        "cash_df": cash_df,
        "realizacii_df": realizacii_df,
        "pidrozdily_df": pidrozdily_df,
        "oborot_df": oborot_df,
        "pravyla": pravyla,
    }


def _compute_proportions_and_basis(
    results: list[MatchResult],
    *,
    oborot_df: pd.DataFrame,
    pravyla: list,
    realizacii_df: pd.DataFrame,
) -> tuple[dict[int, Rozpodil], dict[int, dict | None]]:
    """Для кожного bank_only порахувати розподіл і знайти основу (Реалізацію)."""
    rozpodily: dict[int, Rozpodil] = {}
    basis: dict[int, dict | None] = {}
    for idx, r in enumerate(results):
        if r.kind != "bank_only" or r.bank_row is None:
            continue
        b = r.bank_row
        # Розподіл — тільки для витрат (out).
        if b.get("direction") == "out":
            text = (b.get("purpose", "") + " " + b.get("counterparty", "")).strip()
            pravylo = find_pravylo(text, pravyla)
            rozp = rozpodilyty(
                suma=b["amount"],
                data=b["date"],
                pravylo=pravylo,
                oborot_df=oborot_df,
            )
            rozpodily[idx] = rozp
        # Основа — тільки для приходів (in).
        elif b.get("direction") == "in" and not realizacii_df.empty:
            basis[idx] = find_realization_basis(b, realizacii_df)
    return rozpodily, basis


# ─── CLI команди ─────────────────────────────────────────────────────────


@click.group()
def main():
    """Звірка ПриватБанк ↔ Каса 1С + масова проводка через .epf."""


@main.command()
@click.option("--month", required=True, help="Період у форматі YYYY-MM, наприклад 2024-01")
def recon(month: str):
    """Виконати звірку за вказаний місяць → reports/recon-YYYY-MM.xlsx."""
    click.echo(f"🚀 Звірка за {month}\n")
    data = _load_data_for_month(month)

    expected_fn = _build_expected_podrozdil_fn(data["pidrozdily_df"])

    click.echo("\n🔍 Співставлення банк ↔ каса 1С...")
    results = reconcile(
        bank_df=data["bank_df"],
        cash_df=data["cash_df"],
        expected_podrozdil_fn=expected_fn,
    )

    counts: dict[str, int] = {}
    for r in results:
        counts[r.kind] = counts.get(r.kind, 0) + 1

    click.echo("\n📊 Результат:")
    click.echo(f"   точних збігів:           {counts.get('exact_match', 0)}")
    click.echo(f"   нечітких збігів:         {counts.get('fuzzy_match', 0)}")
    click.echo(f"   пересортів:              {counts.get('mismatch_podrozdil', 0)}")
    click.echo(f"   до проведення (банк):    {counts.get('bank_only', 0)}")
    click.echo(f"   тільки в касі (1С):      {counts.get('cash_only', 0)}")

    click.echo("\n🧮 Розрахунок розподілів і пошук основ...")
    rozpodily, basis = _compute_proportions_and_basis(
        results,
        oborot_df=data["oborot_df"],
        pravyla=data["pravyla"],
        realizacii_df=data["realizacii_df"],
    )
    click.echo(f"   розраховано розподілів: {len(rozpodily)}")
    click.echo(f"   знайдено основ:          {sum(1 for v in basis.values() if v)}")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"recon-{month}.xlsx"
    write_excel_report(
        out_path,
        results,
        rozpodily=rozpodily,
        realization_basis=basis,
        month_label=month,
    )
    click.echo(f"\n✅ Звіт готовий: {out_path}")
    click.echo(
        "\nНаступний крок: відкрий звіт в Excel, проглянь листи "
        "«До проведення» і «Пересорт», постав 1 в колонці «Підтвердити». "
        "Потім: python -m recon export --month " + month
    )


@main.command()
@click.option("--month", required=True, help="Період YYYY-MM")
def export(month: str):
    """Зчитати підтверджені рядки зі звіту → output/import-YYYY-MM.xlsx (на імпорт у 1С)."""
    report_path = REPORTS_DIR / f"recon-{month}.xlsx"
    if not report_path.exists():
        raise click.UsageError(
            f"Спочатку запусти `recon --month {month}` — нема файлу {report_path}"
        )

    do_conf, pere_conf = read_confirmed_export(report_path)
    click.echo(
        f"📋 Підтверджено: {len(do_conf)} до проведення, "
        f"{len(pere_conf)} пересорт(ів)"
    )

    if do_conf.empty and pere_conf.empty:
        click.echo("⚠️  Жодного рядка не підтверджено (колонки 'Підтвердити' порожні).")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"import-{month}.xlsx"
    with pd.ExcelWriter(out_path, engine="xlsxwriter") as writer:
        do_conf.to_excel(writer, sheet_name="ДоПроведення", index=False)
        pere_conf.to_excel(writer, sheet_name="Пересорт", index=False)
    click.echo(f"✅ Файл для імпорту в 1С: {out_path}")
    click.echo(
        "\nНаступний крок: у 1С відкрий 1c-epf/BankReconciliation.epf "
        "(коли вже буде створена), обери цей файл, натисни «Створити документи»."
    )


@main.command()
@click.option("--month", required=True, help="Період YYYY-MM")
def analyze(month: str):
    """Швидкий аналіз без створення Excel — статистика в консоль."""
    data = _load_data_for_month(month)
    expected_fn = _build_expected_podrozdil_fn(data["pidrozdily_df"])
    results = reconcile(
        bank_df=data["bank_df"],
        cash_df=data["cash_df"],
        expected_podrozdil_fn=expected_fn,
    )
    counts: dict[str, int] = {}
    for r in results:
        counts[r.kind] = counts.get(r.kind, 0) + 1
    click.echo("\nПідсумок:")
    for k, v in counts.items():
        click.echo(f"  {k:25s} {v:5d}")


@main.command(name="init-config")
def init_config():
    """Створити шаблонні файли у data/config/."""
    config_dir = DATA_DIR / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    # pidrozdily.xlsx
    pidrozdily_path = config_dir / "pidrozdily.xlsx"
    if not pidrozdily_path.exists():
        pd.DataFrame(
            [
                {"код": "1", "назва_1С": "Магазин_А", "назва_Instagram": "@magazyn_a", "картка_Privat": "4***1234"},
                {"код": "2", "назва_1С": "Магазин_Б", "назва_Instagram": "@magazyn_b", "картка_Privat": "4***5678"},
            ]
        ).to_excel(pidrozdily_path, index=False)
        click.echo(f"✅ Створено {pidrozdily_path}")
    else:
        click.echo(f"⏭️  Вже існує: {pidrozdily_path}")

    # oborot-pidrozdil.xlsx
    oborot_path = config_dir / "oborot-pidrozdil.xlsx"
    if not oborot_path.exists():
        pd.DataFrame(
            [
                {"рік": 2024, "місяць": 1, "підрозділ": "Магазин_А", "оборот": 50000},
                {"рік": 2024, "місяць": 1, "підрозділ": "Магазин_Б", "оборот": 30000},
            ]
        ).to_excel(oborot_path, index=False)
        click.echo(f"✅ Створено {oborot_path}")
    else:
        click.echo(f"⏭️  Вже існує: {oborot_path}")

    # pravyla-vytrat.xlsx
    pravyla_path = config_dir / "pravyla-vytrat.xlsx"
    if not pravyla_path.exists():
        pd.DataFrame(
            [
                {"стаття_витрат": "Оренда", "тип_розподілу": "пропорційно",
                 "прямий_підрозділ": "", "ключові_слова": '"оренда","орендна"'},
                {"стаття_витрат": "Реклама Інстаграм", "тип_розподілу": "пропорційно",
                 "прямий_підрозділ": "", "ключові_слова": '"facebook","fb.com","meta"'},
                {"стаття_витрат": "Комунальні", "тип_розподілу": "пропорційно",
                 "прямий_підрозділ": "", "ключові_слова": '"водоканал","газ","електро"'},
                {"стаття_витрат": "Постачальник_Х", "тип_розподілу": "прямо",
                 "прямий_підрозділ": "Магазин_А", "ключові_слова": '"тов постачальник х"'},
            ]
        ).to_excel(pravyla_path, index=False)
        click.echo(f"✅ Створено {pravyla_path}")
    else:
        click.echo(f"⏭️  Вже існує: {pravyla_path}")

    click.echo("\nЗаповни ці файли реальними даними і запускай `recon --month YYYY-MM`.")


if __name__ == "__main__":
    main()
