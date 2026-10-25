"""Support tickets — tickets + ticket_comments

Revision ID: b3e7f1a8c2d9
Revises: a9b2c4d5e6f7
Create Date: 2026-07-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3e7f1a8c2d9'
down_revision: Union[str, Sequence[str], None] = 'a9b2c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'tickets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False, server_default='bug'),
        sa.Column('severity', sa.String(length=20), nullable=False, server_default='minor'),
        sa.Column('page', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='open'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.create_index('ix_tickets_status', ['status'])

    op.create_table(
        'ticket_comments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('ticket_comments', schema=None) as batch_op:
        batch_op.create_index('ix_ticket_comments_ticket_id', ['ticket_id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('ticket_comments', schema=None) as batch_op:
        batch_op.drop_index('ix_ticket_comments_ticket_id')
    op.drop_table('ticket_comments')
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.drop_index('ix_tickets_status')
    op.drop_table('tickets')
