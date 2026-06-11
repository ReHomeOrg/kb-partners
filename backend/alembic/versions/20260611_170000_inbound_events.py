"""inbound_events: дедуп/replay-защита входящих (M3.3, E5)

Revision ID: 20260611_170000_inbound_events
Revises: 20260611_160000_channels
Create Date: 2026-06-11 17:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260611_170000_inbound_events"
down_revision: str | None = "20260611_160000_channels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inbound_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel_config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nonce", sa.String(length=255), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["channel_config_id"],
            ["partner_channel_configs.id"],
            name="fk_inbound_events_channel_config_id",
        ),
        sa.UniqueConstraint("channel_config_id", "nonce", name="uq_inbound_events_channel_nonce"),
    )


def downgrade() -> None:
    op.drop_table("inbound_events")
