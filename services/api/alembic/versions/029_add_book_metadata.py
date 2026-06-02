"""029_add_book_metadata

Revision ID: 029
Revises: 028
Create Date: 2026-06-02

Adds Book Intelligence fields to the documents table:
  author, subtitle, isbn, metadata_source, metadata_confidence

These fields are populated by the MetadataService after upload and can
be overridden by the user.  All nullable — existing rows unaffected.
"""

import sqlalchemy as sa
from alembic import op

revision = '029'
down_revision = '028'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('author',              sa.String(512),  nullable=True))
    op.add_column('documents', sa.Column('subtitle',            sa.String(512),  nullable=True))
    op.add_column('documents', sa.Column('isbn',                sa.String(20),   nullable=True))
    op.add_column('documents', sa.Column('metadata_source',     sa.String(50),   nullable=True))
    op.add_column('documents', sa.Column('metadata_confidence', sa.Float(),      nullable=True))

    # Index for future search by author / isbn
    op.create_index('ix_documents_author', 'documents', ['author'])
    op.create_index('ix_documents_isbn',   'documents', ['isbn'])


def downgrade() -> None:
    op.drop_index('ix_documents_isbn',   table_name='documents')
    op.drop_index('ix_documents_author', table_name='documents')
    op.drop_column('documents', 'metadata_confidence')
    op.drop_column('documents', 'metadata_source')
    op.drop_column('documents', 'isbn')
    op.drop_column('documents', 'subtitle')
    op.drop_column('documents', 'author')
