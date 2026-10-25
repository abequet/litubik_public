"""imports: document-type limit and the fields a search ran on (PRISMA-S)

Revision ID: c3e7a1f5b9d2
Revises: d4f9b2c7e1a5
Create Date: 2026-10-21 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3e7a1f5b9d2'
down_revision: Union[str, Sequence[str], None] = 'd4f9b2c7e1a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('imports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('doc_type_restricted', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('doc_types', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('search_fields', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('imports', schema=None) as batch_op:
        batch_op.drop_column('search_fields')
        batch_op.drop_column('doc_types')
        batch_op.drop_column('doc_type_restricted')
