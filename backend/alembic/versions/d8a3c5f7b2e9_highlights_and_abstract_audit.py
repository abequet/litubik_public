"""T14 highlight word lists on projects + T21 abstract edit audit on records

Revision ID: d8a3c5f7b2e9
Revises: c7f2b4d8e1a3
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8a3c5f7b2e9'
down_revision: Union[str, Sequence[str], None] = 'c7f2b4d8e1a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('projects') as batch:
        batch.add_column(sa.Column('highlights', sa.JSON(), nullable=False,
                                   server_default='{}'))
    with op.batch_alter_table('records') as batch:
        batch.add_column(sa.Column('abstract_original', sa.Text(),
                                   nullable=True))
        batch.add_column(sa.Column('abstract_edited_by', sa.Integer(),
                                   nullable=True))
        batch.add_column(sa.Column('abstract_edited_at',
                                   sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key('fk_records_abstract_edited_by', 'users',
                                 ['abstract_edited_by'], ['id'],
                                 ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('records') as batch:
        batch.drop_constraint('fk_records_abstract_edited_by',
                              type_='foreignkey')
        batch.drop_column('abstract_edited_at')
        batch.drop_column('abstract_edited_by')
        batch.drop_column('abstract_original')
    with op.batch_alter_table('projects') as batch:
        batch.drop_column('highlights')
