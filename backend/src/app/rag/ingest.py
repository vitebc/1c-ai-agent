"""Инжест документов в RAG-хранилище: load -> chunk -> embed -> insert.

Сейчас — markdown/txt без внешних зависимостей. PDF/DOCX через Docling —
когда появятся реальные документы (см. backend/README, «Отложено»).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Chunk, Document
from app.rag.chunking import split_markdown
from app.rag.embeddings import Embeddings

_TEXT_SUFFIXES = {".md", ".markdown", ".txt"}


def load_text(path: Path) -> str:
    if path.suffix.lower() not in _TEXT_SUFFIXES:
        raise RuntimeError(
            f"{path.suffix}: нужен Docling (PDF/DOCX) — отложено до реальных документов. "
            "Сейчас инжестятся только .md/.txt."
        )
    return path.read_text(encoding="utf-8")


async def ingest_file(
    path: Path,
    *,
    access_profile: str,
    session_factory: async_sessionmaker[AsyncSession],
    embeddings: Embeddings,
    title: str | None = None,
    agent_name: str | None = None,
) -> int:
    text = load_text(path)
    chunks = split_markdown(text)
    if not chunks:
        raise ValueError(f"В {path} нет текста для инжеста")
    vectors = await embeddings.embed(chunks)
    async with session_factory() as session:
        doc = Document(
            title=title or path.stem,
            source=str(path),
            access_profile=access_profile,
            agent_name=agent_name,
        )
        session.add(doc)
        await session.flush()
        for i, (chunk_text, vec) in enumerate(zip(chunks, vectors, strict=True)):
            session.add(Chunk(document_id=doc.id, position=i, text=chunk_text, embedding=vec))
        await session.commit()
        return doc.id
