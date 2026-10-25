"""imports.disciplines: the subject areas a search was limited to

Revision ID: b7d2e4f9a1c3
Revises: f3a9c1d7e2b4
Create Date: 2026-10-18 21:10:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7d2e4f9a1c3'
down_revision: Union[str, Sequence[str], None] = 'f3a9c1d7e2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('imports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('disciplines', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('imports', schema=None) as batch_op:
        batch_op.drop_column('disciplines')
