"""projects.archived_at (soft delete / archive)

Revision ID: e7c4a2f9b153
Revises: d5f9a3b71c48
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7c4a2f9b153'
down_revision: Union[str, Sequence[str], None] = 'd5f9a3b71c48'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('archived_at', sa.DateTime(timezone=True),
                                      nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('archived_at')
