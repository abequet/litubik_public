"""M9 extraction: configs/assignments, JBI appraisals, per-user values,
record study design

Revision ID: e1a4b6c8d2f3
Revises: c9f2d4e7a1b5
Create Date: 2026-07-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1a4b6c8d2f3'
down_revision: Union[str, Sequence[str], None] = 'c9f2d4e7a1b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'extraction_configs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(),
                  sa.ForeignKey('projects.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('n_extractors', sa.Integer(), nullable=False,
                  server_default='1'),
        sa.Column('extractor_ids', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False,
                  server_default='draft'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('project_id'),
    )
    op.create_table(
        'extraction_assignments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('config_id', sa.Integer(),
                  sa.ForeignKey('extraction_configs.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('record_id', sa.Integer(),
                  sa.ForeignKey('records.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'),
                  nullable=False),
        sa.UniqueConstraint('config_id', 'record_id', 'user_id'),
    )
    op.create_table(
        'jbi_appraisals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('record_id', sa.Integer(),
                  sa.ForeignKey('records.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('design', sa.String(length=40), nullable=False),
        sa.Column('answers', sa.JSON(), nullable=False),
        sa.Column('overall', sa.String(length=20), nullable=False,
                  server_default=''),
        sa.Column('comment', sa.Text(), nullable=False, server_default=''),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('record_id', 'user_id'),
    )
    with op.batch_alter_table('records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('study_design', sa.String(length=40),
                                      nullable=True))
        batch_op.add_column(sa.Column('design_origin', sa.String(length=10),
                                      nullable=True))
    # per-extractor cells: unique (record, column) -> (record, column, user).
    # The table was never fed before M9, so recreate it with the new shape
    # (SQLite can't alter an unnamed unique constraint in place).
    op.drop_table('extraction_values')
    _create_values_table(with_user=True)


def _create_values_table(with_user: bool) -> None:
    cols = [
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('record_id', sa.Integer(),
                  sa.ForeignKey('records.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('column_id', sa.Integer(),
                  sa.ForeignKey('extraction_columns.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('value', sa.JSON(), nullable=False),
        sa.Column('origin', sa.String(length=10), nullable=False,
                  server_default='human'),
        sa.Column('validated', sa.Boolean(), nullable=False,
                  server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    ]
    if with_user:
        cols.insert(3, sa.Column('user_id', sa.Integer(),
                                 sa.ForeignKey('users.id', ondelete='CASCADE'),
                                 nullable=True))
        unique = sa.UniqueConstraint('record_id', 'column_id', 'user_id')
    else:
        unique = sa.UniqueConstraint('record_id', 'column_id')
    op.create_table('extraction_values', *cols, unique)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('extraction_values')
    _create_values_table(with_user=False)
    with op.batch_alter_table('records', schema=None) as batch_op:
        batch_op.drop_column('design_origin')
        batch_op.drop_column('study_design')
    op.drop_table('jbi_appraisals')
    op.drop_table('extraction_assignments')
    op.drop_table('extraction_configs')
