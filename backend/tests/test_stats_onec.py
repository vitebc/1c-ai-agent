"""Тесты дашборда GET /stats/onec — опрос MCP_ONEC_URL (публикация 1С прокси)."""

from __future__ import annotations

import asyncio

import pytest

from app.config import settings


def _run() -> dict[str, object]:
    """Эндпоинт без TestClient: он чисто async, БД не трогает."""
    from app.api.stats import onec_status

    return asyncio.run(onec_status())


def test_onec_dashboard_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустой MCP_ONEC_URL — источник не задан, сеть не трогаем."""
    from app.api import stats

    async def boom(*a: object, **k: object) -> tuple[int, str]:
        raise AssertionError("сеть не должна трогаться при пустом MCP_ONEC_URL")

    monkeypatch.setattr(settings, "mcp_onec_url", "")
    monkeypatch.setattr(stats, "_probe_onec", boom)
    body = _run()

    assert body["configured"] is False
    assert body["ok"] is False
    assert body["url"] == ""
    assert body["tools"] is None
    assert body["elapsed_ms"] == 0
    assert body["error"] == "MCP_ONEC_URL не задан"


def test_onec_dashboard_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Успешный tools/list: ok=True и число инструментов."""
    from app.api import stats

    seen: dict[str, object] = {}

    async def fake(url: str, username: str, password: str | None) -> tuple[int, str]:
        seen.update(url=url, user=username)
        return 200, '{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"a"},{"name":"b"}]}}'

    monkeypatch.setattr(settings, "mcp_onec_url", "http://h/base/")  # хвостовой слэш режется
    monkeypatch.setattr(settings, "onec_username", "agent")
    monkeypatch.setattr(stats, "_probe_onec", fake)
    body = _run()

    assert seen["url"] == "http://h/base"  # нормализован
    assert seen["user"] == "agent"
    assert body["url"] == "http://h/base"
    assert body["configured"] is True
    assert body["ok"] is True
    assert body["tools"] == 2
    assert body["error"] is None
    assert isinstance(body["elapsed_ms"], int)


def test_onec_dashboard_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Не-200 отдаём кодом: дашборд показывает проблему, а не падает."""
    from app.api import stats

    async def fake(url: str, username: str, password: str | None) -> tuple[int, str]:
        return 401, ""

    monkeypatch.setattr(settings, "mcp_onec_url", "http://h/base")
    monkeypatch.setattr(stats, "_probe_onec", fake)
    body = _run()

    assert body["ok"] is False
    assert body["tools"] is None
    assert body["error"] == "HTTP 401"


def test_onec_dashboard_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сетевая ошибка не роняет эндпоинт — текст ошибки в ответе."""
    from app.api import stats

    async def fake(url: str, username: str, password: str | None) -> tuple[int, str]:
        raise ConnectionError("All connection attempts failed")

    monkeypatch.setattr(settings, "mcp_onec_url", "http://h/base")
    monkeypatch.setattr(stats, "_probe_onec", fake)
    body = _run()

    assert body["ok"] is False
    assert body["tools"] is None
    assert "All connection attempts failed" in str(body["error"])


def test_onec_dashboard_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """200 с не-JSON телом (прокси/прокси-сервер отдал HTML) — ошибка, не 500."""
    from app.api import stats

    async def fake(url: str, username: str, password: str | None) -> tuple[int, str]:
        return 200, "<html>oops</html>"

    monkeypatch.setattr(settings, "mcp_onec_url", "http://h/base")
    monkeypatch.setattr(stats, "_probe_onec", fake)
    body = _run()

    assert body["ok"] is False
    assert body["error"]
