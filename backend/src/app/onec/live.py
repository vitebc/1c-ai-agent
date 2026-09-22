"""Live-адаптер: те же 3 инструмента, но обработчики ходят в 1С через OnecClient.

Схемы аргументов — общие (app.onec.schemas), имена — как у моков: замена
MOCK_ONEC_TOOLS на build_onec_tools(client) прозрачна для модели.
Форматы ответов повторяют мок-совместимые JSON (found/rows/hint).
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.agent.tools import ToolContext, ToolDefinition
from app.onec.client import OnecClient
from app.onec.schemas import (
    CounterpartyArgs,
    ExecuteSelectArgs,
    MetadataListArgs,
    MetadataStructureArgs,
    SkdReportArgs,
    StockArgs,
    ValidateQueryArgs,
)


def _dump(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _as_list(result: Any, tool: str) -> list[Any]:
    if isinstance(result, list):
        return result
    raise ValueError(f"Инструмент '{tool}' вернул не массив: {str(result)[:200]}")


async def _stock(client: OnecClient, args: StockArgs, ctx: ToolContext) -> str:  # noqa: ARG001
    rows = _as_list(await client.call_tool("get_stock_balance", args.model_dump()), "get_stock_balance")
    if not rows:
        return _dump({"found": False, "hint": "Номенклатура/склад не найдены, уточните название у пользователя."})
    groups: dict[str, dict[str, Any]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        sku = str(r.get("sku", "?"))
        groups.setdefault(sku, {})[str(r.get("warehouse", "?"))] = r.get("qty")
    if not groups:
        return _dump({"found": False, "hint": "Неожиданный формат ответа 1С."})
    if len(groups) == 1:
        sku = next(iter(groups))
        return _dump({"found": True, "sku": sku, "balances": groups[sku]})
    return _dump({"found": True, "matches": [{"sku": s, "balances": groups[s]} for s in groups]})


async def _counterparty(client: OnecClient, args: CounterpartyArgs, ctx: ToolContext) -> str:  # noqa: ARG001
    rows = _as_list(await client.call_tool("get_counterparty", args.model_dump()), "get_counterparty")
    if not rows:
        return _dump({"found": False, "hint": "Контрагент не найден, уточните название или ИНН у пользователя."})
    if len(rows) == 1 and isinstance(rows[0], dict):
        return _dump({"found": True, **rows[0]})
    return _dump({"found": True, "matches": rows, "hint": "Несколько совпадений — уточните запрос."})


async def _report(client: OnecClient, args: SkdReportArgs, ctx: ToolContext) -> str:  # noqa: ARG001
    rows = _as_list(await client.call_tool("run_skd_report", args.model_dump()), "run_skd_report")
    return _dump({"report": args.report, "period": args.period, "rows": rows})


async def _select(client: OnecClient, args: ExecuteSelectArgs, ctx: ToolContext) -> str:  # noqa: ARG001
    # 1С возвращает структуру {rows, truncated} — отдаём как есть.
    return _dump(await client.call_tool("execute_select", args.model_dump()))


async def _validate(client: OnecClient, args: ValidateQueryArgs, ctx: ToolContext) -> str:  # noqa: ARG001
    result = await client.call_tool("validate_query", args.model_dump())
    return result if isinstance(result, str) else _dump(result)


async def _meta(client: OnecClient, tool_name: str, args: MetadataListArgs | MetadataStructureArgs) -> str:
    # Passthrough к одноимённым инструментам ядра 1c_mcp; None не шлём.
    payload = {k: v for k, v in args.model_dump().items() if v is not None}
    result = await client.call_tool(tool_name, payload)
    return result if isinstance(result, str) else _dump(result)


class _GenericArgs(BaseModel):
    """Приёмник любых аргументов динамического MCP-тулза (схему даёт прокси)."""

    model_config = ConfigDict(extra="allow")


def _make_generic_tool(
    client: OnecClient, name: str, description: str, input_schema: dict[str, Any] | None
) -> ToolDefinition:
    schema = input_schema if isinstance(input_schema, dict) and input_schema else {"type": "object", "properties": {}}

    async def handler(args: Any, ctx: ToolContext) -> str:  # noqa: ARG001
        payload = args.model_dump() if hasattr(args, "model_dump") else {}
        result = await client.call_tool(name, payload)
        return result if isinstance(result, str) else _dump(result)

    return ToolDefinition(
        name=name,
        description=description or f"MCP-тул {name} из 1С (динамический).",
        args_model=_GenericArgs,
        handler=handler,
        parameters_schema=schema,
    )


def build_onec_tools(client: OnecClient) -> list[ToolDefinition]:
    async def stock_handler(args: Any, ctx: ToolContext) -> str:
        return await _stock(client, args, ctx)

    async def counterparty_handler(args: Any, ctx: ToolContext) -> str:
        return await _counterparty(client, args, ctx)

    async def report_handler(args: Any, ctx: ToolContext) -> str:
        return await _report(client, args, ctx)

    async def select_handler(args: Any, ctx: ToolContext) -> str:
        return await _select(client, args, ctx)

    async def validate_handler(args: Any, ctx: ToolContext) -> str:
        return await _validate(client, args, ctx)

    async def meta_list_handler(args: Any, ctx: ToolContext) -> str:  # noqa: ARG001
        return await _meta(client, "list_metadata_objects", args)

    async def meta_structure_handler(args: Any, ctx: ToolContext) -> str:  # noqa: ARG001
        return await _meta(client, "get_metadata_structure", args)

    return [
        ToolDefinition(
            name="get_stock_balance",
            description="Остатки номенклатуры по складам (регистр накопления ТоварыНаСкладах, КА2). Только чтение.",
            args_model=StockArgs,
            handler=stock_handler,
        ),
        ToolDefinition(
            name="get_counterparty",
            description="Карточка контрагента КА2: наименование, ИНН, партнёр, задолженность. Только чтение.",
            args_model=CounterpartyArgs,
            handler=counterparty_handler,
        ),
        ToolDefinition(
            name="run_skd_report",
            description="Отчёт по готовому макету КА2: sales_by_warehouse (продажи по складам) "
            "или debtors (дебиторская задолженность). Период форматом ГГГГ-Q[1-4]/H[1-2]/Y.",
            args_model=SkdReportArgs,
            handler=report_handler,
        ),
        ToolDefinition(
            name="execute_select",
            description=(
                "Универсальный SELECT по данным 1С (Документы, Справочники, Регистры). "
                "ТОЛЬКО ВЫБРАТЬ/SELECT, кап 200. Параметры (&q) НЕ поддерживаются — только литералы. "
                "Сначала сверь имена через "
                "list_metadata_objects/get_metadata_structure. Пример: "
                "'ВЫБРАТЬ Номер, Дата ИЗ Документ.ЗаказКлиента ГДЕ Партнер.Наименование ПОДОБНО \"%Прокудин%\"'"
            ),
            args_model=ExecuteSelectArgs,
            handler=select_handler,
        ),
        ToolDefinition(
            name="validate_query",
            description="Проверка синтаксиса запроса пробным выполнением (ПЕРВЫЕ 1). Возвращает вердикт строкой.",
            args_model=ValidateQueryArgs,
            handler=validate_handler,
        ),
        ToolDefinition(
            name="list_metadata_objects",
            description=(
                "Разведка: список объектов метаданных 1С. Вызывай ПЕРЕД execute_select, "
                "чтобы узнать точные имена справочников/документов/регистров."
            ),
            args_model=MetadataListArgs,
            handler=meta_list_handler,
        ),
        ToolDefinition(
            name="get_metadata_structure",
            description=(
                "Разведка: поля/измерения/ресурсы объекта метаданных. Вызывай ПЕРЕД execute_select, "
                "чтобы запрос не упал на неверном имени поля."
            ),
            args_model=MetadataStructureArgs,
            handler=meta_structure_handler,
        ),
    ]
