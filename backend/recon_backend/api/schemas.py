"""Pydantic схеми для API request/response."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# ─── ФОП ────────────────────────────────────────────────────────────


class FopBase(BaseModel):
    name: str = Field(..., max_length=200)
    edrpou: str | None = Field(None, max_length=20)
    odata_base_url: str | None = Field(None, max_length=500)
    odata_username: str | None = Field(None, max_length=100)
    odata_password: str | None = Field(None, max_length=200)
    privat_token: str | None = Field(None, max_length=200)


class FopCreate(FopBase):
    pass


class FopUpdate(FopBase):
    name: str | None = None  # усі поля опційні в update


class FopOut(FopBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime


# ─── Банк-рахунок ──────────────────────────────────────────────────


class BankAccountBase(BaseModel):
    iban: str = Field(..., max_length=40)
    label: str = Field(..., max_length=100)
    currency: str = Field("UAH", max_length=3)
    expected_cash_account_id: str | None = None


class BankAccountCreate(BankAccountBase):
    pass


class BankAccountOut(BankAccountBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    fop_id: str


# ─── Каса ──────────────────────────────────────────────────────────


class CashAccountBase(BaseModel):
    name_1c: str = Field(..., max_length=200)
    kind: str = Field("bank", description="bank | cash | terminal")
    odata_ref: str | None = None


class CashAccountCreate(CashAccountBase):
    pass


class CashAccountOut(CashAccountBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    fop_id: str


# ─── Підрозділ ─────────────────────────────────────────────────────


class PidrozdilCreate(BaseModel):
    name_1c: str = Field(..., max_length=200)
    instagram_handle: str | None = None


class PidrozdilOut(PidrozdilCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    fop_id: str


# ─── Звірка ────────────────────────────────────────────────────────


class ReconRunRequest(BaseModel):
    fop_id: str
    period_from: date
    period_to: date
    date_window_days: int = 14
    fuzzy_name_threshold: int = 85


class ReconSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    fop_id: str
    period_from: date
    period_to: date
    status: str
    date_window_days: int
    fuzzy_name_threshold: int
    created_at: datetime
    posted_at: datetime | None
    # підрахунки заповнюються окремо
    total_bank_ops: int = 0
    total_cash_ops: int = 0
    matched_exact: int = 0
    matched_fuzzy: int = 0
    peresort: int = 0
    bank_only: int = 0
    cash_only: int = 0


class MatchRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    session_id: str
    kind: str
    bank_op_id: str | None
    cash_op_id: str | None
    expected_cash_account_id: str | None
    score: float
    date_diff_days: int
    counterparty_similarity: float
    notes: str | None
    approved: bool

    # Розгорнута інформація для UI — заповнюємо вручну
    bank_op_summary: dict | None = None
    cash_op_summary: dict | None = None


class HealthOut(BaseModel):
    status: str
    version: str
    db: str
