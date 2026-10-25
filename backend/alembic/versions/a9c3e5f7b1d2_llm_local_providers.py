"""LLM: local / OpenAI-compatible providers

llm_credentials.base_url — endpoint of a self-hosted server (Ollama, LM
Studio, vLLM…), NULL for the hosted providers.
projects.llm_no_fallback — open only the best-ranked key, never fall back to
another provider (a confidentiality setting for teams on a local model).

Revision ID: a9c3e5f7b1d2
Revises: e7b2f4a91c06
Create Date: 2026-10-13 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a9c3e5f7b1d2'
down_revision: Union[str, Sequence[str], None] = 'e7b2f4a91c06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('llm_credentials', schema=None) as batch_op:
        batch_op.add_column(sa.Column('base_url', sa.String(length=300),
                                      nullable=True))
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('llm_no_fallback', sa.Boolean(),
                                      nullable=False,
                                      server_default=sa.false()))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('llm_no_fallback')
    with op.batch_alter_table('llm_credentials', schema=None) as batch_op:
        batch_op.drop_column('base_url')
