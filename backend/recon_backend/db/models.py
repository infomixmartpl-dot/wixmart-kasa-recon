"""SQLAlchemy 2.0 моделі для звірки.

Логіка домену:
- Fop — ФОП (юр.особа), кожен зі своїми ОДатою-credentials і Privat-токеном.
- BankAccount — рахунок у банку (IBAN), належить ФОПу.
- CashAccount — каса/рахунок в 1С УНФ (об'єкт довідника «Банковский счет, касса»).
  Зв'язок BankAccount ↔ CashAccount: один-до-одного, опційно (юзер мапить вручну).
- Pidrozdil — підрозділ в 1С (Instagram-сторінка / магазин).
- BankOp — операція у виписці Privat (один рядок).
- CashOp — касовий документ в 1С (ПКО/ВКО/Перемещение).
- ReconSession — окрема сесія звірки за період (наприклад «жовтень 2023, ФОП Аня»).
- MatchRow — результат матчингу для пари банк-каса або одного боку.
- ExpenseRule — правило розподілу витрати (пропорційно/прямо).
- MonthlyOborot — оборот підрозділу за конкретний місяць.

Усі ID — UUID. Часові штампи — UTC.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    DECIMAL,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# ─── Довідники ─────────────────────────────────────────────────────────


class Fop(Base):
    """ФОП — юр.особа з власною базою 1С і Privat-кабінетом."""

    __tablename__ = "fop"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))  # "ФОП Аня Петренко"
    edrpou: Mapped[str | None] = mapped_column(String(20), index=True)

    # 1С OData credentials
    odata_base_url: Mapped[str | None] = mapped_column(String(500))  # http://vmi.../Fish/odata/standard.odata
    odata_username: Mapped[str | None] = mapped_column(String(100))
    odata_password: Mapped[str | None] = mapped_column(String(200))  # TODO: шифрування

    # Privat24 Business API
    privat_token: Mapped[str | None] = mapped_column(String(200))  # TODO: шифрування

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    bank_accounts: Mapped[list["BankAccount"]] = relationship(back_populates="fop", cascade="all, delete-orphan")
    cash_accounts: Mapped[list["CashAccount"]] = relationship(back_populates="fop", cascade="all, delete-orphan")
    pidrozdily: Mapped[list["Pidrozdil"]] = relationship(back_populates="fop", cascade="all, delete-orphan")


class BankAccount(Base):
    """Банк-рахунок (IBAN) ФОПа в Privat. На один ФОП може бути кілька карт/рахунків."""

    __tablename__ = "bank_account"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    fop_id: Mapped[str] = mapped_column(String(36), ForeignKey("fop.id", ondelete="CASCADE"))
    iban: Mapped[str] = mapped_column(String(40), index=True)
    label: Mapped[str] = mapped_column(String(100))  # "Картка-FOP", "Транзитний"
    currency: Mapped[str] = mapped_column(String(3), default="UAH")

    # Опційний мапінг на конкретну касу в 1С (для нормального шляху платежу)
    expected_cash_account_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("cash_account.id"))

    fop: Mapped[Fop] = relationship(back_populates="bank_accounts")
    expected_cash_account: Mapped["CashAccount | None"] = relationship(foreign_keys=[expected_cash_account_id])

    __table_args__ = (UniqueConstraint("fop_id", "iban"),)


class CashAccount(Base):
    """Каса/рахунок в 1С УНФ (довідник «Банковский счет, касса»)."""

    __tablename__ = "cash_account"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    fop_id: Mapped[str] = mapped_column(String(36), ForeignKey("fop.id", ondelete="CASCADE"))
    name_1c: Mapped[str] = mapped_column(String(200))  # "Касса Аня ФОП", "Гарик КАСА налічка"
    odata_ref: Mapped[str | None] = mapped_column(String(50))  # GUID з 1С OData
    kind: Mapped[str] = mapped_column(String(20), default="bank")  # bank | cash | terminal

    fop: Mapped[Fop] = relationship(back_populates="cash_accounts")

    __table_args__ = (UniqueConstraint("fop_id", "name_1c"),)


class Pidrozdil(Base):
    """Підрозділ (Instagram-сторінка / магазин)."""

    __tablename__ = "pidrozdil"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    fop_id: Mapped[str] = mapped_column(String(36), ForeignKey("fop.id", ondelete="CASCADE"))
    name_1c: Mapped[str] = mapped_column(String(200))
    instagram_handle: Mapped[str | None] = mapped_column(String(100))
    odata_ref: Mapped[str | None] = mapped_column(String(50))

    fop: Mapped[Fop] = relationship(back_populates="pidrozdily")

    __table_args__ = (UniqueConstraint("fop_id", "name_1c"),)


class MonthlyOborot(Base):
    """Оборот підрозділу за місяць (для пропорційного розподілу витрат)."""

    __tablename__ = "monthly_oborot"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    pidrozdil_id: Mapped[str] = mapped_column(String(36), ForeignKey("pidrozdil.id", ondelete="CASCADE"))
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)  # 1..12
    amount: Mapped[Decimal] = mapped_column(DECIMAL(15, 2))

    __table_args__ = (
        UniqueConstraint("pidrozdil_id", "year", "month"),
        Index("ix_oborot_period", "year", "month"),
    )


class ExpenseRule(Base):
    """Правило розподілу витрат за призначенням платежу."""

    __tablename__ = "expense_rule"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    fop_id: Mapped[str] = mapped_column(String(36), ForeignKey("fop.id", ondelete="CASCADE"))
    stattia: Mapped[str] = mapped_column(String(200))  # "Оренда", "Реклама Instagram"
    distribution_type: Mapped[str] = mapped_column(String(20))  # "пропорційно" | "прямо"
    direct_pidrozdil_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("pidrozdil.id"))
    keywords: Mapped[str] = mapped_column(Text, default="")  # JSON або через кому


# ─── Операції ──────────────────────────────────────────────────────────


class Direction(str, Enum):
    IN = "in"   # прихід
    OUT = "out"  # видаток


class BankOp(Base):
    """Одна операція з виписки Privat."""

    __tablename__ = "bank_op"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    fop_id: Mapped[str] = mapped_column(String(36), ForeignKey("fop.id", ondelete="CASCADE"))
    bank_account_id: Mapped[str] = mapped_column(String(36), ForeignKey("bank_account.id", ondelete="CASCADE"))

    op_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(DECIMAL(15, 2))
    direction: Mapped[Direction] = mapped_column(SQLEnum(Direction))

    doc_number: Mapped[str | None] = mapped_column(String(50))
    counterparty: Mapped[str | None] = mapped_column(String(500))
    edrpou: Mapped[str | None] = mapped_column(String(20), index=True)
    purpose: Mapped[str | None] = mapped_column(Text)
    account_correspondent: Mapped[str | None] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(3), default="UAH")

    source: Mapped[str] = mapped_column(String(20), default="csv")  # csv | api
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_bank_op_lookup", "fop_id", "op_date", "amount", "direction"),
    )


class CashOpType(str, Enum):
    PKO = "ПКО"           # Поступление денег
    VKO = "ВКО"           # Списание/Расход денег
    PEREMESHCHENIE = "Перемещение"  # Перемещение денег (між касами)


class CashOp(Base):
    """Один касовий документ з 1С (ПКО / ВКО / Перемещение)."""

    __tablename__ = "cash_op"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    fop_id: Mapped[str] = mapped_column(String(36), ForeignKey("fop.id", ondelete="CASCADE"))
    cash_account_id: Mapped[str] = mapped_column(String(36), ForeignKey("cash_account.id", ondelete="CASCADE"))

    op_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(DECIMAL(15, 2))
    op_type: Mapped[CashOpType] = mapped_column(SQLEnum(CashOpType))

    doc_number: Mapped[str | None] = mapped_column(String(50))
    odata_ref: Mapped[str | None] = mapped_column(String(50))  # GUID документа в 1С
    counterparty: Mapped[str | None] = mapped_column(String(500))
    edrpou: Mapped[str | None] = mapped_column(String(20), index=True)
    pidrozdil_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("pidrozdil.id"))
    stattia: Mapped[str | None] = mapped_column(String(200))
    dok_osnova: Mapped[str | None] = mapped_column(String(500))  # Реалізація/Замовлення
    comment: Mapped[str | None] = mapped_column(Text)

    source: Mapped[str] = mapped_column(String(20), default="report")  # report | odata | xlsx
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_cash_op_lookup", "fop_id", "op_date", "amount", "op_type"),
    )


# ─── Звірка ────────────────────────────────────────────────────────────


class ReconStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    POSTED = "posted"


class ReconSession(Base):
    """Одна сесія звірки за період + ФОП. Зберігає налаштування й історію."""

    __tablename__ = "recon_session"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    fop_id: Mapped[str] = mapped_column(String(36), ForeignKey("fop.id", ondelete="CASCADE"))
    period_from: Mapped[date] = mapped_column(Date)
    period_to: Mapped[date] = mapped_column(Date)
    status: Mapped[ReconStatus] = mapped_column(SQLEnum(ReconStatus), default=ReconStatus.DRAFT)

    # Параметри алгоритму
    date_window_days: Mapped[int] = mapped_column(Integer, default=14)
    fuzzy_name_threshold: Mapped[int] = mapped_column(Integer, default=85)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime)

    rows: Mapped[list["MatchRow"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class MatchKind(str, Enum):
    EXACT = "exact"               # точний збіг дата+сума+тип
    FUZZY = "fuzzy"               # ±14 днів + сума + контрагент
    PERESORT = "peresort"         # каса А ↔ виписка Б (не та каса!)
    BANK_ONLY = "bank_only"       # тільки в банку, треба провести в касу
    CASH_ONLY = "cash_only"       # тільки в касі, нема в банку (готівка?)


class MatchRow(Base):
    """Один рядок у звірці. Може посилатись на BankOp, CashOp або обидва."""

    __tablename__ = "match_row"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("recon_session.id", ondelete="CASCADE"))
    kind: Mapped[MatchKind] = mapped_column(SQLEnum(MatchKind))

    bank_op_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("bank_op.id"))
    cash_op_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("cash_op.id"))

    # Для peresort — куди мало піти насправді (за мапінгом IBAN → каса)
    expected_cash_account_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("cash_account.id"))

    score: Mapped[float] = mapped_column(DECIMAL(5, 2), default=0)
    date_diff_days: Mapped[int] = mapped_column(Integer, default=0)
    counterparty_similarity: Mapped[float] = mapped_column(DECIMAL(5, 2), default=0)
    notes: Mapped[str | None] = mapped_column(Text)

    # Дії юзера
    approved: Mapped[bool] = mapped_column(default=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    posted_doc_ref: Mapped[str | None] = mapped_column(String(50))  # GUID документа що створили в 1С

    session: Mapped[ReconSession] = relationship(back_populates="rows")
