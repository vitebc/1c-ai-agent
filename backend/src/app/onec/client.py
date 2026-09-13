"""MCP-клиент к прокси 1С (Streamable HTTP).

Петля зависит только от протокола OnecClient — в тестах FakeOnecClient,
в проде McpOnecClient поверх `mcp` SDK (тот же пин, что у прокси апстрима).
"""

from __future__ import annotations

from typing import Any, Protocol

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class OnecError(Exception):
    """Транспортная/протокольная ошибка вызова инструмента 1С."""


class OnecClient(Protocol):
    async def list_tools(self) -> list[dict[str, Any]]:
        """Инструменты прокси: [{name, description, inputSchema}]."""
        ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Вызов tools/call. Возвращает JSON-совместимый результат 1С."""
        ...


class McpOnecClient:
    """Клиент MCP Streamable HTTP. Сессия на каждый вызов (stateless)."""

    def __init__(self, mcp_url: str, token: str | None = None, timeout: float = 120.0) -> None:
        self._url = mcp_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    async def list_tools(self) -> list[dict[str, Any]]:
        async with streamablehttp_client(self._url, headers=self._headers()) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
        return [{"name": t.name, "description": t.description, "inputSchema": t.inputSchema} for t in result.tools]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        async with streamablehttp_client(self._url, headers=self._headers()) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
        if result.isError:
            raise OnecError(_content_text(result))
        return _parse_content(result)

    @property
    def url(self) -> str:
        return self._url


def _content_text(result: Any) -> str:
    parts = [getattr(block, "text", "") for block in (result.content or [])]
    return "\n".join(p for p in parts if p) or "(пустой ответ инструмента)"


def _parse_content(result: Any) -> Any:
    import json

    text = _content_text(result)
    try:
        return json.loads(text)
    except ValueError:
        return text


class FakeOnecClient:
    """Скриптованный клиент для тестов: tools + ответы/ошибки по именам."""

    def __init__(
        self,
        tools: list[dict[str, Any]] | None = None,
        calls: dict[str, Any] | None = None,
    ) -> None:
        self._tools = tools or []
        self._calls = calls or {}
        self.requested: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[dict[str, Any]]:
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.requested.append((name, arguments))
        if name not in self._calls:
            raise OnecError(f"fake: неизвестный инструмент '{name}'")
        response = self._calls[name]
        if isinstance(response, Exception):
            raise response
        return response
