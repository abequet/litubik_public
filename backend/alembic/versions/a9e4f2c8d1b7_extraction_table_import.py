"""External extraction-table import: records.ft_forced_included flag
(articles imported at the extraction stage, screened on another platform)

Revision ID: a9e4f2c8d1b7
Revises: f5c8d2a6b9e4
Create Date: 2026-07-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9e4f2c8d1b7'
down_revision: Union[str, Sequence[str], None] = 'f5c8d2a6b9e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("records", sa.Column("ft_forced_included", sa.Boolean(),
                                       nullable=False,
                                       server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("records", "ft_forced_included")
