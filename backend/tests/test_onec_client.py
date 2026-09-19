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


def test_stock_multiple_matches_grouped() -> None:
    rows = [
        {"sku": "Стул", "warehouse": "Основной", "qty": 1},
        {"sku": "Стул детский", "warehouse": "Основной", "qty": 2},
    ]
    client = FakeOnecClient(calls={"get_stock_balance": rows})
    tools = _tools(client)
    out = _call(tools, "get_stock_balance", {"sku": "стул"})
    data = json.loads(out)
    assert data == {
        "found": True,
        "matches": [
            {"sku": "Стул", "balances": {"Основной": 1}},
            {"sku": "Стул детский", "balances": {"Основной": 2}},
        ],
    }


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


def test_universal_tools_passthrough() -> None:
    select_result = {"rows": [{"a": 1}], "truncated": False}
    client = FakeOnecClient(
        calls={
            "execute_select": select_result,
            "validate_query": "OK: синтаксис корректен.",
        }
    )
    tools = _tools(client)
    assert set(tools) >= {"execute_select", "validate_query"}
    out = _call(tools, "execute_select", {"query": "ВЫБРАТЬ 1 КАК А"})
    assert json.loads(out) == select_result
    assert _call(tools, "validate_query", {"query": "ВЫБРАТЬ 1"}) == "OK: синтаксис корректен."
    assert client.requested[0] == ("execute_select", {"query": "ВЫБРАТЬ 1 КАК А", "limit": 50})


def test_live_fixture_shapes() -> None:
    """Шейпинг на живых ответах пилота КА2 (tests/fixtures/ka2_pilot.json)."""
    from pathlib import Path

    fixture_path = Path(__file__).resolve().parent / "fixtures" / "ka2_pilot.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    tools = _tools(FakeOnecClient(calls=fixture))

    stock = json.loads(_call(tools, "get_stock_balance", {"sku": "стул"}))
    assert stock["found"] is True
    assert len(stock["matches"]) == 5  # все 5 позиций, ничего не потеряно
    assert stock["matches"][0]["balances"] == {"1.Магазин распродаж": 3}

    debtors = json.loads(_call(tools, "run_skd_report", {"report": "debtors", "period": "2026-Q1"}))
    assert debtors["period"] == "2026-Q1" and len(debtors["rows"]) == 5
    lebedev = next(r for r in debtors["rows"] if "Лебедев" in r["name"])
    assert lebedev["debt"] == 16938288.82  # float из 1С едет как есть

    empty = json.loads(_call(tools, "get_counterparty", {"query": "Ромашка"}))
    assert empty["found"] is False
