"""Reviewer work time: work_sessions

One row per stretch of active work by a member on a stage of a project,
measured from front-end heartbeats (roadmap chantier 14). Stage and duration
only — no record ids.

Revision ID: c7e2a9f4d1b6
Revises: b4d7f1a3c9e5
Create Date: 2026-10-14 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c7e2a9f4d1b6'
down_revision: Union[str, Sequence[str], None] = 'b4d7f1a3c9e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'work_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('stage', sa.String(length=20), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('n_heartbeats', sa.Integer(), nullable=False),
        sa.Column('instance_id', sa.String(length=64), nullable=False),
        sa.Column('imported_from', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('work_sessions', schema=None) as batch_op:
        batch_op.create_index('ix_work_sessions_uuid', ['uuid'], unique=True)
        batch_op.create_index('ix_work_sessions_project_id', ['project_id'])
        batch_op.create_index('ix_work_sessions_user_id', ['user_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('work_sessions')
