"""Тесты прямого JSON-RPC клиента 1С и per-base реестра (без сети)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent import ToolRegistry
from app.api.chat import build_registry_for_base_url, get_llm, get_registry
from app.llm import AssistantMessage
from app.main import app
from app.onec.client import FakeOnecClient, OnecError
from app.onec.direct import JsonRpcOnecClient, validate_base_url
from app.tools import MOCK_ONEC_TOOLS
from tests.fake_llm import FakeLLM
from tests.test_chat_api import TEST_USER, _cleanup

BASE = "http://192.168.0.178/ca2_td_update"


def test_validate_base_url_ok() -> None:
    assert validate_base_url("http://192.168.0.178/ca2_td_update") == "http://192.168.0.178/ca2_td_update"
    assert validate_base_url("http://HOST:8080/base/") == "http://host:8080/base"
    assert validate_base_url("  http://h/b  ") == "http://h/b"


@pytest.mark.parametrize(
    "raw",
    [None, "", "   ", "ftp://h/b", "http://user:pass@h/b", "http:///nonhost", "http://"],
)
def test_validate_base_url_rejects(raw: str | None) -> None:
    with pytest.raises(ValueError):
        validate_base_url(raw)


def _transport(payloads: dict[str, dict[str, Any]]) -> httpx.MockTransport:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content.decode("utf-8"))
        assert body["jsonrpc"] == "2.0"
        assert request.url.path == "/ca2_td_update/hs/mcp/rpc"
        return httpx.Response(200, json=payloads[body["method"]])

    transport = httpx.MockTransport(handler)
    transport.seen = seen  # type: ignore[attr-defined]
    return transport


def _client(payloads: dict[str, dict[str, Any]]) -> tuple[JsonRpcOnecClient, httpx.MockTransport]:
    transport = _transport(payloads)
    client = JsonRpcOnecClient(BASE, username="agent", password="agent007", transport=transport)
    assert client.url == f"{BASE}/hs/mcp/rpc"
    return client, transport


def test_list_tools() -> None:
    client, _ = _client(
        {"tools/list": {"result": {"tools": [{"name": "get_stock_balance", "description": "d", "inputSchema": {}}]}}}
    )
    tools = asyncio.run(client.list_tools())
    assert tools == [{"name": "get_stock_balance", "description": "d", "inputSchema": {}}]


def test_call_tool_json_and_text() -> None:
    client, transport = _client(
        {
            "tools/call": {
                "result": {
                    "content": [{"type": "text", "text": '{"rows": []}'}],
                    "isError": False,
                }
            }
        }
    )
    out = asyncio.run(client.call_tool("execute_select", {"query": "ВЫБРАТЬ 1"}))
    assert out == {"rows": []}
    req = transport.seen[0]  # type: ignore[attr-defined]
    assert req.headers["authorization"].startswith("Basic ")


def test_call_tool_error_envelope() -> None:
    client, _ = _client(
        {"tools/call": {"result": {"content": [{"type": "text", "text": "Ошибка запроса"}], "isError": True}}}
    )
    with pytest.raises(OnecError, match="Ошибка запроса"):
        asyncio.run(client.call_tool("execute_select", {"query": "X"}))


def test_call_tool_jsonrpc_error() -> None:
    err = {"error": {"code": -32603, "message": "внутренняя"}}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=err))
    client = JsonRpcOnecClient(BASE, transport=transport)
    with pytest.raises(OnecError, match="-32603"):
        asyncio.run(client.call_tool("x", {}))


def test_call_tool_http_error() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(500, text="boom"))
    client = JsonRpcOnecClient(BASE, transport=transport)
    with pytest.raises(OnecError, match="HTTP ошибка"):
        asyncio.run(client.list_tools())


def test_build_registry_for_base_url() -> None:
    fake = FakeOnecClient(
        tools=[{"name": "get_stock_balance", "description": "d", "inputSchema": {}}],
        calls={"get_stock_balance": [{"sku": "стул"}]},
    )
    reg = asyncio.run(build_registry_for_base_url(BASE, client=fake))
    assert "get_stock_balance" in reg.names
    assert "search_knowledge_base" in reg.names  # локальные тулзы всегда на месте


def test_build_registry_bad_url() -> None:
    with pytest.raises(ValueError):
        asyncio.run(build_registry_for_base_url("ftp://h/b"))


def test_chat_bad_base_url_400() -> None:
    fake = FakeLLM([AssistantMessage(content="ok")])
    app.dependency_overrides[get_llm] = lambda: fake
    app.dependency_overrides[get_registry] = lambda: ToolRegistry(MOCK_ONEC_TOOLS)
    try:
        with TestClient(app) as client:
            r = client.post(
                "/chat",
                json={"message": "привет", "user_id": TEST_USER, "base_url": "ftp://h/b"},
            )
            assert r.status_code == 400, r.text
    finally:
        _cleanup()


def test_parse_bases_map_ok() -> None:
    from app.onec.direct import parse_bases_map

    assert parse_bases_map("") == {}
    assert parse_bases_map("  ; ") == {}
    assert parse_bases_map("ca2_td_update=http://192.168.0.178/ca2_td_update;ERP=http://h:8080/erp/") == {
        "ca2_td_update": "http://192.168.0.178/ca2_td_update",
        "erp": "http://h:8080/erp",
    }


def test_parse_bases_map_rejects() -> None:
    import pytest

    from app.onec.direct import parse_bases_map

    for raw in ("noequals", "=http://h/b", "a=http://h/1;a=http://h/2", "a=ftp://h/b", "a=http://"):
        with pytest.raises(ValueError):
            parse_bases_map(raw)


def test_config_rejects_bad_map() -> None:
    import pytest

    from app.config import Settings

    with pytest.raises(ValueError, match="ONEC_BASES"):
        Settings(onec_bases="a=http://h/1;a=http://h/2")


def test_resolve_base_root_order(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.chat import resolve_base_root
    from app.onec import bases as bases_mod

    # Мапа теперь hot (app.onec.bases): переопределяем get_bases_map напрямую.
    monkeypatch.setattr(
        bases_mod, "get_bases_map", lambda: {"ca2": "http://192.168.0.178:8080/ca2"}
    )
    # Мапа побеждает присланный адрес.
    assert resolve_base_root("ca2", "http://other/h") == "http://192.168.0.178:8080/ca2"
    assert resolve_base_root("CA2", None) == "http://192.168.0.178:8080/ca2"
    # Вне мапы — валидный присланный адрес.
    assert resolve_base_root("other", "http://h/b/") == "http://h/b"
    # Пусто — штатный путь (None).
    assert resolve_base_root(None, None) is None
    assert resolve_base_root("", "  ") is None
    # Имя есть, адреса нигде нет — громкая ошибка с эхом.
    with pytest.raises(ValueError, match="file_base"):
        resolve_base_root("file_base", None)
    try:
        resolve_base_root("file_base", "  ")
    except ValueError as e:
        assert "file_base" in str(e) and "проверьте адрес публикации" in str(e)
    else:
        raise AssertionError("жди ValueError")
    # Мусор в адресе — ValueError.
    with pytest.raises(ValueError):
        resolve_base_root("x", "ftp://h/b")


def test_chat_unresolvable_base_400_no_session(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from sqlalchemy import func, select

    from app.db.models import ChatSession
    from app.db.session import SessionFactory, engine
    from app.onec import bases as bases_mod

    monkeypatch.setattr(bases_mod, "get_bases_map", lambda: {})
    fake = FakeLLM([AssistantMessage(content="ok")])
    app.dependency_overrides[get_llm] = lambda: fake
    app.dependency_overrides[get_registry] = lambda: ToolRegistry(MOCK_ONEC_TOOLS)

    async def count_sessions() -> int:
        await engine.dispose()
        async with SessionFactory() as s:
            res = await s.execute(select(func.count()).select_from(ChatSession))
            return int(res.scalar() or 0)

    try:
        with TestClient(app) as client:
            before = asyncio.run(count_sessions())
            r = client.post(
                "/chat",
                json={"message": "привет", "user_id": TEST_USER, "base_name": "file_base"},
            )
            assert r.status_code == 400, r.text
            assert "file_base" in r.text and "адрес публикации" in r.text
            assert asyncio.run(count_sessions()) == before  # сессия не заведена
    finally:
        _cleanup()


def test_tools_by_base_name_uses_map(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.onec import bases as bases_mod

    monkeypatch.setattr(
        bases_mod, "get_bases_map", lambda: {"ca2": "http://127.0.0.1:9/ca2"}
    )  # закрытый порт: быстрый refused
    fake = FakeLLM([AssistantMessage(content="ok")])
    app.dependency_overrides[get_llm] = lambda: fake
    app.dependency_overrides[get_registry] = lambda: ToolRegistry(MOCK_ONEC_TOOLS)
    try:
        with TestClient(app) as client:
            r = client.get("/tools", params={"base_name": "ca2"})
            # База недоступна из тестовой сети — реестр из статического набора, но без 400.
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["base_url"] == "http://127.0.0.1:9/ca2"
            assert "get_stock_balance" in [t["name"] for t in body["tools"]]
            r2 = client.get("/tools", params={"base_name": "nope", "base_url": ""})
            assert r2.status_code == 400, r2.text
    finally:
        _cleanup()
