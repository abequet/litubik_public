"""demo AI budget: daily rows next to the monthly ones (period up to 10 chars)

Revision ID: b8e4f2a6c1d9
Revises: a7d3e9b1c4f6
Create Date: 2026-10-26 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b8e4f2a6c1d9'
down_revision: Union[str, Sequence[str], None] = 'a7d3e9b1c4f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("demo_ai_budget") as batch:
        batch.alter_column("period", existing_type=sa.String(length=7),
                           type_=sa.String(length=10), existing_nullable=False)


def downgrade() -> None:
    # day rows ("YYYY-MM-DD") do not fit the monthly column
    op.execute("DELETE FROM demo_ai_budget WHERE length(period) > 7")
    with op.batch_alter_table("demo_ai_budget") as batch:
        batch.alter_column("period", existing_type=sa.String(length=10),
                           type_=sa.String(length=7), existing_nullable=False)
