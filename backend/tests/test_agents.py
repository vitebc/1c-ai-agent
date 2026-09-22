"""Тесты мультиагентности: парсинг AGENT.md, резолв, фильтры, RAG-изоляция, API."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.agent import ToolRegistry, run_agent
from app.agents import AgentRegistry
from app.api.chat import get_agent_registry, get_llm, get_registry, get_skill_registry
from app.db.models import ChatSession, Chunk, Document
from app.db.session import SessionFactory
from app.llm import AssistantMessage
from app.main import app
from app.rag import FakeEmbeddings, ingest_file, retrieve
from app.skills import SkillRegistry
from app.tools import MOCK_ONEC_TOOLS
from tests.fake_llm import FakeLLM
from tests.test_chat_api import _parse_sse

REPO_AGENTS = Path(__file__).resolve().parent.parent / "agents"

GOOD_MD = """---
name: test-agent
title: Тестовый
description: тестовый агент
tools: [get_counterparty]
skills: [zakazy]
mcp: default
model:
---

Промпт агента.
"""


def _write_agent(root: Path, dirname: str, content: str) -> Path:
    d = root / dirname
    d.mkdir(parents=True)
    p = d / "AGENT.md"
    p.write_text(content, encoding="utf-8")
    return p


def _write_skill(root: Path, dirname: str, name: str) -> None:
    d = root / dirname
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: заказы клиента\ntools: [get_counterparty]\n---\n\nПравило.\n",
        encoding="utf-8",
    )


def test_parse_repo_agents() -> None:
    """Три поставленных агента обязаны оставаться валидными."""
    reg = AgentRegistry.load(REPO_AGENTS)
    assert not reg.errors, reg.errors
    assert sorted(reg.names) == ["analyst", "assistant", "tz-helper"]
    assistant = reg.get("assistant")
    assert assistant is not None and assistant.allows_all_skills
    assert assistant.title == "Ассистент"
    tz = reg.get("tz-helper")
    assert tz is not None
    assert tz.tools == ("search_knowledge_base",)
    assert tz.skills == ()
    assert not tz.allows_skill("zakazy-prokudina")
    analyst = reg.get("analyst")
    assert analyst is not None and "execute_select" in analyst.tools
    # Дата-агенты обязаны знать про ленивую подгрузку паттерна запросов.
    for name in ("assistant", "analyst"):
        agent = reg.get(name)
        assert agent is not None
        assert 'get_pattern({"name": "query-patterns"})' in agent.prompt
        assert "get_pattern" in agent.tools
        assert agent.max_rounds is None  # дефолт 15
    tz = reg.get("tz-helper")
    assert tz is not None and "get_pattern" not in tz.tools
    assert tz.max_rounds == 8
    assert AgentRegistry.load(REPO_AGENTS).get("assistant").max_rounds is None  # type: ignore[union-attr]


def test_bad_agent_files_skipped(tmp_path: Path) -> None:
    _write_agent(tmp_path, "bad1", "no frontmatter")
    _write_agent(tmp_path, "other", GOOD_MD)  # name test-agent != папка other
    _write_agent(tmp_path, "test-agent", GOOD_MD)
    reg = AgentRegistry.load(tmp_path)
    assert reg.names == ["test-agent"]
    assert len(reg.errors) == 2
    _write_agent(tmp_path, "bad-max", GOOD_MD.replace("mcp: default", "mcp: default\nmax_rounds: 99"))
    reg2 = AgentRegistry.load(tmp_path)
    assert reg2.names == ["test-agent"]
    assert len(reg2.errors) == 3


def test_load_missing_dir_returns_empty() -> None:
    reg = AgentRegistry.load("/definitely/not/here")
    assert reg.names == [] and reg.errors == []


def test_run_agent_uses_agent_prompt() -> None:
    llm = FakeLLM([AssistantMessage(content="ok")])
    res = asyncio.run(
        run_agent(
            llm=llm,
            registry=ToolRegistry(MOCK_ONEC_TOOLS),
            user_message="тест",
            base_system="ПРОМПТ-АГЕНТА",
            extra_system="# Скилл: s\nПравило.",
            agent_name="test-agent",
            skill_name="s",
        )
    )
    assert res.answer == "ok"
    system = llm.seen_messages[0][0]["content"]
    assert "ПРОМПТ-АГЕНТА" in system
    assert "Правило." in system
    assert "Ты — ассистент пользователей 1С" not in system


def _api_client(tmp_path: Path, script: list[AssistantMessage]) -> tuple[TestClient, FakeLLM]:
    agents_dir = tmp_path / "agents"
    skills_dir = tmp_path / "skills"
    assistant_md = (
        "---\nname: assistant\ntitle: Ассистент\ndescription: общий\n"
        'tools: [get_counterparty, get_stock_balance]\nskills: ["*"]\n'
        "mcp: default\nmodel:\n---\n\nПромпт ассистента.\n"
    )
    tz_md = (
        "---\nname: tz\ntitle: ТЗ\ndescription: требования\n"
        "tools: [search_knowledge_base]\nskills: []\n"
        "mcp: default\nmodel:\n---\n\nПромпт ТЗ.\n"
    )
    _write_agent(agents_dir, "assistant", assistant_md)
    _write_agent(agents_dir, "tz", tz_md)
    _write_skill(skills_dir, "zakazy", "zakazy")
    fake = FakeLLM(script)
    app.dependency_overrides[get_llm] = lambda: fake
    app.dependency_overrides[get_registry] = lambda: ToolRegistry(MOCK_ONEC_TOOLS)
    app.dependency_overrides[get_skill_registry] = lambda: SkillRegistry.load(skills_dir)
    app.dependency_overrides[get_agent_registry] = lambda: AgentRegistry.load(agents_dir)
    return TestClient(app), fake


def _agent_skill_of_session(sid: int) -> tuple[str | None, str | None]:
    async def go() -> tuple[str | None, str | None]:
        from app.db.session import engine

        await engine.dispose()
        async with SessionFactory() as s:
            row = (
                await s.execute(select(ChatSession.agent_name, ChatSession.skill_name).where(ChatSession.id == sid))
            ).one()
            return row[0], row[1]

    return asyncio.run(go())


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


def test_list_agents(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path, [AssistantMessage(content="x")])
    try:
        with client:
            r = client.get("/agents")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["default"] == "assistant"
            assert sorted(a["name"] for a in body["agents"]) == ["assistant", "tz"]
            assert body["errors"] == []
    finally:
        pass


def test_list_skills_filtered_by_agent(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path, [AssistantMessage(content="x")])
    try:
        with client:
            assert len(client.get("/skills").json()["skills"]) == 1
            assert len(client.get("/skills", params={"agent": "assistant"}).json()["skills"]) == 1
            assert client.get("/skills", params={"agent": "tz"}).json()["skills"] == []
            assert client.get("/skills", params={"agent": "nope"}).status_code == 404
    finally:
        pass


def test_chat_default_agent(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path, [AssistantMessage(content="готово")])
    try:
        with client:
            r = client.post("/chat", json={"message": "привет", "user_id": "agent-u1"})
            assert r.status_code == 200, r.text
            done = _parse_sse(r.text)["done"][0]
            assert done["agent"] == "assistant"
            assert _agent_skill_of_session(done["session_id"])[0] == "assistant"
    finally:
        _cleanup_user("agent-u1")


def test_chat_unknown_agent_404(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path, [AssistantMessage(content="x")])
    try:
        with client:
            r = client.post("/chat", json={"message": "hi", "user_id": "agent-u2", "agent": "nope"})
            assert r.status_code == 404
    finally:
        _cleanup_user("agent-u2")


def test_chat_skill_not_allowed_for_agent_404(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path, [AssistantMessage(content="x")])
    try:
        with client:
            r = client.post("/chat", json={"message": "hi", "user_id": "agent-u3", "agent": "tz", "skill": "zakazy"})
            assert r.status_code == 404
    finally:
        _cleanup_user("agent-u3")


def test_chat_agent_sticky_in_session(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path, [AssistantMessage(content="a"), AssistantMessage(content="b")])
    try:
        with client:
            r1 = client.post("/chat", json={"message": "тз?", "user_id": "agent-u4", "agent": "tz"})
            sid = _parse_sse(r1.text)["done"][0]["session_id"]
            r2 = client.post("/chat", json={"message": "ещё", "user_id": "agent-u4", "session_id": sid})
            assert r2.status_code == 200, r2.text
            assert _parse_sse(r2.text)["done"][0]["agent"] == "tz"
    finally:
        _cleanup_user("agent-u4")


def test_chat_agent_switch_resets_foreign_skill(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path, [AssistantMessage(content="a"), AssistantMessage(content="b")])
    try:
        with client:
            r1 = client.post(
                "/chat",
                json={"message": "заказы?", "user_id": "agent-u5", "agent": "assistant", "skill": "zakazy"},
            )
            sid = _parse_sse(r1.text)["done"][0]["session_id"]
            assert _parse_sse(r1.text)["done"][0]["skill"] == "zakazy"
            r2 = client.post("/chat", json={"message": "тз?", "user_id": "agent-u5", "session_id": sid, "agent": "tz"})
            assert r2.status_code == 200, r2.text
            done = _parse_sse(r2.text)["done"][0]
            assert done["agent"] == "tz"
            assert done["skill"] is None
    finally:
        _cleanup_user("agent-u5")


RAG_CASES = [
    ("TEST_AGENT_DOC_A", "TEST_AGENT_MARKER_ALFA_7", "agent-a"),
    ("TEST_AGENT_DOC_B", "TEST_AGENT_MARKER_BETA_8", "agent-b"),
    ("TEST_AGENT_DOC_COMMON", "TEST_AGENT_MARKER_OBSHIY_9", None),
]


async def _rag_scenario() -> None:
    emb = FakeEmbeddings()
    paths = []
    try:
        async with SessionFactory() as s:
            for title, _, _ in RAG_CASES:
                await s.execute(delete(Document).where(Document.title == title))
            await s.commit()
        ids = {}
        for title, marker, agent in RAG_CASES:
            p = Path(f"/tmp/{title}.md")
            p.write_text(f"# Тест\n\n{marker} находится именно здесь.\n", encoding="utf-8")
            paths.append(p)
            ids[title] = await ingest_file(
                p, access_profile="all", session_factory=SessionFactory, embeddings=emb, agent_name=agent
            )
        assert all(v > 0 for v in ids.values())

        async def texts(agent: str) -> list[str]:
            async with SessionFactory() as s:
                chunk_text = (
                    (
                        await s.execute(
                            select(Chunk.text)
                            .where(Chunk.document_id == ids["TEST_AGENT_DOC_A"])
                            .order_by(Chunk.position)
                        )
                    )
                    .scalars()
                    .first()
                )
            assert chunk_text
            rows = await retrieve(
                session_factory=SessionFactory,
                embeddings=emb,
                query=chunk_text,
                access_profile="all",
                top_k=10,
                agent_name=agent,
            )
            return [r["text"] for r in rows]

        a_texts = await texts("agent-a")
        assert any("ALFA_7" in t for t in a_texts)
        assert any("OBSHIY_9" in t for t in a_texts)
        assert all("BETA_8" not in t for t in a_texts)
        b_texts = await texts("agent-b")
        assert all("ALFA_7" not in t for t in b_texts)
    finally:
        async with SessionFactory() as s:
            for title, _, _ in RAG_CASES:
                await s.execute(delete(Document).where(Document.title == title))
            await s.commit()
        for p in paths:
            p.unlink(missing_ok=True)


def test_rag_isolation_by_agent() -> None:
    asyncio.run(_rag_scenario())
