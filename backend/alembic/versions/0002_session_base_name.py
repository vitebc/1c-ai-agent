"""sessions.base_name: имя ИБ 1С для мультибазовости.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("base_name", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "base_name")
