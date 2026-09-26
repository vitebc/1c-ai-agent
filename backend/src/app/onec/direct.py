"""Прямой JSON-RPC клиент к HTTP-сервису 1С (без MCP-прокси).

Форма 1С присылает base_url (http://srvr/Ref — публикация живёт там же, откуда
запущена база, имя публикации совпадает с именем базы). Бэкенд ходит в
{base_url}/hs/mcp/rpc напрямую: так вопрос из базы X отвечает база X без
карты соответствий на бэкенде (зеркала — отдельные равноправные базы).

Контракт повторяет прокси (onec/1c_mcp/src/py_server): Basic-авторизация,
POST JSON-RPC {tools/list, tools/call}, envelope результата
{content: [{type, text}], isError}.
"""

from __future__ import annotations

import itertools
import json
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.onec.client import OnecError

log = logging.getLogger("agent1c.direct")


def validate_base_url(raw: str | None) -> str:
    """Проверить адрес базы из запроса, вернуть нормализованный корень публикации.

    Правила: непустой; схема только http/https (прод — только http);
    без userinfo в URL; хост обязан присутствовать; слэш в конце режется.
    URL берётся из запроса доверенной формы 1С закрытого контура, но проверять
    всё равно надо — иначе любая строка уйдёт в httpx. Ошибки — ValueError.
    """
    if raw is None:
        raise ValueError("пустой base_url: форма обязана прислать адрес публикации базы")
    text = raw.strip().strip("'\"")
    if not text:
        raise ValueError("пустой base_url: форма обязана прислать адрес публикации базы")
    parts = urlsplit(text if "://" in text else f"http://{text}")
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"base_url: разрешены только http/https, получено {raw!r}")
    if parts.username or parts.password:
        raise ValueError("base_url: креды в URL запрещены, авторизация — через ONEC_USERNAME/ONEC_PASSWORD")
    if not parts.hostname:
        raise ValueError(f"base_url: нет хоста в {raw!r}")
    host = parts.hostname.lower()
    port = f":{parts.port}" if parts.port else ""
    path = parts.path.rstrip("/") if parts.path else ""
    return f"{parts.scheme}://{host}{port}{path}"


class JsonRpcOnecClient:
    """Прямой клиент к /hs/mcp/rpc конкретной базы. Совместим с OnecClient."""

    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str | None = None,
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._root = validate_base_url(base_url)
        self._rpc_url = f"{self._root}/hs/mcp/rpc"
        self._auth = httpx.BasicAuth(username, password or "")
        self._timeout = timeout
        self._transport = transport
        self._ids = itertools.count(1)

    @property
    def url(self) -> str:
        return self._rpc_url

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params}
        try:
            async with httpx.AsyncClient(auth=self._auth, timeout=self._timeout, transport=self._transport) as client:
                resp = await client.post(self._rpc_url, json=payload)
                resp.raise_for_status()
                data: Any = resp.json()
        except httpx.HTTPError as e:
            raise OnecError(f"HTTP ошибка {self._rpc_url}: {e}") from e
        except ValueError as e:
            raise OnecError(f"Не JSON в ответе {self._rpc_url}: {e}") from e
        if not isinstance(data, dict):
            raise OnecError(f"Не JSON-RPC ответ от {self._rpc_url}")
        if "error" in data:
            err = data["error"] if isinstance(data["error"], dict) else {}
            raise OnecError(f"JSON-RPC ошибка {err.get('code', '?')}: {err.get('message', 'без текста')}")
        result = data.get("result")
        if not isinstance(result, dict):
            raise OnecError(f"Нет result в ответе {self._rpc_url}")
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._rpc("tools/list", {})
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            raise OnecError(f"Нет tools в ответе {self._rpc_url}")
        out: list[dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict) or not tool.get("name"):
                continue
            out.append(
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "inputSchema": tool.get("inputSchema", {}),
                }
            )
        return out

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise OnecError(_blocks_text(result.get("content")))
        text = _blocks_text(result.get("content"))
        try:
            return json.loads(text)
        except ValueError:
            return text


def _blocks_text(content: Any) -> str:
    parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    text = "\n".join(p for p in parts if p)
    return text or "(пустой ответ инструмента)"
