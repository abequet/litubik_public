"""Several studies per article: extraction_studies + study_id keys

Roadmap chantier 9. One ExtractionStudy row per study an article reports;
extraction values, appraisals and consensus rows are re-keyed on the study,
synthesis outcomes list study ids. The default study (position 0) is created
here for every record that already carries extraction data, an appraisal, a
consensus, a design or a synthesis reference — eagerly, so the same study
gets the same uuid on every instance that migrates the same data.

Revision ID: f9c2e4a7b1d5
Revises: f4b8d2e6a9c3
Create Date: 2026-10-14 21:00:00.000000

"""
import json
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f9c2e4a7b1d5'
down_revision: Union[str, Sequence[str], None] = 'f4b8d2e6a9c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# the pre-existing unique constraints were created without a name; batch mode
# names reflected constraints with this convention so they can be dropped
NAMING = {"uq": "uq_%(table_name)s_%(column_0_N_name)s"}

TABLES = ("extraction_values", "jbi_appraisals", "appraisal_consensus")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'extraction_studies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column('record_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('study_design', sa.String(length=40), nullable=True),
        sa.Column('design_origin', sa.String(length=10), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['record_id'], ['records.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('record_id', 'position',
                            name='uq_extraction_studies_record_position'),
    )
    with op.batch_alter_table('extraction_studies', schema=None) as batch_op:
        batch_op.create_index('ix_extraction_studies_uuid', ['uuid'], unique=True)
        batch_op.create_index('ix_extraction_studies_record_id', ['record_id'])

    # -- eager default studies for every record already touched --------------
    conn = op.get_bind()
    touched: set[int] = set()
    for table in TABLES:
        touched |= {row[0] for row in conn.execute(
            sa.text(f"SELECT DISTINCT record_id FROM {table}"))}
    touched |= {row[0] for row in conn.execute(sa.text(
        "SELECT id FROM records WHERE study_design IS NOT NULL"))}
    for (raw,) in conn.execute(sa.text("SELECT record_ids FROM synthesis_outcomes")):
        try:
            ids = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except ValueError:
            ids = []
        touched |= {int(x) for x in ids if isinstance(x, int)}
    designs = {row[0]: (row[1], row[2]) for row in conn.execute(sa.text(
        "SELECT id, study_design, design_origin FROM records"))}
    now = datetime.now(timezone.utc)
    for rid in sorted(touched):
        if rid not in designs:
            continue  # dangling reference
        design, origin = designs[rid]
        conn.execute(sa.text(
            "INSERT INTO extraction_studies (uuid, record_id, label, position, "
            "study_design, design_origin, created_by, created_at) VALUES "
            "(:uuid, :rid, 'Study 1', 0, :design, :origin, NULL, :now)"),
            {"uuid": str(uuid.uuid4()), "rid": rid, "design": design,
             "origin": origin, "now": now})

    # -- study_id on the three keyed tables ----------------------------------
    for table in TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('study_id', sa.Integer(), nullable=True))
        conn.execute(sa.text(
            f"UPDATE {table} SET study_id = (SELECT s.id FROM extraction_studies s "
            f"WHERE s.record_id = {table}.record_id AND s.position = 0)"))

    with op.batch_alter_table('extraction_values', schema=None,
                              naming_convention=NAMING) as batch_op:
        batch_op.drop_constraint('uq_extraction_values_record_id_column_id_user_id',
                                 type_='unique')
        batch_op.alter_column('study_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key('fk_extraction_values_study', 'extraction_studies',
                                    ['study_id'], ['id'], ondelete='CASCADE')
        batch_op.create_unique_constraint('uq_extraction_values_study_column_user',
                                          ['study_id', 'column_id', 'user_id'])
        batch_op.create_index('ix_extraction_values_study_id', ['study_id'])

    with op.batch_alter_table('jbi_appraisals', schema=None,
                              naming_convention=NAMING) as batch_op:
        batch_op.drop_constraint('uq_jbi_appraisals_record_id_user_id', type_='unique')
        batch_op.alter_column('study_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key('fk_jbi_appraisals_study', 'extraction_studies',
                                    ['study_id'], ['id'], ondelete='CASCADE')
        batch_op.create_unique_constraint('uq_jbi_appraisals_study_user',
                                          ['study_id', 'user_id'])
        batch_op.create_index('ix_jbi_appraisals_study_id', ['study_id'])

    with op.batch_alter_table('appraisal_consensus', schema=None,
                              naming_convention=NAMING) as batch_op:
        batch_op.drop_constraint('uq_appraisal_consensus_record_id', type_='unique')
        batch_op.alter_column('study_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key('fk_appraisal_consensus_study', 'extraction_studies',
                                    ['study_id'], ['id'], ondelete='CASCADE')
        batch_op.create_unique_constraint('uq_appraisal_consensus_study', ['study_id'])
        batch_op.create_index('ix_appraisal_consensus_study_id', ['study_id'])

    # -- synthesis outcomes: record_ids -> study_ids -------------------------
    with op.batch_alter_table('synthesis_outcomes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('study_ids', sa.JSON(), nullable=True))
    default_study = {row[0]: row[1] for row in conn.execute(sa.text(
        "SELECT record_id, id FROM extraction_studies WHERE position = 0"))}
    for oid, raw in conn.execute(sa.text("SELECT id, record_ids FROM synthesis_outcomes")):
        try:
            ids = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except ValueError:
            ids = []
        study_ids = [default_study[int(x)] for x in ids
                     if isinstance(x, int) and int(x) in default_study]
        conn.execute(sa.text("UPDATE synthesis_outcomes SET study_ids = :ids WHERE id = :oid"),
                     {"ids": json.dumps(study_ids), "oid": oid})
    conn.execute(sa.text("UPDATE synthesis_outcomes SET study_ids = '[]' WHERE study_ids IS NULL"))
    with op.batch_alter_table('synthesis_outcomes', schema=None) as batch_op:
        batch_op.alter_column('study_ids', existing_type=sa.JSON(), nullable=False)
        batch_op.drop_column('record_ids')


def downgrade() -> None:
    """Downgrade schema: values fold back onto the article (first study)."""
    conn = op.get_bind()
    with op.batch_alter_table('synthesis_outcomes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('record_ids', sa.JSON(), nullable=True))
    record_of = {row[0]: row[1] for row in conn.execute(sa.text(
        "SELECT id, record_id FROM extraction_studies"))}
    for oid, raw in conn.execute(sa.text("SELECT id, study_ids FROM synthesis_outcomes")):
        ids = json.loads(raw) if isinstance(raw, str) else (raw or [])
        rids = list(dict.fromkeys(record_of[s] for s in ids if s in record_of))
        conn.execute(sa.text("UPDATE synthesis_outcomes SET record_ids = :ids WHERE id = :oid"),
                     {"ids": json.dumps(rids), "oid": oid})
    with op.batch_alter_table('synthesis_outcomes', schema=None) as batch_op:
        batch_op.drop_column('study_ids')

    for table in TABLES:
        # keep one row per article: the first study's
        conn.execute(sa.text(
            f"DELETE FROM {table} WHERE study_id NOT IN "
            "(SELECT id FROM extraction_studies WHERE position = 0)"))
    with op.batch_alter_table('extraction_values', schema=None) as batch_op:
        batch_op.drop_index('ix_extraction_values_study_id')
        batch_op.drop_constraint('uq_extraction_values_study_column_user', type_='unique')
        batch_op.drop_constraint('fk_extraction_values_study', type_='foreignkey')
        batch_op.drop_column('study_id')
        batch_op.create_unique_constraint(None, ['record_id', 'column_id', 'user_id'])
    with op.batch_alter_table('jbi_appraisals', schema=None) as batch_op:
        batch_op.drop_index('ix_jbi_appraisals_study_id')
        batch_op.drop_constraint('uq_jbi_appraisals_study_user', type_='unique')
        batch_op.drop_constraint('fk_jbi_appraisals_study', type_='foreignkey')
        batch_op.drop_column('study_id')
        batch_op.create_unique_constraint(None, ['record_id', 'user_id'])
    with op.batch_alter_table('appraisal_consensus', schema=None) as batch_op:
        batch_op.drop_index('ix_appraisal_consensus_study_id')
        batch_op.drop_constraint('uq_appraisal_consensus_study', type_='unique')
        batch_op.drop_constraint('fk_appraisal_consensus_study', type_='foreignkey')
        batch_op.drop_column('study_id')
        batch_op.create_unique_constraint(None, ['record_id'])
    op.drop_table('extraction_studies')
