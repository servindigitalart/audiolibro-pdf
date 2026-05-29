"""022_add_analytics_tables

Revision ID: 022
Revises: 021
Create Date: 2026-05-27

WHY THIS MIGRATION EXISTS
--------------------------
Phase 3.7 — Behavioral Intelligence, Retention Analytics & Conversion Optimization.

Adds two tables for product analytics:

  playback_sessions — one row per continuous listening session.  Tracks
    listened_seconds, completion_percentage, playback_speed, chapters_visited,
    session_source, and whether the user resumed via Continue Listening.
    The frontend starts a session (POST /analytics/sessions) and ends it
    when the user pauses or navigates away (PATCH /analytics/sessions/{id}).

  analytics_events — lightweight event log for signals that don't fit into
    a PlaybackSession: paywall views, upgrade clicks, voice previews,
    audiobook completion, chapter changes.  Intentionally sparse — just
    event_type + JSON properties + optional session/document links.

Both tables use UUID PKs and cascade-safe FK policies:
  - ON DELETE CASCADE for user_id (user deleted → sessions deleted)
  - ON DELETE SET NULL for document_id / session_id (orphan safely rather
    than block deletion)
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = '022'
down_revision = '021'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playback_sessions",
        sa.Column("id",           UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id",      UUID(as_uuid=True), sa.ForeignKey("users.id",      ondelete="CASCADE"),  nullable=False),
        sa.Column("document_id",  UUID(as_uuid=True), sa.ForeignKey("documents.id",  ondelete="SET NULL"), nullable=True),
        sa.Column("started_at",   sa.DateTime(),       nullable=False, server_default=sa.text("now()")),
        sa.Column("ended_at",     sa.DateTime(),       nullable=True),
        sa.Column("listened_seconds",              sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_percentage",         sa.Float(),   nullable=False, server_default="0"),
        sa.Column("playback_speed",                sa.Float(),   nullable=False, server_default="1"),
        sa.Column("chapters_visited",              sa.JSON(),    nullable=False, server_default="'[]'"),
        sa.Column("resumed_from_continue_listening", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("session_source", sa.String(50), nullable=True),
    )
    op.create_index("idx_playback_sessions_user_started", "playback_sessions", ["user_id", "started_at"])
    op.create_index("idx_playback_sessions_document",     "playback_sessions", ["document_id"])

    op.create_table(
        "analytics_events",
        sa.Column("id",          UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id",     UUID(as_uuid=True), sa.ForeignKey("users.id",            ondelete="SET NULL"), nullable=True),
        sa.Column("session_id",  UUID(as_uuid=True), sa.ForeignKey("playback_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id",         ondelete="SET NULL"), nullable=True),
        sa.Column("event_type",  sa.String(64),  nullable=False),
        sa.Column("created_at",  sa.DateTime(),  nullable=False, server_default=sa.text("now()")),
        sa.Column("properties",  sa.JSON(),      nullable=False, server_default="'{}'"),
    )
    op.create_index("idx_analytics_events_user_created", "analytics_events", ["user_id",    "created_at"])
    op.create_index("idx_analytics_events_type_created", "analytics_events", ["event_type", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_analytics_events_type_created", table_name="analytics_events")
    op.drop_index("idx_analytics_events_user_created", table_name="analytics_events")
    op.drop_table("analytics_events")

    op.drop_index("idx_playback_sessions_document",     table_name="playback_sessions")
    op.drop_index("idx_playback_sessions_user_started", table_name="playback_sessions")
    op.drop_table("playback_sessions")
