"""M9: users.token_version — session-token epoch, bumped on password change so
previously issued JWTs stop validating.

Revision ID: b1d7e93a4c2f
Revises: b2d6f8a3c1e5
Create Date: 2026-07-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1d7e93a4c2f'
down_revision: Union[str, Sequence[str], None] = 'b2d6f8a3c1e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_version", sa.Integer(),
                                     nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("users", "token_version")
