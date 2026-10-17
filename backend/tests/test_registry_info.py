"""Тесты тулзы list_registry: агенту виден собственный реестр проекта."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.agent import ToolRegistry
from app.agent.tools import ToolContext, ToolDefinition
from app.tools.registry_info import ListRegistryArgs, make_list_registry_tool


def _ctx() -> ToolContext:
    return ToolContext(user_id="u", access_profile="all", agent_name="skill-writer")


def _reg_with_tools() -> ToolRegistry:
    """Реестр-заглушка: локальная тулза + тулза агрегатора (server__tool)."""

    async def handler(args: object, ctx: object) -> str:
        return "{}"

    class _A(BaseModel):
        pass

    return ToolRegistry(
        [
            ToolDefinition(
                name="execute_select",
                description="выборка",
                args_model=_A,
                handler=handler,
                server="default",
            ),
            ToolDefinition(
                name="search-obrabotki__semantic_find",
                description="поиск по коду",
                args_model=_A,
                handler=handler,
                server="search-obrabotki",
            ),
        ]
    )


def _tool(**kw: object) -> ToolDefinition:
    async def provider() -> ToolRegistry:
        return _reg_with_tools()

    return make_list_registry_tool(tools_provider=provider, **kw)  # type: ignore[arg-type]


def _call(tool: ToolDefinition, **kw: object) -> dict[str, Any]:
    args = ListRegistryArgs(**kw)  # type: ignore[arg-type]
    raw = asyncio.run(tool.handler(args, _ctx()))
    parsed: dict[str, Any] = json.loads(raw)
    return parsed


def test_kind_tools_lists_names_and_servers() -> None:
    body = _call(_tool(), kind="tools")
    names = [t["name"] for t in body["tools"]]
    assert "execute_select" in names
    assert "search-obrabotki__semantic_find" in names
    by_name = {t["name"]: t for t in body["tools"]}
    assert by_name["search-obrabotki__semantic_find"]["server"] == "search-obrabotki"
    assert by_name["execute_select"]["server"] == "default"
    assert body["total"] == len(body["tools"])


def test_kind_tools_filter_narrows_and_reports_total() -> None:
    body = _call(_tool(), kind="tools", filter="obrabotki")
    assert [t["name"] for t in body["tools"]] == ["search-obrabotki__semantic_find"]
    assert body["total"] == 2  # сузилось — видно, что всего было больше


def test_kind_tools_include_schemas() -> None:
    without = _call(_tool(), kind="tools")
    assert all("parameters" not in t for t in without["tools"])

    with_schemas = _call(_tool(), kind="tools", include_schemas=True)
    assert all("parameters" in t for t in with_schemas["tools"])


def test_kind_skills(tmp_path: Path) -> None:
    d = tmp_path / "skills" / "my-skill"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: пример\ntools: [execute_select]\n---\n\nТело.\n",
        encoding="utf-8",
    )
    body = _call(_tool(skills_dir=str(tmp_path / "skills")), kind="skills")
    assert [s["name"] for s in body["skills"]] == ["my-skill"]
    assert body["skills"][0]["tools"] == ["execute_select"]


def test_kind_agents(tmp_path: Path) -> None:
    d = tmp_path / "agents" / "writer"
    d.mkdir(parents=True)
    (d / "AGENT.md").write_text(
        "---\nname: writer\ntitle: Писатель\ndescription: пишет\n"
        "tools: [execute_select]\nskills: []\nmcp: [default]\n---\n\nПромпт.\n",
        encoding="utf-8",
    )
    body = _call(_tool(agents_dir=str(tmp_path / "agents")), kind="agents")
    assert [a["name"] for a in body["agents"]] == ["writer"]
    assert body["agents"][0]["mcp"] == ["default"]


def test_kind_patterns(tmp_path: Path) -> None:
    root = tmp_path / "patterns"
    root.mkdir()
    (root / "query-patterns.md").write_text(
        "---\nname: query-patterns\ndescription: правила запросов\n---\n\nПравила.\n",
        encoding="utf-8",
    )
    body = _call(_tool(patterns_dir=str(root)), kind="patterns")
    assert [p["name"] for p in body["patterns"]] == ["query-patterns"]
    assert body["patterns"][0]["enabled"] is True


def test_bad_file_reported_not_fatal(tmp_path: Path) -> None:
    """Битый файл не роняет тулзу — причина в errors, как в остальных реестрах."""
    root = tmp_path / "skills"
    (root / "broken").mkdir(parents=True)
    (root / "broken" / "SKILL.md").write_text("без frontmatter\n", encoding="utf-8")
    body = _call(_tool(skills_dir=str(root)), kind="skills")
    assert body["skills"] == []
    assert body["errors"]


def test_invalid_kind_rejected_by_schema() -> None:
    """Неизвестный kind отсекается pydantic до похода в данные."""
    with pytest.raises(ValidationError):
        ListRegistryArgs(kind="wat")  # type: ignore[arg-type]


def test_tool_registered_as_local() -> None:
    tool = make_list_registry_tool()
    assert tool.name == "list_registry"
    assert tool.server == "local"
