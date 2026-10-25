"""projects.research_question + golden_refs.apa

Revision ID: c8d42fa1e977
Revises: b7c31e9d5a20
Create Date: 2026-07-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8d42fa1e977'
down_revision: Union[str, Sequence[str], None] = 'b7c31e9d5a20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('research_question', sa.Text(), nullable=False,
                                      server_default=''))
    with op.batch_alter_table('golden_refs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('apa', sa.Text(), nullable=False,
                                      server_default=''))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('golden_refs', schema=None) as batch_op:
        batch_op.drop_column('apa')
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('research_question')
