"""Instance backup endpoint: superadmin gate, consistent DB copy, stored
files inclusion."""
import io
import sqlite3
import zipfile

from app.core.config import get_settings


def test_backup_requires_superadmin(user_client):
    user_client.post("/api/auth/register", json={
        "email": "pleb@example.com", "password": "password123",
        "display_name": "Pleb"})  # register logs the new (non-admin) user in
    r = user_client.get("/api/admin/backup")
    assert r.status_code == 403


def test_backup_zip_holds_a_working_database(user_client, tmp_path):
    user_client.post("/api/projects", json={"name": "To backup"})
    r = user_client.get("/api/admin/backup")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert "litubik_backup_" in r.headers.get("content-disposition", "")

    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert "litubik.db" in zf.namelist()
        db_path = tmp_path / "restored.db"
        db_path.write_bytes(zf.read("litubik.db"))
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        names = [row[0] for row in conn.execute(
            "SELECT name FROM projects").fetchall()]
        assert "To backup" in names
    finally:
        conn.close()


def test_backup_optionally_includes_stored_files(user_client):
    storage = get_settings().storage_dir / "999" / "pdfs"
    storage.mkdir(parents=True, exist_ok=True)
    (storage / "paper.pdf").write_bytes(b"%PDF-fake")
    try:
        r = user_client.get("/api/admin/backup")
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            assert not any(n.startswith("storage/") for n in zf.namelist())

        r = user_client.get("/api/admin/backup?files=true")
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            assert "storage/projects/999/pdfs/paper.pdf" in zf.namelist()
            assert zf.read("storage/projects/999/pdfs/paper.pdf") == b"%PDF-fake"
    finally:
        (storage / "paper.pdf").unlink(missing_ok=True)
