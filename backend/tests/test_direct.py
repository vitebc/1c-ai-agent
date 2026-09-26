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
