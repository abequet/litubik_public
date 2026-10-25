"""M7: full-text screening — conflict reasons + shared PDF annotations

Revision ID: d5f9a3b71c48
Revises: c4d18ba90e37
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5f9a3b71c48'
down_revision: Union[str, Sequence[str], None] = 'c4d18ba90e37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('conflicts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reasons', sa.JSON(), nullable=True))

    op.create_table(
        'pdf_annotations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('record_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('page', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('rects', sa.JSON(), nullable=True),
        sa.Column('quote', sa.Text(), nullable=False, server_default=''),
        sa.Column('note', sa.Text(), nullable=False, server_default=''),
        sa.Column('color', sa.String(length=20), nullable=False,
                  server_default='yellow'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['record_id'], ['records.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('pdf_annotations', schema=None) as batch_op:
        batch_op.create_index('ix_pdf_annotations_project_id', ['project_id'])
        batch_op.create_index('ix_pdf_annotations_record_id', ['record_id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('pdf_annotations', schema=None) as batch_op:
        batch_op.drop_index('ix_pdf_annotations_record_id')
        batch_op.drop_index('ix_pdf_annotations_project_id')
    op.drop_table('pdf_annotations')
    with op.batch_alter_table('conflicts', schema=None) as batch_op:
        batch_op.drop_column('reasons')
