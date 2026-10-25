"""M6 demo allowlist: provenance of an entry (manual vs project invitation)

Revision ID: b2d6f8a3c1e5
Revises: a9e4f2c8d1b7
Create Date: 2026-07-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2d6f8a3c1e5'
down_revision: Union[str, Sequence[str], None] = 'a9e4f2c8d1b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trusted_emails",
                  sa.Column("source", sa.String(length=20),
                            nullable=False, server_default="manual"))


def downgrade() -> None:
    op.drop_column("trusted_emails", "source")
