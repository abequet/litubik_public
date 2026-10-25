"""M5: per-installation signing key + author key binding

The project passphrase is shared by every member, so the HMAC on a contribution
package proves membership, not authorship. Each installation now signs its
outbound packages with an Ed25519 key, and the coordinator binds an author to
the key seen on their first signed package.

Revision ID: d5b2c9e037a1
Revises: c3f8a1d64b70
Create Date: 2026-07-25
"""
import sqlalchemy as sa
from alembic import op

revision = "d5b2c9e037a1"
down_revision = "c3f8a1d64b70"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("instance_meta") as batch:
        batch.add_column(sa.Column("signing_key_encrypted", sa.Text(),
                                   nullable=False, server_default=""))
    with op.batch_alter_table("project_members") as batch:
        batch.add_column(sa.Column("sync_pubkey", sa.String(length=64),
                                   nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("project_members") as batch:
        batch.drop_column("sync_pubkey")
    with op.batch_alter_table("instance_meta") as batch:
        batch.drop_column("signing_key_encrypted")
