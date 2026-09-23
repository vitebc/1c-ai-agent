"""Мок-инструменты 1С для шага 1 (смоук agent loop без живой базы).

На шаге 3 обработчики заменяются вызовами tools/call к MCP-прокси; pydantic-схемы
аргументов и имена инструментов сохраняются — модель этого не заметит.
"""

from __future__ import annotations

import json
from typing import Any, TypedDict

from app.agent.tools import ToolContext, ToolDefinition
from app.onec.schemas import (
    CounterpartyArgs,
    ExecuteQueryArgs,
    GetEventLogArgs,
    GetMetadataTreeArgs,
    GetObjectStructureArgs,
    SkdReportArgs,
    StockArgs,
    ValidateQueryArgs,
)

# --- Тестовые данные -----------------------------------------------------------


class Counterparty(TypedDict):
    name: str
    full: str
    inn: str
    debt: int


class SalesRow(TypedDict):
    sku: str
    warehouse: str
    qty: int
    sum: int


_COUNTERPARTIES: list[Counterparty] = [
    {"name": "Ромашка", "full": 'ООО "Ромашка"', "inn": "7701234567", "debt": 125000},
    {"name": "Василёк", "full": "ИП Василёк", "inn": "7707654321", "debt": 0},
    {"name": "Теремок", "full": 'ООО "Теремок"', "inn": "7712345678", "debt": 48250},
]

_STOCK: dict[str, dict[str, int]] = {
    "стул офисный": {"Основной": 42, "Розничный": 7},
    "стол письменный": {"Основной": 15, "Розничный": 3},
    "кресло": {"Основной": 0, "Розничный": 5},
}

_SALES: list[SalesRow] = [
    {"sku": "Стул офисный", "warehouse": "Основной", "qty": 120, "sum": 840000},
    {"sku": "Стул офисный", "warehouse": "Розничный", "qty": 35, "sum": 280000},
    {"sku": "Стол письменный", "warehouse": "Основной", "qty": 40, "sum": 600000},
    {"sku": "Кресло", "warehouse": "Розничный", "qty": 22, "sum": 330000},
]

# --- Схемы аргументов — общий контракт, см. app.onec.schemas --------------------
# (SkdReportArgs, CounterpartyArgs, StockArgs импортированы выше и используются
# в MOCK_ONEC_TOOLS ниже без изменений.)


# --- Обработчики ---------------------------------------------------------------


def _dump(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)


async def run_skd_report(args: SkdReportArgs, ctx: ToolContext) -> str:  # noqa: ARG001
    rows: list[Any]
    if args.report == "sales_by_warehouse":
        rows = [r for r in _SALES if args.warehouse is None or r["warehouse"] == args.warehouse]
    else:
        rows = [{"name": c["name"], "inn": c["inn"], "debt": c["debt"]} for c in _COUNTERPARTIES if c["debt"] > 0]
    return _dump({"report": args.report, "period": args.period, "rows": rows[: args.limit]})


async def get_counterparty(args: CounterpartyArgs, ctx: ToolContext) -> str:  # noqa: ARG001
    q = args.query.strip().lower()
    for c in _COUNTERPARTIES:
        if q in c["name"].lower() or q == c["inn"]:
            return _dump({"found": True, **c})
    # Пустой результат — НЕ ошибка: модели нечего чинить, пусть отвечает «не найден».
    return _dump({"found": False, "hint": "Контрагент не найден, уточните название или ИНН у пользователя."})


async def get_stock_balance(args: StockArgs, ctx: ToolContext) -> str:  # noqa: ARG001
    q = args.sku.strip().lower()
    for sku, wh in _STOCK.items():
        if q in sku:
            if args.warehouse is not None and args.warehouse not in wh:
                return _dump({"found": False, "hint": f"Склада '{args.warehouse}' нет. Есть: {sorted(wh)}."})
            qty = wh if args.warehouse is None else {args.warehouse: wh[args.warehouse]}
            return _dump({"found": True, "sku": sku, "balances": qty})
    return _dump({"found": False, "hint": "Номенклатура не найдена, уточните название у пользователя."})


async def get_metadata_tree(args: GetMetadataTreeArgs, ctx: ToolContext) -> str:  # noqa: ARG001
    tree = [
        {"type": "Catalogs", "name": "Контрагенты", "synonym": "Контрагенты"},
        {"type": "Catalogs", "name": "Номенклатура", "synonym": "Номенклатура"},
        {"type": "Documents", "name": "ЗаказКлиента", "synonym": "Заказ клиента"},
        {"type": "Documents", "name": "РеализацияТоваровУслуг", "synonym": "Реализация"},
        {"type": "AccumulationRegisters", "name": "ТоварыНаСкладах", "synonym": "Товары на складах"},
    ]
    if args.typeFilter:
        tree = [x for x in tree if x["type"].lower() == args.typeFilter.lower()]
    if args.subsystem:
        tree = [x for x in tree if args.subsystem.lower() in x["name"].lower()]
    return _dump({"tree": tree[:20]})


async def get_object_structure(args: GetObjectStructureArgs, ctx: ToolContext) -> str:  # noqa: ARG001
    return _dump({"name": args.name, "objectType": args.objectType or "Unknown", "fields": ["Ссылка", "Наименование"]})


async def execute_query(args: ExecuteQueryArgs, ctx: ToolContext) -> str:  # noqa: ARG001
    return _dump({"rows": [], "truncated": False, "hint": f"мок execute_query: {args.query[:60]}"})


async def validate_query_mock(args: ValidateQueryArgs, ctx: ToolContext) -> str:  # noqa: ARG001
    return "OK: синтаксис корректен (мок)."


async def get_event_log(args: GetEventLogArgs, ctx: ToolContext) -> str:  # noqa: ARG001
    return _dump({"events": [], "hint": "мок-журнал пуст", "filter": args.model_dump()})


MOCK_ONEC_TOOLS = [
    ToolDefinition(
        name="run_skd_report",
        description="Отчёт СКД по готовому макету: sales_by_warehouse (продажи по складам) "
        "или debtors (дебиторская задолженность). Период форматом ГГГГ-Q[1-4]/H[1-2]/Y.",
        args_model=SkdReportArgs,
        handler=run_skd_report,
    ),
    ToolDefinition(
        name="get_counterparty",
        description="Карточка контрагента: название, ИНН, задолженность. Поиск по подстроке названия или ИНН.",
        args_model=CounterpartyArgs,
        handler=get_counterparty,
    ),
    ToolDefinition(
        name="get_stock_balance",
        description="Остатки номенклатуры по складам. Поиск товара по подстроке названия.",
        args_model=StockArgs,
        handler=get_stock_balance,
    ),
    ToolDefinition(
        name="get_metadata_tree",
        description="Дерево метаданных (feenlace/MIT): типы/объекты/подсистемы.",
        args_model=GetMetadataTreeArgs,
        handler=get_metadata_tree,
    ),
    ToolDefinition(
        name="get_object_structure",
        description="Структура объекта 1С (feenlace/MIT): реквизиты/ТЧ/измерения.",
        args_model=GetObjectStructureArgs,
        handler=get_object_structure,
    ),
    ToolDefinition(
        name="execute_query",
        description="Запрос 1С с &параметрами (feenlace/MIT): ВЫБРАТЬ с parameters.",
        args_model=ExecuteQueryArgs,
        handler=execute_query,
    ),
    ToolDefinition(
        name="validate_query",
        description="Проверка запроса 1С (feenlace: синтаксис + параметры).",
        args_model=ValidateQueryArgs,
        handler=validate_query_mock,
    ),
    ToolDefinition(
        name="get_event_log",
        description="Журнал регистрации (feenlace/MIT): фильтр дата/уровень/юзер.",
        args_model=GetEventLogArgs,
        handler=get_event_log,
    ),
]
