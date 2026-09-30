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


def test_registry_live_no_initiative_to_1c(monkeypatch: pytest.MonkeyPatch) -> None:
    """live-режим: реестр без обращения к 1С (прокси не поднят по умолчанию).

    Тулзы базы появляются только через build_registry_for_root(base_url) —
    при явном запросе из 1С с адресом публикации.
    """
    from app.onec.client import McpOnecClient

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("обращение к 1С без явного запроса недопустимо")

    monkeypatch.setattr(settings, "onec_mode", "live")
    monkeypatch.setattr(McpOnecClient, "list_tools", boom)
    reg = asyncio.run(get_registry())
    assert "search_knowledge_base" in reg.names
    assert "check_extension_freshness" in reg.names
    assert "execute_select" not in reg.names  # тулзы базы — только с base_url


def test_registry_base_url_merges_dynamic_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """Динамические тулзы базы (a1c_Инструмент*) попадают в реестр по base_url —
    только при явном запросе с адресом публикации, без прокси."""

    from app.api.chat import build_registry_for_base_url
    from app.onec.client import FakeOnecClient

    fake = FakeOnecClient(
        [
            {
                "name": "a1c_my_new_tool",
                "description": "Новый тул из 1С",
                "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
            },
            {"name": "get_stock_balance", "description": "dup", "inputSchema": {"type": "object", "properties": {}}},
        ]
    )
    reg = asyncio.run(build_registry_for_base_url("http://h/base", client=fake))
    assert "a1c_my_new_tool" in reg.names
    schema = next(s for s in reg.schemas() if s["function"]["name"] == "a1c_my_new_tool")
    assert schema["function"]["parameters"]["properties"]["q"]["type"] == "string"
    assert reg.names.count("get_stock_balance") == 1  # дубликат из базы не клонируется


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
