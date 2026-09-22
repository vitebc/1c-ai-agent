"""Тест POST /chat: фейковый LLM, мок-реестр, живой postgres для истории.

Нужен `up -d postgres`. Тестовый пользователь удаляется в конце.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.agent import ToolRegistry
from app.api.chat import get_llm, get_registry
from app.db.models import Message, User
from app.db.session import SessionFactory
from app.llm import AssistantMessage, ToolCall
from app.main import app
from app.tools import MOCK_ONEC_TOOLS
from tests.fake_llm import FakeLLM

TEST_USER = "test-chat-u1"


def _client(script: list[AssistantMessage]) -> TestClient:
    fake = FakeLLM(script)
    app.dependency_overrides[get_llm] = lambda: fake
    app.dependency_overrides[get_registry] = lambda: ToolRegistry(MOCK_ONEC_TOOLS)
    return TestClient(app)


def _parse_sse(body: str) -> dict[str, list[dict[str, Any]]]:
    events: dict[str, list[dict[str, Any]]] = {}
    event = ""
    for line in body.splitlines():
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            events.setdefault(event, []).append(json.loads(line.split(":", 1)[1]))
    return events


def _cleanup() -> None:
    """Удаление тестового пользователя. Отдельный loop -> сначала сброс пула."""

    async def go() -> None:
        from app.db.session import engine

        await engine.dispose()
        async with SessionFactory() as s:
            users = (await s.execute(select(User).where(User.onec_id == TEST_USER))).scalars().all()
            for u in users:
                await s.delete(u)  # sessions/messages — ON DELETE CASCADE в БД
            await s.commit()

    asyncio.run(go())


def test_chat_round_trip_and_history() -> None:
    script = [
        AssistantMessage(
            content=None,
            tool_calls=[ToolCall(id="c1", name="get_stock_balance", arguments='{"sku": "стул"}')],
        ),
        AssistantMessage(content="На основном 42."),
        AssistantMessage(content="Кресел 5."),
    ]
    client = _client(script)
    try:
        with client:
            r1 = client.post("/chat", json={"message": "сколько стульев?", "user_id": TEST_USER})
            assert r1.status_code == 200, r1.text
            r2 = client.post(
                "/chat",
                json={
                    "message": "а кресел?",
                    "user_id": TEST_USER,
                    "session_id": _parse_sse(r1.text)["done"][0]["session_id"],
                },
            )
            assert r2.status_code == 200, r2.text
        ev1 = _parse_sse(r1.text)
        assert [e["tool"] for e in ev1.get("tool", [])] == ["get_stock_balance"]
        assert "42" in "".join(e["delta"] for e in ev1.get("answer", []))
        session_id = ev1["done"][0]["session_id"]
        assert _parse_sse(r2.text)["done"][0]["session_id"] == session_id

        import asyncio

        from app.db.session import engine

        async def count() -> int:
            await engine.dispose()  # count идёт в другом loop, чем портал TestClient
            async with SessionFactory() as s:
                res = await s.execute(select(func.count()).select_from(Message).where(Message.session_id == session_id))
                return int(res.scalar() or 0)

        # 2 вопроса + 2 ответа
        assert asyncio.run(count()) == 4
    finally:
        _cleanup()


def test_chat_base_name_splits_session() -> None:
    """Сессия чужой базы не переиспользуется: история баз не смешивается."""
    from app.db.models import ChatSession

    client = _client([AssistantMessage(content="a1"), AssistantMessage(content="a2")])
    try:
        with client:
            r1 = client.post("/chat", json={"message": "q1", "user_id": TEST_USER, "base_name": "base_a"})
            assert r1.status_code == 200, r1.text
            sid_a = _parse_sse(r1.text)["done"][0]["session_id"]
            # Тот же session_id, но другая база -> новая сессия.
            r2 = client.post(
                "/chat", json={"message": "q2", "user_id": TEST_USER, "session_id": sid_a, "base_name": "base_b"}
            )
            assert r2.status_code == 200, r2.text
            sid_b = _parse_sse(r2.text)["done"][0]["session_id"]
            assert sid_b != sid_a

        import asyncio

        from app.db.session import engine

        async def bases() -> dict[int, str | None]:
            await engine.dispose()
            async with SessionFactory() as s:
                rows = (await s.execute(select(ChatSession.id, ChatSession.base_name))).all()
                return {i: b for i, b in rows}

        mapping = asyncio.run(bases())
        assert mapping[sid_a] == "base_a"
        assert mapping[sid_b] == "base_b"
    finally:
        _cleanup()


def test_chat_unknown_session_404() -> None:
    client = _client([AssistantMessage(content="x")])
    with client:
        r = client.post("/chat", json={"message": "hi", "user_id": TEST_USER, "session_id": 999999})
        assert r.status_code == 404
    _cleanup()


def test_cors_open_for_chat_form() -> None:
    client = _client([AssistantMessage(content="x")])
    with client:
        r = client.options(
            "/chat",
            headers={"Origin": "null", "Access-Control-Request-Method": "POST"},
        )
        assert r.headers.get("access-control-allow-origin") == "*"
