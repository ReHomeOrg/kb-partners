"""push_subscriptions: web-push подписки портала (M11.4, E8, ADR-0004)

Revision ID: 20260611_190000_push
Revises: 20260611_180000_outbox
Create Date: 2026-06-11 19:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260611_190000_push"
down_revision: str | None = "20260611_180000_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("audience", sa.String(length=32), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_push_subscriptions_owner_id", "push_subscriptions", ["owner_id"])
    op.create_index(
        "uq_push_subscriptions_owner_endpoint",
        "push_subscriptions",
        ["owner_id", "endpoint"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("push_subscriptions")
