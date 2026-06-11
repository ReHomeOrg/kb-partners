"""init

Empty initial migration — anchor head.

Создаёт пустую базу. Реальные таблицы (service_requests, request_messages,
request_history, partner_channel_configs, dispatch_attempts, automation_rules,
outbox) появятся в последующих миграциях эпиков M1+.

Revision ID: 20260611_120000_init
Revises:
Create Date: 2026-06-11 12:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "20260611_120000_init"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
