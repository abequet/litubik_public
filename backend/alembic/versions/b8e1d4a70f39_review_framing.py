"""Project review type and question framework (PICO -> SPIDER & co)

Revision ID: b8e1d4a70f39
Revises: a3f7c15d9b62
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e1d4a70f39'
down_revision: Union[str, Sequence[str], None] = 'a3f7c15d9b62'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    server_default carries every existing project onto the historical
    behaviour (systematic review, PICOS) with no data migration.
    """
    op.add_column('projects', sa.Column(
        'review_type', sa.String(length=30), nullable=False,
        server_default='systematic'))
    op.add_column('projects', sa.Column(
        'question_framework', sa.String(length=20), nullable=False,
        server_default='picos'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('projects', 'question_framework')
    op.drop_column('projects', 'review_type')
