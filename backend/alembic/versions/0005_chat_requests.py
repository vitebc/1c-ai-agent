"""Статистика обращений: таблица chat_requests.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-01

Хранит метаданные каждого запроса /chat: пользователь, база, агент, скил,
модель, токены, время, тулзы. Для отчётов и дашборда в ai-1c-server.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("base_name", sa.String(128), nullable=True),
        sa.Column("base_url", sa.String(256), nullable=True),
        sa.Column("agent", sa.String(64), nullable=True),
        sa.Column("skill", sa.String(64), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="ok"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rounds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("elapsed_s", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_requests_user_id", "chat_requests", ["user_id"])
    op.create_index("ix_chat_requests_base_name", "chat_requests", ["base_name"])
    op.create_index("ix_chat_requests_agent", "chat_requests", ["agent"])
    op.create_index("ix_chat_requests_created_at", "chat_requests", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_requests_created_at", table_name="chat_requests")
    op.drop_index("ix_chat_requests_agent", table_name="chat_requests")
    op.drop_index("ix_chat_requests_base_name", table_name="chat_requests")
    op.drop_index("ix_chat_requests_user_id", table_name="chat_requests")
    op.drop_table("chat_requests")
