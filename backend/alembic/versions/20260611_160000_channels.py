"""channels: partner_channel_configs + dispatch_attempts (M3.2)

Таблицы каналов доставки (§6.4) и попыток диспетчеризации (§6.5). Enum-поля —
VARCHAR (native_enum=False).

Revision ID: 20260611_160000_channels
Revises: 20260611_133000_service_requests
Create Date: 2026-06-11 16:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260611_160000_channels"
down_revision: str | None = "20260611_133000_service_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUM_LEN = 32


def upgrade() -> None:
    op.create_table(
        "partner_channel_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("collaborator_id", sa.String(length=255), nullable=False),
        sa.Column("channel_type", sa.String(length=_ENUM_LEN), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column(
            "config", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("inbound_token", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("health", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "collaborator_id", "channel_type", name="uq_partner_channel_collaborator_type"
        ),
    )
    op.create_index(
        "ix_partner_channel_configs_collaborator_id",
        "partner_channel_configs",
        ["collaborator_id"],
    )

    op.create_table(
        "dispatch_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_type", sa.String(length=_ENUM_LEN), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=_ENUM_LEN), nullable=False),
        sa.Column("provider_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("outbox_ref", sa.String(length=255), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id"], ["service_requests.id"], name="fk_dispatch_attempts_request_id"
        ),
    )
    op.create_index("ix_dispatch_attempts_request_id", "dispatch_attempts", ["request_id"])
    op.create_index("ix_dispatch_attempts_ts", "dispatch_attempts", ["ts"])
    op.create_index(
        "uq_dispatch_attempts_idempotency_key",
        "dispatch_attempts",
        ["idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("dispatch_attempts")
    op.drop_table("partner_channel_configs")
