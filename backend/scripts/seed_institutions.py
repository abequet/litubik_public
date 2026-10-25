"""One-time import of pre-existing EZProxy/CAS credentials into LitUbik.

Reads a JSON file of institutions and stores them as GLOBAL full-text retrieval
settings (shared across every project), passwords Fernet-encrypted in the
database. The source file, which holds plaintext passwords, is only read — never
copied into the repository or the data directory.

Expected format — either a bare list, or an object with an "institutions" key:

    {"institutions": [
      {"name": "…", "ezproxy_url": "https://…/login?url=$@",
       "username": "…", "password": "…", "scope": "", "auth_type": ""}
    ]}

Usage:
    python -m scripts.seed_institutions PATH_TO_INSTITUTIONS_JSON
"""
import json
import sys
from pathlib import Path

from app.core.db import SessionLocal
from app.services.fulltext.service import resolve_config, seed_global_institutions


def load(source: Path) -> list[dict]:
    data = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("institutions", [])
    return [i for i in data if isinstance(i, dict) and i.get("ezproxy_url")]


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    source = Path(sys.argv[1])
    if not source.is_file():
        print(f"[seed] File not found: {source}")
        sys.exit(1)
    institutions = load(source)
    if not institutions:
        print(f"[seed] No usable institution in {source}")
        sys.exit(1)
    with SessionLocal() as db:
        n = seed_global_institutions(db, institutions)
        check = resolve_config(db, project_id=-1)  # no such project -> global only
    print(f"[seed] Stored {n} global institution(s) (passwords encrypted):")
    for inst in check["institutions"]:
        has_pwd = "yes" if inst.get("password") else "no"
        print(f"  - {inst['name']}  ({inst['ezproxy_url']})  password:{has_pwd}")


if __name__ == "__main__":
    main()
