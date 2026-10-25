"""M8: snowballing — snowball_runs + citation_edges

Revision ID: a9b2c4d5e6f7
Revises: f8a1d63b2e40
Create Date: 2026-07-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9b2c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'f8a1d63b2e40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'snowball_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('round', sa.Integer(), nullable=False),
        sa.Column('seed_record_ids', sa.JSON(), nullable=True),
        sa.Column('n_seeds', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('n_backward', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('n_forward', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('n_new_records', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('n_new_unique', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('snowball_runs', schema=None) as batch_op:
        batch_op.create_index('ix_snowball_runs_project_id', ['project_id'])

    op.create_table(
        'citation_edges',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('citing_record_id', sa.Integer(), nullable=False),
        sa.Column('cited_record_id', sa.Integer(), nullable=False),
        sa.Column('direction', sa.String(length=10), nullable=False),
        sa.Column('round', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['citing_record_id'], ['records.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['cited_record_id'], ['records.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('citing_record_id', 'cited_record_id'),
    )
    with op.batch_alter_table('citation_edges', schema=None) as batch_op:
        batch_op.create_index('ix_citation_edges_project_id', ['project_id'])
        batch_op.create_index('ix_citation_edges_citing_record_id', ['citing_record_id'])
        batch_op.create_index('ix_citation_edges_cited_record_id', ['cited_record_id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('citation_edges', schema=None) as batch_op:
        batch_op.drop_index('ix_citation_edges_cited_record_id')
        batch_op.drop_index('ix_citation_edges_citing_record_id')
        batch_op.drop_index('ix_citation_edges_project_id')
    op.drop_table('citation_edges')
    with op.batch_alter_table('snowball_runs', schema=None) as batch_op:
        batch_op.drop_index('ix_snowball_runs_project_id')
    op.drop_table('snowball_runs')
