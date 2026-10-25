"""Sync phase 3: shared API keys — ownership + opt-in sharing on credentials,
project sync passphrase

Revision ID: a3c6f9b2d5e8
Revises: f1a8d4c7e2b9
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c6f9b2d5e8'
down_revision: Union[str, Sequence[str], None] = 'f1a8d4c7e2b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    for table in ('llm_credentials', 'database_credentials'):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('owner_user_id', sa.Integer(),
                                       nullable=True))
            batch.add_column(sa.Column('shared', sa.Boolean(), nullable=False,
                                       server_default='0'))
            batch.create_foreign_key(f'fk_{table}_owner_user_id', 'users',
                                     ['owner_user_id'], ['id'],
                                     ondelete='SET NULL')
        # continuity: existing project-scoped keys were de facto common to the
        # project — they stay usable and shared, owned by the project creator
        op.execute(sa.text(
            f"UPDATE {table} SET shared = 1, owner_user_id = ("
            f"  SELECT created_by FROM projects"
            f"  WHERE projects.id = {table}.project_id)"
            f" WHERE project_id IS NOT NULL"))

    with op.batch_alter_table('projects') as batch:
        batch.add_column(sa.Column('sync_passphrase_encrypted', sa.Text(),
                                   nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('projects') as batch:
        batch.drop_column('sync_passphrase_encrypted')
    for table in ('database_credentials', 'llm_credentials'):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f'fk_{table}_owner_user_id',
                                  type_='foreignkey')
            batch.drop_column('shared')
            batch.drop_column('owner_user_id')
