"""Тесты тулз get_agent / get_skill: чтение AGENT.md и SKILL.md целиком."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.agent import ToolRegistry
from app.agent.tools import ToolContext, ToolDefinition
from app.tools.config_files import _NameArgs, make_get_agent_tool, make_get_skill_tool


def _ctx() -> ToolContext:
    return ToolContext(user_id="u", access_profile="all", agent_name="skill-writer")


def _call(tool: ToolDefinition, name: str) -> str:
    return asyncio.run(tool.handler(_NameArgs(name=name), _ctx()))


@pytest.fixture()
def agents_dir(tmp_path: Path) -> Path:
    root = tmp_path / "agents"
    d = root / "my-agent"
    d.mkdir(parents=True)
    (d / "AGENT.md").write_text(
        "---\nname: my-agent\ntitle: Мой\ndescription: тестовый агент\n"
        "tools: [execute_select]\nskills: []\nmcp: [default]\n---\n\nТело промпта агента.\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture()
def skills_dir(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    d = root / "my-skill"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: тестовый скил\ntools: [execute_select]\n---\n\nТело скила.\n",
        encoding="utf-8",
    )
    return root


def test_get_agent_returns_whole_file(agents_dir: Path) -> None:
    out = _call(make_get_agent_tool(agents_dir=str(agents_dir)), "my-agent")
    # Сырой файл: и frontmatter, и тело — как лежит на диске.
    assert out.startswith("---")
    assert "name: my-agent" in out
    assert "tools: [execute_select]" in out
    assert "Тело промпта агента." in out
    assert out == (agents_dir / "my-agent" / "AGENT.md").read_text(encoding="utf-8")


def test_get_skill_returns_whole_file(skills_dir: Path) -> None:
    out = _call(make_get_skill_tool(skills_dir=str(skills_dir)), "my-skill")
    assert out.startswith("---")
    assert "description: тестовый скил" in out
    assert "Тело скила." in out


def test_unknown_name_lists_available(agents_dir: Path, skills_dir: Path) -> None:
    out = _call(make_get_agent_tool(agents_dir=str(agents_dir)), "nope")
    assert out.startswith("ERROR")
    assert "не найден" in out
    assert "my-agent" in out  # перечень доступных — чтобы модель выбрала

    out2 = _call(make_get_skill_tool(skills_dir=str(skills_dir)), "nope")
    assert out2.startswith("ERROR")
    assert "my-skill" in out2


@pytest.mark.parametrize("bad", ["../../etc/passwd", "../secrets", "my agent", "a/b"])
def test_traversal_and_junk_names_rejected(agents_dir: Path, bad: str) -> None:
    """Имя с обходом отсекается ДО обращения к диску (построение, не фильтр)."""
    out = _call(make_get_agent_tool(agents_dir=str(agents_dir)), bad)
    assert out.startswith("ERROR")
    assert "root:" not in out  # точно не отдали содержимое /etc/passwd


def test_empty_name_rejected_by_schema(agents_dir: Path) -> None:
    """Пустое имя отсекает pydantic (min_length=1) — до вызова обработчика."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _NameArgs(name="")


def test_empty_registry_reports_no_names(tmp_path: Path) -> None:
    out = _call(make_get_agent_tool(agents_dir=str(tmp_path / "empty")), "my-agent")
    assert out.startswith("ERROR")
    assert "(пусто)" in out


def test_large_file_truncated_with_marker(agents_dir: Path) -> None:
    """Потолок ответа: раздутый файл обрезается с явным маркером."""
    from app.tools import config_files

    big = agents_dir / "my-agent" / "AGENT.md"
    big.write_text(
        "---\nname: my-agent\ntitle: Мой\ndescription: d\ntools: [execute_select]\n"
        "skills: []\nmcp: [default]\n---\n\n" + ("x" * (config_files.MAX_FILE_CHARS + 500)),
        encoding="utf-8",
    )
    out = _call(make_get_agent_tool(agents_dir=str(agents_dir)), "my-agent")
    assert "[ОБРЕЗАНО" in out
    assert len(out) < config_files.MAX_FILE_CHARS + 200


def test_both_tools_are_local() -> None:
    for factory in (make_get_agent_tool, make_get_skill_tool):
        t = factory()
        assert t.server == "local"
        assert t.name in ("get_agent", "get_skill")


def test_tools_present_in_chat_registry(monkeypatch: pytest.MonkeyPatch, agents_dir: Path) -> None:
    """Регресс: локальные тулзы не теряются в пути чата (build_registry_for_root)."""
    import asyncio as _a

    from app.api.chat import build_registry_for_root
    from app.onec.client import FakeOnecClient

    monkeypatch.setattr("app.config.settings.agents_dir", str(agents_dir))
    reg: ToolRegistry = _a.run(build_registry_for_root("http://h/base", client=FakeOnecClient([])))
    assert {"get_agent", "get_skill", "list_registry"} <= set(reg.names)


def test_name_args_normalizes_case() -> None:
    assert _NameArgs(name="  My-Agent ").safe_name == "my-agent"


def test_unknown_agents_dir_is_handled(tmp_path: Path) -> None:
    """Каталога агентов нет — тулза отвечает текстом, а не падает."""
    out = _call(make_get_agent_tool(agents_dir=str(tmp_path / "нет-такого")), "x")
    assert out.startswith("ERROR")
