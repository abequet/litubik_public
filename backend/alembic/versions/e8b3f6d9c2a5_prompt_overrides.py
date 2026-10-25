"""Prompt overrides: per-project editable AI instruction blocks (M2)

Revision ID: e8b3f6d9c2a5
Revises: d7a2e5c8f1b4
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8b3f6d9c2a5'
down_revision: Union[str, Sequence[str], None] = 'd7a2e5c8f1b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'prompt_overrides',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(),
                  sa.ForeignKey('projects.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('feature_key', sa.String(length=60), nullable=False),
        sa.Column('text', sa.Text(), nullable=False, server_default=''),
        sa.Column('updated_by', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('project_id', 'feature_key'),
    )
    op.create_index('ix_prompt_overrides_project_id', 'prompt_overrides',
                    ['project_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_prompt_overrides_project_id', table_name='prompt_overrides')
    op.drop_table('prompt_overrides')
