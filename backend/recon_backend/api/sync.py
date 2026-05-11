"""Sync операцій: upload CSV/XLSX → запис в БД.

Тимчасова реалізація — поки нема API клієнтів Privat і OData.
Юзер завантажує файли через UI, ми парсимо і складаємо в bank_op / cash_op.

Майбутні endpoints (після клієнтів):
- POST /api/sync/privat/{fop_id}?from=&to=  — затягнути напряму з Privat API
- POST /api/sync/1c/{fop_id}?from=&to=      — затягнути напряму з 1С OData
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.parse_cash_journal import load_cash_journal
from ..db.models import BankAccount, BankOp, CashAccount, CashOp, CashOpType, Direction
from ..db.session import get_session

# Імпортуємо парсери з legacy CLI (вони вже добре працюють з УНФ-форматами).
import sys
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
from recon.parse_1c import load_1c_dvizhenie_report, load_1c_kasa  # noqa: E402
from recon.parse_privat import load_privat_statement  # noqa: E402

router = APIRouter()


@router.post("/privat-upload")
async def upload_privat_statement(
    fop_id: str = Form(...),
    bank_account_id: str = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """Завантажити CSV/XLSX виписку Privat для конкретного банк-рахунку.

    Перевіряє що bank_account належить fop. Парсить файл, додає рядки в bank_op.
    Не дублює — якщо (fop_id, bank_account_id, op_date, amount, doc_number) уже є — пропускає.
    """
    acc = await session.get(BankAccount, bank_account_id)
    if not acc or acc.fop_id != fop_id:
        raise HTTPException(status_code=404, detail="Банк-рахунок не належить цьому ФОПу")

    # Зберігаємо upload у тимчасовий файл.
    suffix = Path(file.filename or "upload.csv").suffix or ".csv"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        parsed = load_privat_statement(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    added = 0
    duplicates = 0
    for _, row in parsed.df.iterrows():
        op_date = row["date"].date() if pd.notna(row["date"]) else None
        if not op_date or row["amount"] is None:
            continue
        # Дедуплікація по (account, дата, сума, doc_number).
        doc_num = str(row["raw"].get("Номер документу", "")).strip() or None
        existing = await session.execute(
            select(BankOp).where(
                BankOp.bank_account_id == bank_account_id,
                BankOp.op_date == op_date,
                BankOp.amount == row["amount"],
                BankOp.doc_number == doc_num,
            )
        )
        if existing.scalar_one_or_none():
            duplicates += 1
            continue
        bop = BankOp(
            fop_id=fop_id,
            bank_account_id=bank_account_id,
            op_date=op_date,
            amount=row["amount"],
            direction=Direction(row["direction"]),
            doc_number=doc_num,
            counterparty=row["counterparty"] or None,
            edrpou=row["edrpou"] or None,
            purpose=row["purpose"] or None,
            account_correspondent=row.get("account_correspondent") or None,
            currency=row["currency"],
        )
        session.add(bop)
        added += 1
    await session.commit()
    return {"added": added, "duplicates": duplicates, "total_parsed": len(parsed.df)}


@router.post("/cash-upload")
async def upload_cash_export(
    fop_id: str = Form(...),
    cash_account_id: str = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """Завантажити XLSX вивантаження з УНФ (журнал документів АБО звіт «Движение денег»).

    Автоматично визначає формат і використовує відповідний парсер.
    """
    acc = await session.get(CashAccount, cash_account_id)
    if not acc or acc.fop_id != fop_id:
        raise HTTPException(status_code=404, detail="Каса не належить цьому ФОПу")

    suffix = Path(file.filename or "upload.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # Auto-detect: звіт «Движение денег» має 5 колонок з «остаток»/«поступление»
        preview = pd.read_excel(tmp_path, dtype=str, nrows=2).fillna("")
        is_report = (
            any("остаток" in str(c).lower() or "залишок" in str(c).lower() for c in preview.columns)
            and any("оступл" in str(c).lower() for c in preview.columns)
        )
        if is_report:
            parsed = load_1c_dvizhenie_report(tmp_path)
            source = "report"
        else:
            parsed = load_1c_kasa(tmp_path)
            source = "xlsx"
    finally:
        tmp_path.unlink(missing_ok=True)

    type_map = {"ПКО": CashOpType.PKO, "ВКО": CashOpType.VKO}

    added = 0
    duplicates = 0
    for _, row in parsed.df.iterrows():
        op_date = row["date"].date() if pd.notna(row["date"]) else None
        if not op_date or row["amount"] is None:
            continue
        # Тип: ПКО / ВКО / Перемещение
        doc_type_str = row["doc_type"]
        comment = str(row.get("comment", "")).lower()
        if "перемещ" in comment or "перемі" in comment:
            op_type = CashOpType.PEREMESHCHENIE
        else:
            op_type = type_map.get(doc_type_str)
            if op_type is None:
                continue

        doc_num = str(row.get("doc_number") or "").strip() or None
        existing = await session.execute(
            select(CashOp).where(
                CashOp.cash_account_id == cash_account_id,
                CashOp.op_date == op_date,
                CashOp.amount == row["amount"],
                CashOp.doc_number == doc_num,
            )
        )
        if existing.scalar_one_or_none():
            duplicates += 1
            continue

        cop = CashOp(
            fop_id=fop_id,
            cash_account_id=cash_account_id,
            op_date=op_date,
            amount=row["amount"],
            op_type=op_type,
            doc_number=doc_num,
            counterparty=row.get("counterparty") or None,
            edrpou=row.get("edrpou") or None,
            stattia=row.get("stattia") or None,
            dok_osnova=row.get("dok_osnova") or None,
            comment=row.get("comment") or None,
            source=source,
        )
        session.add(cop)
        added += 1
    await session.commit()
    return {"added": added, "duplicates": duplicates, "total_parsed": len(parsed.df), "source": source}


@router.post("/cash-journal-upload")
async def upload_cash_journal(
    fop_id: str = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """Завантажити повний журнал документів каси з полем «Касса/Счет».

    На відміну від /cash-upload не вимагає вибору каси: парсер сам мапить
    кожен рядок на відповідну `cash_account` за іменем у колонці «Касса/Счет».

    Один файл = всі каси цього ФОПа. Зручно для першого заливання історії
    за весь час.
    """
    # Збираємо мапінг імен кас → cash_account_id для цього ФОПа.
    result = await session.execute(select(CashAccount).where(CashAccount.fop_id == fop_id))
    cash_by_name: dict[str, str] = {}
    for c in result.scalars():
        cash_by_name[c.name_1c.strip().lower()] = c.id

    if not cash_by_name:
        raise HTTPException(
            status_code=400,
            detail="У ФОПа немає кас. Спочатку зроби /api/odata/{fop_id}/sync-catalogs",
        )

    # Зберігаємо upload у тимчасовий файл.
    suffix = Path(file.filename or "upload.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        parsed = load_cash_journal(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    type_map = {
        "ПКО": CashOpType.PKO,
        "ВКО": CashOpType.VKO,
        "Перемещение": CashOpType.PEREMESHCHENIE,
    }

    added = 0
    duplicates = 0
    unmapped: dict[str, int] = {}  # назви кас яких нема у БД → кількість рядків

    for row in parsed.rows:
        key = row.cash_account_name.strip().lower()
        cash_account_id = cash_by_name.get(key)
        if not cash_account_id:
            unmapped[row.cash_account_name] = unmapped.get(row.cash_account_name, 0) + 1
            continue

        op_type = type_map.get(row.op_type)
        if op_type is None:
            continue

        # Дедуплікація за (cash_account, дата, сума, doc_number).
        doc_num = row.doc_number or None
        existing = await session.execute(
            select(CashOp).where(
                CashOp.cash_account_id == cash_account_id,
                CashOp.op_date == row.op_date,
                CashOp.amount == row.amount,
                CashOp.doc_number == doc_num,
            )
        )
        if existing.scalar_one_or_none():
            duplicates += 1
            continue

        # Зберігаємо: операція → stattia (тип як «Поставщику» / «От покупателя»),
        # структурна одиниця → comment з префіксом, щоб не плутати з 1С-коментарем.
        comment_parts = []
        if row.structural_unit:
            comment_parts.append(f"Підрозділ: {row.structural_unit}")
        session.add(CashOp(
            fop_id=fop_id,
            cash_account_id=cash_account_id,
            op_date=row.op_date,
            amount=row.amount,
            op_type=op_type,
            doc_number=doc_num,
            counterparty=row.counterparty or None,
            stattia=row.operation or None,
            comment="; ".join(comment_parts) if comment_parts else None,
            source="journal_xlsx",
        ))
        added += 1

    await session.commit()
    return {
        "added": added,
        "duplicates": duplicates,
        "total_parsed": len(parsed.rows),
        "skipped_no_date": parsed.skipped_no_date,
        "skipped_no_amount": parsed.skipped_no_amount,
        "skipped_no_cash": parsed.skipped_no_cash,
        "unmapped_cash_accounts": unmapped,  # назви які не знайдено у БД
    }
