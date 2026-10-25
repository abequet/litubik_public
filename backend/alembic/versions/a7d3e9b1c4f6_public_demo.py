"""public demo: guest accounts, AI budget of demo visitors, legal pages

Revision ID: a7d3e9b1c4f6
Revises: c3e7a1f5b9d2
Create Date: 2026-10-25 18:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7d3e9b1c4f6'
down_revision: Union[str, Sequence[str], None] = 'c3e7a1f5b9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("is_guest", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))
        batch.add_column(sa.Column("demo_ai_spent_usd", sa.Float(),
                                   nullable=False, server_default="0"))
    op.create_table(
        "demo_ai_budget",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("spent_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("n_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("period"),
    )
    op.create_table(
        "legal_pages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=20), nullable=False),
        sa.Column("lang", sa.String(length=5), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("updated_by", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.UniqueConstraint("slug", "lang", name="uq_legal_page"),
    )
    op.create_table(
        "legal_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operator_name", sa.String(length=200), nullable=False,
                  server_default=""),
        sa.Column("contact_email", sa.String(length=255), nullable=False,
                  server_default=""),
        sa.Column("host_name", sa.String(length=200), nullable=False,
                  server_default=""),
        sa.Column("host_address", sa.String(length=400), nullable=False,
                  server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("legal_settings")
    op.drop_table("legal_pages")
    op.drop_table("demo_ai_budget")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("demo_ai_spent_usd")
        batch.drop_column("is_guest")
