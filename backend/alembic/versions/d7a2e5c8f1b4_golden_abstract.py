"""Golden refs: cached abstract (OpenAlex) feeding the AI strategy advisor

Revision ID: d7a2e5c8f1b4
Revises: c5e8b2f4a7d1
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7a2e5c8f1b4'
down_revision: Union[str, Sequence[str], None] = 'c5e8b2f4a7d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('golden_refs') as batch:
        batch.add_column(sa.Column('abstract', sa.Text(), nullable=False,
                                   server_default=''))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('golden_refs') as batch:
        batch.drop_column('abstract')
