"""Screening "decide later": assignments.skipped_at

Revision ID: c9f2d4e7a1b5
Revises: b3e7f1a8c2d9
Create Date: 2026-07-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9f2d4e7a1b5'
down_revision: Union[str, Sequence[str], None] = 'b3e7f1a8c2d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('assignments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('skipped_at', sa.DateTime(timezone=True),
                                      nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('assignments', schema=None) as batch_op:
        batch_op.drop_column('skipped_at')
