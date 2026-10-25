"""record translations

AI translations of a record's title and abstract, cached per target language
on the record itself. Empty until someone asks for one.

Revision ID: e7b2f4a91c06
Revises: d41a7c9e52b3
Create Date: 2026-09-19 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e7b2f4a91c06'
down_revision: Union[str, Sequence[str], None] = 'd41a7c9e52b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('translations', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('records', schema=None) as batch_op:
        batch_op.drop_column('translations')
