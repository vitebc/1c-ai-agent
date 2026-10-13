"""MCP-клиент к прокси 1С (Streamable HTTP).

Петля зависит только от протокола OnecClient — в тестах FakeOnecClient,
в проде McpOnecClient поверх `mcp` SDK (тот же пин, что у прокси апстрима).
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Protocol
from urllib.parse import urlsplit

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

log = logging.getLogger("agent1c.onec")


def _extract_real_error(exc: BaseException) -> str:
    """Распаковать anyio ExceptionGroup / TaskGroup до реального sub-exception.

    MCP SDK использует anyio.TaskGroup внутри; при обрыве SSE или таймауте
    возникает "unhandled errors in a TaskGroup (N sub-exception)" без деталей.
    Здесь достаём фактическую причину для логирования и сообщения пользователю.
    """
    # Python 3.11+ native ExceptionGroup
    if hasattr(sys.modules.get("__builtins__", {}), "BaseExceptionGroup"):
        pass
    try:
        EG = ExceptionGroup  # type: ignore[name-defined]
    except NameError:
        return f"{type(exc).__name__}: {exc}"[:500]

    def dig(e: BaseException, depth: int = 0) -> str:
        if isinstance(e, EG):
            subs = [dig(s, depth + 1) for s in e.exceptions]
            return "; ".join(subs)[:800]
        return f"[{depth}]{type(e).__name__}: {e}"[:400]

    result = dig(exc)
    log.warning("MCP call_tool real error chain: %s", result)
    return result


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
        # Прокси 1c_mcp отдаёт Streamable HTTP строго на /mcp/ (в корень — 405).
        # Если путь не указан, подставляем его сами, чтобы голый хост из .env работал.
        url = mcp_url.rstrip("/")
        if urlsplit(url).path in ("", "/"):
            url += "/mcp/"
        self._url = url
        self._token = token
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    async def list_tools(self) -> list[dict[str, Any]]:
        try:
            async with streamablehttp_client(self._url, headers=self._headers()) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
            return [{"name": t.name, "description": t.description, "inputSchema": t.inputSchema} for t in result.tools]
        except BaseException as e:
            raise type(e)(f"list_tools {self._url}: {_extract_real_error(e)}") from None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        import time as _time
        _t0 = _time.monotonic()
        try:
            async with streamablehttp_client(self._url, headers=self._headers()) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments)
        except BaseException as e:
            elapsed_ms = int((_time.monotonic() - _t0) * 1000)
            real_err = _extract_real_error(e)
            log.error("call_tool %s FAILED after %dms: %s", name, elapsed_ms, real_err[:500])
            # Перебрасываем с реальной причиной вместо абстрактного TaskGroup
            inner = self._first_sub_exception(e)
            raise OnecError(f"tool '{name}' failed ({type(inner).__name__}): {str(inner)[:300]}") from None
        if result.isError:
            raise OnecError(_content_text(result))
        return _parse_content(result)

    @staticmethod
    def _first_sub_exception(exc: BaseException) -> BaseException:
        """Распаковать ExceptionGroup до первого реального sub-exception."""
        while hasattr(exc, "exceptions"):
            excs = getattr(exc, "exceptions", [])
            if not excs:
                break
            exc = excs[0]
        return exc

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
