"""Клієнт до 1С OData (стандартний інтерфейс).

Документація 1С: «Стандартный OData-интерфейс» — https://its.1c.eu/db/v8316doc

Загальна структура URL:
    http://<host>/<база>/odata/standard.odata/<EntitySet>?<query>

EntitySet — це назва довідника/документа в метаданих, ПЕРЕЛАМАНА у форму
з префіксом + ім'я з конфігурації:
    Catalog_Контрагенты         — довідник Контрагенти
    Catalog_БанковскиеСчетаКассы — довідник «Банковские счета, кассы» (УНФ 1.6)
    Document_ПоступлениеВКассу   — документ Поступление в кассу
    Document_РасходИзКассы       — документ Расход из кассы
    Document_ПеремещениеДенег    — переміщення між касами
    Document_РеализацияТоваровУслуг — реалізації

Точні назви залежать від конфігурації. Найперший крок — `fetch_metadata()` і
`list_entity_sets()` — дізнатись що саме доступне.

Auth — Basic. Користувач 1С повинен мати роль з правами на читання документів
(зазвичай «ПолныеПрава» або кастомна роль для звірок).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

import httpx
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

# OData метадані використовують XML namespace edmx — 1С повертає метадані саме у цьому форматі.
_EDMX_NS = "{http://schemas.microsoft.com/ado/2007/06/edmx}"
_EDM_NS = "{http://schemas.microsoft.com/ado/2009/11/edm}"


class OData1CError(Exception):
    """Будь-яка помилка від клієнта OData 1С."""


class OData1CClient:
    """Тонкий async-обгортка над httpx для 1С OData.

    Викоремий контекст-менеджер, щоб httpx коректно закрив пул з'єднань:
        async with OData1CClient(base_url, login, password) as client:
            metadata = await client.fetch_metadata()
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout_s: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._auth = httpx.BasicAuth(username, password)
        self._timeout = timeout_s
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> OData1CClient:
        self._client = httpx.AsyncClient(
            auth=self._auth,
            timeout=self._timeout,
            headers={"Accept": "application/json"},
            # Не валідуємо SSL — у багатьох корп. серверах самопідписаний.
            verify=False,
        )
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ─── Низькорівневі ──────────────────────────────────────────────

    async def _get(self, url: str, *, params: dict | None = None) -> httpx.Response:
        if not self._client:
            raise RuntimeError("Використовуй `async with OData1CClient(...)`.")
        try:
            r = await self._client.get(url, params=params)
        except httpx.HTTPError as e:
            raise OData1CError(f"HTTP помилка {url}: {e}") from e
        if r.status_code == 401:
            raise OData1CError("Невірний логін/пароль 1С (401).")
        if r.status_code == 403:
            raise OData1CError("Користувачу 1С не вистачає прав (403). Перевір ролі.")
        if r.status_code == 404:
            raise OData1CError(f"Не знайдено: {url} (404). Перевір ім'я EntitySet або URL бази.")
        if r.status_code >= 400:
            raise OData1CError(f"HTTP {r.status_code} {url}: {r.text[:300]}")
        return r

    # ─── Метадані ───────────────────────────────────────────────────

    async def fetch_metadata(self) -> str:
        """Повертає сирий XML $metadata. Корисно для діагностики і знаходження EntitySet-ів."""
        url = f"{self.base_url}/$metadata"
        r = await self._get(url)
        return r.text

    @staticmethod
    def _local_name(tag: str) -> str:
        """Прибрати XML namespace із тега: '{http://...}EntitySet' → 'EntitySet'."""
        return tag.rsplit("}", 1)[-1] if "}" in tag else tag

    def _extract_entity_sets(self, xml: str) -> tuple[str, list[str]]:
        """Розпарсити $metadata, повернути (version, [EntitySet names]).

        Шукає теги з local-name = 'EntitySet' під будь-яким namespace —
        бо різні версії 1С повертають метадані з різними префіксами
        (`edm`, `edmx`, default xmlns=...).
        """
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as e:
            raise OData1CError(f"Не вдалось розпарсити $metadata: {e}") from e
        version = root.attrib.get("Version", "?")
        sets: list[str] = []
        for elem in root.iter():
            if self._local_name(elem.tag) == "EntitySet":
                name = elem.attrib.get("Name")
                if name:
                    sets.append(name)
        return version, sets

    async def list_entity_sets(self) -> list[str]:
        """Розпарсити $metadata і повернути назви всіх EntitySet (довідники + документи)."""
        xml = await self.fetch_metadata()
        _, sets = self._extract_entity_sets(xml)
        return sorted(sets)

    async def ping(self) -> dict[str, Any]:
        """Швидка перевірка з'єднання + парсинг базової інформації з $metadata.

        Повертає словник з полями:
            ok: True/False
            version: версія edmx (наприклад "1.0" для 1С / "4.0" для нових)
            entity_count: скільки EntitySet знайдено
            catalog_count / document_count: кількість Catalog_* і Document_*
            catalogs_sample / documents_sample: перші 10 з кожного типу
        """
        try:
            xml = await self.fetch_metadata()
        except OData1CError as e:
            return {"ok": False, "error": str(e)}
        version, sets = self._extract_entity_sets(xml)
        catalogs = sorted([s for s in sets if s.startswith("Catalog_")])
        documents = sorted([s for s in sets if s.startswith("Document_")])
        return {
            "ok": True,
            "version": version,
            "entity_count": len(sets),
            "catalogs_sample": catalogs[:10],
            "documents_sample": documents[:10],
            "catalog_count": len(catalogs),
            "document_count": len(documents),
        }

    # ─── Запити до сутностей ────────────────────────────────────────

    async def query(
        self,
        entity_set: str,
        *,
        filter_: str | None = None,
        top: int | None = None,
        skip: int | None = None,
        select: list[str] | None = None,
        expand: list[str] | None = None,
        order_by: str | None = None,
    ) -> list[dict[str, Any]]:
        """Виконати один OData GET до `entity_set`. Повертає масив об'єктів.

        Зверніть увагу: 1С не завжди обмежує результат, тому для великих
        EntitySet використовуй `top` + `skip` або `fetch_all`.
        """
        url = f"{self.base_url}/{entity_set}"
        params: dict[str, Any] = {"$format": "json"}
        if filter_:
            params["$filter"] = filter_
        if top is not None:
            params["$top"] = str(top)
        if skip is not None:
            params["$skip"] = str(skip)
        if select:
            params["$select"] = ",".join(select)
        if expand:
            params["$expand"] = ",".join(expand)
        if order_by:
            params["$orderby"] = order_by

        r = await self._get(url, params=params)
        data = r.json()
        return data.get("value", [])

    async def fetch_all(
        self,
        entity_set: str,
        *,
        filter_: str | None = None,
        expand: list[str] | None = None,
        page_size: int = 500,
        max_pages: int = 200,
    ) -> list[dict[str, Any]]:
        """Скачати ВСЕ з пагінацією. Зупиняється коли сторінка повертає менше ніж page_size."""
        all_rows: list[dict[str, Any]] = []
        for page in range(max_pages):
            chunk = await self.query(
                entity_set,
                filter_=filter_,
                expand=expand,
                top=page_size,
                skip=page * page_size,
            )
            all_rows.extend(chunk)
            logger.info("OData %s: сторінка %d, +%d, всього %d",
                        entity_set, page + 1, len(chunk), len(all_rows))
            if len(chunk) < page_size:
                break
        return all_rows

    # ─── Високорівневі helper-и під УНФ 1.6 ─────────────────────────

    @staticmethod
    def odata_datetime(d: date | datetime) -> str:
        """Сформатувати дату для $filter згідно з OData v3 від 1С.

        Приклад: `Date ge datetime'2024-01-01T00:00:00'`
        """
        if isinstance(d, datetime):
            return d.strftime("datetime'%Y-%m-%dT%H:%M:%S'")
        return f"datetime'{d.isoformat()}T00:00:00'"

    async def fetch_documents_period(
        self,
        entity_set: str,
        period_from: date,
        period_to: date,
        *,
        date_field: str = "Date",
        expand: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Витягти всі документи `entity_set` за період [from..to] включно.

        Стандартне поле дати у 1С OData — `Date`. У деяких документах може
        бути `DateAndTime` або інше — передавай через `date_field`.

        Деякі конфігурації УНФ 1.6 відмовляються застосовувати `$filter` по
        `Date` через AUTOORDER (внутрішня помилка 1С: «Операция не разрешена
        в предложении ГДЕ»). У такому випадку робимо fallback: качаємо всі
        документи з пагінацією і фільтруємо локально по даті.
        """
        from_dt = datetime.combine(period_from, datetime.min.time())
        to_dt = datetime.combine(period_to, datetime.max.time())
        from_str = self.odata_datetime(from_dt)
        to_str = self.odata_datetime(to_dt)
        filter_ = f"{date_field} ge {from_str} and {date_field} le {to_str}"

        try:
            return await self.fetch_all(entity_set, filter_=filter_, expand=expand)
        except OData1CError as e:
            msg = str(e)
            # AUTOORDER або інша помилка ГДЕ → fallback на повне завантаження.
            if "AUTOORDER" in msg or "предложении" in msg or "ГДЕ" in msg:
                logger.warning(
                    "OData %s: $filter по %s заборонено (%s). Fallback: full fetch + local filter.",
                    entity_set, date_field, msg[:120],
                )
                all_docs = await self.fetch_all(entity_set, expand=expand)
                # Локальний фільтр по полю Date (рядок ISO).
                result = []
                for d in all_docs:
                    raw = d.get(date_field) or ""
                    try:
                        doc_dt = datetime.fromisoformat(raw[:19])
                    except ValueError:
                        continue
                    if from_dt <= doc_dt <= to_dt:
                        result.append(d)
                logger.info("Локальний фільтр %s: %d з %d документів у періоді.",
                            entity_set, len(result), len(all_docs))
                return result
            raise


def safe_filter(value: str) -> str:
    """Екранує одинарні лапки в значенні для OData $filter.

    OData екранує `'` через подвоєння. `O'Reilly` → `O''Reilly`.
    """
    return quote(value.replace("'", "''"), safe="")
