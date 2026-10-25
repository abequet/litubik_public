"""import limits (date/discipline declared) + AI triage control sample

Revision ID: f3a9c1d7e2b4
Revises: e15ba86c88ed
Create Date: 2026-10-18 18:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f3a9c1d7e2b4'
down_revision: Union[str, Sequence[str], None] = 'e15ba86c88ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('imports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('date_restricted', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('discipline_restricted', sa.Boolean(), nullable=True))
    with op.batch_alter_table('screening_configs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('triage_control_pct', sa.Integer(),
                                      server_default='0', nullable=False))
    op.create_table(
        'triage_controls',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('record_id', sa.Integer(), nullable=False),
        sa.Column('stage', sa.String(length=5), nullable=False),
        sa.Column('round', sa.Integer(), nullable=False),
        sa.Column('held_by', sa.Integer(), nullable=True),
        sa.Column('job_id', sa.Integer(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['record_id'], ['records.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['held_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('record_id', 'stage', 'round', 'held_by'),
    )
    with op.batch_alter_table('triage_controls', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_triage_controls_project_id'),
                              ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_triage_controls_record_id'),
                              ['record_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('triage_controls', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_triage_controls_record_id'))
        batch_op.drop_index(batch_op.f('ix_triage_controls_project_id'))
    op.drop_table('triage_controls')
    with op.batch_alter_table('screening_configs', schema=None) as batch_op:
        batch_op.drop_column('triage_control_pct')
    with op.batch_alter_table('imports', schema=None) as batch_op:
        batch_op.drop_column('discipline_restricted')
        batch_op.drop_column('date_restricted')
