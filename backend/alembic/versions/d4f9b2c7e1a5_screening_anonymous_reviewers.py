"""Anonymous reviewers: an optional per-round blinding of the reviewers' names

Revision ID: d4f9b2c7e1a5
Revises: c3e8a1f5d7b2
Create Date: 2026-10-20 10:00:00.000000

Additive: one boolean column on screening_configs, false for every existing
round.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4f9b2c7e1a5'
down_revision: Union[str, Sequence[str], None] = 'c3e8a1f5d7b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('screening_configs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('anonymous', sa.Boolean(), nullable=False,
                                      server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('screening_configs', schema=None) as batch_op:
        batch_op.drop_column('anonymous')
