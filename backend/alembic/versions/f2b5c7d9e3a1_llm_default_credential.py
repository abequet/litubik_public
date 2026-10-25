"""LLM credentials: is_default flag (B2 — pick the model jobs use)

Revision ID: f2b5c7d9e3a1
Revises: e1a4b6c8d2f3
Create Date: 2026-07-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2b5c7d9e3a1'
down_revision: Union[str, Sequence[str], None] = 'e1a4b6c8d2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('llm_credentials', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_default', sa.Boolean(),
                                      nullable=False,
                                      server_default=sa.false()))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('llm_credentials', schema=None) as batch_op:
        batch_op.drop_column('is_default')
