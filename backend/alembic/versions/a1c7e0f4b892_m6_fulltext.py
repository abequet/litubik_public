"""M6: full-text retrieval — fulltexts columns + fulltext_configs

Revision ID: a1c7e0f4b892
Revises: f3b82ae65c04
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c7e0f4b892'
down_revision: Union[str, Sequence[str], None] = 'f3b82ae65c04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('fulltexts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('filename', sa.String(length=500),
                                      nullable=False, server_default=''))
        batch_op.add_column(sa.Column('oa_url', sa.Text(), nullable=False,
                                      server_default=''))
        batch_op.add_column(sa.Column('error', sa.Text(), nullable=False,
                                      server_default=''))
        batch_op.add_column(sa.Column('size_kb', sa.Integer(), nullable=True))

    op.create_table(
        'fulltext_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('unpaywall_email', sa.String(length=255), nullable=False,
                  server_default=''),
        sa.Column('scihub_mirror', sa.String(length=255), nullable=False,
                  server_default=''),
        sa.Column('institutions', sa.JSON(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('fulltext_configs')
    with op.batch_alter_table('fulltexts', schema=None) as batch_op:
        batch_op.drop_column('size_kb')
        batch_op.drop_column('error')
        batch_op.drop_column('oa_url')
        batch_op.drop_column('filename')
