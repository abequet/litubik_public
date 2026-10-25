"""M5: screening config allocation/conflict/status fields

Revision ID: e7a91cd438f2
Revises: d9e53fb2c611
Create Date: 2026-07-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a91cd438f2'
down_revision: Union[str, Sequence[str], None] = 'd9e53fb2c611'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('screening_configs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('allocation', sa.String(length=20),
                                      nullable=False, server_default='all'))
        batch_op.add_column(sa.Column('overlap_pct', sa.Integer(),
                                      nullable=False, server_default='20'))
        batch_op.add_column(sa.Column('conflict_resolution', sa.String(length=20),
                                      nullable=False, server_default='consensus'))
        batch_op.add_column(sa.Column('reviewer_ids', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('status', sa.String(length=20),
                                      nullable=False, server_default='draft'))
        batch_op.add_column(sa.Column('started_at', sa.DateTime(timezone=True),
                                      nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('screening_configs', schema=None) as batch_op:
        for col in ('started_at', 'status', 'reviewer_ids', 'conflict_resolution',
                    'overlap_pct', 'allocation'):
            batch_op.drop_column(col)
