"""
Billing Engine Tables

Revision ID: 011
Revises: 010
Create Date: 2026-05-12

Adds four tables for the production billing engine:
  - subscription_audit_log   : immutable state-transition records
  - usage_aggregate          : daily/monthly API-call and cost rollups
  - idempotency_keys         : two-phase duplicate-charge prevention
  - webhook_events           : idempotent inbound webhook processing
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op


revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_audit_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.String(30), nullable=True),
        sa.Column("to_status", sa.String(30), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("actor", sa.String(50), nullable=False, server_default="system"),
        sa.Column("stripe_event_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_log_user_id", "subscription_audit_log", ["user_id"])
    op.create_index("ix_audit_log_created_at", "subscription_audit_log", ["created_at"])
    op.create_index("ix_audit_log_user_created", "subscription_audit_log", ["user_id", "created_at"])

    op.create_table(
        "usage_aggregate",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_type", sa.String(10), nullable=False),
        sa.Column("period_key", sa.String(10), nullable=False),
        sa.Column("api_calls", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("compute_ms", sa.Float, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "period_type", "period_key", name="uq_usage_aggregate_period"),
    )
    op.create_index("ix_usage_aggregate_user_period", "usage_aggregate", ["user_id", "period_type", "period_key"])

    op.create_table(
        "idempotency_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="locked"),
        sa.Column("request_hash", sa.String(64), nullable=True),
        sa.Column("response_payload", sa.Text, nullable=True),
        sa.Column("response_status_code", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_idempotency_keys_key", "idempotency_keys", ["idempotency_key"])
    op.create_index("ix_idempotency_keys_user_id", "idempotency_keys", ["user_id"])
    op.create_index("ix_idempotency_keys_expires_at", "idempotency_keys", ["expires_at"])

    op.create_table(
        "webhook_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("stripe_event_id", sa.String(255), nullable=False, unique=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_webhook_events_stripe_event_id", "webhook_events", ["stripe_event_id"])
    op.create_index("ix_webhook_events_event_type", "webhook_events", ["event_type"])
    op.create_index("ix_webhook_events_created_at", "webhook_events", ["created_at"])
    op.create_index("ix_webhook_events_type_status", "webhook_events", ["event_type", "status"])


def downgrade() -> None:
    op.drop_table("webhook_events")
    op.drop_table("idempotency_keys")
    op.drop_table("usage_aggregate")
    op.drop_table("subscription_audit_log")
