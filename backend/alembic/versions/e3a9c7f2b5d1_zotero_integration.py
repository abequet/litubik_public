"""Zotero integration: user_integrations, record_external_links

A personal API key per (user, provider) and the record ↔ external item links
that let a second export update instead of duplicate (roadmap chantier 4).

Revision ID: e3a9c7f2b5d1
Revises: d8f3b0c5e2a7
Create Date: 2026-10-14 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e3a9c7f2b5d1'
down_revision: Union[str, Sequence[str], None] = 'd8f3b0c5e2a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'user_integrations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('api_key_encrypted', sa.Text(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'provider'),
    )
    with op.batch_alter_table('user_integrations', schema=None) as batch_op:
        batch_op.create_index('ix_user_integrations_user_id', ['user_id'])

    op.create_table(
        'record_external_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('record_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('library', sa.String(length=60), nullable=False),
        sa.Column('external_key', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['record_id'], ['records.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('record_id', 'provider', 'library'),
    )
    with op.batch_alter_table('record_external_links', schema=None) as batch_op:
        batch_op.create_index('ix_record_external_links_record_id', ['record_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('record_external_links')
    op.drop_table('user_integrations')
