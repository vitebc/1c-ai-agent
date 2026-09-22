"""sessions.skill_name: рантайм-скил сессии (NULL — без скила).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("skill_name", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "skill_name")
