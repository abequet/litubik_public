"""Identity sent to the open scholarly APIs (app/core/polite.py): the
operator's address when there is one, no address otherwise — never a
placeholder one."""
import re
from pathlib import Path

import pytest

from app.core import polite
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _no_cache():
    polite.reset_cache()
    yield
    polite.reset_cache()


def test_without_an_address_nothing_is_claimed():
    assert polite.contact_email() == ""
    assert "mailto" not in polite.user_agent()
    assert polite.user_agent().startswith("LitUbik/")
    assert polite.mailto() == {}
    assert polite.ncbi_params() == {"tool": "litubik"}


def test_the_instance_setting_wins(monkeypatch):
    monkeypatch.setattr(get_settings(), "contact_email", "ops@lab.example")
    assert polite.mailto() == {"mailto": "ops@lab.example"}
    assert "mailto:ops@lab.example" in polite.user_agent()
    assert polite.ncbi_params() == {"tool": "litubik", "email": "ops@lab.example"}


def test_falls_back_on_the_global_unpaywall_address():
    from app.core.db import SessionLocal
    from app.models import FulltextConfig
    with SessionLocal() as db:
        db.add(FulltextConfig(project_id=None, unpaywall_email="lib@uni.example"))
        db.commit()
    assert polite.mailto() == {"mailto": "lib@uni.example"}


def test_no_placeholder_address_left_in_the_sources():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    placeholder = re.compile(r"(contact|litubik)@example\.(org|com)")
    offenders = [str(p.relative_to(app_dir)) for p in app_dir.rglob("*.py")
                 if placeholder.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
