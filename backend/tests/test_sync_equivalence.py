"""Sync equivalence: a review split across a coordinator and a satellite gives
the same conflicts, the same agreement statistics (Cohen's kappa, raw
agreement) and the same PRISMA counts as the same review run on one instance.

Three separate SQLite databases stand for three installations:

- ``single``      — scenario A: alice and bob screen on one shared instance;
- ``coordinator`` — scenario B: alice's instance, the project's reference;
- ``satellite``   — scenario B: bob's own instance, bootstrapped from the
                    coordinator's snapshot, sending his votes back as
                    contribution packages.

Both scenarios replay the same logical timeline (same votes, same instants,
same conflict resolutions). In B the satellite's votes reach the coordinator
only when a package is imported, so some of bob's votes are cast BEFORE
alice's but land on the coordinator AFTER them — the realistic case the
merge must absorb. Everything is driven through the services, mirroring what
the screening endpoints do (vote / resolve / start), because the API is bound
to the process-wide database and an installation here is a database.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.core.security import hash_password
from app.models import (
    Assignment, Conflict, Import, Project, ProjectMember, Protocol, Record,
    ScreeningConfig, Source, User, Vote,
)
from app.services.prisma.compute import prisma_counts
from app.services.screening.core import (
    agreement_stats, ensure_conflict, generate_assignments, record_outcome,
    screening_outcomes, screening_stats,
)
from app.services.screening.reasons import exclusion_reasons, primary_reason
from app.services.sync.contributions import (
    build_contributions, import_contributions,
)
from app.services.sync.snapshot import build_snapshot, import_snapshot

ALICE, BOB = "alice@a.org", "bob@b.org"
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


CRITERIA = [
    {"code": "I1", "type": "include", "label": "Adult drivers",
     "description": ""},
    {"code": "I2", "type": "include", "label": "Empirical study",
     "description": ""},
    {"code": "E1", "type": "exclude", "label": "Wrong population",
     "description": ""},
    {"code": "E2", "type": "exclude", "label": "Not empirical",
     "description": ""},
    {"code": "E3", "type": "exclude", "label": "Wrong outcome",
     "description": ""},
]

# title/abstract: (record, alice, bob, admin resolution if the votes conflict)
# None as resolution on a conflicting pair = the conflict stays open.
TA_PLAN = [
    ("R01", "include", "include", None),
    ("R02", "include", "include", None),
    ("R03", "include", "include", None),
    ("R04", "exclude", "exclude", None),
    ("R05", "exclude", "exclude", None),
    ("R06", "exclude", "exclude", None),
    ("R07", "include", "exclude", "include"),
    ("R08", "include", "exclude", "exclude"),
    ("R09", "exclude", "include", "include"),
    ("R10", "maybe", "exclude", "exclude"),
    ("R11", "maybe", "maybe", "include"),
    ("R12", "include", "maybe", "include"),
    ("R13", "maybe", "include", None),        # left open
    ("R14", "exclude", "exclude", None),
    ("R15", "include", "include", None),
    ("R16", "exclude", "maybe", "exclude"),
]
# alice screens the first half before bob's package reaches the coordinator,
# the second half after it
TA_ALICE_EARLY = 8

# full text, on the T/A includes: (record, (alice, reasons), (bob, reasons),
# resolution (decision, reasons) or None)
FT_PLAN = [
    ("R01", ("include", []), ("include", []), None),
    ("R02", ("include", []), ("exclude", ["E1"]), ("include", [])),
    ("R03", ("exclude", ["E2"]), ("exclude", ["E2"]), None),
    ("R07", ("exclude", ["E1"]), ("exclude", ["E1"]), None),
    ("R09", ("exclude", ["NOTFOUND"]), ("exclude", ["NOTFOUND"]), None),
    ("R11", ("maybe", []), ("include", []), ("exclude", ["E3", "E1"])),
    ("R12", ("include", []), ("include", []), None),
    ("R15", ("exclude", ["E3"]), ("include", []), None),   # left open
]
FT_ALICE_EARLY = 4

# the logical timeline (minutes after T0), shared by both scenarios
T_BOB_TA = 1          # bob screens T/A on his satellite: 1..16
T_ALICE_TA_EARLY = 20  # alice, first half: 20..27
T_IMPORT_P1 = 30
T_ALICE_TA_LATE = 31   # alice, second half: 31..38
T_RESOLVE_TA = 40
T_START_FT = 50
T_BOB_FT = 53          # bob screens full texts on his satellite: 53..60
T_ALICE_FT_EARLY = 61  # alice: 61..64 — AFTER bob, but before his package
T_IMPORT_P2 = 70
T_ALICE_FT_LATE = 71
T_RESOLVE_FT = 80


# ---------------------------------------------------------------------------
# Installations
# ---------------------------------------------------------------------------

@pytest.fixture
def instance(tmp_path):
    """Factory: one isolated SQLite database = one LitUbik installation."""
    engines = []

    def make(name: str) -> sessionmaker:
        eng = create_engine(f"sqlite:///{tmp_path / (name + '.db')}",
                            connect_args={"check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _pragmas(dbapi_connection, _):
            # snapshot updates rely on ON DELETE CASCADE, as in app.core.db
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(eng)
        engines.append(eng)
        return sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)

    yield make
    for eng in engines:
        eng.dispose()


def _user(db, email: str) -> User:
    return db.query(User).filter_by(email=email).one()


def _project(db) -> Project:
    return db.query(Project).one()


def _record(db, project_id: int, title: str) -> Record:
    return db.query(Record).filter_by(project_id=project_id, title=title).one()


def _config(db, project_id: int, stage: str) -> ScreeningConfig:
    return (db.query(ScreeningConfig)
            .filter_by(project_id=project_id, stage=stage, round=1).one())


def _seed(db) -> int:
    """The project as the coordinator (or the single instance) sets it up:
    validated protocol, two database searches, one duplicate, T/A round 1
    started with dual allocation, arbiter resolution."""
    alice = User(email=ALICE, password_hash=hash_password("password1"),
                 display_name="Alice", is_admin=True)
    bob = User(email=BOB, password_hash=hash_password("password2"),
               display_name="Bob")
    db.add_all([alice, bob])
    db.flush()
    p = Project(name="Equivalence SLR", research_question="rq")
    db.add(p)
    db.flush()
    db.add_all([ProjectMember(project_id=p.id, user_id=alice.id, role="admin"),
                ProjectMember(project_id=p.id, user_id=bob.id,
                              role="reviewer")])
    db.add(Protocol(project_id=p.id, version=1, protocol_md="# protocol",
                    criteria=CRITERIA, validated_at=at(-60)))

    imports = {}
    for name in ("PubMed", "Scopus"):
        src = Source(project_id=p.id, type="database", name=name)
        db.add(src)
        db.flush()
        imp = Import(project_id=p.id, source_id=src.id, filename="",
                     imported_by=alice.id)
        db.add(imp)
        db.flush()
        imports[name] = imp
    records = []
    for i, (title, *_rest) in enumerate(TA_PLAN):
        imp = imports["PubMed" if i % 3 else "Scopus"]
        r = Record(project_id=p.id, import_id=imp.id, title=title,
                   doi=f"10.1/{title.lower()}", year=2020 + i % 5,
                   dedup_status="unique")
        db.add(r)
        records.append(r)
    db.flush()
    dup = Record(project_id=p.id, import_id=imports["Scopus"].id,
                 title="R01 (Scopus copy)", doi="10.1/r01",
                 dedup_status="duplicate", canonical_id=records[0].id)
    db.add(dup)
    db.commit()

    _start_round(db, p.id, "ta", at(0))
    return p.id


def _start_round(db, project_id: int, stage: str, when: datetime):
    """What POST /screening/start does, for a dual-allocated round."""
    alice, bob = _user(db, ALICE), _user(db, BOB)
    config = ScreeningConfig(project_id=project_id, stage=stage, round=1,
                             allocation="dual", conflict_resolution="arbiter",
                             reviewer_ids=[alice.id, bob.id])
    db.add(config)
    db.flush()
    summary = generate_assignments(db, config)
    assert summary["records"] > 0
    config.status = "active"
    config.started_at = when
    db.commit()


def _cast(db, stage: str, title: str, email: str, decision: str,
          reasons: list[str], when: datetime):
    """What POST /screening/vote does (assignment check, closed-record check,
    full-text reason validation, upsert, live conflict detection)."""
    project = _project(db)
    config = _config(db, project.id, stage)
    record = _record(db, project.id, title)
    user = _user(db, email)
    assert (db.query(Assignment)
            .filter_by(config_id=config.id, record_id=record.id,
                       user_id=user.id).first()) is not None, \
        f"{title} not assigned to {email} at {stage}"
    assert record_outcome(db, config, record.id) is None, \
        f"voting on {title} ({stage}) is closed"
    if stage == "ft" and decision == "exclude":
        valid = {r["code"] for r in exclusion_reasons(db, project.id, "ft")}
        reasons = [c for c in dict.fromkeys(reasons) if c in valid]
        assert reasons, f"no valid primary reason for {title}"
    vote = (db.query(Vote)
            .filter_by(project_id=project.id, record_id=record.id,
                       stage=stage, round=1, voter_user_id=user.id,
                       is_ai=False).first())
    if vote is None:
        vote = Vote(project_id=project.id, record_id=record.id, stage=stage,
                    round=1, voter_user_id=user.id, is_ai=False,
                    decision=decision, created_at=when)
        db.add(vote)
    vote.decision = decision
    vote.reasons = reasons
    vote.justification = ""
    vote.updated_at = when
    db.flush()
    ensure_conflict(db, config, record.id)
    db.commit()


def _resolve(db, stage: str, title: str, decision: str, reasons: list[str],
             when: datetime):
    """What POST /screening/conflicts/{id}/resolve does, as the arbiter."""
    project = _project(db)
    record = _record(db, project.id, title)
    conflict = (db.query(Conflict)
                .filter_by(project_id=project.id, record_id=record.id,
                           stage=stage, round=1).one())
    assert conflict.status == "open"
    if stage == "ft" and decision == "exclude":
        valid = {r["code"] for r in exclusion_reasons(db, project.id, "ft")}
        reasons = [c for c in dict.fromkeys(reasons) if c in valid]
        assert reasons
    else:
        reasons = []
    conflict.status = "resolved"
    conflict.resolution = decision
    conflict.reasons = reasons
    conflict.resolved_by = _user(db, ALICE).id
    conflict.resolved_at = when
    db.commit()


# ---------------------------------------------------------------------------
# Observables, normalised (no ids, no timestamps, no instance-specific uuid)
# ---------------------------------------------------------------------------

def _oriented(cells: dict, rows: str | None, cols: str | None) -> dict:
    """A two-rater cross-tab put in a fixed orientation (rows = the
    alphabetically first e-mail). The app orients it by LOCAL user id —
    rows = the lower id — and ids are per-instance: on bob's satellite he is
    account #1, so the same matrix comes out transposed there. Same
    numbers, same kappa; only the display orientation is local."""
    if rows and cols and rows > cols:
        cells = {a: {b: cells[b][a] for b in cells} for a in cells}
        rows, cols = cols, rows
    return {"cells": cells, "rows": rows, "cols": cols}


def _observables(db) -> dict:
    project = _project(db)
    pid = project.id
    titles = {r.id: r.title for r in db.query(Record).filter_by(project_id=pid)}
    emails = {u.id: u.email for u in db.query(User)}

    conflicts = sorted(
        (titles[c.record_id], c.stage, c.round, c.status, c.resolution or "",
         tuple(c.reasons or []), c.origin)
        for c in db.query(Conflict).filter_by(project_id=pid))
    votes = sorted(
        (titles[v.record_id], v.stage, v.round, emails[v.voter_user_id],
         v.decision, tuple(v.reasons or []))
        for v in db.query(Vote).filter_by(project_id=pid, is_ai=False))

    per_stage = {}
    for config in (db.query(ScreeningConfig)
                   .filter_by(project_id=pid, status="active")):
        agreement = agreement_stats(db, config)
        m = agreement["matrix"]
        m = m and _oriented(m["cells"], emails.get(m["rows_user_id"]),
                            emails.get(m["cols_user_id"]))
        stats = screening_stats(db, config)
        per_stage[(config.stage, config.round)] = {
            "agreement": {
                "method": agreement["method"],
                "kappa": (None if agreement["kappa"] is None
                          else round(agreement["kappa"], 12)),
                "percent": agreement["percent"],
                "n_records": agreement["n_records"],
                "maybe_as_include": agreement["maybe_as_include"],
                "matrix": m,
                "pairs": [{**_oriented(pr["cells"],
                                       emails[pr["rows_user_id"]],
                                       emails[pr["cols_user_id"]]),
                           "n_records": pr["n_records"],
                           "kappa": round(pr["kappa"], 12),
                           "percent": pr["percent"]}
                          for pr in agreement["pairs"]],
            },
            "stats": {k: stats[k] for k in (
                "assignments_total", "votes_done", "completed", "included",
                "excluded", "conflicts_open", "conflicts_resolved",
                "auto_excluded")},
            "per_reviewer": sorted(
                (emails[r["user_id"]], r["assigned"], r["done"],
                 r["include"], r["exclude"], r["maybe"])
                for r in stats["per_reviewer"]),
            "outcomes": sorted((titles[rid], d) for rid, d in
                               screening_outcomes(db, config).items()),
            "primary_reasons": sorted(
                (titles[rid], primary_reason(db, config, rid))
                for rid, d in screening_outcomes(db, config).items()
                if d == "exclude"),
        }

    return {"conflicts": conflicts, "votes": votes, "stages": per_stage,
            "prisma": prisma_counts(db, pid)}


# ---------------------------------------------------------------------------
# Scenario A — one instance
# ---------------------------------------------------------------------------

def _ta_votes():
    """Every T/A vote with its logical instant: [(t, email, title, decision)]."""
    out = []
    for i, (title, alice, bob, _) in enumerate(TA_PLAN):
        out.append((T_BOB_TA + i, BOB, title, bob))
        t_alice = (T_ALICE_TA_EARLY + i if i < TA_ALICE_EARLY
                   else T_ALICE_TA_LATE + i - TA_ALICE_EARLY)
        out.append((t_alice, ALICE, title, alice))
    return out


def _ft_votes(ft_plan):
    out = []
    for i, (title, (a_dec, a_rs), (b_dec, b_rs), _) in enumerate(ft_plan):
        out.append((T_BOB_FT + i, BOB, title, b_dec, b_rs))
        t_alice = (T_ALICE_FT_EARLY + i if i < FT_ALICE_EARLY
                   else T_ALICE_FT_LATE + i - FT_ALICE_EARLY)
        out.append((t_alice, ALICE, title, a_dec, a_rs))
    return out


def _resolve_ta(db):
    for i, (title, a, b, resolution) in enumerate(
            [p for p in TA_PLAN if p[3]]):
        _resolve(db, "ta", title, resolution, [], at(T_RESOLVE_TA + i))


def _resolve_ft(db, ft_plan):
    for i, (title, _a, _b, resolution) in enumerate(
            [p for p in ft_plan if p[3]]):
        _resolve(db, "ft", title, resolution[0], resolution[1],
                 at(T_RESOLVE_FT + i))


def run_single(Session, ft_plan=FT_PLAN) -> tuple[dict, dict]:
    """Scenario A. Returns (observables after T/A, observables at the end)."""
    with Session() as db:
        _seed(db)
        for t, email, title, decision in sorted(_ta_votes()):
            _cast(db, "ta", title, email, decision, [], at(t))
        _resolve_ta(db)
        after_ta = _observables(db)

        _start_round(db, _project(db).id, "ft", at(T_START_FT))
        for t, email, title, decision, reasons in sorted(_ft_votes(ft_plan)):
            _cast(db, "ft", title, email, decision, reasons, at(t))
        _resolve_ft(db, ft_plan)
        return after_ta, _observables(db)


# ---------------------------------------------------------------------------
# Scenario B — coordinator + satellite
# ---------------------------------------------------------------------------

def _import_package(Coord, package) -> dict:
    with Coord() as db:
        return import_contributions(db, package, _user(db, ALICE))


def run_distributed(Coord, Sat, ft_plan=FT_PLAN) -> tuple[dict, dict]:
    """Scenario B. Returns (observables after T/A, observables at the end),
    both read on the coordinator, and checks re-import idempotence on the
    way."""
    ta_votes = _ta_votes()
    ft_votes = _ft_votes(ft_plan)

    # coordinator: set-up, then the first snapshot for bob
    with Coord() as db:
        _seed(db)
        snapshot_v1 = build_snapshot(db, _project(db), include_pdfs=False,
                                     exporter=_user(db, ALICE))

    # satellite: bob is the first (hence superadmin) account of his install
    with Sat() as db:
        db.add(User(email=BOB, password_hash=hash_password("password2"),
                    display_name="Bob", is_admin=True))
        db.commit()
        report = import_snapshot(db, snapshot_v1, _user(db, BOB))
        assert report["mode"] == "create"
        assert report["shadow_users"] == [ALICE]
        assert report["quarantined_count"] == 0
        assert _project(db).sync_role == "satellite"

    # T/A: bob screens everything on his satellite (t = 1..16)
    with Sat() as db:
        for t, email, title, decision in sorted(ta_votes):
            if email == BOB:
                _cast(db, "ta", title, BOB, decision, [], at(t))
        # one voter per record locally: no conflict can open on the satellite
        assert db.query(Conflict).count() == 0
        package_1, _ = build_contributions(db, _project(db), _user(db, BOB))
    assert len(package_1["votes"]) == len(TA_PLAN)

    # coordinator: alice's first half, bob's package, alice's second half
    with Coord() as db:
        for t, email, title, decision in sorted(ta_votes):
            if email == ALICE and t < T_IMPORT_P1:
                _cast(db, "ta", title, ALICE, decision, [], at(t))
    report = _import_package(Coord, package_1)
    assert report["votes"] == {"new": len(TA_PLAN), "updated": 0,
                               "unchanged": 0}
    assert report["quarantined_count"] == 0
    with Coord() as db:
        for t, email, title, decision in sorted(ta_votes):
            if email == ALICE and t > T_IMPORT_P1:
                _cast(db, "ta", title, ALICE, decision, [], at(t))

    # idempotence: the same package again changes nothing
    with Coord() as db:
        before = _observables(db)
    report = _import_package(Coord, package_1)
    assert report["votes"] == {"new": 0, "updated": 0,
                               "unchanged": len(TA_PLAN)}
    assert report["conflicts_created"] == 0
    with Coord() as db:
        assert _observables(db) == before
        _resolve_ta(db)
        after_ta = _observables(db)

    # full text: the coordinator starts the round and ships snapshot v2
    with Coord() as db:
        _start_round(db, _project(db).id, "ft", at(T_START_FT))
        snapshot_v2 = build_snapshot(db, _project(db), include_pdfs=False,
                                     exporter=_user(db, ALICE))
    with Sat() as db:
        report = import_snapshot(db, snapshot_v2, _user(db, BOB))
        assert report["mode"] == "update"
        assert report["quarantined_count"] == 0
        # the satellite now sees the resolved T/A round and the FT queue
        assert _config(db, _project(db).id, "ft").status == "active"
        for t, email, title, decision, reasons in sorted(ft_votes):
            if email == BOB:
                _cast(db, "ft", title, BOB, decision, reasons, at(t))
        package_2, _ = build_contributions(db, _project(db), _user(db, BOB))
    assert package_2["seq"] == 2

    with Coord() as db:
        for t, email, title, decision, reasons in sorted(ft_votes):
            if email == ALICE and t < T_IMPORT_P2:
                _cast(db, "ft", title, ALICE, decision, reasons, at(t))
    report = _import_package(Coord, package_2)
    assert report["votes"] == {"new": len(ft_plan), "updated": 0,
                               "unchanged": len(TA_PLAN)}
    with Coord() as db:
        for t, email, title, decision, reasons in sorted(ft_votes):
            if email == ALICE and t > T_IMPORT_P2:
                _cast(db, "ft", title, ALICE, decision, reasons, at(t))
        _resolve_ft(db, ft_plan)
        final = _observables(db)

    # idempotence once everything is settled: the latest package, and an
    # older one arriving late (e.g. from the shared folder), are both no-ops
    for package in (package_2, package_1):
        report = _import_package(Coord, package)
        assert report["votes"]["new"] == 0
        assert report["votes"]["updated"] == 0
        assert report["conflicts_created"] == 0
        assert report["quarantined_count"] == 0
        with Coord() as db:
            assert _observables(db) == final
    return after_ta, final


def refresh_satellite(Coord, Sat) -> dict:
    """The coordinator ships the settled state; the satellite's own reading
    of it (what bob sees on his screen: dashboard, kappa, PRISMA)."""
    with Coord() as db:
        snapshot = build_snapshot(db, _project(db), include_pdfs=False,
                                  exporter=_user(db, ALICE))
    with Sat() as db:
        report = import_snapshot(db, snapshot, _user(db, BOB))
        assert report["mode"] == "update"
        assert report["quarantined_count"] == 0
        return _observables(db)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_distributed_review_matches_single_instance(instance):
    single_ta, single_final = run_single(instance("single"))
    coord, sat = instance("coordinator"), instance("satellite")
    dist_ta, dist_final = run_distributed(coord, sat)

    # sanity: the scenario exercises what it claims to
    ta = single_final["stages"][("ta", 1)]
    assert ta["agreement"]["method"] == "cohen"
    assert ta["agreement"]["n_records"] == len(TA_PLAN)
    assert ta["agreement"]["kappa"] is not None
    assert 0 < ta["agreement"]["kappa"] < 1
    assert ta["stats"]["conflicts_open"] == 1          # R13
    assert ta["stats"]["conflicts_resolved"] == 7
    ft = single_final["stages"][("ft", 1)]
    assert ft["stats"]["conflicts_open"] == 1          # R15
    assert ft["stats"]["conflicts_resolved"] == 2
    prisma = single_final["prisma"]
    assert prisma["duplicates_removed"] == 1
    assert prisma["records_screened"] == len(TA_PLAN)
    assert prisma["reports_sought"] == len(FT_PLAN)
    assert prisma["reports_not_retrieved"] == 1        # R09 NOTFOUND
    assert prisma["reports_included"] == 3             # R01, R02, R12
    assert {r["code"]: r["n"] for r in
            prisma["reports_excluded_by_reason"]} == {"E2": 1, "E1": 1,
                                                       "E3": 1}

    # the claim: same conflicts, same kappa, same PRISMA — after T/A and at
    # the end of full-text screening
    assert dist_ta["conflicts"] == single_ta["conflicts"]
    assert dist_ta["stages"] == single_ta["stages"]
    assert dist_ta["prisma"] == single_ta["prisma"]
    assert dist_ta == single_ta

    assert dist_final["votes"] == single_final["votes"]
    assert dist_final["conflicts"] == single_final["conflicts"]
    assert dist_final["stages"] == single_final["stages"]
    assert dist_final["prisma"] == single_final["prisma"]
    assert dist_final == single_final

    # and the satellite, once it receives the settled state, reads the same
    # numbers (its local user ids differ: bob is account #1 there)
    assert refresh_satellite(coord, sat) == single_final


# A full-text record both reviewers exclude, for DIFFERENT primary reasons
# (alice E1, bob E3; bob votes first in time, on his satellite).
FT_PLAN_REASON_TIE = [
    (title, a, b, res) if title != "R07"
    else ("R07", ("exclude", ["E1"]), ("exclude", ["E3"]), None)
    for title, a, b, res in FT_PLAN
]


def test_primary_reason_tie_is_the_same_on_every_instance(instance):
    """PRISMA's per-reason tally takes, for a record excluded without a
    conflict, the modal primary reason across the exclude votes. A tie must
    not depend on local account ids — on a satellite the local reviewer is
    account #1 — so it goes to the reviewer whose e-mail sorts first
    (services/screening/reasons.py, primary_reason): the coordinator, the
    satellite and a single instance report the same breakdown."""
    _, single_final = run_single(instance("single"), FT_PLAN_REASON_TIE)
    coord, sat = instance("coordinator"), instance("satellite")
    _, dist_final = run_distributed(coord, sat, FT_PLAN_REASON_TIE)

    single_reasons = dict(single_final["stages"][("ft", 1)]["primary_reasons"])
    # alice's e-mail sorts first: her E1 wins, although bob's E3 vote came
    # first in time
    assert single_reasons["R07"] == "E1"
    assert dist_final == single_final

    satellite = refresh_satellite(coord, sat)
    sat_reasons = dict(satellite["stages"][("ft", 1)]["primary_reasons"])
    assert sat_reasons["R07"] == "E1"  # bob is account #1 there
    assert satellite["prisma"] == dist_final["prisma"]
