"""Sync phase 4: shared-folder transport — per-project folder path and
auto-publish flag

Revision ID: b4d7a1e3f6c9
Revises: a3c6f9b2d5e8
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4d7a1e3f6c9'
down_revision: Union[str, Sequence[str], None] = 'a3c6f9b2d5e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('projects') as batch:
        batch.add_column(sa.Column('sync_dir', sa.Text(), nullable=False,
                                   server_default=''))
        batch.add_column(sa.Column('sync_auto_publish', sa.Boolean(),
                                   nullable=False, server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('projects') as batch:
        batch.drop_column('sync_auto_publish')
        batch.drop_column('sync_dir')
