"""raw equations, golden PMIDs, recall per database, import search date

Revision ID: c4e8a1f27b93
Revises: a7d3f9c1e5b2
Create Date: 2026-10-15 10:12:00.000000

Every change is additive:
- equations.mode (server_default "concepts": every existing variant was built
  from concepts);
- golden_refs.pmid, and golden_refs.doi becomes nullable (a reference may be
  known by its PMID alone);
- equation_recalls: the per-database golden-set history;
- imports.searched_at / declared_hits (declared by the uploader);
- records.pmid (exact dedup key + recall lookup).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c4e8a1f27b93'
down_revision: Union[str, Sequence[str], None] = 'a7d3f9c1e5b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('equations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('mode', sa.String(length=10),
                                      server_default='concepts', nullable=False))
    with op.batch_alter_table('golden_refs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pmid', sa.String(length=20), nullable=True))
        batch_op.alter_column('doi', existing_type=sa.String(length=255),
                              nullable=True)
    op.create_table(
        'equation_recalls',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('equation_id', sa.Integer(), nullable=False),
        sa.Column('database_name', sa.String(length=100), nullable=False),
        sa.Column('method', sa.String(length=20), nullable=False),
        sa.Column('total', sa.Integer(), nullable=False),
        sa.Column('found', sa.Integer(), nullable=False),
        sa.Column('missing', sa.JSON(), nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['equation_id'], ['equations.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('imports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('searched_at', sa.DateTime(timezone=True),
                                      nullable=True))
        batch_op.add_column(sa.Column('declared_hits', sa.Integer(), nullable=True))
    with op.batch_alter_table('records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pmid', sa.String(length=20), nullable=True))
        batch_op.create_index(batch_op.f('ix_records_pmid'), ['pmid'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_records_pmid'))
        batch_op.drop_column('pmid')
    with op.batch_alter_table('imports', schema=None) as batch_op:
        batch_op.drop_column('declared_hits')
        batch_op.drop_column('searched_at')
    op.drop_table('equation_recalls')
    with op.batch_alter_table('golden_refs', schema=None) as batch_op:
        batch_op.alter_column('doi', existing_type=sa.String(length=255),
                              nullable=False)
        batch_op.drop_column('pmid')
    with op.batch_alter_table('equations', schema=None) as batch_op:
        batch_op.drop_column('mode')
