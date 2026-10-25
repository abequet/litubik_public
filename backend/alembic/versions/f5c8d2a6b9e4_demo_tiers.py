"""M6 demo instance: account tiers (users.is_trusted) + trusted_emails allowlist

Revision ID: f5c8d2a6b9e4
Revises: e8b3f6d9c2a5
Create Date: 2026-07-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f5c8d2a6b9e4'
down_revision: Union[str, Sequence[str], None] = 'e8b3f6d9c2a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # existing accounts stay full accounts even if the instance is later
    # flipped to demo mode (the flag only matters there)
    op.add_column("users", sa.Column("is_trusted", sa.Boolean(),
                                     nullable=False,
                                     server_default=sa.true()))
    op.create_table(
        "trusted_emails",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("added_by", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_trusted_emails_email", "trusted_emails", ["email"])


def downgrade() -> None:
    op.drop_index("ix_trusted_emails_email", table_name="trusted_emails")
    op.drop_table("trusted_emails")
    op.drop_column("users", "is_trusted")
