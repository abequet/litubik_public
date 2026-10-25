"""Sync phase 2: contribution packages — sync_events journal + per-row
imported_from provenance on the contribution tables

Revision ID: f1a8d4c7e2b9
Revises: e9f4a7c2b5d1
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a8d4c7e2b9'
down_revision: Union[str, Sequence[str], None] = 'e9f4a7c2b5d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROVENANCE_TABLES = ['votes', 'jbi_appraisals', 'extraction_values',
                     'pdf_annotations']


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'sync_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('direction', sa.String(10), nullable=False),
        sa.Column('kind', sa.String(15), nullable=False),
        sa.Column('author_email', sa.String(255), nullable=False,
                  server_default=''),
        sa.Column('instance_id', sa.String(36), nullable=False,
                  server_default=''),
        sa.Column('seq', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('based_on_version', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('filename', sa.String(500), nullable=False,
                  server_default=''),
        sa.Column('counts', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('warnings', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'],
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sync_events_project_id', 'sync_events', ['project_id'])

    for table in PROVENANCE_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('imported_from', sa.String(255),
                                       nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    for table in reversed(PROVENANCE_TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_column('imported_from')
    op.drop_index('ix_sync_events_project_id', table_name='sync_events')
    op.drop_table('sync_events')
