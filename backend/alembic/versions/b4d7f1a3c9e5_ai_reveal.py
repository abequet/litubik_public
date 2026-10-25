"""Screening: AI suggestion revealed after the vote

screening_configs.ai_reveal — always | after_vote.
ai_reveals — a reviewer's deliberate choice to see a cached suggestion before
voting in an after_vote round (recorded for the disclosure statement and the
paired human/AI corpus).

Revision ID: b4d7f1a3c9e5
Revises: a9c3e5f7b1d2
Create Date: 2026-10-13 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b4d7f1a3c9e5'
down_revision: Union[str, Sequence[str], None] = 'a9c3e5f7b1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('screening_configs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ai_reveal', sa.String(length=12),
                                      nullable=False,
                                      server_default='always'))
    op.create_table(
        'ai_reveals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('record_id', sa.Integer(), nullable=False),
        sa.Column('stage', sa.String(length=5), nullable=False),
        sa.Column('round', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('revealed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('imported_from', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['record_id'], ['records.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('record_id', 'stage', 'round', 'user_id',
                            name='uq_ai_reveals_record_stage_round_user'),
    )
    with op.batch_alter_table('ai_reveals', schema=None) as batch_op:
        batch_op.create_index('ix_ai_reveals_project_id', ['project_id'])
        batch_op.create_index('ix_ai_reveals_record_id', ['record_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('ai_reveals')
    with op.batch_alter_table('screening_configs', schema=None) as batch_op:
        batch_op.drop_column('ai_reveal')
