"""protocols: source_text + generated_with

Revision ID: a41f9c2d7b83
Revises: e6b5d21e4137
Create Date: 2026-07-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a41f9c2d7b83'
down_revision: Union[str, Sequence[str], None] = 'e6b5d21e4137'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('protocols', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_text', sa.Text(), nullable=False,
                                      server_default=''))
        batch_op.add_column(sa.Column('generated_with', sa.String(length=120),
                                      nullable=False, server_default=''))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('protocols', schema=None) as batch_op:
        batch_op.drop_column('generated_with')
        batch_op.drop_column('source_text')
