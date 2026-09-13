"""Тесты инжеста и retrieval на живом postgres (нужен `up -d postgres`).

Пишут документы с префиксом TEST_ и удаляют за собой. Весь тест — один
asyncio.run (пул коннектов привязан к loop, см. conftest).

Fake-эмбеддинги случайны, поэтому запрос — ТОЧНЫЙ текст чанка из БД
(прочитан обратно): distance 0 всегда ранжируется первым. Это же делает
тест прав сильным: чанк с distance 0 чужой профиль увидеть не должен.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import delete, func, select

from app.db.models import Chunk, Document
from app.db.session import SessionFactory
from app.rag import FakeEmbeddings, ingest_file, retrieve

MARKER = "TEST_RAG_UNIKALNAYA_STROKA_42"
TITLE = "TEST_doc"


async def _scenario() -> None:
    path = Path("/tmp/test_rag_doc.md")
    path.write_text(f"# Тест\n\n{MARKER} находится именно здесь.\n", encoding="utf-8")
    try:
        emb = FakeEmbeddings()
        async with SessionFactory() as s:
            await s.execute(delete(Document).where(Document.title == TITLE))
            await s.commit()
        doc_id = await ingest_file(path, access_profile="sales", session_factory=SessionFactory, embeddings=emb)
        assert doc_id > 0

        async with SessionFactory() as s:
            chunk_text = (
                (await s.execute(select(Chunk.text).where(Chunk.document_id == doc_id).order_by(Chunk.position)))
                .scalars()
                .first()
            )
        assert chunk_text and MARKER in chunk_text

        async def search(profile: str) -> list[dict[str, str]]:
            return await retrieve(
                session_factory=SessionFactory,
                embeddings=emb,
                query=chunk_text,
                access_profile=profile,
                top_k=5,
            )

        # Точный текст чанка — первый результат.
        assert (await search("all"))[0]["text"] == chunk_text
        assert (await search("sales"))[0]["text"] == chunk_text
        # Чужой профиль не видит даже distance-0 чанк: фильтр в WHERE, не постфактум.
        assert all(MARKER not in r["text"] for r in await search("accounting"))

        async with SessionFactory() as s:
            n = await s.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id == doc_id))
            assert (n or 0) >= 1
    finally:
        async with SessionFactory() as s:
            await s.execute(delete(Document).where(Document.title == TITLE))
            await s.commit()
        path.unlink(missing_ok=True)


def test_ingest_and_retrieve_with_rights() -> None:
    asyncio.run(_scenario())
