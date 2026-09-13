"""Тесты MCP-клиента и live-адаптера — только FakeOnecClient, без сети."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from typing import Any, TypeVar

import pytest

from app.agent import ToolContext, ToolDefinition
from app.onec import FakeOnecClient, OnecError, build_onec_tools

T = TypeVar("T")


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _tools(client: FakeOnecClient) -> dict[str, Any]:
    return {t.name: t for t in build_onec_tools(client)}


def _call(tools: dict[str, ToolDefinition], name: str, args_dict: dict[str, Any]) -> str:
    """Как петля: сначала валидация схемой инструмента, потом обработчик."""
    tool = tools[name]
    return _run(tool.handler(tool.args_model(**args_dict), ToolContext(user_id="u")))


def test_stock_shapes_single_and_empty() -> None:
    client = FakeOnecClient(calls={"get_stock_balance": [{"sku": "Стул", "warehouse": "Основной", "qty": 42}]})
    tools = _tools(client)
    out = _call(tools, "get_stock_balance", {"sku": "стул"})
    data = json.loads(out)
    assert data == {"found": True, "sku": "Стул", "balances": {"Основной": 42}}

    client2 = FakeOnecClient(calls={"get_stock_balance": []})
    tools2 = _tools(client2)
    out2 = _call(tools2, "get_stock_balance", {"sku": "диван"})
    assert json.loads(out2)["found"] is False


def test_stock_multiple_matches_flagged() -> None:
    rows = [
        {"sku": "Стул", "warehouse": "Основной", "qty": 1},
        {"sku": "Стул детский", "warehouse": "Основной", "qty": 2},
    ]
    client = FakeOnecClient(calls={"get_stock_balance": rows})
    tools = _tools(client)
    out = _call(tools, "get_stock_balance", {"sku": "стул"})
    data = json.loads(out)
    assert data["found"] is True and data["more"] == 1


def test_counterparty_single_multi_empty() -> None:
    card = {"name": "Ромашка", "full": "ООО", "inn": "7701234567", "debt": 0}
    single = _tools(FakeOnecClient(calls={"get_counterparty": [card]}))
    assert json.loads(_call(single, "get_counterparty", {"query": "ромашка"})) == {
        "found": True,
        **card,
    }

    multi = _tools(FakeOnecClient(calls={"get_counterparty": [card, card]}))
    data = json.loads(_call(multi, "get_counterparty", {"query": "машка"}))
    assert data["found"] is True and len(data["matches"]) == 2

    empty = _tools(FakeOnecClient(calls={"get_counterparty": []}))
    out = _call(empty, "get_counterparty", {"query": "нет"})
    assert json.loads(out)["found"] is False


def test_report_echoes_params() -> None:
    rows = [{"name": "Ромашка", "inn": "1", "debt": 5}]
    client = FakeOnecClient(calls={"run_skd_report": rows})
    tools = _tools(client)
    args = {"report": "debtors", "period": "2026-Q1"}
    out = _call(tools, "run_skd_report", args)
    assert json.loads(out) == {"report": "debtors", "period": "2026-Q1", "rows": rows}
    # model_dump отдаёт полные аргументы с дефолтами — сервер их и получает.
    assert client.requested == [
        ("run_skd_report", {"report": "debtors", "period": "2026-Q1", "warehouse": None, "limit": 20})
    ]


def test_transport_error_propagates() -> None:
    client = FakeOnecClient(calls={"get_stock_balance": OnecError("обрыв")})
    tools = _tools(client)
    with pytest.raises(OnecError):
        _call(tools, "get_stock_balance", {"sku": "стул"})


def test_non_list_result_rejected() -> None:
    client = FakeOnecClient(calls={"run_skd_report": {"oops": 1}})
    tools = _tools(client)
    with pytest.raises(ValueError, match="не массив"):
        _call(tools, "run_skd_report", {"report": "debtors", "period": "2026-Q1"})
