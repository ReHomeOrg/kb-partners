"""service_requests core (M1.1)

Ядро заявки: таблицы service_requests / request_messages / request_history (ТЗ
§6.1–§6.3) + последовательность человекочитаемых номеров. Enum-поля — VARCHAR
(native_enum=False): добавление значений в M2+ не требует ALTER TYPE.

Revision ID: 20260611_133000_service_requests
Revises: 20260611_120000_init
Create Date: 2026-06-11 13:30:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260611_133000_service_requests"
down_revision: str | None = "20260611_120000_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Длина VARCHAR enum-колонок (синхронно с models._ENUM_LEN).
_ENUM_LEN = 32


def upgrade() -> None:
    # Последовательность для человекочитаемых номеров (RQ-NNNNNNNN), §6.1.
    op.execute(sa.schema.CreateSequence(sa.Sequence("service_request_number_seq")))

    op.create_table(
        "service_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("requester_id", sa.String(length=255), nullable=False),
        sa.Column("booking_id", sa.String(length=255), nullable=True),
        sa.Column("premises_id", sa.String(length=255), nullable=True),
        sa.Column("channel_in", sa.String(length=_ENUM_LEN), nullable=False),
        sa.Column("source_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_input", sa.Text(), nullable=False),
        sa.Column("raw_input_masked", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=_ENUM_LEN), nullable=True),
        sa.Column("product_code", sa.String(length=64), nullable=True),
        sa.Column("classification", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("partner_id", sa.String(length=255), nullable=True),
        sa.Column("match_trace", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fallback_chain", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("delivery_channel", sa.String(length=_ENUM_LEN), nullable=True),
        sa.Column("service_order_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=_ENUM_LEN), nullable=False),
        sa.Column("sla", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("amount_ref", sa.String(length=255), nullable=True),
        sa.Column("escrow_ref", sa.String(length=255), nullable=True),
        sa.Column("dispute_id", sa.String(length=255), nullable=True),
        sa.Column("claim_ref", sa.String(length=255), nullable=True),
        sa.Column("rating_ref", sa.String(length=255), nullable=True),
        sa.Column(
            "custom_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("access_level", sa.String(length=_ENUM_LEN), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by_user_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("number", name="uq_service_requests_number"),
    )
    op.create_index("ix_service_requests_requester_id", "service_requests", ["requester_id"])
    op.create_index("ix_service_requests_partner_id", "service_requests", ["partner_id"])
    op.create_index("ix_service_requests_status", "service_requests", ["status"])
    op.create_index("ix_service_requests_category", "service_requests", ["category"])
    op.create_index("ix_service_requests_created_at", "service_requests", ["created_at"])
    # Идемпотентность приёма: уникален только заполненный ключ (NULL не участвует).
    op.create_index(
        "uq_service_requests_idempotency_key",
        "service_requests",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "request_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_type", sa.String(length=_ENUM_LEN), nullable=False),
        sa.Column("author_id", sa.String(length=255), nullable=True),
        sa.Column("is_internal", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "attachments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["request_id"], ["service_requests.id"], name="fk_request_messages_request_id"
        ),
    )
    op.create_index("ix_request_messages_request_id", "request_messages", ["request_id"])

    op.create_table(
        "request_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=_ENUM_LEN), nullable=False),
        sa.Column("from_value", sa.String(length=255), nullable=True),
        sa.Column("to_value", sa.String(length=255), nullable=True),
        sa.Column(
            "ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["request_id"], ["service_requests.id"], name="fk_request_history_request_id"
        ),
    )
    op.create_index("ix_request_history_request_id", "request_history", ["request_id"])
    op.create_index("ix_request_history_ts", "request_history", ["ts"])


def downgrade() -> None:
    op.drop_table("request_history")
    op.drop_table("request_messages")
    op.drop_table("service_requests")
    op.execute(sa.schema.DropSequence(sa.Sequence("service_request_number_seq")))
