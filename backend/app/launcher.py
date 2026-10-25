# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""LitUbik one-click launcher: data dir + migrations + server + browser.

Entry point of the packaged executable (PyInstaller) and of
`python -m app.launcher` from a source checkout. Environment overrides:
  LITUBIK_DATA_DIR    where the DB/files live (default: per-user app data)
  LITUBIK_PORT        fixed port (default: 8000, else first free port)
  LITUBIK_NO_BROWSER  set to 1 to not open the browser (smoke tests, servers)
"""
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path


def _default_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        return base / "LitUbik" / "data"
    return Path.home() / ".local" / "share" / "litubik"


def _pick_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("0.0.0.0", port))
                return sock.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("No free TCP port")


def main() -> int:
    if not os.environ.get("LITUBIK_DATA_DIR"):
        data_dir = _default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        # must be set BEFORE any app import: settings load at import time
        os.environ["LITUBIK_DATA_DIR"] = str(data_dir)

    print("[LitUbik] Data:", os.environ["LITUBIK_DATA_DIR"], flush=True)
    print("[LitUbik] Applying database migrations...", flush=True)
    from alembic import command
    from alembic.config import Config

    from app.core.paths import alembic_dir, alembic_ini
    alembic_cfg = Config(str(alembic_ini()))
    alembic_cfg.set_main_option("script_location", str(alembic_dir()))
    command.upgrade(alembic_cfg, "head")

    import uvicorn

    from app.main import app  # noqa: E402 — after env + migrations

    port = _pick_port(int(os.environ.get("LITUBIK_PORT", "8000")))
    url = f"http://localhost:{port}"
    print(f"\n[LitUbik] Running on {url}", flush=True)
    print(f"[LitUbik] Teammates on your network: "
          f"http://{socket.gethostname()}:{port}", flush=True)
    print("[LitUbik] Keep this window open — close it (or Ctrl+C) to stop.\n",
          flush=True)
    if not os.environ.get("LITUBIK_NO_BROWSER"):
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
