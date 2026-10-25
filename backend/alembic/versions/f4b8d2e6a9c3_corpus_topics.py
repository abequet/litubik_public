"""Thematic map of the corpus: corpus_topic_runs

One row per clustering run (TF-IDF → SVD → k-means → 2-D projection) with
its points and cluster terms/labels (roadmap chantier 11).

Revision ID: f4b8d2e6a9c3
Revises: e3a9c7f2b5d1
Create Date: 2026-10-14 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f4b8d2e6a9c3'
down_revision: Union[str, Sequence[str], None] = 'e3a9c7f2b5d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'corpus_topic_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('scope', sa.String(length=20), nullable=False),
        sa.Column('k_requested', sa.Integer(), nullable=True),
        sa.Column('k', sa.Integer(), nullable=False),
        sa.Column('n_docs', sa.Integer(), nullable=False),
        sa.Column('silhouette', sa.Float(), nullable=True),
        sa.Column('projection', sa.String(length=10), nullable=False),
        sa.Column('params', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('label_provider', sa.String(length=30), nullable=False),
        sa.Column('label_model', sa.String(length=100), nullable=False),
        sa.Column('label_cost_usd', sa.Float(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('corpus_topic_runs', schema=None) as batch_op:
        batch_op.create_index('ix_corpus_topic_runs_project_id', ['project_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('corpus_topic_runs')
