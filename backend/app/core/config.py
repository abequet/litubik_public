# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import secrets
import stat
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LITUBIK_",
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "LitUbik"
    secret_key: str = "dev-insecure-secret-change-me"
    access_token_expire_minutes: int = 720
    # H1: False (the default) does NOT close registration outright — it makes it
    # *restricted*: only the first account of a fresh instance, an allowlisted
    # email (LITUBIK_TRUSTED_EMAILS / TrustedEmail), someone a project admin
    # already added to a team, or an open project invitation can register. See
    # _registration_allowed() in app/api/auth.py. True restores free signup.
    allow_registration: bool = False
    # M8: mark the session cookie Secure so the JWT never travels over plain
    # HTTP. Off by default to keep LAN/desktop dev on http://; set
    # LITUBIK_SESSION_COOKIE_SECURE=true on any HTTPS deployment.
    session_cookie_secure: bool = False
    # M1: expose /docs, /redoc and /openapi.json. Off by default — the explorer
    # maps the whole API surface for any visitor. Turn on while developing.
    api_docs: bool = False
    # silent abstract backfill after every search/upload (open APIs: OpenAlex,
    # Semantic Scholar, PubMed). Off = records keep whatever the source gave;
    # the manual pass of the Snowballing page stays available.
    abstract_backfill: bool = True
    # Contact address sent to Crossref / OpenAlex (polite pool) and NCBI
    # E-utilities. Empty: the instance-wide Unpaywall e-mail is used if an
    # admin set one, otherwise requests go out without an address — never a
    # placeholder one (app/core/polite.py).
    contact_email: str = ""
    # L8: when set, a project's shared-sync folder must live under this base
    # directory — bounds the arbitrary-mkdir primitive of set_folder on a hosted
    # instance. Empty (desktop default) keeps the previous free-path behaviour.
    sync_folder_base: str = ""
    data_dir: Path = PROJECT_ROOT / "data"
    database_url: str = ""  # derived from data_dir when empty
    # Public demo instance. demo_mode splits accounts in two tiers: emails on
    # the superadmin's allowlist register as full ("trusted") accounts;
    # everyone else gets a sandbox account that the daily reset purges and
    # that never reaches the optional retrieval extension. These settings are
    # inert on a normal instance.
    # env is LITUBIK_DEMO (the field name would otherwise map to
    # LITUBIK_DEMO_MODE under the prefix — both are accepted here)
    demo_mode: bool = Field(
        default=False,
        validation_alias=AliasChoices("LITUBIK_DEMO", "LITUBIK_DEMO_MODE"))
    demo_reset_hour: int = 4  # UTC hour of the daily selective purge; -1 = never
    trusted_emails: str = ""  # comma-separated allowlist seed (env-provisioned)
    # Host names (fnmatch patterns, comma-separated) that open the one-click
    # guest entry of a demo instance. One deployment can then answer on
    # `demo.example.org` with the guest button and on `example.org` with the
    # ordinary sign-in of its full accounts.
    demo_guest_hosts: str = "demo.*"
    # What the demo visitors may spend on the app-wide AI key (USD): per
    # sandbox account, and all of them together per UTC day and per calendar
    # month — the daily share keeps one busy afternoon from emptying the
    # month. 0 turns AI off for visitors.
    demo_ai_user_cap_usd: float = 2.0
    demo_ai_daily_cap_usd: float = 1.0
    demo_ai_monthly_cap_usd: float = 10.0

    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'litubik.db').as_posix()}"

    @property
    def storage_dir(self) -> Path:
        return self.data_dir / "storage" / "projects"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    if settings.secret_key == "dev-insecure-secret-change-me":
        # no key configured (env / backend/.env): auto-generate one and keep
        # it with the data — it signs sessions AND encrypts stored API keys,
        # so it must survive restarts (packaged one-click mode relies on this)
        key_file = settings.data_dir / "secret.key"
        if key_file.exists():
            stored = key_file.read_text(encoding="utf-8").strip()
        else:
            stored = secrets.token_urlsafe(48)
            # L1: the key signs JWTs AND decrypts stored API keys — on a shared
            # host another local user must not be able to read it. Create it
            # owner-only (0600) via os.open so it is never briefly world-
            # readable; chmod is best-effort/no-op on Windows.
            fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                         stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(stored)
        try:
            key_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        if stored:
            settings.secret_key = stored
    return settings
