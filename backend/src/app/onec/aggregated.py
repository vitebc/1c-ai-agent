"""Агрегирующий MCP-сервер: подсерверы вида server__tool.

Агрегатор (напр. http://192.168.60.39:9224/api/mcp-aggregated/mcp) отдаёт
инструменты подсерверов одним списком; вызов — по полному имени
`server__tool` через тот же tools/call. Кэш списка — TTL, чтобы не дёргать
агрегатор на каждый /chat (ответ тяжёлый: 100+ тулзов с большими схемами).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.agent.tools import ToolDefinition
from app.onec.client import OnecClient
from app.onec.live import make_generic_tool

log = logging.getLogger("agent1c.aggregated")

#: Разделитель имени подсервера и тулза в полном имени.
SEP = "__"

#: Кэш сырых списков tools/list: url -> (timestamp, tools).
_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def split_server(full_name: str) -> tuple[str, str]:
    """'search-ka-update__semantic_find' -> ('search-ka-update', 'semantic_find').

    Без разделителя — ('default', name): тулзы прокси 1С без неймспейса.
    """
    if SEP in full_name:
        server, _, tool = full_name.partition(SEP)
        if server and tool:
            return server, tool
    return "default", full_name


def build_agg_tools(client: OnecClient, raw_tools: list[dict[str, Any]]) -> list[ToolDefinition]:
    """Сырой tools/list агрегатора -> ToolDefinition с тегом server."""
    out: list[ToolDefinition] = []
    seen: set[str] = set()
    for pt in raw_tools:
        name = pt.get("name")
        if not isinstance(name, str) or not name or name in seen:
            continue
        seen.add(name)
        server, _ = split_server(name)
        description = pt.get("description")
        schema = pt.get("inputSchema")
        out.append(
            make_generic_tool(
                client,
                name,
                description if isinstance(description, str) else "",
                schema if isinstance(schema, dict) else None,
                server=server,
            )
        )
    return out


async def fetch_agg_tools(client: OnecClient, url: str, ttl: float = 300.0) -> list[dict[str, Any]]:
    """tools/list агрегатора с TTL-кэшем. Падение — исключение вызывателю."""
    now = time.monotonic()
    hit = _CACHE.get(url)
    if hit is not None and now - hit[0] < ttl:
        return hit[1]
    tools = await client.list_tools()
    _CACHE[url] = (now, tools)
    log.info("агрегатор %s: %d тулзов", url, len(tools))
    return tools


def clear_agg_cache() -> None:
    """Сброс кэша (для тестов)."""
    _CACHE.clear()
