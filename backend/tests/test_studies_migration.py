"""Chantier 9 — the extraction_studies migration on a populated database.

The suite builds its schema from the models, never through alembic, so this
test drives alembic in a subprocess against its own throwaway data dir:
upgrade to the revision before the change, seed rows the way the old schema
stored them, upgrade to head, and check that every row was re-keyed onto an
eagerly created default study while untouched records got none.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
BEFORE = "f4b8d2e6a9c3"
NOW = datetime.now(timezone.utc).isoformat()


def _alembic(data_dir: str, target: str) -> None:
    env = dict(os.environ, LITUBIK_DATA_DIR=data_dir,
               LITUBIK_SECRET_KEY="migration-test-key-0000")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", target],
                   cwd=BACKEND, env=env, check=True, capture_output=True)


def _insert(conn: sqlite3.Connection, table: str, **given) -> int:
    """INSERT with the given columns, filling every other NOT NULL column
    that has no default with a type-appropriate dummy — the seed only has to
    name what the migration reads."""
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    row = dict(given)
    for _, name, ctype, notnull, default, pk in cols:
        if name in row or pk or not notnull or default is not None:
            continue
        t = (ctype or "").upper()
        if "INT" in t or "BOOL" in t or "FLOAT" in t or "NUM" in t:
            row[name] = 0
        elif "DATE" in t:
            row[name] = NOW
        elif "JSON" in t:
            row[name] = "{}"
        else:
            row[name] = ""
    keys = list(row)
    conn.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES "
                 f"({', '.join('?' for _ in keys)})", [row[k] for k in keys])
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def test_migration_rekeys_rows_onto_default_studies():
    data_dir = tempfile.mkdtemp(prefix="litubik_mig_")
    _alembic(data_dir, BEFORE)
    db_path = next(Path(data_dir).rglob("*.db"))
    conn = sqlite3.connect(db_path)
    uid = _insert(conn, "users", email="a@example.com", password_hash="x",
                  display_name="A", is_admin=1)
    pid = _insert(conn, "projects", uuid="p-1", name="P")
    sid = _insert(conn, "sources", uuid="s-1", project_id=pid, type="database",
                  name="pubmed", round=1)
    iid = _insert(conn, "imports", uuid="i-1", project_id=pid, source_id=sid)
    rec = [_insert(conn, "records", uuid=f"r-{i}", project_id=pid, import_id=iid,
                   title=f"Record {i}", authors="[]", dedup_status="unique")
           for i in range(1, 5)]
    # record 1: a value + an appraisal + a consensus + a design
    # record 2: only a design; record 3: only referenced by an outcome
    # record 4: untouched -> must NOT get a study
    conn.execute("UPDATE records SET study_design='rct', design_origin='human' "
                 "WHERE id IN (?, ?)", (rec[0], rec[1]))
    col = _insert(conn, "extraction_columns", uuid="c-1", project_id=pid,
                  name="Country", col_type="text", options="[]", is_jbi=0,
                  position=0)
    val = _insert(conn, "extraction_values", record_id=rec[0], column_id=col,
                  user_id=uid, value=json.dumps({"v": "FR"}), origin="human",
                  validated=1, updated_at=NOW)
    jbi = _insert(conn, "jbi_appraisals", record_id=rec[0], user_id=uid,
                  design="rct", answers=json.dumps({"q1": {"answer": "yes"}}),
                  overall="include", updated_at=NOW)
    cons = _insert(conn, "appraisal_consensus", project_id=pid, record_id=rec[0],
                   design="rct", answers="{}", updated_at=NOW)
    out = _insert(conn, "synthesis_outcomes", uuid="o-1", project_id=pid,
                  label="Outcome", record_ids=json.dumps([rec[0], rec[2]]))
    conn.commit()
    conn.close()

    _alembic(data_dir, "head")

    conn = sqlite3.connect(db_path)
    studies = {r[0]: r for r in conn.execute(
        "SELECT record_id, id, position, label, study_design, design_origin, uuid "
        "FROM extraction_studies")}
    assert set(studies) == {rec[0], rec[1], rec[2]}       # record 4 untouched
    for r in studies.values():
        assert r[2] == 0 and r[3] == "Study 1" and len(r[6]) == 36
    assert studies[rec[0]][4:6] == ("rct", "human")
    assert studies[rec[2]][4] is None
    s1 = studies[rec[0]][1]
    assert conn.execute("SELECT study_id FROM extraction_values WHERE id=?",
                        (val,)).fetchone()[0] == s1
    assert conn.execute("SELECT study_id FROM jbi_appraisals WHERE id=?",
                        (jbi,)).fetchone()[0] == s1
    assert conn.execute("SELECT study_id FROM appraisal_consensus WHERE id=?",
                        (cons,)).fetchone()[0] == s1
    study_ids = json.loads(conn.execute(
        "SELECT study_ids FROM synthesis_outcomes WHERE id=?", (out,)).fetchone()[0])
    assert study_ids == [s1, studies[rec[2]][1]]
    columns = {c[1] for c in conn.execute("PRAGMA table_info(synthesis_outcomes)")}
    assert "record_ids" not in columns and "study_ids" in columns
    # the new unique keys hold: a second value on the same study/column/user
    # is refused, one on another study is fine
    with __import__("pytest").raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO extraction_values (record_id, study_id, column_id, "
                     "user_id, value, origin, validated, updated_at) VALUES "
                     "(?, ?, ?, ?, '{}', 'human', 0, ?)", (rec[0], s1, col, uid, NOW))
    conn.rollback()
    uniques = conn.execute("SELECT sql FROM sqlite_master WHERE name='extraction_values'"
                           ).fetchone()[0]
    assert "uq_extraction_values_study_column_user" in uniques
    assert "record_id, column_id, user_id" not in uniques.replace('"', "")
    conn.close()
