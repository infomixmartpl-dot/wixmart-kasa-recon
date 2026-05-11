"""Пропорційний розподіл витрат по підрозділах.

Логіка:
- Для витрати з типом 'пропорційно' → ділимо суму по підрозділах згідно з
  оборотом кожного підрозділу за **той самий місяць** що дата витрати.
- Для витрати з типом 'прямо' → вся сума йде на один заздалегідь вказаний підрозділ.
- Якщо нема обороту або правила — повертаємо неповний розподіл з міткою для ручної перевірки.

Сума часток завжди дорівнює вихідній сумі до копійки (різниця округлень
прикладається до найбільшої частки).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd


@dataclass
class Pravylo:
    """Правило для статті витрат."""

    stattia: str  # назва статті
    typ: str  # "пропорційно" або "прямо"
    pryamiy_pidrozdil: str  # для typ='прямо'
    kliuchovi_slova: list[str]  # для розпізнавання за призначенням платежу


@dataclass
class Chastka:
    """Одна частка розподілу витрати."""

    pidrozdil: str
    suma: Decimal
    vidsotok: float  # 0..100
    notes: str = ""


@dataclass
class Rozpodil:
    """Повний результат розподілу однієї витрати."""

    sukupna_suma: Decimal
    chastky: list[Chastka]
    pravylo: Pravylo | None
    status: str  # "ok" | "no_pravylo" | "no_oborot" | "partial"
    warnings: list[str]


def load_pidrozdily(path: str | Path) -> pd.DataFrame:
    """Прочитати список підрозділів.

    Очікувані колонки: код, назва_1С, назва_Instagram, картка_Privat.
    """
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=["код", "назва_1С", "назва_Instagram", "картка_Privat"])
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, dtype=str).fillna("")
    return pd.read_csv(path, dtype=str).fillna("")


def load_oborot(path: str | Path) -> pd.DataFrame:
    """Прочитати таблицю оборотів.

    Очікувані колонки: рік, місяць, підрозділ, оборот.
    Повертає DataFrame з типами: рік:int, місяць:int, підрозділ:str, оборот:Decimal.
    """
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=["рік", "місяць", "підрозділ", "оборот"])
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str).fillna("")
    else:
        df = pd.read_csv(path, dtype=str).fillna("")
    df["рік"] = pd.to_numeric(df["рік"], errors="coerce").astype("Int64")
    df["місяць"] = pd.to_numeric(df["місяць"], errors="coerce").astype("Int64")
    df["оборот"] = df["оборот"].apply(_to_decimal)
    df = df.dropna(subset=["рік", "місяць", "підрозділ"])
    return df


def load_pravyla(path: str | Path) -> list[Pravylo]:
    """Прочитати правила розподілу витрат.

    Очікувані колонки: стаття_витрат, тип_розподілу, прямий_підрозділ, ключові_слова.
    """
    path = Path(path)
    if not path.exists():
        return []
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str).fillna("")
    else:
        df = pd.read_csv(path, dtype=str).fillna("")

    pravyla: list[Pravylo] = []
    for _, row in df.iterrows():
        words_raw = str(row.get("ключові_слова", "")).strip()
        # Підтримуємо два формати: "оренда","орендна" або просто через кому.
        words = [
            w.strip().strip('"').strip("'").lower()
            for w in re.split(r"[,;]", words_raw)
            if w.strip()
        ]
        pravyla.append(
            Pravylo(
                stattia=str(row.get("стаття_витрат", "")).strip(),
                typ=str(row.get("тип_розподілу", "")).strip().lower(),
                pryamiy_pidrozdil=str(row.get("прямий_підрозділ", "")).strip(),
                kliuchovi_slova=words,
            )
        )
    return pravyla


def find_pravylo(text: str, pravyla: list[Pravylo]) -> Pravylo | None:
    """Знайти правило, яке відповідає тексту (призначення платежу + контрагент).

    Повертає перше правило, в якого є ≥1 ключове слово в тексті.
    """
    if not text:
        return None
    text_lower = text.lower()
    for p in pravyla:
        for kw in p.kliuchovi_slova:
            if kw and kw in text_lower:
                return p
    return None


def _to_decimal(value: object) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    s = str(value).replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except Exception:  # noqa: BLE001
        return None


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rozpodilyty(
    suma: Decimal,
    data: date | pd.Timestamp,
    pravylo: Pravylo | None,
    oborot_df: pd.DataFrame,
) -> Rozpodil:
    """Розрахувати розподіл однієї витрати.

    Args:
        suma: сума витрати.
        data: дата витрати (визначає місяць для пошуку обороту).
        pravylo: знайдене правило або None.
        oborot_df: таблиця обороту з load_oborot.

    Returns:
        Rozpodil зі списком часток.
    """
    warnings: list[str] = []

    if pravylo is None:
        return Rozpodil(
            sukupna_suma=suma,
            chastky=[
                Chastka(pidrozdil="?", suma=suma, vidsotok=100.0, notes="Правило не знайдено")
            ],
            pravylo=None,
            status="no_pravylo",
            warnings=["Не знайдено правило для цієї витрати — обери підрозділ вручну"],
        )

    if pravylo.typ == "прямо":
        target = pravylo.pryamiy_pidrozdil or "?"
        return Rozpodil(
            sukupna_suma=suma,
            chastky=[Chastka(pidrozdil=target, suma=suma, vidsotok=100.0)],
            pravylo=pravylo,
            status="ok",
            warnings=warnings,
        )

    if pravylo.typ != "пропорційно":
        warnings.append(f"Невідомий тип розподілу: '{pravylo.typ}'")
        return Rozpodil(
            sukupna_suma=suma,
            chastky=[Chastka(pidrozdil="?", suma=suma, vidsotok=100.0, notes="Невідомий тип")],
            pravylo=pravylo,
            status="no_pravylo",
            warnings=warnings,
        )

    # Пропорційно — беремо оборот за рік-місяць дати витрати.
    ts = pd.Timestamp(data)
    year = int(ts.year)
    month = int(ts.month)

    mask = (oborot_df["рік"] == year) & (oborot_df["місяць"] == month)
    month_oborot = oborot_df[mask]

    if month_oborot.empty:
        return Rozpodil(
            sukupna_suma=suma,
            chastky=[
                Chastka(
                    pidrozdil="?",
                    suma=suma,
                    vidsotok=100.0,
                    notes=f"Нема обороту за {year}-{month:02d}",
                )
            ],
            pravylo=pravylo,
            status="no_oborot",
            warnings=[
                f"Заповни в oborot-pidrozdil.xlsx оборот для {year}-{month:02d}, "
                "інакше пропорційний розподіл неможливий"
            ],
        )

    total_oborot = sum((row["оборот"] or Decimal("0")) for _, row in month_oborot.iterrows())
    if total_oborot <= 0:
        return Rozpodil(
            sukupna_suma=suma,
            chastky=[
                Chastka(pidrozdil="?", suma=suma, vidsotok=100.0, notes="Сумарний оборот = 0")
            ],
            pravylo=pravylo,
            status="no_oborot",
            warnings=["Сумарний оборот за місяць = 0, ділити нема як"],
        )

    chastky: list[Chastka] = []
    for _, row in month_oborot.iterrows():
        oborot = row["оборот"] or Decimal("0")
        if oborot <= 0:
            continue
        chastka_amount = _quantize(suma * oborot / total_oborot)
        vidsotok = float(oborot / total_oborot * 100)
        chastky.append(
            Chastka(
                pidrozdil=str(row["підрозділ"]),
                suma=chastka_amount,
                vidsotok=round(vidsotok, 2),
            )
        )

    # Виправляємо округлення: сума часток має дорівнювати початковій сумі.
    diff = suma - sum(c.suma for c in chastky)
    if diff != 0 and chastky:
        # Прикладаємо різницю до найбільшої частки.
        biggest = max(chastky, key=lambda c: c.suma)
        biggest.suma += diff

    return Rozpodil(
        sukupna_suma=suma,
        chastky=chastky,
        pravylo=pravylo,
        status="ok",
        warnings=warnings,
    )
