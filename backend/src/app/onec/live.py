"""Live-адаптер: те же 3 инструмента, но обработчики ходят в 1С через OnecClient.

Схемы аргументов — общие (app.onec.schemas), имена — как у моков: замена
MOCK_ONEC_TOOLS на build_onec_tools(client) прозрачна для модели.
Форматы ответов повторяют мок-совместимые JSON (found/rows/hint).
"""

from __future__ import annotations

import json
from typing import Any

from app.agent.tools import ToolContext, ToolDefinition
from app.onec.client import OnecClient
from app.onec.schemas import CounterpartyArgs, SkdReportArgs, StockArgs


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
    first = rows[0]
    balances = {str(r.get("warehouse", "?")): r.get("qty") for r in rows if isinstance(r, dict)}
    payload: dict[str, Any] = {"found": True, "sku": first.get("sku"), "balances": balances}
    if len(rows) > 1:
        payload["more"] = len(rows) - 1
    return _dump(payload)


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


def build_onec_tools(client: OnecClient) -> list[ToolDefinition]:
    async def stock_handler(args: Any, ctx: ToolContext) -> str:
        return await _stock(client, args, ctx)

    async def counterparty_handler(args: Any, ctx: ToolContext) -> str:
        return await _counterparty(client, args, ctx)

    async def report_handler(args: Any, ctx: ToolContext) -> str:
        return await _report(client, args, ctx)

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
    ]
