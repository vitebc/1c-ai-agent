"""SQLAlchemy-модели. DDL — в alembic-миграциях, здесь только объявления."""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 1024  # deepvk/USER-bge-m3; fake-эмбеддинги той же размерности


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Идентификатор пользователя 1С из токена сессии (см. AGENTS.md, «Схема запросов»).
    onec_id: Mapped[str] = mapped_column(String(128), unique=True)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    # Профиль прав для фильтрации retrieval: 'all' видит всё.
    access_profile: Mapped[str] = mapped_column(String(64), default="all")


class ChatSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(256), default="")
    # Имя ИБ 1С (НРег): сессии разных баз не смешиваем.
    base_name: Mapped[str | None] = mapped_column(String(128), default=None)
    # Рантайм-скил сессии (backend/skills/<name>); NULL — без скила.
    skill_name: Mapped[str | None] = mapped_column(String(64), default=None)
    # Рантайм-агент сессии (backend/agents/<name>); NULL — дефолтный.
    agent_name: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    source: Mapped[str] = mapped_column(String(1024), default="")
    # Профиль прав: чанки документа видит только пользователь с таким же
    # access_profile либо 'all'. 'all' у документа = виден всем.
    access_profile: Mapped[str] = mapped_column(String(64), default="all")
    # Рантайм-агент RAG-изоляции (backend/agents/<name>); NULL — общий документ.
    agent_name: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(default=0)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Vector] = mapped_column(Vector(EMBEDDING_DIM))
