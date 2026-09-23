"""Контракт инструментов 1С: pydantic-схемы аргументов.

Единый источник правды для моков (шаг 1), BSL-инструментов расширения
`onec/ext` и live-адаптера: имена и параметры совпадают 1:1, поэтому замена
моков на живые вызовы прозрачна для модели.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SkdReportArgs(BaseModel):
    """Отчёт по готовому макету из каталога."""

    report: Literal["sales_by_warehouse", "debtors"]
    period: str = Field(pattern=r"^\d{4}-(Q[1-4]|H[12]|Y)$", examples=["2026-Q1"])
    warehouse: str | None = Field(default=None, description="Фильтр по складу, только для sales_by_warehouse")
    limit: int = Field(default=20, le=100)


class CounterpartyArgs(BaseModel):
    """Карточка контрагента по названию (подстрока) или ИНН."""

    query: str = Field(min_length=2)


class StockArgs(BaseModel):
    """Остатки номенклатуры по складам."""

    sku: str = Field(min_length=2)
    warehouse: str | None = None


class ExecuteSelectArgs(BaseModel):
    """Произвольный запрос: только ВЫБРАТЬ/SELECT, кап строк на стороне 1С."""

    query: str = Field(min_length=1)
    limit: int = Field(default=50, le=200)


class ValidateQueryArgs(BaseModel):
    """Проверка синтаксиса запроса пробным выполнением (ПЕРВЫЕ 1)."""

    query: str = Field(min_length=1)
    parameters: dict[str, object] | None = Field(
        default=None, description="Параметры & для проверки, как в execute_query"
    )


class MetadataListArgs(BaseModel):
    """Список объектов метаданных (разведка перед execute_select)."""

    metaType: str | None = Field(default=None, description="Catalogs, Documents, Registers... (см. tools/list)")
    nameMask: str | None = Field(default=None, description="Подстрока имени/синонима")
    maxItems: int = Field(default=50, le=200)


class MetadataStructureArgs(BaseModel):
    """Структура объекта: поля, измерения, ресурсы, реквизиты."""

    metaType: str | None = None
    name: str | None = None


# --- Расширения из feenlace/mcp-1c (MIT) — адаптированы под наш CFE ---


class GetMetadataTreeArgs(BaseModel):
    """Дерево метаданных: типы объектов и подсистемы."""

    subsystem: str | None = Field(default=None, description="Фильтр по имени подсистемы")
    typeFilter: str | None = Field(default=None, description="Фильтр по типу: Catalogs, Documents...")


class GetObjectStructureArgs(BaseModel):
    """Структура одного объекта (синоним get_metadata_structure, имя как в дереве)."""

    name: str = Field(
        min_length=1, description="Имя объекта, например Справочник.Контрагенты или Catalog.Counterparties"
    )
    objectType: str | None = Field(default=None, description="Тип для уточнения, напр. Catalog, Document, Subsystem")


class ExecuteQueryArgs(BaseModel):
    """Запрос 1С с параметрами (&p), только ВЫБРАТЬ/SELECT."""

    query: str = Field(min_length=1)
    parameters: dict[str, object] | None = Field(
        default=None, description='Значения &параметров, например {"q": "строка"}'
    )
    limit: int = Field(default=50, le=200)


class GetEventLogArgs(BaseModel):
    """Чтение журнала регистрации (только чтение, фильтр и кап)."""

    dateFrom: str | None = Field(default=None, description="ISO-дата начала, напр. 2026-09-22T00:00:00")
    dateTo: str | None = Field(default=None, description="ISO-дата конца")
    level: str | None = Field(default=None, description="Уровень: Information, Warning, Error...")
    user: str | None = Field(default=None, description="Подстрока имени пользователя")
    event: str | None = Field(default=None, description="Подстрока имени события")
    limit: int = Field(default=50, le=200)


# --- OneBridge (MIT): навигация и права ---


class GetObjectByLinkArgs(BaseModel):
    """Получить объект по навигационной ссылке (OneBridge/MIT)."""

    link: str = Field(min_length=1, description="Навигационная ссылка в формате 1С")


class GetLinkOfObjectArgs(BaseModel):
    """Получить навигационную ссылку объекта по его ссылке (OneBridge/MIT)."""

    ref: str = Field(min_length=1, description="Ссылка на объект (Guid/Идентификатор)")


class FindReferencesToObjectArgs(BaseModel):
    """Найти все ссылки на объект в базе (OneBridge/MIT)."""

    ref: str = Field(min_length=1, description="Ссылка на объект")
    limit: int = Field(default=50, le=200)


class GetAccessRightsArgs(BaseModel):
    """Права доступа к объектам метаданных (OneBridge/MIT)."""

    objectName: str | None = Field(default=None, description="Имя объекта метаданных (необязательно)")
    userName: str | None = Field(default=None, description="Имя пользователя/роли (необязательно)")
