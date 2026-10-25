"""drop fulltext_configs.scihub_mirror

The per-project custom-mirror setting was removed from the full-text
retrieval: it let a user point the downloader at an arbitrary host (an SSRF
vector), and no source in the cascade uses it any more.

Revision ID: c3f8a1d64b70
Revises: 4921b25a4349
Create Date: 2026-07-25
"""
import sqlalchemy as sa
from alembic import op

revision = "c3f8a1d64b70"
down_revision = "4921b25a4349"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("fulltext_configs") as batch:
        batch.drop_column("scihub_mirror")


def downgrade() -> None:
    with op.batch_alter_table("fulltext_configs") as batch:
        batch.add_column(sa.Column("scihub_mirror", sa.String(length=255),
                                   nullable=False, server_default=""))
