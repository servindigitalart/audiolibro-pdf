"""add affiliate system

Revision ID: 023
Revises: 022
Create Date: 2026-05-28

Adds:
  - affiliates table
  - affiliate_clicks table
  - affiliate_conversions table
  - users.referred_by_affiliate_id column (nullable FK to affiliates)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── affiliates ─────────────────────────────────────────────────────────────
    op.create_table(
        "affiliates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name",  sa.String(200), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("slug",  sa.String(50),  nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("commission_rate_pct", sa.Float, nullable=False, server_default="20.0"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_affiliates_slug",   "affiliates", ["slug"])
    op.create_index("idx_affiliates_status", "affiliates", ["status"])
    op.create_index("ix_affiliates_email",   "affiliates", ["email"])

    # ── users.referred_by_affiliate_id ─────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column(
            "referred_by_affiliate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("affiliates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_users_referred_by_affiliate_id", "users", ["referred_by_affiliate_id"])

    # ── affiliate_clicks ───────────────────────────────────────────────────────
    op.create_table(
        "affiliate_clicks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("affiliate_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("affiliates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("visitor_id",      sa.String(64),  nullable=True),
        sa.Column("landing_path",    sa.String(500), nullable=True),
        sa.Column("user_agent_hash", sa.String(64),  nullable=True),
        sa.Column("ip_hash",         sa.String(64),  nullable=True),
        sa.Column("converted_to_signup", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_affiliate_clicks_affiliate_created", "affiliate_clicks", ["affiliate_id", "created_at"])
    op.create_index("idx_affiliate_clicks_visitor",           "affiliate_clicks", ["visitor_id"])

    # ── affiliate_conversions ──────────────────────────────────────────────────
    op.create_table(
        "affiliate_conversions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("affiliate_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("affiliates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("referred_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("stripe_customer_id",     sa.String(100), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(100), nullable=True),
        sa.Column("stripe_event_id", sa.String(200), nullable=False, unique=True),
        sa.Column("plan_tier",  sa.String(20), nullable=False),
        sa.Column("amount_usd", sa.Float,      nullable=False),
        sa.Column("commission_pct",        sa.Float, nullable=False),
        sa.Column("commission_amount_usd", sa.Float, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_affiliate_conversions_affiliate_created", "affiliate_conversions", ["affiliate_id", "created_at"])
    op.create_index("idx_affiliate_conversions_status",            "affiliate_conversions", ["status"])
    op.create_index("ix_affiliate_conversions_stripe_event_id",    "affiliate_conversions", ["stripe_event_id"], unique=True)


def downgrade() -> None:
    op.drop_table("affiliate_conversions")
    op.drop_index("ix_users_referred_by_affiliate_id", table_name="users")
    op.drop_column("users", "referred_by_affiliate_id")
    op.drop_table("affiliate_clicks")
    op.drop_table("affiliates")
