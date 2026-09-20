"""Тесты вложений и context_size для POST /chat."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agent import ToolRegistry
from app.api.chat import get_llm, get_registry
from app.db.models import User
from app.db.session import SessionFactory, engine
from app.llm import AssistantMessage
from app.main import app
from app.tools import MOCK_ONEC_TOOLS
from tests.fake_llm import FakeLLM

TEST_USER_A = "test-attach-u1"
TEST_USER_C = "test-ctx-u1"


def _client(script: list[AssistantMessage]) -> tuple[TestClient, FakeLLM]:
    fake = FakeLLM(script)
    app.dependency_overrides[get_llm] = lambda: fake
    app.dependency_overrides[get_registry] = lambda: ToolRegistry(MOCK_ONEC_TOOLS)
    return TestClient(app), fake


def _parse_sse(body: str) -> dict[str, list[dict[str, Any]]]:
    events: dict[str, list[dict[str, Any]]] = {}
    event = ""
    for line in body.splitlines():
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            events.setdefault(event, []).append(json.loads(line.split(":", 1)[1]))
    return events


def _cleanup(user_id: str) -> None:
    async def go() -> None:
        await engine.dispose()
        async with SessionFactory() as s:
            users = (await s.execute(select(User).where(User.onec_id == user_id))).scalars().all()
            for u in users:
                await s.delete(u)
            await s.commit()

    asyncio.run(go())


def test_chat_with_image_attachment_multimodal() -> None:
    fake_messages = [AssistantMessage(content="готово")]
    client, fake = _client(fake_messages)
    b64 = base64.b64encode(b"fake-png-bytes").decode()
    try:
        with client:
            r = client.post(
                "/chat",
                json={
                    "message": "что на картинке?",
                    "user_id": TEST_USER_A,
                    "attachments": [
                        {"filename": "cat.png", "mime_type": "image/png", "content_base64": b64},
                        {"filename": "doc.pdf", "mime_type": "application/pdf", "content_base64": b64},
                    ],
                },
            )
            assert r.status_code == 200, r.text
            assert "text/event-stream" in r.headers.get("content-type", "")
        # Проверяем что LLM получил multimodal content с image_url
        assert len(fake.seen_messages) == 1
        msgs = fake.seen_messages[0]
        # последнее сообщение — user с list content
        user_msg = msgs[-1]
        assert user_msg["role"] == "user"
        content = user_msg["content"]
        assert isinstance(content, list), f"content должен быть list, получен {type(content)}"
        types = [p.get("type") for p in content]
        assert "text" in types
        assert "image_url" in types
        # image_url должен быть data URI
        img_parts = [p for p in content if p.get("type") == "image_url"]
        assert any("data:image/png;base64," in p["image_url"]["url"] for p in img_parts)
        # для pdf — текстовый маркер
        text_parts = [p for p in content if p.get("type") == "text"]
        assert any("doc.pdf" in p["text"] for p in text_parts)
    finally:
        _cleanup(TEST_USER_A)


def test_chat_attachment_aliases_name_mime_data_base64() -> None:
    """Форма 1С шлёт {name, mime, data_base64} — псевдонимы должны приняться."""
    client, fake = _client([AssistantMessage(content="ok")])
    b64 = base64.b64encode(b"xyz").decode()
    try:
        with client:
            r = client.post(
                "/chat",
                json={
                    "message": "alias test",
                    "user_id": TEST_USER_A,
                    "attachments": [{"name": "pic.jpg", "mime": "image/jpeg", "data_base64": b64}],
                },
            )
            assert r.status_code == 200, r.text
        user_msg = fake.seen_messages[0][-1]
        content = user_msg["content"]
        assert isinstance(content, list)
        assert any(p.get("type") == "image_url" for p in content)
    finally:
        _cleanup(TEST_USER_A)


def test_chat_context_size_limits_history() -> None:
    """context_size=N передаёт только N последних пар."""
    # создаём сессию с двумя раундами истории
    client, fake = _client(
        [
            AssistantMessage(content="ans1"),
            AssistantMessage(content="ans2"),
            AssistantMessage(content="final"),
        ]
    )
    try:
        with client:
            r1 = client.post("/chat", json={"message": "hello1", "user_id": TEST_USER_C})
            assert r1.status_code == 200, r1.text
            sid = _parse_sse(r1.text)["done"][0]["session_id"]
            r2 = client.post("/chat", json={"message": "hello2", "user_id": TEST_USER_C, "session_id": sid})
            assert r2.status_code == 200, r2.text
            # третий запрос с context_size=1 — должен увидеть только последнюю пару до себя
            # сбрасываем fake script для третьего вызова
            fake2 = FakeLLM([AssistantMessage(content="final")])
            app.dependency_overrides[get_llm] = lambda: fake2
            r3 = client.post(
                "/chat",
                json={"message": "hello3", "user_id": TEST_USER_C, "session_id": sid, "context_size": 1},
            )
            assert r3.status_code == 200, r3.text
            # Проверяем что в третьем вызове история ограничена
            assert len(fake2.seen_messages) == 1
            msgs = fake2.seen_messages[0]
            # system + history (2 сообщения) + user = 4
            # при context_size=1 history = 2 сообщения (последняя пара)
            assert msgs[0]["role"] == "system"
            history_slice = msgs[1:-1]
            assert len(history_slice) == 2, f"ожидали 2 сообщения истории, получили {history_slice}"
            # должны быть последние сообщения: hello2 и ans2
            assert any("hello2" in str(m.get("content")) for m in history_slice)
            assert any("ans2" in str(m.get("content")) for m in history_slice)
            # hello1 не должен попасть в ограниченную историю
            assert not any("hello1" in str(m.get("content")) for m in history_slice)
    finally:
        _cleanup(TEST_USER_C)


def test_chat_background_query_param_accepted() -> None:
    """?background=true не должен ломать SSE, а возвращать JSON с job_id."""
    client, fake = _client([AssistantMessage(content="bg answer")])
    try:
        with client:
            r = client.post("/chat?background=true", json={"message": "bg?", "user_id": "test-bg-u1"})
            assert r.status_code == 200, r.text
            data = r.json()
            assert "job_id" in data
            assert data["status"] == "running"
            assert "session_id" in data
            job_id = data["job_id"]
            # polling endpoint должен отвечать
            r2 = client.get(f"/chat/result/{job_id}")
            assert r2.status_code in (200, 404)  # 200 running/done, 404 если не найден
    finally:
        _cleanup("test-bg-u1")
        # cleanup job store
        from app.api.chat import _background_jobs

        _background_jobs.clear()
