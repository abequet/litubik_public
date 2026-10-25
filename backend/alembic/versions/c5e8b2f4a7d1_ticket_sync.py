"""Ticket sync: uuid + provenance on tickets and ticket_comments so a
reviewer's tickets travel in their contribution packages

Revision ID: c5e8b2f4a7d1
Revises: b4d7a1e3f6c9
Create Date: 2026-07-18

"""
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5e8b2f4a7d1'
down_revision: Union[str, Sequence[str], None] = 'b4d7a1e3f6c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    for table in ('tickets', 'ticket_comments'):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('uuid', sa.String(36), nullable=True))
            batch.add_column(sa.Column('imported_from', sa.String(255),
                                       nullable=True))
        rows = conn.execute(
            sa.text(f"SELECT id FROM {table} WHERE uuid IS NULL")).fetchall()
        if rows:
            conn.execute(
                sa.text(f"UPDATE {table} SET uuid = :u WHERE id = :i"),
                [{"u": str(uuid4()), "i": r[0]} for r in rows])
        with op.batch_alter_table(table) as batch:
            batch.alter_column('uuid', existing_type=sa.String(36),
                               nullable=False)
        op.create_index(f'ix_{table}_uuid', table, ['uuid'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    for table in ('ticket_comments', 'tickets'):
        op.drop_index(f'ix_{table}_uuid', table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column('imported_from')
            batch.drop_column('uuid')
