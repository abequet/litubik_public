"""Meta-analysis bridge: synthesis_outcomes.effect_spec

Per outcome, which effect measure to compute and which extraction columns
hold its inputs ({measure, mapping: {role: column_id}}), roadmap chantier 10.

Revision ID: a7d3f9c1e5b2
Revises: f9c2e4a7b1d5
Create Date: 2026-10-14 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7d3f9c1e5b2'
down_revision: Union[str, Sequence[str], None] = 'f9c2e4a7b1d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('synthesis_outcomes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('effect_spec', sa.JSON(), nullable=True))
    op.execute("UPDATE synthesis_outcomes SET effect_spec = '{}' WHERE effect_spec IS NULL")
    with op.batch_alter_table('synthesis_outcomes', schema=None) as batch_op:
        batch_op.alter_column('effect_spec', existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('synthesis_outcomes', schema=None) as batch_op:
        batch_op.drop_column('effect_spec')
