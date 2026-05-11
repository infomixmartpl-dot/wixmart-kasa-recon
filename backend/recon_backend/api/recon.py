"""Запуск звірки + перегляд результатів."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.match_global import BankOpData, CashOpData, reconcile_global
from ..db.models import (
    BankAccount,
    BankOp,
    CashAccount,
    CashOp,
    MatchKind,
    MatchRow,
    ReconSession,
    ReconStatus,
)
from ..db.session import get_session
from .schemas import MatchRowOut, ReconRunRequest, ReconSessionOut

router = APIRouter()


_KIND_MAP = {
    "exact": MatchKind.EXACT,
    "fuzzy": MatchKind.FUZZY,
    "amount_only": MatchKind.AMOUNT_ONLY,
    "peresort_exact": MatchKind.PERESORT,
    "peresort_fuzzy": MatchKind.PERESORT,
    "bank_only": MatchKind.BANK_ONLY,
    "cash_only": MatchKind.CASH_ONLY,
}


async def _load_bank_to_cash_mapping(session: AsyncSession, fop_id: str) -> dict[str, str | None]:
    """Зібрати мапінг bank_account_id → expected_cash_account_id для ФОПа."""
    result = await session.execute(select(BankAccount).where(BankAccount.fop_id == fop_id))
    return {acc.id: acc.expected_cash_account_id for acc in result.scalars()}


async def _load_session_stats(session: AsyncSession, recon: ReconSession) -> dict[str, int]:
    """Підрахувати скільки рядків кожного типу у сесії."""
    result = await session.execute(select(MatchRow).where(MatchRow.session_id == recon.id))
    rows = result.scalars().all()
    stats = {
        "matched_exact": 0,
        "matched_fuzzy": 0,
        "peresort": 0,
        "bank_only": 0,
        "cash_only": 0,
    }
    for r in rows:
        if r.kind == MatchKind.EXACT:
            stats["matched_exact"] += 1
        elif r.kind == MatchKind.FUZZY:
            stats["matched_fuzzy"] += 1
        elif r.kind == MatchKind.PERESORT:
            stats["peresort"] += 1
        elif r.kind == MatchKind.BANK_ONLY:
            stats["bank_only"] += 1
        elif r.kind == MatchKind.CASH_ONLY:
            stats["cash_only"] += 1
    return stats


@router.post("/run", response_model=ReconSessionOut, status_code=status.HTTP_201_CREATED)
async def run_recon(payload: ReconRunRequest, session: AsyncSession = Depends(get_session)):
    """Запустити звірку за період для ФОПа.

    Послідовність:
    1. Перевіряємо що ФОП існує.
    2. Витягуємо всі BankOp і CashOp ФОПа за період [from..to].
    3. Збираємо мапінг bank_account → expected_cash_account.
    4. Запускаємо `reconcile_global` — отримуємо список MatchOutcome.
    5. Створюємо ReconSession + MatchRow-и в БД.
    6. Повертаємо ReconSessionOut з підрахунками.
    """
    # 1. Витягуємо BankOp і CashOp за період.
    bank_q = await session.execute(
        select(BankOp).where(
            BankOp.fop_id == payload.fop_id,
            BankOp.op_date >= payload.period_from,
            BankOp.op_date <= payload.period_to,
        )
    )
    bank_ops_db = list(bank_q.scalars())
    # Cash беремо ШИРШЕ — на ±dateWindow днів від періоду банку. Бо в 1С
    # документ може бути проведений із затримкою (наприклад, банк 30.09,
    # ПКО проведено 10.10) і алгоритм має знайти таку пару у fuzzy.
    _w = timedelta(days=payload.date_window_days)
    cash_q = await session.execute(
        select(CashOp).where(
            CashOp.fop_id == payload.fop_id,
            CashOp.op_date >= payload.period_from - _w,
            CashOp.op_date <= payload.period_to + _w,
        )
    )
    cash_ops_db = list(cash_q.scalars())

    if not bank_ops_db and not cash_ops_db:
        raise HTTPException(
            status_code=400,
            detail=f"Нема даних для ФОПа {payload.fop_id} за період {payload.period_from}..{payload.period_to}. "
                   f"Спочатку завантаж виписки і вивантаження 1С.",
        )

    # 2. Конвертуємо в dataclass для ядра.
    bank_data = [
        BankOpData(
            id=b.id,
            op_date=b.op_date,
            amount=Decimal(b.amount),
            direction=b.direction.value if hasattr(b.direction, "value") else str(b.direction),
            bank_account_id=b.bank_account_id,
            counterparty=b.counterparty or "",
            edrpou=b.edrpou or "",
            purpose=b.purpose or "",
        )
        for b in bank_ops_db
    ]
    cash_data = [
        CashOpData(
            id=c.id,
            op_date=c.op_date,
            amount=Decimal(c.amount),
            op_type=c.op_type.value if hasattr(c.op_type, "value") else str(c.op_type),
            cash_account_id=c.cash_account_id,
            counterparty=c.counterparty or "",
            edrpou=c.edrpou or "",
            pidrozdil_id=c.pidrozdil_id or "",
            dok_osnova=c.dok_osnova or "",
            comment=c.comment or "",
        )
        for c in cash_ops_db
    ]

    # 3. Мапінг bank → expected cash.
    mapping = await _load_bank_to_cash_mapping(session, payload.fop_id)

    # 4. Запуск ядра.
    outcomes = reconcile_global(
        bank_data,
        cash_data,
        bank_to_cash_mapping=mapping,
        date_window_days=payload.date_window_days,
        name_threshold=payload.fuzzy_name_threshold,
    )

    # 5. Створюємо сесію і рядки.
    recon_session = ReconSession(
        fop_id=payload.fop_id,
        period_from=payload.period_from,
        period_to=payload.period_to,
        date_window_days=payload.date_window_days,
        fuzzy_name_threshold=payload.fuzzy_name_threshold,
        status=ReconStatus.DRAFT,
    )
    session.add(recon_session)
    await session.flush()

    for o in outcomes:
        row = MatchRow(
            session_id=recon_session.id,
            kind=_KIND_MAP.get(o.kind, MatchKind.BANK_ONLY),
            bank_op_id=o.bank_op_id,
            cash_op_id=o.cash_op_id,
            expected_cash_account_id=o.expected_cash_account_id,
            score=o.score,
            date_diff_days=o.date_diff_days,
            counterparty_similarity=o.counterparty_similarity,
            notes="; ".join(o.notes) if o.notes else None,
        )
        session.add(row)
    await session.commit()
    await session.refresh(recon_session)

    stats = await _load_session_stats(session, recon_session)
    return ReconSessionOut(
        id=recon_session.id,
        fop_id=recon_session.fop_id,
        period_from=recon_session.period_from,
        period_to=recon_session.period_to,
        status=recon_session.status.value,
        date_window_days=recon_session.date_window_days,
        fuzzy_name_threshold=recon_session.fuzzy_name_threshold,
        created_at=recon_session.created_at,
        posted_at=recon_session.posted_at,
        total_bank_ops=len(bank_data),
        total_cash_ops=len(cash_data),
        **stats,
    )


@router.get("/sessions", response_model=list[ReconSessionOut])
async def list_sessions(fop_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(ReconSession).where(ReconSession.fop_id == fop_id).order_by(ReconSession.created_at.desc())
    )
    sessions = result.scalars().all()
    out = []
    for s in sessions:
        stats = await _load_session_stats(session, s)
        bank_count = await session.execute(
            select(func.count(BankOp.id)).where(
                BankOp.fop_id == s.fop_id,
                BankOp.op_date >= s.period_from,
                BankOp.op_date <= s.period_to,
            )
        )
        cash_count = await session.execute(
            select(func.count(CashOp.id)).where(
                CashOp.fop_id == s.fop_id,
                CashOp.op_date >= s.period_from,
                CashOp.op_date <= s.period_to,
            )
        )
        out.append(ReconSessionOut(
            id=s.id,
            fop_id=s.fop_id,
            period_from=s.period_from,
            period_to=s.period_to,
            status=s.status.value,
            date_window_days=s.date_window_days,
            fuzzy_name_threshold=s.fuzzy_name_threshold,
            created_at=s.created_at,
            posted_at=s.posted_at,
            total_bank_ops=bank_count.scalar() or 0,
            total_cash_ops=cash_count.scalar() or 0,
            **stats,
        ))
    return out


def _bank_op_summary(b: BankOp | None) -> dict[str, Any] | None:
    if not b:
        return None
    return {
        "op_date": b.op_date.isoformat(),
        "amount": str(b.amount),
        "direction": b.direction.value if hasattr(b.direction, "value") else str(b.direction),
        "counterparty": b.counterparty,
        "edrpou": b.edrpou,
        "purpose": b.purpose,
        "bank_account_id": b.bank_account_id,
    }


def _cash_op_summary(c: CashOp | None) -> dict[str, Any] | None:
    if not c:
        return None
    return {
        "op_date": c.op_date.isoformat(),
        "amount": str(c.amount),
        "op_type": c.op_type.value if hasattr(c.op_type, "value") else str(c.op_type),
        "doc_number": c.doc_number,
        "counterparty": c.counterparty,
        "cash_account_id": c.cash_account_id,
        "stattia": c.stattia,
        "dok_osnova": c.dok_osnova,
        "comment": c.comment,
    }


@router.get("/{session_id}/rows", response_model=list[MatchRowOut])
async def get_session_rows(
    session_id: str,
    kind: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Повернути рядки звірки. Можна фільтрувати за kind (exact|fuzzy|peresort|bank_only|cash_only)."""
    q = select(MatchRow).where(MatchRow.session_id == session_id)
    if kind:
        try:
            q = q.where(MatchRow.kind == MatchKind(kind.upper() if kind.isupper() else kind.lower()))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Невідомий kind: {kind}")

    result = await session.execute(q)
    rows = result.scalars().all()

    # Підтягуємо bank_op і cash_op детальки для UI.
    out: list[MatchRowOut] = []
    for r in rows:
        bank_op = await session.get(BankOp, r.bank_op_id) if r.bank_op_id else None
        cash_op = await session.get(CashOp, r.cash_op_id) if r.cash_op_id else None
        out.append(MatchRowOut(
            id=r.id,
            session_id=r.session_id,
            kind=r.kind.value,
            bank_op_id=r.bank_op_id,
            cash_op_id=r.cash_op_id,
            expected_cash_account_id=r.expected_cash_account_id,
            score=float(r.score),
            date_diff_days=r.date_diff_days,
            counterparty_similarity=float(r.counterparty_similarity),
            notes=r.notes,
            approved=r.approved,
            bank_op_summary=_bank_op_summary(bank_op),
            cash_op_summary=_cash_op_summary(cash_op),
        ))
    return out


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, session: AsyncSession = Depends(get_session)):
    s = await session.get(ReconSession, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Сесію не знайдено")
    # Спочатку явно видаляємо MatchRow — у async lazy-load для ORM cascade
    # зависає, тому робимо чисте DELETE statement.
    await session.execute(delete(MatchRow).where(MatchRow.session_id == session_id))
    await session.delete(s)
    await session.commit()
    return None


@router.get("/{session_id}/breakdown")
async def session_breakdown(session_id: str, session: AsyncSession = Depends(get_session)):
    """Діагностика: скільки яких op_type у БД за період сесії + по касах.

    Допомагає зрозуміти: «чому жоден ПКО не зматчився» — може у БД ПКО
    взагалі немає? Або вони на «не тій» касі?
    """
    s = await session.get(ReconSession, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Сесію не знайдено")

    # Каса-операції за період — по op_type.
    r = await session.execute(
        select(CashOp.op_type, func.count(CashOp.id))
        .where(
            CashOp.fop_id == s.fop_id,
            CashOp.op_date >= s.period_from,
            CashOp.op_date <= s.period_to,
        )
        .group_by(CashOp.op_type)
    )
    by_type: dict[str, int] = {}
    for op_type, cnt in r.all():
        key = op_type.value if hasattr(op_type, "value") else str(op_type)
        by_type[key] = cnt

    # По касах (top 10).
    r2 = await session.execute(
        select(CashOp.cash_account_id, CashOp.op_type, func.count(CashOp.id))
        .where(
            CashOp.fop_id == s.fop_id,
            CashOp.op_date >= s.period_from,
            CashOp.op_date <= s.period_to,
        )
        .group_by(CashOp.cash_account_id, CashOp.op_type)
    )
    by_cash: dict[str, dict[str, int]] = {}
    for cash_id, op_type, cnt in r2.all():
        key = op_type.value if hasattr(op_type, "value") else str(op_type)
        by_cash.setdefault(cash_id, {})[key] = cnt

    # Резолвимо ім'я каси.
    if by_cash:
        cash_r = await session.execute(
            select(CashAccount.id, CashAccount.name_1c)
            .where(CashAccount.id.in_(list(by_cash.keys())))
        )
        names = {cid: nm for cid, nm in cash_r.all()}
    else:
        names = {}

    return {
        "period": f"{s.period_from} .. {s.period_to}",
        "cash_ops_by_type": by_type,
        "cash_ops_by_account": [
            {"cash_account": names.get(cid, cid), "breakdown": br}
            for cid, br in by_cash.items()
        ],
    }


@router.post("/{session_id}/rerun", response_model=ReconSessionOut)
async def rerun_session(session_id: str, session: AsyncSession = Depends(get_session)):
    """Перерахувати сесію тими ж параметрами (period, dateWindow, threshold).

    Видаляє існуючі MatchRow і запускає matchінг наново з поточними даними
    у БД (наприклад, якщо щойно залив нові документи).
    """
    s = await session.get(ReconSession, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Сесію не знайдено")

    # Видаляємо старі рядки.
    await session.execute(delete(MatchRow).where(MatchRow.session_id == session_id))

    # Bank в межах періоду, cash — ширше на ±dateWindow (затримка проводки в 1С).
    _w = timedelta(days=s.date_window_days)
    bank_q = await session.execute(
        select(BankOp).where(
            BankOp.fop_id == s.fop_id,
            BankOp.op_date >= s.period_from,
            BankOp.op_date <= s.period_to,
        )
    )
    bank_ops_db = list(bank_q.scalars())
    cash_q = await session.execute(
        select(CashOp).where(
            CashOp.fop_id == s.fop_id,
            CashOp.op_date >= s.period_from - _w,
            CashOp.op_date <= s.period_to + _w,
        )
    )
    cash_ops_db = list(cash_q.scalars())

    bank_data = [
        BankOpData(
            id=b.id, op_date=b.op_date, amount=Decimal(b.amount),
            direction=b.direction.value if hasattr(b.direction, "value") else str(b.direction),
            bank_account_id=b.bank_account_id,
            counterparty=b.counterparty or "", edrpou=b.edrpou or "", purpose=b.purpose or "",
        ) for b in bank_ops_db
    ]
    cash_data = [
        CashOpData(
            id=c.id, op_date=c.op_date, amount=Decimal(c.amount),
            op_type=c.op_type.value if hasattr(c.op_type, "value") else str(c.op_type),
            cash_account_id=c.cash_account_id,
            counterparty=c.counterparty or "", edrpou=c.edrpou or "",
            pidrozdil_id=c.pidrozdil_id or "",
            dok_osnova=c.dok_osnova or "", comment=c.comment or "",
        ) for c in cash_ops_db
    ]

    mapping = await _load_bank_to_cash_mapping(session, s.fop_id)
    outcomes = reconcile_global(
        bank_data, cash_data,
        bank_to_cash_mapping=mapping,
        date_window_days=s.date_window_days,
        name_threshold=s.fuzzy_name_threshold,
    )

    for o in outcomes:
        session.add(MatchRow(
            session_id=s.id,
            kind=_KIND_MAP.get(o.kind, MatchKind.BANK_ONLY),
            bank_op_id=o.bank_op_id,
            cash_op_id=o.cash_op_id,
            expected_cash_account_id=o.expected_cash_account_id,
            score=o.score,
            date_diff_days=o.date_diff_days,
            counterparty_similarity=o.counterparty_similarity,
            notes="; ".join(o.notes) if o.notes else None,
        ))
    await session.commit()
    await session.refresh(s)
    stats = await _load_session_stats(session, s)
    return ReconSessionOut(
        id=s.id, fop_id=s.fop_id,
        period_from=s.period_from, period_to=s.period_to,
        status=s.status.value,
        date_window_days=s.date_window_days,
        fuzzy_name_threshold=s.fuzzy_name_threshold,
        created_at=s.created_at, posted_at=s.posted_at,
        total_bank_ops=len(bank_data), total_cash_ops=len(cash_data),
        **stats,
    )


@router.delete("/sessions/all", status_code=status.HTTP_200_OK)
async def delete_all_sessions(fop_id: str, session: AsyncSession = Depends(get_session)):
    """Видалити ВСІ сесії звірки для ФОПа — швидке очищення чорнеток."""
    result = await session.execute(
        select(ReconSession.id).where(ReconSession.fop_id == fop_id)
    )
    session_ids = [row[0] for row in result.all()]
    if not session_ids:
        return {"deleted": 0}

    # Видаляємо рядки потім сесії — двома запитами.
    await session.execute(delete(MatchRow).where(MatchRow.session_id.in_(session_ids)))
    await session.execute(delete(ReconSession).where(ReconSession.id.in_(session_ids)))
    await session.commit()
    return {"deleted": len(session_ids)}


class RowStatusUpdate(BaseModel):
    """approved | rejected | pending."""
    user_status: str


@router.patch("/rows/{row_id}")
async def update_row_status(
    row_id: str,
    payload: RowStatusUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Підтвердити / відхилити рядок звірки.

    - approved: юзер підтверджує що матч правильний (або bank_only треба провести).
    - rejected: юзер відхиляє (false positive — не та операція).
    - pending: скинути назад у невирішений стан.
    """
    valid = {"approved", "rejected", "pending"}
    if payload.user_status not in valid:
        raise HTTPException(status_code=400, detail=f"user_status має бути одним з: {valid}")
    row = await session.get(MatchRow, row_id)
    if not row:
        raise HTTPException(status_code=404, detail="Рядок не знайдено")
    row.user_status = payload.user_status if payload.user_status != "pending" else None
    if payload.user_status == "approved":
        row.approved = True
        from datetime import datetime
        row.approved_at = datetime.utcnow()
    else:
        row.approved = False
        row.approved_at = None
    await session.commit()
    return {"id": row.id, "user_status": row.user_status, "approved": row.approved}


class ManualMatchRequest(BaseModel):
    bank_op_id: str
    cash_op_id: str


@router.post("/{session_id}/manual-match", status_code=status.HTTP_201_CREATED)
async def manual_match(
    session_id: str,
    payload: ManualMatchRequest,
    session: AsyncSession = Depends(get_session),
):
    """Створити ручний матч bank ↔ cash. Видаляє старі рядки що посилаються
    на ці bank_op_id / cash_op_id у цій сесії (bank_only / cash_only / fuzzy).
    """
    s = await session.get(ReconSession, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Сесію не знайдено")
    b = await session.get(BankOp, payload.bank_op_id)
    if not b or b.fop_id != s.fop_id:
        raise HTTPException(status_code=404, detail="Bank-операція не належить цьому ФОПу")
    c = await session.get(CashOp, payload.cash_op_id)
    if not c or c.fop_id != s.fop_id:
        raise HTTPException(status_code=404, detail="Cash-операція не належить цьому ФОПу")

    # Видаляємо існуючі рядки що посилаються на ці bank/cash у цій сесії.
    await session.execute(
        delete(MatchRow).where(
            MatchRow.session_id == session_id,
            (MatchRow.bank_op_id == payload.bank_op_id) | (MatchRow.cash_op_id == payload.cash_op_id),
        )
    )

    # Створюємо новий manual matchrow.
    from datetime import datetime
    new_row = MatchRow(
        session_id=session_id,
        kind=MatchKind.FUZZY,
        bank_op_id=payload.bank_op_id,
        cash_op_id=payload.cash_op_id,
        score=100.0,
        date_diff_days=abs((b.op_date - c.op_date).days),
        counterparty_similarity=0.0,
        notes="Ручний матч",
        manual=True,
        user_status="approved",
        approved=True,
        approved_at=datetime.utcnow(),
    )
    session.add(new_row)
    await session.commit()
    return {"id": new_row.id, "kind": "fuzzy", "manual": True}
