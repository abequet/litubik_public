"""Reporting stage: AI-use journal + generated report sections

Revision ID: a3f7c15d9b62
Revises: d5b2c9e037a1
Create Date: 2026-07-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f7c15d9b62'
down_revision: Union[str, Sequence[str], None] = 'd5b2c9e037a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'ai_usage',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(),
                  sa.ForeignKey('projects.id', ondelete='CASCADE'),
                  nullable=True),
        sa.Column('feature', sa.String(length=40), nullable=False),
        sa.Column('provider', sa.String(length=30), nullable=False,
                  server_default=''),
        sa.Column('model', sa.String(length=100), nullable=False,
                  server_default=''),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('day', sa.String(length=10), nullable=False),
        sa.Column('n_calls', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('tokens_in', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('tokens_out', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cost_usd', sa.Float(), nullable=False, server_default='0'),
        sa.Column('first_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('imported_from', sa.String(length=255), nullable=True),
        sa.UniqueConstraint('project_id', 'feature', 'provider', 'model',
                            'user_id', 'day', name='uq_ai_usage_bucket'),
    )
    op.create_index('ix_ai_usage_project_id', 'ai_usage', ['project_id'])
    op.create_index('ix_ai_usage_feature', 'ai_usage', ['feature'])

    op.create_table(
        'report_sections',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(),
                  sa.ForeignKey('projects.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('lang', sa.String(length=5), nullable=False,
                  server_default='en'),
        sa.Column('content_md', sa.Text(), nullable=False, server_default=''),
        sa.Column('edited_md', sa.Text(), nullable=False, server_default=''),
        sa.Column('form', sa.JSON(), nullable=True),
        sa.Column('provider', sa.String(length=30), nullable=False,
                  server_default=''),
        sa.Column('model', sa.String(length=100), nullable=False,
                  server_default=''),
        sa.Column('tokens_in', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('tokens_out', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cost_usd', sa.Float(), nullable=False, server_default='0'),
        sa.Column('generated_by', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('project_id', 'kind'),
    )
    op.create_index('ix_report_sections_project_id', 'report_sections',
                    ['project_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_report_sections_project_id', table_name='report_sections')
    op.drop_table('report_sections')
    op.drop_index('ix_ai_usage_feature', table_name='ai_usage')
    op.drop_index('ix_ai_usage_project_id', table_name='ai_usage')
    op.drop_table('ai_usage')
