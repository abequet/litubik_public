"""users.session_salt: bind session tokens to the account, not to its id

SQLite gives a deleted account's id to the next account created, so a token
kept from a deleted account would open the new one. Existing accounts keep
NULL: their current tokens carry no salt and stay valid; every account created
from now on gets one.

Revision ID: d5a9c3e7f1b4
Revises: b8e4f2a6c1d9
Create Date: 2026-10-26 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd5a9c3e7f1b4'
down_revision: Union[str, Sequence[str], None] = 'b8e4f2a6c1d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # a plain ADD COLUMN: never a batch rebuild of the users table, which every
    # other table references
    op.add_column("users", sa.Column("session_salt", sa.String(length=32),
                                     nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("session_salt")
