"""Living review: search update plans, update runs, notifications

search_update_plans — one per project: interval, databases, equation, next run.
search_update_runs — audit of each update pass (owns its round, like
snowball_runs). notifications — per-user in-app notices (never synced).

Revision ID: d8f3b0c5e2a7
Revises: c7e2a9f4d1b6
Create Date: 2026-10-14 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd8f3b0c5e2a7'
down_revision: Union[str, Sequence[str], None] = 'c7e2a9f4d1b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'search_update_plans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('interval_days', sa.Integer(), nullable=False),
        sa.Column('databases', sa.JSON(), nullable=False),
        sa.Column('equation_id', sa.Integer(), nullable=True),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['equation_id'], ['equations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', name='uq_search_update_plans_project'),
    )
    with op.batch_alter_table('search_update_plans', schema=None) as batch_op:
        batch_op.create_index('ix_search_update_plans_uuid', ['uuid'], unique=True)
        batch_op.create_index('ix_search_update_plans_project_id', ['project_id'])

    op.create_table(
        'search_update_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('round', sa.Integer(), nullable=False),
        sa.Column('databases', sa.JSON(), nullable=False),
        sa.Column('since_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('n_fetched', sa.Integer(), nullable=False),
        sa.Column('n_new_unique', sa.Integer(), nullable=False),
        sa.Column('triggered_by', sa.String(length=10), nullable=False),
        sa.Column('errors', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('search_update_runs', schema=None) as batch_op:
        batch_op.create_index('ix_search_update_runs_uuid', ['uuid'], unique=True)
        batch_op.create_index('ix_search_update_runs_project_id', ['project_id'])

    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('kind', sa.String(length=40), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.create_index('ix_notifications_user_id', ['user_id'])
        batch_op.create_index('ix_notifications_project_id', ['project_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('notifications')
    op.drop_table('search_update_runs')
    op.drop_table('search_update_plans')
