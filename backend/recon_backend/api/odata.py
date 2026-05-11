"""Endpoints для роботи з 1С OData.

Послідовність типового використання з UI:
1. POST `/api/odata/{fop_id}/test`     — перевірити що OData доступний.
2. POST `/api/odata/{fop_id}/discover` — побачити які EntitySet є у твоїй УНФ.
3. POST `/api/odata/{fop_id}/sync-catalogs` — затягнути довідники кас/підрозділів.
4. POST `/api/odata/{fop_id}/sync-cash`     — затягнути касові документи за період.
5. POST `/api/odata/{fop_id}/sync-realizations` — реалізації (для пошуку основ).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..clients import OData1CClient, OData1CError
from ..db.models import CashAccount, CashOp, CashOpType, Fop, Pidrozdil
from ..db.session import get_session

router = APIRouter()


# ─── Pydantic схеми ─────────────────────────────────────────────────────


class ODataConfigOverride(BaseModel):
    """Опційно переписати OData URL/login/password з ФОПа.

    Корисно коли юзер тестує OData ще до того як зберіг credentials у БД.
    """
    base_url: str | None = None
    username: str | None = None
    password: str | None = None


class SyncCashRequest(BaseModel):
    """Параметри синку касових/банк-документів.

    В УНФ 1.6 для України прихід/розхід поділено на готівку і безготівку:
    - готівка: ПоступлениеВКассу / РасходИзКассы (використовує Catalog_Кассы)
    - безготівка: ПоступлениеНаСчет / РасходСоСчета (використовує Catalog_БанковскиеСчета)

    Тому документи задаються списком — за замовч. підтягуємо обидва типи.
    """
    period_from: date
    period_to: date
    in_documents: list[str] = [
        "Document_ПоступлениеВКассу",
        "Document_ПоступлениеНаСчет",
    ]
    out_documents: list[str] = [
        "Document_РасходИзКассы",
        "Document_РасходСоСчета",
    ]
    transfer_documents: list[str] = ["Document_ПеремещениеДС"]
    cash_account_id: str | None = None


# ─── Допоміжне ──────────────────────────────────────────────────────────


async def _build_client(
    session: AsyncSession,
    fop_id: str,
    override: ODataConfigOverride | None,
) -> OData1CClient:
    fop = await session.get(Fop, fop_id)
    if not fop:
        raise HTTPException(status_code=404, detail="ФОП не знайдено")

    url = (override.base_url if override else None) or fop.odata_base_url
    user = (override.username if override else None) or fop.odata_username
    pwd = (override.password if override else None) or fop.odata_password

    if not (url and user and pwd):
        raise HTTPException(
            status_code=400,
            detail="OData credentials не задано. Заповни odata_base_url/username/password у ФОПі або передай через override.",
        )
    return OData1CClient(url, user, pwd)


# ─── Endpoints ─────────────────────────────────────────────────────────


@router.post("/{fop_id}/test")
async def test_odata(
    fop_id: str,
    override: ODataConfigOverride | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Перевірка з'єднання + базова інформація з $metadata."""
    async with await _build_client(session, fop_id, override) as client:
        return await client.ping()


@router.post("/{fop_id}/discover")
async def discover_entities(
    fop_id: str,
    override: ODataConfigOverride | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Перерахувати ВСІ EntitySet з $metadata, згруповані за типом.

    Допомагає юзеру побачити що саме доступне у його УНФ — і обрати правильні
    імена `Document_*` для синку (бо різні конфігурації мають різні назви).
    """
    async with await _build_client(session, fop_id, override) as client:
        entity_sets = await client.list_entity_sets()
    catalogs = [s for s in entity_sets if s.startswith("Catalog_")]
    documents = [s for s in entity_sets if s.startswith("Document_")]
    enums = [s for s in entity_sets if s.startswith("Enum_")]
    registers = [s for s in entity_sets if s.startswith("AccumulationRegister_") or s.startswith("InformationRegister_")]
    other = [s for s in entity_sets if not any(s.startswith(p) for p in (
        "Catalog_", "Document_", "Enum_", "AccumulationRegister_", "InformationRegister_"
    ))]
    return {
        "total": len(entity_sets),
        "catalogs": catalogs,
        "documents": documents,
        "enums": enums,
        "registers": registers,
        "other": other,
    }


@router.post("/{fop_id}/sync-catalogs")
async def sync_catalogs(
    fop_id: str,
    catalog_kasy: list[str] | None = None,
    catalog_pidrozdil: str = "Catalog_СтруктурныеЕдиницы",
    override: ODataConfigOverride | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Затягнути каси/рахунки і підрозділи з 1С у нашу БД.

    В УНФ 1.6 для України каси і банк-рахунки — це ДВА окремі довідники:
    `Catalog_Кассы` (готівка) і `Catalog_БанковскиеСчета` (безготівка).
    Тому `catalog_kasy` приймає список — за замовч. обидва.

    Підрозділи в УНФ — `Catalog_СтруктурныеЕдиницы` (не `Подразделения`).
    """
    fop = await session.get(Fop, fop_id)
    if not fop:
        raise HTTPException(status_code=404, detail="ФОП не знайдено")

    if catalog_kasy is None:
        catalog_kasy = ["Catalog_Кассы", "Catalog_БанковскиеСчета"]

    added_cash = 0
    updated_cash = 0
    added_pidr = 0
    updated_pidr = 0
    errors: list[str] = []

    async with await _build_client(session, fop_id, override) as client:
        # Каси і банк-рахунки.
        for entity in catalog_kasy:
            try:
                kasy = await client.fetch_all(entity)
            except OData1CError as e:
                errors.append(f"{entity}: {e}")
                continue
            # Тип: bank якщо це БанковскиеСчета, інакше cash.
            kind = "bank" if "Банковск" in entity else "cash"
            for item in kasy:
                ref = item.get("Ref_Key")
                name = item.get("Description") or item.get("Name")
                if not (ref and name):
                    continue
                existing = await session.execute(
                    select(CashAccount).where(CashAccount.odata_ref == ref)
                )
                row = existing.scalar_one_or_none()
                if row:
                    if row.name_1c != name:
                        row.name_1c = name
                        updated_cash += 1
                else:
                    session.add(CashAccount(fop_id=fop_id, name_1c=name, odata_ref=ref, kind=kind))
                    added_cash += 1

        # Підрозділи
        try:
            podr = await client.fetch_all(catalog_pidrozdil)
        except OData1CError as e:
            errors.append(f"Підрозділи: {e}")
            podr = []
        for item in podr:
            ref = item.get("Ref_Key")
            name = item.get("Description") or item.get("Name")
            if not (ref and name):
                continue
            existing = await session.execute(
                select(Pidrozdil).where(Pidrozdil.odata_ref == ref)
            )
            row = existing.scalar_one_or_none()
            if row:
                if row.name_1c != name:
                    row.name_1c = name
                    updated_pidr += 1
            else:
                session.add(Pidrozdil(fop_id=fop_id, name_1c=name, odata_ref=ref))
                added_pidr += 1

    await session.commit()
    return {
        "added": {"cash_accounts": added_cash, "pidrozdily": added_pidr},
        "updated": {"cash_accounts": updated_cash, "pidrozdily": updated_pidr},
        "errors": errors,
    }


@router.post("/{fop_id}/sync-cash")
async def sync_cash_from_odata(
    fop_id: str,
    body: SyncCashRequest,
    session: AsyncSession = Depends(get_session),
):
    """Затягнути всі касові документи (ПКО, ВКО, Перемещение) за період у нашу БД.

    Перед цим синк-ом обов'язково треба зробити /sync-catalogs (інакше cash_account_id
    не знайдеться по GUID-у).
    """
    fop = await session.get(Fop, fop_id)
    if not fop:
        raise HTTPException(status_code=404, detail="ФОП не знайдено")

    # Збираємо мапінг odata_ref → cash_account_id у БД.
    result = await session.execute(select(CashAccount).where(CashAccount.fop_id == fop_id))
    cash_by_ref: dict[str, str] = {c.odata_ref: c.id for c in result.scalars() if c.odata_ref}

    # Підрозділи теж.
    result = await session.execute(select(Pidrozdil).where(Pidrozdil.fop_id == fop_id))
    pidr_by_ref: dict[str, str] = {p.odata_ref: p.id for p in result.scalars() if p.odata_ref}

    summary: dict[str, dict[str, int]] = {}

    # $expand залежить від типу документа:
    # - прихід/розхід: є Контрагент. Подразделение в УНФ 1.6 безготівкових
    #   документах часто немає — не запитуємо щоб уникнути 400.
    # - переміщення: Контрагента немає (це переміщення між рахунками).
    # Назви підрозділів і контрагентів все одно тягнемо як string-поле
    # (`*_Description`), бо без expand 1С зазвичай повертає їх плоско.
    expand_in_out = ["Контрагент"]
    expand_transfer: list[str] = []

    # Готуємо трійки (entity_name, op_type, expand) — підтримуємо списки документів.
    entity_jobs: list[tuple[str, CashOpType, list[str]]] = []
    for entity in body.in_documents:
        entity_jobs.append((entity, CashOpType.PKO, expand_in_out))
    for entity in body.out_documents:
        entity_jobs.append((entity, CashOpType.VKO, expand_in_out))
    for entity in body.transfer_documents:
        entity_jobs.append((entity, CashOpType.PEREMESHCHENIE, expand_transfer))

    async with await _build_client(session, fop_id, None) as client:
        for entity, op_type, expand in entity_jobs:
            stats = await _sync_one_doc_type(
                client, session, fop_id, entity, op_type,
                period_from=body.period_from,
                period_to=body.period_to,
                expand=expand,
                cash_by_ref=cash_by_ref,
                pidr_by_ref=pidr_by_ref,
                filter_cash_id=body.cash_account_id,
            )
            summary[entity] = stats

    await session.commit()
    return summary


async def _sync_one_doc_type(
    client: OData1CClient,
    session: AsyncSession,
    fop_id: str,
    entity: str,
    op_type: CashOpType,
    *,
    period_from: date,
    period_to: date,
    expand: list[str],
    cash_by_ref: dict[str, str],
    pidr_by_ref: dict[str, str],
    filter_cash_id: str | None,
) -> dict[str, int]:
    added = 0
    duplicates = 0
    skipped_no_cash = 0
    errors = 0

    try:
        docs = await client.fetch_documents_period(entity, period_from, period_to, expand=expand)
    except OData1CError as e:
        return {"added": 0, "errors": 1, "error_message": str(e)}

    for doc in docs:
        try:
            ref = doc.get("Ref_Key")
            date_str = doc.get("Date") or ""
            try:
                op_date = date.fromisoformat(date_str[:10])
            except ValueError:
                errors += 1
                continue

            # Сума: різні документи різно називають поле.
            amount_raw = (
                doc.get("СуммаДокумента")
                or doc.get("Сумма")
                or doc.get("DocumentAmount")
                or "0"
            )
            try:
                amount = Decimal(str(amount_raw))
            except Exception:  # noqa: BLE001
                errors += 1
                continue

            # Каса/банк-рахунок — різні реквізити у різних документах:
            # - готівка: Касса_Key (ПоступлениеВКассу, РасходИзКассы)
            # - безготівка: БанковскийСчет_Key (ПоступлениеНаСчет, РасходСоСчета)
            # - переміщення: КассаОтправитель_Key + КассаПолучатель_Key
            # - старий збірний реквізит: БанковскийСчетКасса_Key
            cash_ref = (
                doc.get("Касса_Key")
                or doc.get("БанковскийСчет_Key")
                or doc.get("БанковскийСчетКасса_Key")
                or doc.get("КассаОтправитель_Key")
                or doc.get("СчетОтправитель_Key")
            )
            cash_account_id = cash_by_ref.get(cash_ref) if cash_ref else None
            if not cash_account_id:
                skipped_no_cash += 1
                continue

            # Фільтр по конкретній касі.
            if filter_cash_id and cash_account_id != filter_cash_id:
                continue

            counterparty = ((doc.get("Контрагент") or {}).get("Description")
                            or doc.get("Контрагент_Description") or "")
            pidr_ref = doc.get("Подразделение_Key")
            pidrozdil_id = pidr_by_ref.get(pidr_ref) if pidr_ref else None

            # Дедуплікація по odata_ref (GUID) — найнадійніше.
            if ref:
                existing = await session.execute(
                    select(CashOp).where(CashOp.odata_ref == ref)
                )
                if existing.scalar_one_or_none():
                    duplicates += 1
                    continue

            session.add(CashOp(
                fop_id=fop_id,
                cash_account_id=cash_account_id,
                op_date=op_date,
                amount=amount,
                op_type=op_type,
                doc_number=str(doc.get("Number") or doc.get("Номер") or "").strip() or None,
                odata_ref=ref,
                counterparty=counterparty or None,
                pidrozdil_id=pidrozdil_id,
                stattia=doc.get("СтатьяДвиженияДенежныхСредств_Description"),
                dok_osnova=(doc.get("ДокументОснование") or {}).get("Description") if doc.get("ДокументОснование") else None,
                comment=doc.get("Комментарий"),
                source="odata",
            ))
            added += 1
        except Exception as e:  # noqa: BLE001
            errors += 1
            # Не зупиняємось — підрахуємо помилки в результаті.
            continue

    return {
        "added": added,
        "duplicates": duplicates,
        "skipped_no_cash_mapping": skipped_no_cash,
        "errors": errors,
        "total_fetched": len(docs),
    }


@router.post("/{fop_id}/sync-realizations")
async def sync_realizations(
    fop_id: str,
    period_from: date,
    period_to: date,
    realization_entity: str = "Document_РеализацияТоваровУслуг",
    override: ODataConfigOverride | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Затягнути реалізації для пошуку основ приходу.

    Поки що (MVP) — просто рахуємо скільки знайшли. Окрема таблиця Realization
    додається у наступному PR коли підключимо матчинг основ через БД.
    """
    async with await _build_client(session, fop_id, override) as client:
        try:
            docs = await client.fetch_documents_period(
                realization_entity, period_from, period_to,
                expand=["Контрагент", "Подразделение"],
            )
        except OData1CError as e:
            raise HTTPException(status_code=502, detail=str(e))

    sample = [
        {
            "date": d.get("Date", "")[:10],
            "number": d.get("Number"),
            "amount": str(d.get("СуммаДокумента") or d.get("Сумма") or ""),
            "counterparty": ((d.get("Контрагент") or {}).get("Description")) or "",
        }
        for d in docs[:10]
    ]
    return {"total_fetched": len(docs), "sample": sample}
