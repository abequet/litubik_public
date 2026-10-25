# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Locations that differ between a source checkout and a frozen (PyInstaller)
build. The spec bundles frontend/dist as `frontend_dist` and the alembic
scripts + ini next to the executable's extraction root."""
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", "."))


def backend_dir() -> Path:
    if is_frozen():
        return bundle_dir()
    return Path(__file__).resolve().parents[2]


def frontend_dist() -> Path:
    if is_frozen():
        return bundle_dir() / "frontend_dist"
    return backend_dir().parent / "frontend" / "dist"


def alembic_dir() -> Path:
    if is_frozen():
        return bundle_dir() / "alembic"
    return backend_dir() / "alembic"


def alembic_ini() -> Path:
    if is_frozen():
        return bundle_dir() / "alembic.ini"
    return backend_dir() / "alembic.ini"


def help_dir() -> Path:
    if is_frozen():
        return bundle_dir() / "docs_help"
    return backend_dir().parent / "docs" / "help"


def app_data_dir() -> Path:
    """Static data files shipped with the backend (e.g. the EZproxy database)."""
    if is_frozen():
        return bundle_dir() / "app_data"
    return backend_dir() / "app" / "data"
