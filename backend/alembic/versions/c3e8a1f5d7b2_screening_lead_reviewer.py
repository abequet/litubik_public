"""Lead-reviewer allocation: one reviewer screens everything, the others share

Revision ID: c3e8a1f5d7b2
Revises: b7d2e4f9a1c3
Create Date: 2026-10-19 10:00:00.000000

Additive: one nullable column on screening_configs (the lead reviewer of an
allocation = lead round). Existing rounds are untouched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3e8a1f5d7b2'
down_revision: Union[str, Sequence[str], None] = 'b7d2e4f9a1c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('screening_configs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lead_user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_screening_configs_lead_user_id', 'users',
                                    ['lead_user_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('screening_configs', schema=None) as batch_op:
        batch_op.drop_constraint('fk_screening_configs_lead_user_id',
                                 type_='foreignkey')
        batch_op.drop_column('lead_user_id')
