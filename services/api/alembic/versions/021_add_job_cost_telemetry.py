"""021_add_job_cost_telemetry

Revision ID: 021
Revises: 020
Create Date: 2026-05-27

WHY THIS MIGRATION EXISTS
--------------------------
Phase 3.6 — Cost Intelligence & Sustainable Monetization.

Adds three nullable columns to processing_jobs so that every successful
audiobook generation records its own cost footprint.  These columns allow:

  characters_processed    — exact TTS chars sent (not the pre-flight estimate),
                            enabling accurate cost-per-job and cost-per-listening-hour
                            metrics without re-querying CostEvent rows.

  estimated_cost_usd      — computed at job completion using UnitEconomicsEngine
                            rates (TTS + infra overhead).  Stored so the admin
                            expensive-jobs endpoint can ORDER BY without aggregating
                            across a separate cost_events table.

  plan_tier_at_generation — the user's plan tier at the moment of generation.
                            Lets us compute per-plan average costs from historical
                            data even if the user later upgrades or downgrades.

All three columns are nullable so existing rows remain valid.
"""

import sqlalchemy as sa
from alembic import op

revision = '021'
down_revision = '020'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "processing_jobs",
        sa.Column("characters_processed", sa.Integer(), nullable=True),
    )
    op.add_column(
        "processing_jobs",
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
    )
    op.add_column(
        "processing_jobs",
        sa.Column("plan_tier_at_generation", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("processing_jobs", "plan_tier_at_generation")
    op.drop_column("processing_jobs", "estimated_cost_usd")
    op.drop_column("processing_jobs", "characters_processed")
