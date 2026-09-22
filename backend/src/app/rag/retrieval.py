"""Поиск по базе знаний: embed -> cosine в pgvector -> фильтр прав.

Фильтр (см. AGENTS.md, «Схема запросов»): документ с access_profile='all'
виден всем; остальные — только пользователям с тем же профилем; профиль
пользователя 'all' (админ) видит всё. Фильтрация — WHERE-клаузой на этапе
retrieval, а не постобработкой.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.tools import ToolContext, ToolDefinition
from app.db.models import Chunk, Document
from app.rag.embeddings import Embeddings


class KbSearchArgs(BaseModel):
    query: str = Field(min_length=2)
    top_k: int = Field(default=5, le=10)


async def retrieve(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    embeddings: Embeddings,
    query: str,
    access_profile: str,
    top_k: int = 5,
    agent_name: str = "",
) -> list[dict[str, str]]:
    vectors = await embeddings.embed([query])
    stmt = (
        select(Document.title, Chunk.text)
        .join(Chunk, Chunk.document_id == Document.id)
        .order_by(Chunk.embedding.cosine_distance(vectors[0]))
        .limit(top_k)
    )
    if access_profile != "all":
        stmt = stmt.where(or_(Document.access_profile == "all", Document.access_profile == access_profile))
    if agent_name:
        # RAG-изоляция по агенту: общий документ (NULL) виден всем агентам.
        stmt = stmt.where(or_(Document.agent_name.is_(None), Document.agent_name == agent_name))
    async with session_factory() as session:
        rows = (await session.execute(stmt)).all()
    return [{"title": title, "text": text} for title, text in rows]


def make_kb_search(
    session_factory: async_sessionmaker[AsyncSession],
    embeddings: Embeddings,
) -> ToolDefinition:
    async def handler(args: KbSearchArgs, ctx: ToolContext) -> str:
        rows = await retrieve(
            session_factory=session_factory,
            embeddings=embeddings,
            query=args.query,
            access_profile=ctx.access_profile,
            top_k=args.top_k,
            agent_name=ctx.agent_name,
        )
        if not rows:
            return json.dumps(
                {"found": False, "hint": "В базе знаний ничего не нашлось. Ответь без неё."},
                ensure_ascii=False,
            )
        return json.dumps({"found": True, "fragments": rows}, ensure_ascii=False)

    return ToolDefinition(
        name="search_knowledge_base",
        description="Поиск по корпоративной базе знаний (регламенты, инструкции, каталог отчётов). "
        "Используй для вопросов про правила, сроки, скидки, процедуры.",
        args_model=KbSearchArgs,
        handler=handler,
    )
