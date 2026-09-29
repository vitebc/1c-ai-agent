"""Тулза check_extension_freshness: git-версия vs версия, зашитая в базу."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.agent.tools import ToolContext, ToolDefinition
from app.onec.client import OnecClient
from app.onec.ext_version import (
    EXT_VERSION_FILE,
    CheckFreshnessArgs,
    make_ext_freshness_tool,
    read_git_ext_version,
)


class FakeVersionClient:
    """Мини-клиент: call_tool('get_extension_version') -> зашитая версия."""

    def __init__(self, version: str) -> None:
        self.version = version
        self.called_with: list[str] = []

    async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
        assert name == "get_extension_version"
        assert arguments == {}
        self.called_with.append(name)
        return self.version


def _tool(client: FakeVersionClient) -> ToolDefinition:
    def factory(root: str) -> OnecClient:
        return client  # type: ignore[return-value]

    return make_ext_freshness_tool(factory)


def _ctx(base_url: str = "http://h/b") -> ToolContext:
    return ToolContext(user_id="u", base_url=base_url)


def _args() -> CheckFreshnessArgs:
    return CheckFreshnessArgs()


def test_fresh_when_versions_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.onec.ext_version.read_git_ext_version", lambda *a, **k: "abc1234")
    tool = _tool(FakeVersionClient("abc1234"))
    out = asyncio.run(tool.handler(_args(), _ctx()))
    assert "свежее" in out and "abc1234" in out


def test_stale_reports_both_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.onec.ext_version.read_git_ext_version", lambda *a, **k: "f" * 40)
    monkeypatch.setattr("app.onec.ext_version._is_commit", lambda v: True)
    tool = _tool(FakeVersionClient("e" * 40))
    out = asyncio.run(tool.handler(_args(), _ctx()))
    assert "УСТАРЕЛО" in out


def test_base_from_context_not_args(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.onec.ext_version.read_git_ext_version", lambda *a, **k: "abc1234")
    client = FakeVersionClient("abc1234")
    tool = _tool(client)
    out = asyncio.run(tool.handler(_args(), _ctx(base_url="http://h/b")))
    assert "свежее" in out


def test_no_base_url_explains(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.onec.ext_version.read_git_ext_version", lambda *a, **k: "abc1234")
    tool = _tool(FakeVersionClient("abc1234"))
    out = asyncio.run(tool.handler(CheckFreshnessArgs(), _ctx(base_url="")))
    assert "Неизвестная база" in out


def test_git_version_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.onec.ext_version.read_git_ext_version", lambda *a, **k: "")
    tool = _tool(FakeVersionClient("abc1234"))
    out = asyncio.run(tool.handler(_args(), _ctx()))
    assert "не зафиксирована" in out


def test_base_returns_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.onec.ext_version.read_git_ext_version", lambda *a, **k: "abc1234")
    tool = _tool(FakeVersionClient("0.1.0"))
    out = asyncio.run(tool.handler(_args(), _ctx()))
    assert "перезалить" in out


def test_client_error_is_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.onec.ext_version.read_git_ext_version", lambda *a, **k: "abc1234")

    class Boom:
        async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
            raise RuntimeError("нет сети")

    def boom_factory(root: str) -> OnecClient:
        return Boom()  # type: ignore[return-value]

    tool = make_ext_freshness_tool(boom_factory)
    out = asyncio.run(tool.handler(_args(), _ctx()))
    assert "Не удалось опросить" in out and "нет сети" in out


def test_read_git_ext_version_missing_file(tmp_path: Path) -> None:
    assert read_git_ext_version(tmp_path / "nope.txt") == ""


def test_repo_version_file_is_commit() -> None:
    """ExtVersion.txt в репо — хеш коммита (бамп-скрипт пишет)."""
    version = read_git_ext_version(EXT_VERSION_FILE)
    assert version, "onec/ext/ExtVersion.txt пуст — запусти scripts/bump_ext_version.py"
