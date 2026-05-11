"""Запуск звірки + перегляд результатів."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
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
    cash_q = await session.execute(
        select(CashOp).where(
            CashOp.fop_id == payload.fop_id,
            CashOp.op_date >= payload.period_from,
            CashOp.op_date <= payload.period_to,
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
