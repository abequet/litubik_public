"""M2: golden_refs table + equations.golden_results

Revision ID: b7c31e9d5a20
Revises: a41f9c2d7b83
Create Date: 2026-07-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c31e9d5a20'
down_revision: Union[str, Sequence[str], None] = 'a41f9c2d7b83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'golden_refs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('doi', sa.String(length=255), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('equations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('golden_results', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('equations', schema=None) as batch_op:
        batch_op.drop_column('golden_results')
    op.drop_table('golden_refs')
