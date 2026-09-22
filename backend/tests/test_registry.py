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


def test_registry_rejects_unknown_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "onec_mode", "wat")
    with pytest.raises(ValueError, match="ONEC_MODE"):
        asyncio.run(get_registry())
