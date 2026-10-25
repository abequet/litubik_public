"""fulltext_configs.project_id nullable (global config row)

Revision ID: c4d18ba90e37
Revises: a1c7e0f4b892
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d18ba90e37'
down_revision: Union[str, Sequence[str], None] = 'a1c7e0f4b892'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('fulltext_configs', schema=None) as batch_op:
        batch_op.alter_column('project_id', existing_type=sa.Integer(),
                              nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('fulltext_configs', schema=None) as batch_op:
        batch_op.alter_column('project_id', existing_type=sa.Integer(),
                              nullable=False)
