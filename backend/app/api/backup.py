# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Instance-wide backup, for a recurring pull from an admin's machine.

One zip holding a consistent copy of the SQLite database (VACUUM INTO — safe
while the app runs, WAL included), the auto-generated secret.key when one
exists (without it a restored database cannot decrypt its stored API keys),
and optionally every stored project file (PDFs, raw RIS, protocols).

Superadmin only. The companion script scripts/backup_litubik.ps1 downloads it
on a schedule and keeps the N most recent copies.
"""
import zipfile
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.api.deps import CurrentUser
from app.core.config import get_settings
from app.core.db import engine

router = APIRouter(prefix="/api/admin", tags=["backup"])


@router.get("/backup")
def download_backup(user: CurrentUser, files: bool = False):
    if not user.is_admin:
        raise HTTPException(status_code=403,
                            detail="Réservé à l'administrateur de l'instance")
    if engine.url.get_backend_name() != "sqlite":
        raise HTTPException(status_code=400,
                            detail="Sauvegarde intégrée disponible pour SQLite "
                                   "uniquement — utilisez l'outil de votre SGBD")
    settings = get_settings()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    tmp_dir = settings.data_dir / "exports" / "backups"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    db_copy = tmp_dir / f"db_{uuid4()}.db"
    # VACUUM INTO refuses to run inside a transaction — autocommit connection
    with engine.connect().execution_options(
            isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("VACUUM INTO ?", (str(db_copy),))

    zip_path = tmp_dir / f"backup_{uuid4()}.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_copy, "litubik.db")
            key_file = settings.data_dir / "secret.key"
            if key_file.exists():
                zf.write(key_file, "secret.key")
            if files:
                storage_root = settings.data_dir / "storage"
                for f in sorted(storage_root.rglob("*")):
                    if f.is_file():
                        rel = f.relative_to(storage_root).as_posix()
                        zf.write(f, f"storage/{rel}")
    finally:
        db_copy.unlink(missing_ok=True)

    def _cleanup(path=zip_path):
        path.unlink(missing_ok=True)

    return FileResponse(zip_path, media_type="application/zip",
                        filename=f"litubik_backup_{stamp}.zip",
                        background=BackgroundTask(_cleanup))
