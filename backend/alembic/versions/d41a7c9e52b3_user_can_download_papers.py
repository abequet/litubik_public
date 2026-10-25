"""user can_download_papers

Per-user opt-in for the standalone "Download papers" module, ticked by the
superadmin. Off by default for every existing account.

Revision ID: d41a7c9e52b3
Revises: ca3050419a05
Create Date: 2026-09-18 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd41a7c9e52b3'
down_revision: Union[str, Sequence[str], None] = 'ca3050419a05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('can_download_papers', sa.Boolean(),
                                      server_default='0', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('can_download_papers')
