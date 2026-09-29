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


def test_metadata_list_schema_requires_metatype() -> None:
    """BSL ядра читает Аргументы.metaType безусловно + бэкенд не шлёт None:
    опущенный metaType = «Поле объекта не обнаружено (metaType)» в 1С (живой лог).
    Поэтому required в схеме, а не optional."""
    from pydantic import ValidationError

    from app.onec.schemas import MetadataListArgs

    assert "metaType" in MetadataListArgs.model_json_schema()["required"]
    with pytest.raises(ValidationError):
        MetadataListArgs.model_validate({})  # без параметра — отказ до 1С
    args = MetadataListArgs(metaType="Documents", nameMask="Договор")
    assert args.metaType == "Documents"
    desc = MetadataListArgs.model_fields["metaType"].description or ""
    assert "InformationRegisters" in desc and "Registers" in desc  # явный список + антиподсказка про голое Registers


def test_metadata_structure_schema_requires_both() -> None:
    """СтруктураОбъектаМетаданных читает metaType и name безусловно — оба required."""
    from pydantic import ValidationError

    from app.onec.schemas import MetadataStructureArgs

    required = MetadataStructureArgs.model_json_schema()["required"]
    assert "metaType" in required and "name" in required
    with pytest.raises(ValidationError):
        MetadataStructureArgs.model_validate({"metaType": "Catalogs"})  # нет name — отказ до 1С
    ok = MetadataStructureArgs(metaType="Catalogs", name="ДоговорыКонтрагентов")
    assert ok.name == "ДоговорыКонтрагентов"


def test_object_structure_objecttype_hint() -> None:
    """objectType — только подсказка (наш BSL ищет по имени); в описании реальные имена коллекций."""
    from app.onec.schemas import GetObjectStructureArgs

    desc = GetObjectStructureArgs.model_fields["objectType"].description or ""
    assert "Catalogs" in desc and "Subsystem" not in desc
