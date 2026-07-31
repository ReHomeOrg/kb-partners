"""request scheduled_at: дата визита исполнителя для reschedule (issue #4)

Revision ID: 20260730_120000_scheduled_at
Revises: 20260611_190000_push
Create Date: 2026-07-30 12:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_120000_scheduled_at"
down_revision: str | None = "20260611_190000_push"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "service_requests",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_service_requests_scheduled_at", "service_requests", ["scheduled_at"])


def downgrade() -> None:
    op.drop_index("ix_service_requests_scheduled_at", table_name="service_requests")
    op.drop_column("service_requests", "scheduled_at")
