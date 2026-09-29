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

    # BSL ядра (mcp_ИнструментДанныеОКонфигурации.СписокМетаданных) читает
    # Аргументы.metaType БЕЗ проверки .Свойство() + бэкенд не шлёт None:
    # опущенный параметр = «Поле объекта не обнаружено (metaType)» в 1С.
    # Поэтому required здесь, а не optional — правило для всех курируемых схем.
    metaType: str = Field(
        description=(
            "ОБЯЗАТЕЛЬНО. Тип коллекции метаданных, строго одно из: Catalogs, Documents, "
            "InformationRegisters, AccumulationRegisters, AccountingRegisters, CalculationRegisters, "
            "ChartsOfCharacteristicTypes, ChartsOfAccounts, ChartsOfCalculationTypes, BusinessProcesses, "
            "Tasks, ExchangePlans, FilterCriteria, Reports, DataProcessors, Enums, CommonModules, "
            "SessionParameters, CommonTemplates, CommonPictures, XDTOPackages, WebServices, HTTPServices, "
            "WSReferences, Styles, Languages, FunctionalOptions, FunctionalOptionsParameters, DefinedTypes, "
            "CommonAttributes, CommonCommands, CommandGroups, Constants, CommonForms, Roles, Subsystems, "
            "EventSubscriptions, ScheduledJobs, SettingsStorages, Sequences, DocumentJournals, "
            "ExternalDataSources, Interfaces. Голого Registers нет — только полные имена. "
            "Тип сначала уточни через get_metadata_tree."
        )
    )
    nameMask: str | None = Field(default=None, description="Подстрока имени/синонима")
    maxItems: int = Field(default=50, le=200)


class MetadataStructureArgs(BaseModel):
    """Структура объекта: поля, измерения, ресурсы, реквизиты."""

    # BSL ядра (СтруктураОбъектаМетаданных) читает metaType и name безусловно —
    # см. комментарий у MetadataListArgs: оба required.
    metaType: str = Field(
        description=(
            "ОБЯЗАТЕЛЬНО. Тип коллекции, строго одно из: Catalogs, Documents, InformationRegisters, "
            "AccumulationRegisters, AccountingRegisters, CalculationRegisters, Reports, DataProcessors, "
            "ChartsOfCharacteristicTypes, ChartsOfAccounts, ChartsOfCalculationTypes, BusinessProcesses, "
            "Tasks, ExchangePlans, Enums."
        )
    )
    name: str = Field(
        min_length=1,
        description="ОБЯЗАТЕЛЬНО. Точное имя объекта (без учёта регистра), напр. ДоговорыКонтрагентов. "
        "Пару metaType+name сначала уточни через list_metadata_objects или get_metadata_tree.",
    )


# --- Расширения из feenlace/mcp-1c (MIT) — адаптированы под наш CFE ---


class GetMetadataTreeArgs(BaseModel):
    """Дерево метаданных: типы объектов и подсистемы."""

    subsystem: str | None = Field(default=None, description="Фильтр по имени подсистемы")
    typeFilter: str | None = Field(default=None, description="Фильтр по типу: Catalogs, Documents...")


class GetConfigurationInfoArgs(BaseModel):
    """Информация о конфигурации (без параметров)."""


class GetObjectStructureArgs(BaseModel):
    """Структура одного объекта (синоним get_metadata_structure, имя как в дереве)."""

    name: str = Field(
        min_length=1, description="Имя объекта: короткое (ДоговорыКонтрагентов) или dotted (Справочник...)"
    )
    # Наш BSL ищет по имени по 4 коллекциям; objectType — только подсказка,
    # строгий формат не требуется. Не выдумывай: Catalogs, Documents,
    # InformationRegisters, AccumulationRegisters.
    objectType: str | None = Field(default=None, description="Необязательное уточнение типа: Catalogs, Documents...")


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
