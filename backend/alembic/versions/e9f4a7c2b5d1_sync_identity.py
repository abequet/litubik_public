"""Sync phase 0: cross-instance identity — uuid on structural tables,
instance_meta, project sync role, vote/annotation updated_at + AI provenance
(docs/SYNC_IMPLEMENTATION_PLAN.md)

Revision ID: e9f4a7c2b5d1
Revises: d8a3c5f7b2e9
Create Date: 2026-07-17

"""
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9f4a7c2b5d1'
down_revision: Union[str, Sequence[str], None] = 'd8a3c5f7b2e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# entities the sync layer references across instances (users go by email)
UUID_TABLES = [
    'projects', 'protocols', 'concepts', 'equations', 'golden_refs',
    'sources', 'imports', 'records', 'snowball_runs',
    'screening_configs', 'extraction_columns',
]


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    for table in UUID_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('uuid', sa.String(36), nullable=True))
        # per-row backfill: each row needs its own uuid4, no SQL function for
        # that works on both SQLite and Postgres
        rows = conn.execute(
            sa.text(f"SELECT id FROM {table} WHERE uuid IS NULL")).fetchall()
        if rows:
            conn.execute(
                sa.text(f"UPDATE {table} SET uuid = :u WHERE id = :i"),
                [{"u": str(uuid4()), "i": r[0]} for r in rows])
        with op.batch_alter_table(table) as batch:
            batch.alter_column('uuid', existing_type=sa.String(36),
                               nullable=False)
        op.create_index(f'ix_{table}_uuid', table, ['uuid'], unique=True)

    with op.batch_alter_table('projects') as batch:
        batch.add_column(sa.Column('sync_role', sa.String(12), nullable=False,
                                   server_default='coordinator'))
        batch.add_column(sa.Column('coordinator_email', sa.String(255),
                                   nullable=False, server_default=''))
        batch.add_column(sa.Column('coordinator_instance_id', sa.String(36),
                                   nullable=True))
        batch.add_column(sa.Column('snapshot_version', sa.Integer(),
                                   nullable=False, server_default='0'))

    with op.batch_alter_table('votes') as batch:
        batch.add_column(sa.Column('generated_by', sa.String(255),
                                   nullable=True))
        batch.add_column(sa.Column('updated_at', sa.DateTime(timezone=True),
                                   nullable=True))
    conn.execute(sa.text("UPDATE votes SET updated_at = created_at"))
    with op.batch_alter_table('votes') as batch:
        batch.alter_column('updated_at',
                           existing_type=sa.DateTime(timezone=True),
                           nullable=False)

    with op.batch_alter_table('pdf_annotations') as batch:
        batch.add_column(sa.Column('updated_at', sa.DateTime(timezone=True),
                                   nullable=True))
    conn.execute(sa.text("UPDATE pdf_annotations SET updated_at = created_at"))
    with op.batch_alter_table('pdf_annotations') as batch:
        batch.alter_column('updated_at',
                           existing_type=sa.DateTime(timezone=True),
                           nullable=False)

    op.create_table(
        'instance_meta',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('instance_id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('instance_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('instance_meta')

    with op.batch_alter_table('pdf_annotations') as batch:
        batch.drop_column('updated_at')

    with op.batch_alter_table('votes') as batch:
        batch.drop_column('updated_at')
        batch.drop_column('generated_by')

    with op.batch_alter_table('projects') as batch:
        batch.drop_column('snapshot_version')
        batch.drop_column('coordinator_instance_id')
        batch.drop_column('coordinator_email')
        batch.drop_column('sync_role')

    for table in reversed(UUID_TABLES):
        op.drop_index(f'ix_{table}_uuid', table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column('uuid')
