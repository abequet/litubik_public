"""Batch AI suggestion: screening_configs.ai_batch

Revision ID: d5f9a1c3e7b2
Revises: a8c4e2f7d9b1
Create Date: 2026-07-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5f9a1c3e7b2'
down_revision: Union[str, Sequence[str], None] = 'a8c4e2f7d9b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('screening_configs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ai_batch', sa.Boolean(),
                                      nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('screening_configs', schema=None) as batch_op:
        batch_op.drop_column('ai_batch')
