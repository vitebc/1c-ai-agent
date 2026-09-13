"""POST /chat: вопрос -> агент -> SSE-стрим событий с персистентностью.

События: `tool` (вызов инструмента), `answer` (финальный ответ кусками),
`done` (мета: session_id, rounds, tool_errors).
Настоящий токен-стриминг появится с локальной моделью; пока ответ режем кусками.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent import AgentResult, ToolRegistry, run_agent
from app.config import settings
from app.db.models import ChatSession, Message, User
from app.db.session import SessionFactory
from app.llm import ChatLLM, OpenAICompatibleLLM
from app.rag import build_embeddings, make_kb_search
from app.tools import MOCK_ONEC_TOOLS

router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: int | None = None
    # Идентификатор пользователя 1С. На шаге 3 сюда придёт OAuth-токен прокси.
    user_id: str = "dev"


async def get_llm() -> ChatLLM:
    return OpenAICompatibleLLM(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        top_p=settings.llm_top_p,
        top_k=settings.llm_top_k,
        repetition_penalty=settings.llm_repetition_penalty,
        enable_thinking=settings.llm_enable_thinking,
    )


async def get_registry() -> ToolRegistry:
    embeddings = build_embeddings(settings.embeddings_provider, settings.tei_base_url)
    return ToolRegistry(MOCK_ONEC_TOOLS + [make_kb_search(SessionFactory, embeddings)])


@router.post("/chat")
async def chat(
    req: ChatRequest,
    llm: ChatLLM = Depends(get_llm),  # noqa: B008 — идиома FastAPI
    registry: ToolRegistry = Depends(get_registry),  # noqa: B008 — идиома FastAPI
) -> StreamingResponse:
    async with SessionFactory() as session:
        user = (await session.execute(select(User).where(User.onec_id == req.user_id))).scalar_one_or_none()
        if user is None:
            user = User(onec_id=req.user_id, display_name=req.user_id)
            session.add(user)
            await session.flush()
        if req.session_id is not None:
            chat_session = (
                await session.execute(
                    select(ChatSession).where(ChatSession.id == req.session_id, ChatSession.user_id == user.id)
                )
            ).scalar_one_or_none()
            if chat_session is None:
                raise HTTPException(status_code=404, detail="session not found")
        else:
            chat_session = ChatSession(user_id=user.id, title=req.message[:80])
            session.add(chat_session)
            await session.flush()
        session.add(Message(session_id=chat_session.id, role="user", content=req.message))
        await session.commit()
        session_id, profile = chat_session.id, user.access_profile

    result = await run_agent(
        llm=llm,
        registry=registry,
        user_message=req.message,
        user_id=req.user_id,
        access_profile=profile,
        max_rounds=settings.agent_max_rounds,
    )

    async with SessionFactory() as session:
        session.add(Message(session_id=session_id, role="assistant", content=result.answer))
        await session.commit()

    return StreamingResponse(_events(session_id, result), media_type="text/event-stream")


async def _events(session_id: int, result: AgentResult) -> AsyncIterator[str]:
    for tool_name in result.tool_calls:
        yield f"event: tool\ndata: {json.dumps({'tool': tool_name}, ensure_ascii=False)}\n\n"
    # Ответ кусками по ~500 символов — скелет стриминга до токенного.
    for i in range(0, len(result.answer), 500):
        yield f"event: answer\ndata: {json.dumps({'delta': result.answer[i : i + 500]}, ensure_ascii=False)}\n\n"
    meta = {"session_id": session_id, "rounds": result.rounds, "tool_errors": result.tool_errors}
    yield f"event: done\ndata: {json.dumps(meta, ensure_ascii=False)}\n\n"
