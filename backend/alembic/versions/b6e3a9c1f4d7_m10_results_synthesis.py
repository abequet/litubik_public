"""M10 results: results_syntheses (stored AI narrative; aggregates stay computed)

Revision ID: b6e3a9c1f4d7
Revises: d5f9a1c3e7b2
Create Date: 2026-07-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6e3a9c1f4d7'
down_revision: Union[str, Sequence[str], None] = 'd5f9a1c3e7b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'results_syntheses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('content_md', sa.Text(), nullable=False),
        sa.Column('provider', sa.String(length=30), nullable=False),
        sa.Column('model', sa.String(length=100), nullable=False),
        sa.Column('tokens_in', sa.Integer(), nullable=False),
        sa.Column('tokens_out', sa.Integer(), nullable=False),
        sa.Column('cost_usd', sa.Float(), nullable=False),
        sa.Column('generated_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['generated_by'], ['users.id'],
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('results_syntheses')
