"""013_normalize_plan_tier_to_uppercase

Revision ID: 013
Revises: 012
Create Date: 2026-05-19

WHY THIS MIGRATION EXISTS
--------------------------
The users.plan_tier column was created by migration 003 with server_default='FREE'
(uppercase) and the User model also defaults to "FREE".  However a secondary
PlanTier enum in app/financial/quota/quota_limits.py used lowercase values
("free", "basic", "pro", "enterprise"), while the canonical enum in
app/pricing/tiers.py used uppercase ("FREE", "BASIC", "PRO", "ENTERPRISE").

When account_service.py and quota_service.py called PlanTier(user.plan_tier)
using the lowercase enum, any "FREE" value from the DB raised:

    ValueError: 'FREE' is not a valid PlanTier

The quota_limits.py enum has been fixed to use uppercase values.  This
migration is a safety normalizer: it uppercases any rows that somehow contain
lowercase plan_tier values so the DB is uniformly uppercase going forward.

Down migration: lowercase all values back (mirrors the old state).
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Normalize any stale lowercase plan_tier values to uppercase.
    # The UPPER() call is idempotent — rows already uppercase are unchanged.
    op.execute(
        "UPDATE users SET plan_tier = UPPER(plan_tier) "
        "WHERE plan_tier != UPPER(plan_tier)"
    )

    # Ensure the server default is uppercase (migration 003 set 'FREE' already,
    # but make it explicit so future introspection is unambiguous).
    op.execute(
        "ALTER TABLE users ALTER COLUMN plan_tier SET DEFAULT 'FREE'"
    )


def downgrade() -> None:
    # Reverse: lowercase all values (restores the old broken state).
    op.execute(
        "UPDATE users SET plan_tier = LOWER(plan_tier) "
        "WHERE plan_tier != LOWER(plan_tier)"
    )
    op.execute(
        "ALTER TABLE users ALTER COLUMN plan_tier SET DEFAULT 'free'"
    )
