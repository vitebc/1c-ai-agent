"""Тесты паттернов ленивой подгрузки: парсинг .md, тулза get_pattern, петля."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.agent import ToolRegistry, run_agent
from app.llm import AssistantMessage, ToolCall
from app.patterns import PatternRegistry, make_pattern_tool
from app.tools import MOCK_ONEC_TOOLS
from tests.fake_llm import FakeLLM

REPO_PATTERNS = Path(__file__).resolve().parent.parent / "patterns"

GOOD_MD = """---
name: test-pattern
description: тестовый паттерн
---

Текст паттерна.
"""


def _write_pattern(root: Path, filename: str, content: str) -> Path:
    p = root / filename
    p.write_text(content, encoding="utf-8")
    return p


def test_parse_repo_patterns() -> None:
    reg = PatternRegistry.load(REPO_PATTERNS)
    assert not reg.errors, reg.errors
    pattern = reg.get("query-patterns")
    assert pattern is not None
    assert "ДАТА(2026,9,18)" in pattern.text
    assert "validate_query" in pattern.text


def test_readme_is_skipped_and_bad_files_reported(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# доки\n", encoding="utf-8")
    _write_pattern(tmp_path, "test-pattern.md", GOOD_MD)
    _write_pattern(tmp_path, "other.md", GOOD_MD)  # name test-pattern != other
    _write_pattern(tmp_path, "empty.md", "---\nname: empty\ndescription: x\n---\n")
    reg = PatternRegistry.load(tmp_path)
    assert reg.names == ["test-pattern"]
    assert len(reg.errors) == 2


def test_get_rejects_traversal() -> None:
    reg = PatternRegistry.load(REPO_PATTERNS)
    assert reg.get("../secret") is None
    assert reg.get("") is None


def test_make_pattern_tool_empty_dir_returns_none(tmp_path: Path) -> None:
    assert make_pattern_tool(tmp_path) is None


def test_pattern_tool_handler(tmp_path: Path) -> None:
    from app.agent.tools import ToolContext

    _write_pattern(tmp_path, "test-pattern.md", GOOD_MD)
    tool = make_pattern_tool(tmp_path)
    assert tool is not None and tool.name == "get_pattern"
    assert "test-pattern" in tool.description
    ctx = ToolContext(user_id="u")

    async def go() -> tuple[str, str]:
        ok = await tool.handler(tool.args_model.model_validate({"name": "test-pattern"}), ctx)
        bad = await tool.handler(tool.args_model.model_validate({"name": "nope"}), ctx)
        return ok, bad

    ok, bad = asyncio.run(go())
    assert ok == "Текст паттерна."
    assert bad.startswith("ERROR")


def test_loop_lazy_loads_pattern(tmp_path: Path) -> None:
    """Модель вызывает get_pattern — текст попадает ей в контекст следующим раундом."""
    _write_pattern(tmp_path, "test-pattern.md", GOOD_MD)
    tool = make_pattern_tool(tmp_path)
    assert tool is not None
    llm = FakeLLM(
        [
            AssistantMessage(
                content=None,
                tool_calls=[ToolCall(id="c1", name="get_pattern", arguments='{"name": "test-pattern"}')],
            ),
            AssistantMessage(content="по паттерну готово"),
        ]
    )
    res = asyncio.run(run_agent(llm=llm, registry=ToolRegistry(MOCK_ONEC_TOOLS + [tool]), user_message="тест"))
    assert res.answer == "по паттерну готово"
    assert res.tool_calls == ["get_pattern"]
    tool_messages = [m for m in llm.seen_messages[1] if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert "Текст паттерна." in str(tool_messages[0]["content"])
