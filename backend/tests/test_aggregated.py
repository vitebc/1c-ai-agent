"""Тесты агрегирующего MCP: full_name, теги серверов, отбор агента, кэш."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.agent import ToolRegistry
from app.agents import Agent, AgentRegistry
from app.agents.loader import AgentFormatError, parse_agent_file
from app.api.chat import scope_registry_for_agent
from app.onec.aggregated import build_agg_tools, clear_agg_cache, fetch_agg_tools, split_server
from app.onec.client import FakeOnecClient
from app.tools import MOCK_ONEC_TOOLS

RAW: list[dict[str, Any]] = [
    {
        "name": "search-ka-update__semantic_find",
        "description": "семантический поиск",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
    },
    {"name": "rlm__rlm_start", "description": "старт сессии", "inputSchema": {"type": "object"}},
    {"name": "execute_select", "description": "короткое имя без неймспейса"},
]


def test_split_server() -> None:
    assert split_server("search-ka-update__semantic_find") == ("search-ka-update", "semantic_find")
    assert split_server("rlm__rlm_start") == ("rlm", "rlm_start")
    assert split_server("execute_select") == ("default", "execute_select")
    assert split_server("__x") == ("default", "__x")
    assert split_server("") == ("default", "")


def test_build_agg_tools_tags_servers() -> None:
    tools = build_agg_tools(FakeOnecClient(), RAW)
    by_name = {t.name: t for t in tools}
    assert by_name["search-ka-update__semantic_find"].server == "search-ka-update"
    assert by_name["rlm__rlm_start"].server == "rlm"
    assert by_name["execute_select"].server == "default"
    params = by_name["search-ka-update__semantic_find"].openai_schema["function"]["parameters"]
    assert params["properties"]["query"]["type"] == "string"


def test_build_agg_tools_skips_bad_and_dupes() -> None:
    tools = build_agg_tools(
        FakeOnecClient(),
        [
            {"name": "", "description": "x"},
            {"name": "rlm__a", "description": "1"},
            {"name": "rlm__a", "description": "дубль"},
            {"description": "без имени"},
        ],
    )
    assert [t.name for t in tools] == ["rlm__a"]


def test_agg_handler_calls_by_full_name() -> None:
    async def go() -> None:
        client = FakeOnecClient(calls={"search-ka-update__semantic_find": '{"ok": true}'})
        (tool,) = build_agg_tools(client, [RAW[0]])
        out = await tool.handler(tool.args_model.model_validate({"query": "НДС"}), None)  # type: ignore[arg-type]
        assert out == '{"ok": true}'
        assert client.requested == [("search-ka-update__semantic_find", {"query": "НДС"})]

    asyncio.run(go())


def test_fetch_agg_tools_cached() -> None:
    async def go() -> None:
        clear_agg_cache()

        class Counting(FakeOnecClient):
            calls_made = 0

            async def list_tools(self) -> list[dict[str, Any]]:
                type(self).calls_made += 1
                return [{"name": "rlm__x"}]

        client = Counting()
        try:
            await fetch_agg_tools(client, "http://agg/mcp", ttl=300.0)
            await fetch_agg_tools(client, "http://agg/mcp", ttl=300.0)
            assert Counting.calls_made == 1
            await fetch_agg_tools(client, "http://agg/mcp", ttl=0.0)
            assert Counting.calls_made == 2
        finally:
            clear_agg_cache()

    asyncio.run(go())


def _agent(tmp_path: Path, mcp_line: str, tools: str = "[get_counterparty]") -> Agent:
    d = tmp_path / "a"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "AGENT.md"
    p.write_text(
        f"---\nname: a\ntitle: A\ndescription: d\ntools: {tools}\nskills: []\n{mcp_line}\nmodel:\n---\n\nПромпт.\n",
        encoding="utf-8",
    )
    return parse_agent_file(p)


def test_mcp_parsing_string_and_list(tmp_path: Path) -> None:
    assert _agent(tmp_path, "mcp: default").mcp_servers == ("default",)
    assert _agent(tmp_path, "mcp: [default, search-ka-update, rlm]").mcp_servers == (
        "default",
        "search-ka-update",
        "rlm",
    )


@pytest.mark.parametrize("mcp_line", ["mcp: []", "mcp: [BAD NAME]", "mcp: [default, BAD NAME]"])
def test_mcp_parsing_invalid(tmp_path: Path, mcp_line: str) -> None:
    with pytest.raises(AgentFormatError):
        _agent(tmp_path, mcp_line)


def test_mcp_empty_items_ignored_by_parser(tmp_path: Path) -> None:
    # Пустые элементы выкидывает frontmatter-парсер — остаётся валидный список.
    assert _agent(tmp_path, "mcp: [default, '']").mcp_servers == ("default",)


def test_scope_registry_for_agent_filters_servers() -> None:
    agg = build_agg_tools(FakeOnecClient(), RAW)
    registry = ToolRegistry(MOCK_ONEC_TOOLS + agg)
    analyst = Agent(
        name="analyst",
        title="A",
        description="d",
        tools=("get_counterparty", "search-ka-update__semantic_find", "rlm__rlm_start", "nope"),
        skills=(),
        mcp_servers=("default", "search-ka-update"),
    )
    scoped, rejected = scope_registry_for_agent(registry, analyst)
    assert scoped.names == ["get_counterparty", "search-ka-update__semantic_find"]
    assert any("rlm__rlm_start" in r and "rlm" in r for r in rejected)
    assert any(r.startswith("nope") for r in rejected)


def test_repo_analyst_uses_three_sources() -> None:
    repo = Path(__file__).resolve().parent.parent / "agents"
    analyst = AgentRegistry.load(repo).get("analyst")
    assert analyst is not None
    assert set(analyst.mcp_servers) == {"default", "search-ka-update", "rlm"}
    full = [t for t in analyst.tools if t.startswith("search-ka-update__")]
    assert len(full) == 16
    assert len([t for t in analyst.tools if t.startswith("rlm__")]) == 6
