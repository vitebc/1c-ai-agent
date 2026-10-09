"""Тесты мапы база -> search-серверы: парсинг, hot-reload, фильтрация реестра."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from app.agent import ToolRegistry
from app.agent.tools import ToolDefinition
from app.agents import Agent
from app.api.chat import scope_registry_for_agent
from app.onec import search_maps
from app.tools import MOCK_ONEC_TOOLS


def _agent_with_search_tools() -> Agent:
    """Агент с тулзами двух search-серверов + одной локальной."""
    return Agent(
        name="test-search",
        title="Тест",
        description="тест",
        tools=(
            "search-ka-update__semantic_find",
            "search-ka-rs__semantic_find",
            "search-ka-td__semantic_find",
            "get_counterparty",
        ),
        skills=(),
        mcp_servers=("default", "search-ka-update", "search-ka-rs", "search-ka-td"),
        model="",
        max_rounds=None,
        prompt="Промпт.",
        source="/tmp/test-search/AGENT.md",
    )


class _EmptyArgs(BaseModel):
    pass


def _registry_with_search_tools() -> ToolRegistry:
    """Реестр: mock-тулзы + фиктивные search-тулзы (в MOCK_ONEC_TOOLS их нет)."""

    async def _handler(args, ctx) -> str:
        return "{}"

    tools = list(MOCK_ONEC_TOOLS)
    for srv in ("search-ka-update", "search-ka-rs", "search-ka-td"):
        tools.append(
            ToolDefinition(
                name=f"{srv}__semantic_find",
                description=f"тестовая тулза {srv}",
                args_model=_EmptyArgs,
                handler=_handler,
                server=srv,
            )
        )
    return ToolRegistry(tools)


def test_parse_search_maps() -> None:
    raw = "doc=search-ka-update,search-ka-rs;ca2_td=search-ka-td"
    assert search_maps.parse_search_maps(raw) == {
        "doc": ["search-ka-update", "search-ka-rs"],
        "ca2_td": ["search-ka-td"],
    }


def test_parse_search_maps_bad() -> None:
    for bad in ("no-equals", "name=", "=servers", " , ".replace(" ", "")):
        try:
            search_maps.parse_search_maps(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"ожидался ValueError для {bad!r}")


def test_allowed_servers_no_base() -> None:
    assert search_maps.allowed_search_servers(None) is None
    assert search_maps.allowed_search_servers("") is None


def test_allowed_servers_unknown_base(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "search-maps.conf"
    p.write_text("doc=search-ka-update", encoding="utf-8")
    monkeypatch.setenv("SEARCH_MAPS_FILE", str(p))
    search_maps._state.map = None
    # База не в мапе — без фильтрации.
    assert search_maps.allowed_search_servers("other-base") is None


def test_allowed_servers_mapped_base(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "search-maps.conf"
    p.write_text("doc=search-ka-update,search-ka-rs;ca2_td=search-ka-td", encoding="utf-8")
    monkeypatch.setenv("SEARCH_MAPS_FILE", str(p))
    search_maps._state.map = None
    assert search_maps.allowed_search_servers("DOC") == ["search-ka-update", "search-ka-rs"]
    assert search_maps.allowed_search_servers("ca2_td") == ["search-ka-td"]


def test_allowed_servers_empty_list_means_no_search(tmp_path: Path, monkeypatch) -> None:
    """Запись 'база=' — база в мапе, но серверов нет: кодовые тулзы не выдаются."""
    p = tmp_path / "search-maps.conf"
    p.write_text("ai_base=search-ka-td", encoding="utf-8")
    monkeypatch.setenv("SEARCH_MAPS_FILE", str(p))
    search_maps._state.map = None
    assert search_maps.allowed_search_servers("ai_base") == ["search-ka-td"]


def test_scope_filters_by_map(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "search-maps.conf"
    p.write_text("ca2_td=search-ka-td", encoding="utf-8")
    monkeypatch.setenv("SEARCH_MAPS_FILE", str(p))
    search_maps._state.map = None

    reg = _registry_with_search_tools()
    agent = _agent_with_search_tools()

    # База в мапе: только её сервер.
    scoped, rejected = scope_registry_for_agent(reg, agent, base_name="ca2_td")
    names = set(scoped.names)
    assert "search-ka-td__semantic_find" in names
    assert "search-ka-update__semantic_find" not in names
    assert "search-ka-rs__semantic_find" not in names
    assert "get_counterparty" in names  # не-search — не тронут
    assert any("search-ka-update" in r for r in rejected)

    # База вне мапы: все search-серверы агента.
    scoped2, _ = scope_registry_for_agent(reg, agent, base_name="other-base")
    assert "search-ka-update__semantic_find" in set(scoped2.names)
    assert "search-ka-rs__semantic_find" in set(scoped2.names)

    # Без базы: без фильтрации.
    scoped3, _ = scope_registry_for_agent(reg, agent)
    assert "search-ka-td__semantic_find" in set(scoped3.names)


def test_scope_no_map_file(tmp_path: Path, monkeypatch) -> None:
    """Файла мапы нет — фильтрации нет вообще."""
    monkeypatch.setenv("SEARCH_MAPS_FILE", str(tmp_path / "absent.conf"))
    search_maps._state.map = None

    reg = _registry_with_search_tools()
    agent = _agent_with_search_tools()
    scoped, rejected = scope_registry_for_agent(reg, agent, base_name="any-base")
    assert len(rejected) == 0
    assert "search-ka-update__semantic_find" in set(scoped.names)
