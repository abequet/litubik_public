# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Demo instance — the sandbox example project.

`create_demo_project(db, owner_user_id)` builds a small but realistic review
for one user: 60 real references (bundled OpenAlex export on smartphone-
distracted pedestrians), a validated protocol with criteria, one equation,
deduplication, a dual title/abstract screening ~70% done (agreements,
disagreements, some conflicts resolved) and a started full-text round with a
few justified exclusions — enough for the screening screens, stats and PRISMA
to show the app "in situation".

Every demo visitor gets their own copy at registration (isolation between
visitors). The second reviewer is a shared passwordless account so the
conflict/kappa views have real two-reviewer data; visitors "are" the owner.

Also usable outside the demo, e.g. for documentation screenshots:
    python -m app.services.demo_seed you@lab.org
"""
import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.paths import app_data_dir
from app.models import (
    Conflict, Project, ProjectMember, Protocol, ScreeningConfig, User, Vote,
)
from app.services.connectors.jobs import (
    archive_raw, get_or_create_source, store_import,
)
from app.services.dedup.core import run_dedup
from app.services.equations.translate import build_structure, translate_all
from app.services.ris.parse import parse_file
from app.services.screening.core import ensure_conflict, generate_assignments

logger = logging.getLogger(__name__)

PROJECT_NAME = "Example review — distracted pedestrians (sandbox)"
CO_REVIEWER_EMAIL = "demo-reviewer@litubik.example"
CO_REVIEWER_NAME = "Alex (demo co-reviewer)"

CRITERIA = [
    {"code": "I1", "type": "include", "label": "Pedestrian population",
     "description": "Pedestrians of any age, real or simulated road environment."},
    {"code": "I2", "type": "include", "label": "Phone exposure",
     "description": "Phone/smartphone interaction while walking or crossing."},
    {"code": "I3", "type": "include", "label": "Safety outcome",
     "description": "Safety-related behaviour or crash/near-miss indicators."},
    {"code": "E1", "type": "exclude", "label": "Wrong population",
     "description": "Drivers, cyclists or other non-pedestrian road users only."},
    {"code": "E2", "type": "exclude", "label": "Wrong exposure",
     "description": "No phone interaction measured."},
    {"code": "E3", "type": "exclude", "label": "Wrong publication type",
     "description": "Review, editorial or abstract without original data."},
]

CONCEPTS = [
    ("Population", ["pedestrian", "pedestrians", "walking", "crossing"]),
    ("Exposure", ["smartphone", "mobile phone", "cell phone", "texting",
                  "phone use", "distraction"]),
    ("Outcome", ["safety", "risk", "behaviour", "behavior", "crash",
                 "near-miss", "attention"]),
]

# deterministic pseudo-randomness: the demo looks alive but every sandbox is
# identical and the numbers in tests/help stay stable
def _bucket(key: str, n: int = 100) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest(), 16) % n


def _relevant(record) -> bool:
    """Topical include/exclude heuristic on the real titles: keeps decisions
    meaningful when a visitor opens individual records."""
    text = (record.title or "").lower()
    pedestrian = any(k in text for k in ("pedestrian", "walk", "crossing", "street"))
    phone = any(k in text for k in ("phone", "smartphone", "text", "distract",
                                    "mobile", "device"))
    return pedestrian and phone


def _reason_for(record) -> list[str]:
    text = (record.title or "").lower()
    if any(k in text for k in ("driver", "driving", "cyclist")):
        return ["E1"]
    if any(k in text for k in ("review", "meta-analysis", "systematic")):
        return ["E3"]
    return ["E2"]


def _get_or_create_co_reviewer(db: Session) -> User:
    user = db.query(User).filter_by(email=CO_REVIEWER_EMAIL).first()
    if user is None:
        # passwordless (cannot log in) and trusted so the daily demo reset
        # never deletes it (votes of every sandbox reference this account)
        user = User(email=CO_REVIEWER_EMAIL, password_hash="",
                    display_name=CO_REVIEWER_NAME, is_trusted=True)
        db.add(user)
        db.flush()
    return user


def _vote(db: Session, project_id: int, record_id: int, stage: str,
          user_id: int, decision: str, reasons: list[str] | None = None):
    db.add(Vote(project_id=project_id, record_id=record_id, stage=stage,
                round=1, voter_user_id=user_id, is_ai=False, decision=decision,
                reasons=reasons or []))


def create_demo_project(db: Session, owner_user_id: int) -> Project:
    """Build the sandbox example review owned by `owner_user_id`."""
    project = Project(
        name=PROJECT_NAME,
        description="A ready-made example on smartphone use and pedestrian "
                    "safety: 60 real references, screening partly done. "
                    "Explore, vote, break things — this sandbox is yours.",
        research_question="In pedestrians, how does smartphone use while "
                          "walking or crossing affect safety-related "
                          "behaviour and crash or near-miss risk?",
        # spelled out rather than left to the defaults: the demo is what most
        # people see first, and it is a plain PICOS systematic review
        review_type="systematic", question_framework="picos",
        created_by=owner_user_id)
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=owner_user_id,
                         role="admin"))
    co_reviewer = _get_or_create_co_reviewer(db)
    db.add(ProjectMember(project_id=project.id, user_id=co_reviewer.id,
                         role="reviewer"))

    # protocol (validated: needed for FT exclusion reasons) + concepts + equation
    protocol_md = (app_data_dir() / "demo_project" / "protocol.md").read_text(
        encoding="utf-8")
    db.add(Protocol(project_id=project.id, protocol_md=protocol_md,
                    criteria=CRITERIA,
                    validated_at=datetime.now(timezone.utc)))
    from app.models import Concept, Equation
    concepts = []
    for position, (name, keywords) in enumerate(CONCEPTS):
        concept = Concept(project_id=project.id, name=name, keywords=keywords,
                          position=position)
        db.add(concept)
        concepts.append(concept)
    db.flush()
    structure = build_structure([[c] for c in concepts])  # one block per concept
    params = {"year_from": 2010, "year_to": 2025, "languages": ["en"],
              "fields": ["title", "abstract"]}
    db.add(Equation(project_id=project.id, label="v1 (demo)",
                    structure=structure, params=params,
                    translations={"auto": translate_all(structure, params),
                                  "overrides": {}}))

    # import the bundled corpus + dedup
    seed_path = app_data_dir() / "demo_project" / "seed.ris"
    data = seed_path.read_bytes()
    records_parsed = parse_file("seed.ris", data)
    archived = archive_raw(project.id, "seed.ris", data)
    source = get_or_create_source(db, project.id, "database", "openalex")
    store_import(db, project_id=project.id, source_id=source.id,
                 equation_id=None, filename=archived, records=records_parsed,
                 user_id=owner_user_id)
    db.flush()
    run_dedup(db, project.id)

    # ---- title/abstract screening: dual review, ~70% done -------------------
    ta = ScreeningConfig(project_id=project.id, stage="ta", round=1,
                         allocation="all", conflict_resolution="consensus",
                         ai_enabled=False,
                         reviewer_ids=[owner_user_id, co_reviewer.id],
                         n_reviewers=2)
    db.add(ta)
    db.flush()
    generate_assignments(db, ta)
    ta.status = "active"
    ta.started_at = datetime.now(timezone.utc)

    from app.models import Record
    records = (db.query(Record)
               .filter_by(project_id=project.id, dedup_status="unique")
               .order_by(Record.id).all())
    for record in records:
        roll = _bucket("ta:" + (record.doi or record.title))
        if roll >= 70:          # ~30% left for the visitor to screen
            continue
        decision = "include" if _relevant(record) else "exclude"
        _vote(db, project.id, record.id, "ta", owner_user_id, decision)
        if roll < 12:           # ~12% genuine disagreement -> conflict
            other = "exclude" if decision == "include" else "include"
            _vote(db, project.id, record.id, "ta", co_reviewer.id, other)
            db.flush()
            ensure_conflict(db, ta, record.id)
            if roll < 6:        # half of the conflicts already resolved
                conflict = (db.query(Conflict)
                            .filter_by(project_id=project.id,
                                       record_id=record.id, stage="ta",
                                       round=1).first())
                if conflict is not None:
                    conflict.status = "resolved"
                    conflict.resolution = decision
                    conflict.resolution_note = ("Discussed 2026-07-12: abstract "
                                                "matches the protocol criteria.")
        else:
            _vote(db, project.id, record.id, "ta", co_reviewer.id, decision)
    db.flush()

    # ---- full-text screening: single reviewer, a few decisions --------------
    ft = ScreeningConfig(project_id=project.id, stage="ft", round=1,
                         allocation="all", conflict_resolution="consensus",
                         ai_enabled=False, reviewer_ids=[owner_user_id],
                         n_reviewers=1)
    db.add(ft)
    db.flush()
    summary = generate_assignments(db, ft)
    if summary["records"]:
        ft.status = "active"
        ft.started_at = datetime.now(timezone.utc)
        from app.services.screening.core import eligible_record_ids
        ft_eligible = eligible_record_ids(db, project.id, "ft", 1)
        excluded_ft = 0
        for record_id in ft_eligible:
            record = db.get(Record, record_id)
            roll = _bucket("ft:" + (record.doi or record.title))
            if roll >= 40:      # most full texts still to assess
                continue
            if excluded_ft < 3 and roll < 12:
                _vote(db, project.id, record_id, "ft", owner_user_id,
                      "exclude", reasons=_reason_for(record))
                excluded_ft += 1
            else:
                _vote(db, project.id, record_id, "ft", owner_user_id, "include")

    db.commit()
    db.refresh(project)
    logger.info("Demo project %s seeded for user %s", project.id, owner_user_id)
    return project


def seed_for_new_demo_account(db: Session, user_id: int) -> None:
    """Registration hook: give a fresh demo (sandbox) account its example
    project. Failures must never block registration."""
    try:
        create_demo_project(db, user_id)
    except Exception:
        db.rollback()
        logger.exception("Demo project seeding failed for user %s", user_id)


if __name__ == "__main__":
    import sys

    from app.core.db import SessionLocal

    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m app.services.demo_seed <owner-email>")
    with SessionLocal() as session:
        owner = session.query(User).filter_by(email=sys.argv[1].lower()).first()
        if owner is None:
            raise SystemExit(f"No account with email {sys.argv[1]}")
        created = create_demo_project(session, owner.id)
        print(f"Created project #{created.id} “{created.name}” for {owner.email}")
