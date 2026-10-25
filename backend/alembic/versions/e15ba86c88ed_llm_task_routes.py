"""llm task routes: per-task AI provider/model/effort + project flag

Revision ID: e15ba86c88ed
Revises: a2c7e9f4b1d3
Create Date: 2026-10-18 15:41:16.046444

Autogenerate also proposed the long-standing NOT NULL / index drift on JSON
columns and trusted_emails; left out, as in the previous migrations.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e15ba86c88ed'
down_revision: Union[str, Sequence[str], None] = 'a2c7e9f4b1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'llm_task_routes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('task', sa.String(length=40), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('model', sa.String(length=120), nullable=False),
        sa.Column('effort', sa.String(length=10), nullable=False),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'task'),
    )
    with op.batch_alter_table('llm_task_routes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_llm_task_routes_project_id'),
                              ['project_id'], unique=False)
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('llm_reviewers_can_route', sa.Boolean(),
                                      server_default=sa.text('0'), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('llm_reviewers_can_route')
    with op.batch_alter_table('llm_task_routes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_llm_task_routes_project_id'))
    op.drop_table('llm_task_routes')
