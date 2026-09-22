"""Тесты переключения реестра инструментов mock/live (без сети)."""

from __future__ import annotations

import asyncio

import pytest

from app.api.chat import get_registry
from app.config import settings


def test_registry_mock_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "onec_mode", "mock")
    reg = asyncio.run(get_registry())
    assert "search_knowledge_base" in reg.names
    assert "execute_select" not in reg.names  # в моках только 3 курируемых


def test_registry_live_builds_without_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "onec_mode", "live")
    reg = asyncio.run(get_registry())
    assert set(reg.names) >= {
        "get_stock_balance",
        "get_counterparty",
        "run_skd_report",
        "execute_select",
        "validate_query",
        "search_knowledge_base",
        "get_pattern",
    }


def test_registry_live_merges_dynamic_proxy_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """Динамические тулзы из прокси (a1c_Инструмент*) попадают в реестр без кода."""

    async def fake_list_tools(self: object) -> list[dict[str, object]]:  # noqa: ARG001
        return [
            {
                "name": "a1c_my_new_tool",
                "description": "Новый тул из 1С",
                "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
            },
            {"name": "get_stock_balance", "description": "dup", "inputSchema": {"type": "object", "properties": {}}},
        ]

    from app.onec.client import McpOnecClient

    monkeypatch.setattr(settings, "onec_mode", "live")
    monkeypatch.setattr(McpOnecClient, "list_tools", fake_list_tools)
    reg = asyncio.run(get_registry())
    assert "a1c_my_new_tool" in reg.names
    schema = next(s for s in reg.schemas() if s["function"]["name"] == "a1c_my_new_tool")
    assert schema["function"]["parameters"]["properties"]["q"]["type"] == "string"
    assert reg.names.count("get_stock_balance") == 1  # дубликат из прокси не клонируется


def test_registry_rejects_unknown_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "onec_mode", "wat")
    with pytest.raises(ValueError, match="ONEC_MODE"):
        asyncio.run(get_registry())
