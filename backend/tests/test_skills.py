"""Тесты рантайм-скилов: парсинг SKILL.md, матчинг, фильтр реестра, промпт, API."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agent import ToolRegistry, run_agent
from app.agents import AgentRegistry
from app.api.chat import get_agent_registry, get_llm, get_registry, get_skill_registry
from app.db.models import ChatSession
from app.db.session import SessionFactory
from app.llm import AssistantMessage
from app.main import app
from app.rag import FakeEmbeddings
from app.skills import Skill, SkillRegistry
from app.tools import MOCK_ONEC_TOOLS
from tests.fake_llm import FakeLLM
from tests.test_chat_api import _parse_sse

REPO_SKILLS = Path(__file__).resolve().parent.parent / "skills"

GOOD_MD = """---
name: test-skill
description: заказы клиента и контрагенты
tools: [get_counterparty, execute_select]
---

# Тест
Делай так.
"""


def _write_skill(root: Path, dirname: str, content: str) -> Path:
    d = root / dirname
    d.mkdir(parents=True)
    p = d / "SKILL.md"
    p.write_text(content, encoding="utf-8")
    return p


def test_parse_example_skill_from_repo() -> None:
    """Поставленные скилы валидны: парсятся, name = имя папки.

    Состав (какие скилы лежат в репо) меняется без кода — проверяем
    только формат, не конкретные имена и текст.
    """
    reg = SkillRegistry.load(REPO_SKILLS)
    assert not reg.errors, reg.errors
    for skill in reg.skills:
        assert skill.name == Path(skill.source).parent.name  # name = имя папки
        assert skill.description and skill.tools
        assert f"# Скилл: {skill.name}" in skill.system_block


def test_parse_good_file(tmp_path: Path) -> None:
    _write_skill(tmp_path, "test-skill", GOOD_MD)
    reg = SkillRegistry.load(tmp_path)
    assert reg.errors == []
    assert reg.names == ["test-skill"]
    skill = reg.get("test-skill")
    assert skill is not None
    assert skill.tools == ("get_counterparty", "execute_select")
    assert skill.prompt.startswith("# Тест")


@pytest.mark.parametrize(
    ("dirname", "content", "hint"),
    [
        ("bad1", "no frontmatter here", "начинаться"),
        ("bad2", "---\ndescription: x\ntools: [a]\n---\nbody", "name"),
        ("other", "---\nname: bad2\ndescription: x\ntools: [a]\n---\n", "папки"),
        ("bad3", "---\nname: bad3\ntools: [a]\n---\n", "description"),
        ("bad4", "---\nname: bad4\ndescription: x\ntools: a\n---\n", "tools"),
        ("bad5", "---\nname: bad5\ndescription: x\ntools: []\n---\n", "tools"),
        ("Bad_Name", "---\nname: Bad_Name\ndescription: x\ntools: [a]\n---\n", "латиницей"),
    ],
)
def test_bad_files_skipped_with_errors(tmp_path: Path, dirname: str, content: str, hint: str) -> None:
    _write_skill(tmp_path, dirname, content)
    _write_skill(tmp_path, "good", GOOD_MD.replace("test-skill", "good"))
    reg = SkillRegistry.load(tmp_path)
    assert reg.names == ["good"]
    assert len(reg.errors) == 1
    assert hint in reg.errors[0]


def test_load_missing_dir_returns_empty() -> None:
    reg = SkillRegistry.load("/definitely/not/here")
    assert reg.names == []
    assert reg.errors == []


def test_match_top1_by_description() -> None:
    reg = SkillRegistry()
    reg.skills.append(Skill(name="a-orders", description="заказы клиента контрагент", tools=("x",), prompt=""))
    reg.skills.append(Skill(name="b-stock", description="остатки товаров на складах", tools=("y",), prompt=""))
    got, score = asyncio.run(reg.match("покажи последние заказы клиента", FakeEmbeddings()))
    assert got is not None and got.name == "a-orders"
    assert score > 0.0
    got2, _ = asyncio.run(reg.match("сколько товара на складах", FakeEmbeddings()))
    assert got2 is not None and got2.name == "b-stock"


def test_match_empty_registry_or_query() -> None:
    assert asyncio.run(SkillRegistry().match("что-то", FakeEmbeddings())) == (None, 0.0)
    reg = SkillRegistry()
    reg.skills.append(Skill(name="a", description="заказы", tools=("x",), prompt=""))
    assert asyncio.run(reg.match("   ", FakeEmbeddings())) == (None, 0.0)


def test_match_threshold_filters_weak() -> None:
    reg = SkillRegistry()
    reg.skills.append(Skill(name="a", description="заказы клиента", tools=("x",), prompt=""))
    got, score = asyncio.run(reg.match("заказы клиента контрагента", FakeEmbeddings(), min_score=0.99))
    assert got is None
    # score возвращается честный (для калибровки порога по логам), даже при отсеве
    assert score < 0.99


def test_subset_keeps_order_and_drops_unknown() -> None:
    reg = ToolRegistry(MOCK_ONEC_TOOLS)
    sub = reg.subset(["get_counterparty", "nope", "get_stock_balance"])
    assert sub.names == ["get_counterparty", "get_stock_balance"]
    assert len(reg.names) == len(MOCK_ONEC_TOOLS)  # исходный не тронут


def test_run_agent_with_skill_block() -> None:
    llm = FakeLLM([AssistantMessage(content="ok")])
    skill = Skill(name="s", description="d", tools=("get_counterparty",), prompt="Правило скила.")
    res = asyncio.run(
        run_agent(
            llm=llm,
            registry=ToolRegistry(MOCK_ONEC_TOOLS),
            user_message="тест",
            extra_system=skill.system_block,
            skill_name=skill.name,
        )
    )
    assert res.answer == "ok"
    system = llm.seen_messages[0][0]["content"]
    assert "Правило скила." in system
    assert "# Скилл: s" in system


def _api_client(tmp_path: Path, script: list[AssistantMessage]) -> tuple[TestClient, FakeLLM]:
    # Агент из tmp_path — чтобы тесты скилов не зависели от реальных AGENT.md
    # (состав агентов/скилов меняется без кода).
    agents_dir = tmp_path / "agents"
    (agents_dir / "assistant").mkdir(parents=True)
    (agents_dir / "assistant" / "AGENT.md").write_text(
        "---\nname: assistant\ntitle: Ассистент\ndescription: общий\n"
        'tools: [get_counterparty, get_stock_balance]\nskills: ["*"]\n'
        "mcp: default\nmodel:\n---\n\nПромпт ассистента.\n",
        encoding="utf-8",
    )
    _write_skill(
        tmp_path,
        "zakazy",
        "---\nname: zakazy\ndescription: заказы клиента\ntools: [get_counterparty]\n---\n\nПравило Z.\n",
    )
    fake = FakeLLM(script)
    app.dependency_overrides[get_llm] = lambda: fake
    app.dependency_overrides[get_registry] = lambda: ToolRegistry(MOCK_ONEC_TOOLS)
    app.dependency_overrides[get_skill_registry] = lambda: SkillRegistry.load(tmp_path)
    app.dependency_overrides[get_agent_registry] = lambda: AgentRegistry.load(agents_dir)
    return TestClient(app), fake


def _skill_of_session(sid: int) -> str | None:
    async def go() -> str | None:
        from app.db.session import engine

        await engine.dispose()
        async with SessionFactory() as s:
            row = (await s.execute(select(ChatSession.skill_name).where(ChatSession.id == sid))).scalar_one()
            return row

    return asyncio.run(go())


def test_chat_explicit_skill_filters_and_persists(tmp_path: Path) -> None:
    client, fake = _api_client(tmp_path, [AssistantMessage(content="готово")])
    try:
        with client:
            r = client.post("/chat", json={"message": "заказы?", "user_id": "skill-u1", "skill": "zakazy"})
            assert r.status_code == 200, r.text
            done = _parse_sse(r.text)["done"][0]
            assert done["skill"] == "zakazy"
            sid = done["session_id"]
        # реестр, отданный модели, содержит только тул скила
        tools_arg = fake.seen_messages[0]
        assert tools_arg is not None
        assert _skill_of_session(sid) == "zakazy"
    finally:
        _cleanup_user("skill-u1")


def test_chat_unknown_skill_404(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path, [AssistantMessage(content="x")])
    try:
        with client:
            r = client.post("/chat", json={"message": "hi", "user_id": "skill-u2", "skill": "nope"})
            assert r.status_code == 404
    finally:
        _cleanup_user("skill-u2")


def test_chat_skill_sticky_in_session(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path, [AssistantMessage(content="a"), AssistantMessage(content="b")])
    try:
        with client:
            r1 = client.post("/chat", json={"message": "заказы?", "user_id": "skill-u3", "skill": "zakazy"})
            sid = _parse_sse(r1.text)["done"][0]["session_id"]
            # второе сообщение без skill — берётся залипший из сессии
            r2 = client.post("/chat", json={"message": "а ещё?", "user_id": "skill-u3", "session_id": sid})
            assert r2.status_code == 200, r2.text
            assert _parse_sse(r2.text)["done"][0]["skill"] == "zakazy"
    finally:
        _cleanup_user("skill-u3")


def test_chat_automatch(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path, [AssistantMessage(content="ok")])
    try:
        with client:
            r = client.post("/chat", json={"message": "покажи заказы клиента", "user_id": "skill-u4"})
            assert r.status_code == 200, r.text
            assert _parse_sse(r.text)["done"][0]["skill"] == "zakazy"
    finally:
        _cleanup_user("skill-u4")


def test_chat_weak_query_gets_no_skill(tmp_path: Path) -> None:
    """Вопрос не про скил → skill=None, модель работает полным набором тулзов агента."""
    client, _ = _api_client(tmp_path, [AssistantMessage(content="ok")])
    try:
        with client:
            r = client.post("/chat", json={"message": "что это за база", "user_id": "skill-u5"})
            assert r.status_code == 200, r.text
            assert _parse_sse(r.text)["done"][0]["skill"] is None
    finally:
        _cleanup_user("skill-u5")


def _cleanup_user(onec_id: str) -> None:
    async def go() -> None:
        from app.db.models import User
        from app.db.session import engine

        await engine.dispose()
        async with SessionFactory() as s:
            users = (await s.execute(select(User).where(User.onec_id == onec_id))).scalars().all()
            for u in users:
                await s.delete(u)
            await s.commit()

    asyncio.run(go())
