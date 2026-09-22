"""Мультиагентность: sessions.agent_name + documents.agent_name (RAG-изоляция).

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-22

documents.agent_name NULL = общий документ, виден всем агентам.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("agent_name", sa.String(64), nullable=True))
    op.add_column("documents", sa.Column("agent_name", sa.String(64), nullable=True))
    op.create_index("ix_documents_agent_name", "documents", ["agent_name"])


def downgrade() -> None:
    op.drop_index("ix_documents_agent_name", table_name="documents")
    op.drop_column("documents", "agent_name")
    op.drop_column("sessions", "agent_name")
