"""projects.databases — the databases a review searches

Revision ID: d1f6b3a9c2e7
Revises: c4e8a1f27b93
Create Date: 2026-10-15 14:40:00.000000

NULL = every database of the registry, which is what every existing project
was doing: no data migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd1f6b3a9c2e7'
down_revision: Union[str, Sequence[str], None] = 'c4e8a1f27b93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('databases', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('databases')
