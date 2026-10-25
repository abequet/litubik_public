"""AI title triage: screening_configs.ai_triage + conflicts.origin

Revision ID: a8c4e2f7d9b1
Revises: f2b5c7d9e3a1
Create Date: 2026-07-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8c4e2f7d9b1'
down_revision: Union[str, Sequence[str], None] = 'f2b5c7d9e3a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('screening_configs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ai_triage', sa.String(length=12),
                                      nullable=False, server_default='off'))
    with op.batch_alter_table('conflicts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('origin', sa.String(length=12),
                                      nullable=False, server_default='votes'))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('conflicts', schema=None) as batch_op:
        batch_op.drop_column('origin')
    with op.batch_alter_table('screening_configs', schema=None) as batch_op:
        batch_op.drop_column('ai_triage')
