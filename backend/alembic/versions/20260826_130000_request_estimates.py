"""request_estimates: оценка стоимости работ от партнёра (issue #6)

Revision ID: 20260826_130000_estimates
Revises: 20260730_120000_scheduled_at
Create Date: 2026-08-26 13:00:00

Оценку даёт партнёр по факту осмотра, чаще уже после выезда мастера. Храним
историей (append-only): «до выезда сказали X, после осмотра Y» — это первое, что
спрашивают при разборе с заявителем.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260826_130000_estimates"
down_revision: str | None = "20260730_120000_scheduled_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "request_estimates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("service_requests.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("amount_rub", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("eta_text", sa.String(length=255), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("author_id", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_request_estimates_request_id", "request_estimates", ["request_id"])
    op.create_index(
        "ix_request_estimates_request_created", "request_estimates", ["request_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_request_estimates_request_created", table_name="request_estimates")
    op.drop_index("ix_request_estimates_request_id", table_name="request_estimates")
    op.drop_table("request_estimates")
