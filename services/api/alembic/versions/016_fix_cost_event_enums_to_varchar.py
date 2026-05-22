"""016_fix_cost_event_enums_to_varchar

Revision ID: 016
Revises: 015
Create Date: 2026-05-21

WHY THIS MIGRATION EXISTS
--------------------------
Migration 003 created cost_events with two native PostgreSQL enum columns:

  costeventtype — ('TTS_GENERATION', 'TTS_STREAMING', 'STORAGE_UPLOAD', ...)
  costprovider  — ('OPENAI', 'ANTHROPIC', 'ELEVEN_LABS', ...)

Two separate problems surfaced when TTS synthesis tried to insert a cost event:

1. asyncpg native enum codec bug (same root cause as migrations 012 and 014):
   SQLAlchemy 2.0 + asyncpg sends Python enum member .name through the native
   codec rather than .value.  e.g. CostEventType.TTS_CHARACTERS has .name
   "TTS_CHARACTERS" and .value "tts_characters".  asyncpg sends "TTS_CHARACTERS"
   to the costeventtype enum — which only knows lowercase .value strings from the
   Python model — raising:
     sqlalchemy.exc.DBAPIError:
       invalid input value for enum costeventtype: "TTS_CHARACTERS"

2. Schema drift: the Python CostEventType/CostProvider enums were rewritten after
   migration 003, so their values no longer match the DB enum labels at all.

Fix: convert both columns to VARCHAR(50), identical to what migrations 012 and
014 did for other enum columns.  The Python model already has
  native_enum=False, values_callable=lambda obj: [e.value for e in obj]
after today's model patch, so SQLAlchemy will send lowercase .value strings
directly and bypass the asyncpg native codec entirely.

Existing row data is preserved via the ::text cast.  Old rows that stored
uppercase labels (e.g. "TTS_GENERATION") will remain readable; new rows will
store lowercase .value strings (e.g. "tts_characters").  No backfill is needed
because cost_events is an append-only audit log — old rows are never queried by
the current Python enum values.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "016"
down_revision: Union[str, Sequence[str], None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop indexes that reference the enum-typed columns before altering them.
    op.drop_index("idx_event_type_created", table_name="cost_events", if_exists=True)
    op.drop_index("idx_provider_created",   table_name="cost_events", if_exists=True)
    op.drop_index("ix_cost_events_event_type", table_name="cost_events", if_exists=True)

    # Convert event_type: costeventtype enum → VARCHAR(50)
    op.execute(
        "ALTER TABLE cost_events "
        "ALTER COLUMN event_type TYPE VARCHAR(50) "
        "USING event_type::text"
    )

    # Convert provider: costprovider enum → VARCHAR(50)
    op.execute(
        "ALTER TABLE cost_events "
        "ALTER COLUMN provider TYPE VARCHAR(50) "
        "USING provider::text"
    )

    # Drop the now-unused PostgreSQL enum types.
    # IF EXISTS guards against environments where the types were already dropped
    # or were never created as native types.
    op.execute("DROP TYPE IF EXISTS costeventtype")
    op.execute("DROP TYPE IF EXISTS costprovider")

    # Recreate indexes on the new VARCHAR columns.
    op.create_index("ix_cost_events_event_type", "cost_events", ["event_type"])
    op.create_index(
        "idx_event_type_created",
        "cost_events",
        ["event_type", "created_at"],
        postgresql_using="btree",
    )
    op.create_index(
        "idx_provider_created",
        "cost_events",
        ["provider", "created_at"],
        postgresql_using="btree",
    )


def downgrade() -> None:
    """
    Revert VARCHAR columns back to native PostgreSQL ENUM types.
    Only safe when all existing rows contain values that are valid members of
    the original DB enums defined in migration 003.
    """
    from sqlalchemy.dialects import postgresql

    op.drop_index("idx_provider_created",   table_name="cost_events", if_exists=True)
    op.drop_index("idx_event_type_created", table_name="cost_events", if_exists=True)
    op.drop_index("ix_cost_events_event_type", table_name="cost_events", if_exists=True)

    cost_event_type_enum = postgresql.ENUM(
        "TTS_GENERATION", "TTS_STREAMING", "STORAGE_UPLOAD", "STORAGE_HOSTING",
        "STORAGE_TRANSFER", "API_CALL_EXTERNAL", "API_CALL_INTERNAL",
        "COMPUTE_PROCESSING", "EMAIL_SENT", "CDN_BANDWIDTH", "DATABASE_QUERY",
        "CREDIT_PURCHASE", "CREDIT_USAGE", "INFRASTRUCTURE_HOSTING",
        "INFRASTRUCTURE_DATABASE",
        name="costeventtype",
        create_type=True,
    )
    cost_provider_enum = postgresql.ENUM(
        "OPENAI", "ANTHROPIC", "ELEVEN_LABS", "DIGITALOCEAN",
        "AWS_S3", "SENDGRID", "INTERNAL",
        name="costprovider",
        create_type=True,
    )

    op.execute(
        "ALTER TABLE cost_events "
        "ALTER COLUMN event_type TYPE costeventtype "
        "USING event_type::costeventtype"
    )
    op.execute(
        "ALTER TABLE cost_events "
        "ALTER COLUMN provider TYPE costprovider "
        "USING provider::costprovider"
    )

    op.create_index("ix_cost_events_event_type", "cost_events", ["event_type"])
    op.create_index(
        "idx_event_type_created", "cost_events", ["event_type", "created_at"],
        postgresql_using="btree",
    )
    op.create_index(
        "idx_provider_created", "cost_events", ["provider", "created_at"],
        postgresql_using="btree",
    )
