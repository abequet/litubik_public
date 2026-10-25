# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Legal pages of an instance open to the public: legal notice, terms of use,
privacy notice — in English and French.

Each page is a shipped Markdown template (app/data/legal/<lang>/<slug>.md)
filled with this instance's values, unless the superadmin saved their own
text for it. The values come from the `legal_settings` row, and when a field
is empty, from automatic defaults:

- operator: the display name of the first superadmin account;
- contact: the project's public address (core/version.py);
- host: detected — a Railway container carries RAILWAY_* variables;
- reset hour and AI caps: the instance settings.

Nothing personal is written in the templates themselves: they ship with the
public source code.
"""
import os
import re

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.paths import app_data_dir
from app.models import LegalPage, LegalSettings, User

SLUGS = ("notice", "terms", "privacy")
LANGS = ("en", "fr")

# hosts recognised from their environment (first match wins)
_KNOWN_HOSTS = (
    ("RAILWAY_", "Railway Corporation",
     "548 Market St PMB 68956, San Francisco, CA 94104, USA — "
     "https://railway.com"),
)

_TO_COMPLETE = {"en": "[to be completed]", "fr": "[à compléter]"}


def detected_host() -> tuple[str, str]:
    for prefix, name, address in _KNOWN_HOSTS:
        if any(key.startswith(prefix) for key in os.environ):
            return name, address
    return "", ""


def default_operator(db: Session) -> str:
    admin = (db.query(User).filter(User.is_admin.is_(True))
             .order_by(User.id).first())
    return admin.display_name if admin else ""


def settings_row(db: Session) -> LegalSettings | None:
    return db.get(LegalSettings, 1)


def effective_values(db: Session) -> dict:
    """The values the templates are filled with, defaults applied."""
    from app.core.version import CONTACT_EMAIL, SOURCE_URL
    row = settings_row(db)
    host_name, host_address = detected_host()
    settings = get_settings()
    return {
        "operator_name": (row.operator_name if row and row.operator_name
                          else default_operator(db)),
        "contact_email": (row.contact_email if row and row.contact_email
                          else CONTACT_EMAIL),
        "host_name": row.host_name if row and row.host_name else host_name,
        "host_address": (row.host_address if row and row.host_address
                         else host_address),
        "reset_hour": f"{max(settings.demo_reset_hour, 0):02d}:00",
        "session_hours": str(max(1, settings.access_token_expire_minutes // 60)),
        "ai_user_cap": f"{settings.demo_ai_user_cap_usd:.2f}",
        "ai_daily_cap": f"{settings.demo_ai_daily_cap_usd:.2f}",
        "ai_monthly_cap": f"{settings.demo_ai_monthly_cap_usd:.2f}",
        "source_url": SOURCE_URL,
    }


def render_template(slug: str, lang: str, values: dict) -> str:
    text = (app_data_dir() / "legal" / lang / f"{slug}.md").read_text(
        encoding="utf-8")

    def fill(match: re.Match) -> str:
        value = str(values.get(match.group(1), "")).strip()
        return value or _TO_COMPLETE[lang]

    return re.sub(r"\{\{\s*(\w+)\s*\}\}", fill, text)


def available_slugs(db: Session) -> list[str]:
    """The pages this instance publishes: all of them on a demo instance (it
    is open to the public), elsewhere only those the superadmin wrote — a
    desktop install shows none."""
    if get_settings().demo_mode:
        return list(SLUGS)
    written = {slug for (slug,) in db.query(LegalPage.slug).distinct()}
    return [slug for slug in SLUGS if slug in written]


def page(db: Session, slug: str, lang: str) -> dict:
    custom = db.query(LegalPage).filter_by(slug=slug, lang=lang).first()
    template = render_template(slug, lang, effective_values(db))
    return {
        "slug": slug,
        "lang": lang,
        "body_md": custom.body_md if custom else template,
        "custom": custom is not None,
        "template_md": template,
        "updated_at": (custom.updated_at.isoformat()
                       if custom and custom.updated_at else None),
    }
