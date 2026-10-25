"""Weighted screening lots, rotating pairs, named arbiters

Revision ID: a2c7e9f4b1d3
Revises: d1f6b3a9c2e7
Create Date: 2026-10-15 18:00:00.000000

Additive: screening_lots table, assignments.lot_id, and three nullable
settings on screening_configs. Existing rounds keep allocation all / dual /
single_overlap untouched; nothing is backfilled.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a2c7e9f4b1d3'
down_revision: Union[str, Sequence[str], None] = 'd1f6b3a9c2e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'screening_lots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column('config_id', sa.Integer(), nullable=False),
        sa.Column('index', sa.Integer(), nullable=False),
        sa.Column('user_ids', sa.JSON(), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=10), nullable=False,
                  server_default='open'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['config_id'], ['screening_configs.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('config_id', 'index'),
    )
    op.create_index(op.f('ix_screening_lots_uuid'), 'screening_lots', ['uuid'],
                    unique=True)
    op.create_index(op.f('ix_screening_lots_config_id'), 'screening_lots',
                    ['config_id'], unique=False)
    with op.batch_alter_table('screening_configs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('weights', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('lot_size', sa.Integer(), nullable=False,
                                      server_default='100'))
        batch_op.add_column(sa.Column('arbiter_ids', sa.JSON(), nullable=True))
    with op.batch_alter_table('assignments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lot_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_assignments_lot_id', 'screening_lots',
                                    ['lot_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('assignments', schema=None) as batch_op:
        batch_op.drop_constraint('fk_assignments_lot_id', type_='foreignkey')
        batch_op.drop_column('lot_id')
    with op.batch_alter_table('screening_configs', schema=None) as batch_op:
        batch_op.drop_column('arbiter_ids')
        batch_op.drop_column('lot_size')
        batch_op.drop_column('weights')
    op.drop_index(op.f('ix_screening_lots_config_id'), table_name='screening_lots')
    op.drop_index(op.f('ix_screening_lots_uuid'), table_name='screening_lots')
    op.drop_table('screening_lots')
