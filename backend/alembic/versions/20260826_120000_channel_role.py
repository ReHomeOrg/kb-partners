"""partner_channel_configs.role: канал-копия vs основной канал (ADR-0006, issue #3)

Revision ID: 20260826_120000_channel_role
Revises: 20260730_120000_scheduled_at
Create Date: 2026-08-26 12:00:00

Дефолт PRIMARY: существующие конфигурации продолжают работать как фолбэк, поведение
диспетча не меняется, пока роль не проставлена явно.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_120000_channel_role"
down_revision: str | None = "20260730_120000_scheduled_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "partner_channel_configs",
        sa.Column(
            "role",
            sa.String(length=32),
            nullable=False,
            server_default="PRIMARY",
        ),
    )


def downgrade() -> None:
    op.drop_column("partner_channel_configs", "role")
