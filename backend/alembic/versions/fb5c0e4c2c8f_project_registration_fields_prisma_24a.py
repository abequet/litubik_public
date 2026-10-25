"""project registration fields (PRISMA 24a)

Revision ID: fb5c0e4c2c8f
Revises: b8e1d4a70f39
Create Date: 2026-08-13 17:22:54.382933

Autogenerate also proposed a batch of NOT NULL tightenings on JSON columns and
a uniqueness change on ix_trusted_emails_email. Those are long-standing drift
between the models and the historical schema, not part of this change; a batch
ALTER on SQLite rewrites the whole table, so they are left out rather than
carried along by an unrelated migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'fb5c0e4c2c8f'
down_revision: Union[str, Sequence[str], None] = 'b8e1d4a70f39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default '' = "the question was never answered", which is exactly
    # what every pre-existing project is: no data migration needed.
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('registry', sa.String(length=20),
                                      server_default='', nullable=False))
        batch_op.add_column(sa.Column('registration_id', sa.String(length=120),
                                      server_default='', nullable=False))
        batch_op.add_column(sa.Column('registration_url', sa.String(length=500),
                                      server_default='', nullable=False))
        batch_op.add_column(sa.Column('registered_at',
                                      sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('protocol_url', sa.String(length=500),
                                      server_default='', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('protocol_url')
        batch_op.drop_column('registered_at')
        batch_op.drop_column('registration_url')
        batch_op.drop_column('registration_id')
        batch_op.drop_column('registry')
