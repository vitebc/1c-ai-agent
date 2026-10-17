"""Тулза list_registry: агенту — собственный реестр проекта.

skill-writer генерирует AGENT.md/SKILL.md и обязан знать РЕАЛЬНЫЕ имена тулз,
скилов и подсерверов агрегатора (`server__tool`). Раньше эти данные были видны
только снаружи по HTTP (GET /tools, /skills, /agents), из петли — никак, и агент
домысливал имена. Тулза отдаёт то же самое напрямую из загрузчиков.

Данные берутся из реестров и кэша, а не HTTP-обратно в себя: единственный сетевой
вызов — `fetch_agg_tools` к агрегатору, у него уже есть TTL-кэш.

Никакого универсального HTTP-доступа: тулза узкая (свой реестр), чтобы не дать
агенту SSRF по периметру. server="local" — вне отбора по mcp, доступна тому агенту,
который прописал её в tools:.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.tools import ToolContext, ToolDefinition

log = logging.getLogger("agent1c.registry_info")


class ListRegistryArgs(BaseModel):
    """Аргументы list_registry. kind — что показать; остальное сужает выдачу."""

    kind: Literal["tools", "skills", "agents", "patterns"] = Field(
        description=(
            "Что перечислить: tools — живые инструменты (локальные + агрегатор + "
            "1С текущей базы, полными именами server__tool), skills — скилы, "
            "agents — агенты, patterns — паттерны."
        )
    )
    include_schemas: bool = Field(
        default=False,
        description=(
            "Для kind='tools': добавить JSON-схемы аргументов (нужно, когда "
            "пишешь вызовы инструментов). По умолчанию только имена и описания."
        ),
    )
    filter: str = Field(
        default="",
        max_length=64,
        description="Необязательная подстрока-фильтр по имени (для tools — по server__tool).",
    )


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _tools_payload(
    names: list[str], descriptions: dict[str, str], servers: dict[str, str],
    schemas: dict[str, Any] | None,
) -> dict[str, Any]:
    """Список тулз с сервером и описанием; схемы — по include_schemas."""
    items = []
    for n in names:
        item: dict[str, Any] = {"name": n, "server": servers.get(n, "default")}
        desc = descriptions.get(n)
        if desc:
            item["description"] = desc
        if schemas is not None and n in schemas:
            item["parameters"] = schemas[n]
        items.append(item)
    return {"tools": items}


def make_list_registry_tool(
    *,
    tools_provider: Any = None,
    skills_dir: str | None = None,
    agents_dir: str | None = None,
    patterns_dir: str | None = None,
) -> ToolDefinition:
    """Тулза list_registry.

    tools_provider — опциональная async-функция () -> реестр/список тулз; по
    умолчанию берём из app.api.chat._fallback_registry (живой реестр: локальные
    + агрегатор + mock/1С). Прокидывается как аргумент, чтобы тесты не тянули сеть.
    """
    from app.config import settings  # лениво: не тянем конфиг в импорте модуля

    async def _live_tools() -> Any:
        """Живой реестр тулз. Импортится лениво: app.api.chat тянет эту фабрику."""
        if tools_provider is not None:
            return await tools_provider()
        from app.api.chat import _fallback_registry

        return await _fallback_registry()

    def _dirs() -> tuple[str, str, str]:
        return (
            skills_dir if skills_dir is not None else settings.skills_dir,
            agents_dir if agents_dir is not None else settings.agents_dir,
            patterns_dir if patterns_dir is not None else settings.patterns_dir,
        )

    async def handler(args: ListRegistryArgs, ctx: ToolContext) -> str:  # noqa: ARG001
        f = args.filter.strip().lower()

        payload: dict[str, Any]
        if args.kind == "tools":
            try:
                registry = await _live_tools()
            except Exception as e:  # noqa: BLE001 — источник недоступен: текст в тулзу
                return f"ERROR: не удалось собрать реестр инструментов: {e}"
            all_names = list(registry.names)
            names = [n for n in all_names if not f or f in n.lower()]
            servers = {t.name: t.server for t in registry.tools}
            descriptions = {t.name: t.description for t in registry.tools if t.description}
            schemas = None
            if args.include_schemas:
                schemas = {t.name: t.openai_schema["function"]["parameters"] for t in registry.tools}
            payload = _tools_payload(names, descriptions, servers, schemas)
            payload["total"] = len(all_names)
            payload["hint"] = (
                "В tools: указывай полные имена server__tool из этого списка, "
                "не выдумывай. Локальные тулзы (server='local') доступны вне mcp."
            )
            return _dump(payload)

        skills_root, agents_root, patterns_root = _dirs()

        if args.kind == "skills":
            from app.skills import SkillRegistry

            sreg = SkillRegistry.load(skills_root)
            skill_items = [
                {"name": s.name, "description": s.description, "tools": list(s.tools)}
                for s in sreg.skills
                if not f or f in s.name.lower()
            ]
            payload = {"skills": skill_items, "total": len(sreg.skills)}
            if sreg.errors:
                payload["errors"] = sreg.errors
            return _dump(payload)

        if args.kind == "agents":
            from app.agents import AgentRegistry

            areg = AgentRegistry.load(agents_root)
            agent_items = [
                {
                    "name": a.name,
                    "title": a.title,
                    "description": a.description,
                    "tools": list(a.tools),
                    "mcp": list(a.mcp_servers),
                    "skills": list(a.skills),
                }
                for a in areg.agents
                if not f or f in a.name.lower()
            ]
            payload = {"agents": agent_items, "total": len(areg.agents)}
            if areg.errors:
                payload["errors"] = areg.errors
            return _dump(payload)

        # patterns
        from app.patterns.loader import PatternRegistry

        preg = PatternRegistry.load(patterns_root)
        pattern_items = [
            {"name": p.name, "description": p.description, "enabled": p.enabled}
            for p in preg.patterns
            if not f or f in p.name.lower()
        ]
        payload = {"patterns": pattern_items, "total": len(preg.patterns)}
        if preg.errors:
            payload["errors"] = preg.errors
        return _dump(payload)

    return ToolDefinition(
        name="list_registry",
        description=(
            "Показать собственный реестр ассистента: kind='tools' — живые инструменты "
            "(локальные + агрегатор полными именами server__tool + 1С), 'skills' — скилы, "
            "'agents' — агенты, 'patterns' — паттерны. Перед выдачей tools:/skills: в "
            "AGENT.md или SKILL.md вызови эту тулзу и бери реальные имена оттуда, а не "
            "домысливай. Схемы аргументов — include_schemas=true. Фильтр по имени — filter."
        ),
        args_model=ListRegistryArgs,
        handler=handler,
        server="local",
    )
