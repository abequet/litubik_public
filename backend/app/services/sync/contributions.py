# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contribution packages (sync phase 2): one reviewer's own work as a JSON
file, exported from their (satellite) instance and merged on the coordinator.

The export is always COMPLETE (every row the author owns in the project), so
importing is idempotent and re-sending an old package can never destroy newer
data. Merge rules per table:

- human votes: upsert on (record, stage, round, author); newest updated_at
  wins; never deleted. Only rows authored by the package's author are touched.
- AI votes: insert-if-absent on (record, stage, round) — an AI vote already
  present locally wins, the skipped duplicate is listed in the report.
- JBI appraisals / extraction values: upsert, newest updated_at wins.
- PDF annotations: the package replaces the author's whole local set
  (deletions propagate without tombstones).
- skips: the author's queue state is applied to matching assignments.
- AI-use journal: the author's rows are replaced wholesale (the package holds
  their complete set), so re-importing never double-counts calls.
- support tickets (author's, project-linked or app-global, whole comment
  thread): upsert by uuid, newest wins for the author-owned fields; the
  STATUS stays the importing instance's triage authority — the author only
  propagates closing their own ticket (same rule as the tickets API).
  Comments are insert-if-absent by uuid.

After the merge, conflict detection re-runs for every (stage, round) the
package touched — same code path as a live vote (screening.core).
"""
import json
from sqlalchemy.orm import Session

from sqlalchemy import or_

from app.core.instance import get_instance_id
from app.models import (
    AiReveal,
    AiUsage, Assignment, Conflict, ExtractionColumn, ExtractionValue,
    JbiAppraisal,
    PdfAnnotation, Project, ProjectInvitation, ProjectMember, Record,
    RecordTag, ScreeningConfig, Tag, Ticket, TicketComment, User, Vote,
    WorkSession,
)
from app.models.accounts import utcnow
from app.services.screening.core import ensure_conflict
from app.services.sync.common import SnapshotError, log_event, next_contrib_seq
from app.services.sync.credentials_sync import (
    apply_credentials_blob, build_credentials_blob,
)
from app.services.worktime.sessions import is_closed
from app.services.sync.serialize import ExportContext, as_utc, iso, parse_dt

FORMAT = "litubik-contributions"
FORMAT_VERSION = 2  # 2: studies within articles (chantier 9)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def collect_contributions_data(db: Session, project: Project,
                               author: User) -> dict:
    """The author's contribution rows, serialized (no manifest/credentials).
    Also the folder scanner's change-detection input (hashed)."""
    ctx = ExportContext(db, project)
    config_uuids = {c.id: c.uuid for c in
                    db.query(ScreeningConfig).filter_by(project_id=project.id)}
    column_uuids = {c.id: c.uuid for c in
                    db.query(ExtractionColumn).filter_by(project_id=project.id)}

    votes = [
        {"record": ctx.record(v.record_id), "stage": v.stage,
         "round": v.round, "email": ctx.email(v.voter_user_id),
         "is_ai": v.is_ai, "decision": v.decision, "reasons": v.reasons,
         "justification": v.justification, "criteria_eval": v.criteria_eval,
         "confidence": v.confidence, "generated_by": v.generated_by,
         "created_at": iso(v.created_at), "updated_at": iso(v.updated_at)}
        for v in db.query(Vote).filter_by(project_id=project.id)
        if ((not v.is_ai and v.voter_user_id == author.id)
            or (v.is_ai and v.generated_by == author.email))
    ]

    # chantier 9: the studies the author's rows hang off, plus those the
    # author declared — the coordinator creates the missing ones by
    # (record, position), keeping the uuid
    from app.models import ExtractionStudy
    study_rows = {s.id: s for s in
                  db.query(ExtractionStudy)
                  .join(Record, Record.id == ExtractionStudy.record_id)
                  .filter(Record.project_id == project.id)}

    def study_fields(study_id):
        s = study_rows.get(study_id)
        return {"study": s.uuid if s else None,
                "study_position": s.position if s else 0}

    jbi = [
        {"record": ctx.record(j.record_id), "design": j.design,
         "instrument": j.instrument,
         "answers": j.answers, "overall": j.overall, "comment": j.comment,
         "updated_at": iso(j.updated_at), **study_fields(j.study_id)}
        for j in db.query(JbiAppraisal)
        .join(Record, Record.id == JbiAppraisal.record_id)
        .filter(Record.project_id == project.id,
                JbiAppraisal.user_id == author.id)
    ]

    values = [
        {"record": ctx.record(v.record_id),
         "column": column_uuids.get(v.column_id), "value": v.value,
         "origin": v.origin, "validated": v.validated,
         "updated_at": iso(v.updated_at), **study_fields(v.study_id)}
        for v in db.query(ExtractionValue)
        .join(Record, Record.id == ExtractionValue.record_id)
        .filter(Record.project_id == project.id,
                ExtractionValue.user_id == author.id)
    ]

    used_study_ids = {v.study_id for v in db.query(ExtractionValue)
                      .join(Record, Record.id == ExtractionValue.record_id)
                      .filter(Record.project_id == project.id,
                              ExtractionValue.user_id == author.id)}
    used_study_ids |= {j.study_id for j in db.query(JbiAppraisal)
                       .join(Record, Record.id == JbiAppraisal.record_id)
                       .filter(Record.project_id == project.id,
                               JbiAppraisal.user_id == author.id)}
    extraction_studies = [
        {"uuid": s.uuid, "record": ctx.record(s.record_id),
         "position": s.position, "label": s.label,
         "study_design": s.study_design, "design_origin": s.design_origin}
        for s in study_rows.values()
        if (s.id in used_study_ids or s.created_by == author.id)
        and ctx.record(s.record_id)
    ]

    annotations = [
        {"record": ctx.record(a.record_id), "page": a.page, "rects": a.rects,
         "quote": a.quote, "note": a.note, "color": a.color,
         "created_at": iso(a.created_at), "updated_at": iso(a.updated_at)}
        for a in db.query(PdfAnnotation)
        .filter_by(project_id=project.id, user_id=author.id)
    ]

    skips = [
        {"config": config_uuids.get(a.config_id),
         "record": ctx.record(a.record_id), "skipped_at": iso(a.skipped_at)}
        for a in db.query(Assignment)
        .join(ScreeningConfig, ScreeningConfig.id == Assignment.config_id)
        .filter(ScreeningConfig.project_id == project.id,
                Assignment.user_id == author.id,
                Assignment.skipped_at.isnot(None))
    ]

    # the author's support tickets (linked to this project, or app-global),
    # with their whole comment thread — the coordinator triages them
    tickets = []
    for t in (db.query(Ticket)
              .filter(Ticket.created_by == author.id,
                      or_(Ticket.project_id == project.id,
                          Ticket.project_id.is_(None)))):
        tickets.append({
            "uuid": t.uuid, "title": t.title, "body": t.body,
            "kind": t.kind, "severity": t.severity, "page": t.page,
            "status": t.status, "project_linked": t.project_id is not None,
            "created_at": iso(t.created_at), "updated_at": iso(t.updated_at),
            "comments": [
                {"uuid": c.uuid, "email": ctx.email(c.user_id),
                 "body": c.body, "created_at": iso(c.created_at)}
                for c in t.comments
            ]})

    # tag attachments the author made (tags are get-or-created by name on the
    # receiving side; removal propagates by absence — replace-by-author)
    tag_names = {t.id: t.name for t in
                 db.query(Tag).filter_by(project_id=project.id)}
    tags = [
        {"tag": tag_names.get(rt.tag_id), "record": ctx.record(rt.record_id),
         "created_at": iso(rt.created_at)}
        for rt in db.query(RecordTag)
        .join(Tag, Tag.id == RecordTag.tag_id)
        .filter(Tag.project_id == project.id,
                RecordTag.created_by == author.id)
        if tag_names.get(rt.tag_id) and ctx.record(rt.record_id)
    ]

    # the author's AI-use journal for this project. Without it the
    # coordinator's disclosure statement would describe only the AI run on the
    # coordinator's own machine and silently omit every satellite's.
    ai_usage = [
        {"feature": u.feature, "provider": u.provider, "model": u.model,
         "day": u.day, "n_calls": u.n_calls, "tokens_in": u.tokens_in,
         "tokens_out": u.tokens_out, "cost_usd": u.cost_usd,
         "first_at": iso(u.first_at), "last_at": iso(u.last_at)}
        for u in db.query(AiUsage)
        .filter_by(project_id=project.id, user_id=author.id)
    ]

    # pre-vote reveals of the AI suggestion (after_vote rounds): the author's
    # own choices, part of what the disclosure statement counts
    ai_reveals = [
        {"record": ctx.record(r.record_id), "stage": r.stage, "round": r.round,
         "revealed_at": iso(r.revealed_at)}
        for r in db.query(AiReveal).filter_by(project_id=project.id,
                                              user_id=author.id)
    ]

    # the author's work sessions (chantier 14) — closed ones only, so that a
    # session in progress does not change the package (and its hash, which
    # the folder scanner watches) at every heartbeat
    work_sessions = [
        {"uuid": s.uuid, "stage": s.stage,
         "started_at": iso(s.started_at), "last_seen_at": iso(s.last_seen_at),
         "n_heartbeats": s.n_heartbeats, "instance_id": s.instance_id}
        for s in db.query(WorkSession)
        .filter_by(project_id=project.id, user_id=author.id)
        .order_by(WorkSession.started_at)
        if is_closed(s)
    ]

    return {"votes": votes, "jbi": jbi, "extraction_values": values,
            "extraction_studies": extraction_studies,
            "annotations": annotations, "skips": skips, "tickets": tickets,
            "tags": tags, "ai_usage": ai_usage, "ai_reveals": ai_reveals,
            "work_sessions": work_sessions}


def build_contributions(db: Session, project: Project, author: User,
                        extra_counts: dict | None = None) -> tuple[dict, str]:
    """The author's complete contribution package + the suggested filename."""
    core = collect_contributions_data(db, project, author)
    seq = next_contrib_seq(db, project.id, author.email)
    instance_id = get_instance_id(db)
    # my shared project API keys, encrypted under the project passphrase
    credentials_enc, n_keys, keys_note = build_credentials_blob(
        db, project, owner=author)
    data = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "project_uuid": project.uuid,
        "project_name": project.name,
        "author": {"email": author.email, "display_name": author.display_name,
                   "instance_id": instance_id},
        "seq": seq,
        "based_on_snapshot_version": project.snapshot_version,
        "exported_at": utcnow().isoformat(),
        **core,
        "credentials_enc": credentials_enc,
    }
    # H3: bind the package to a holder of the project passphrase (no-op if none
    # is set — the folder importer then refuses it as unauthenticated).
    # M5: and to THIS installation, which the passphrase cannot do — every
    # member of the project holds it, so it proves membership, not authorship.
    from app.core.instance import get_signing_key
    from app.services.sync import signing
    signing.sign_author(get_signing_key(db), data)
    signing.sign_dict(project, data)
    filename = (f"litubik_{project.uuid[:8]}_"
                f"{author.email.split('@')[0]}_s{seq}.litubik-contrib.json")
    log_event(db, project.id, "export", "contributions",
              author_email=author.email, instance_id=instance_id, seq=seq,
              based_on=project.snapshot_version, filename=filename,
              counts={"votes": len(core["votes"]), "jbi": len(core["jbi"]),
                      "values": len(core["extraction_values"]),
                      "annotations": len(core["annotations"]),
                      "skips": len(core["skips"]),
                      "tickets": len(core["tickets"]),
                      "tags": len(core["tags"]),
                      "shared_keys": n_keys,
                      **(extra_counts or {})},
              warnings=[keys_note] if keys_note else [],
              user_id=author.id)
    db.commit()
    return data, filename


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def parse_package(raw: bytes) -> dict:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SnapshotError(f"Fichier invalide : {e}")
    if payload.get("format") != FORMAT:
        raise SnapshotError("Ce fichier n'est pas un paquet de contributions "
                            "LitUbik")
    if payload.get("format_version", 0) > FORMAT_VERSION:
        raise SnapshotError("Paquet produit par une version plus récente de "
                            "LitUbik — mettez cette instance à jour")
    return payload


def import_contributions(db: Session, payload: dict, importer: User) -> dict:
    project = (db.query(Project)
               .filter_by(uuid=payload.get("project_uuid", "")).first())
    if project is None:
        raise SnapshotError("Projet inconnu sur cette instance — importez "
                            "d'abord son instantané")
    # H3 is enforced on the untrusted auto-import path (folder.scan_project only
    # imports packages with a valid signature). This manual endpoint is gated by
    # require_project_admin — a human explicitly chose this file — so an
    # unsigned/legacy or wrong-passphrase package is still merged (its shared
    # keys fail to decrypt with a warning, exactly as before signing existed).
    member = (db.query(ProjectMember)
              .filter_by(project_id=project.id, user_id=importer.id).first())
    if not importer.is_admin and (member is None or member.role != "admin"):
        raise SnapshotError("Seul un admin du projet peut importer des "
                            "contributions")

    author_info = payload.get("author") or {}
    author_email = (author_info.get("email") or "").lower()
    if not author_email:
        raise SnapshotError("Paquet sans auteur")
    seq = int(payload.get("seq") or 0)
    based_on = int(payload.get("based_on_snapshot_version") or 0)
    provenance = f"{author_email} #{seq}"
    warnings: list[str] = []
    if based_on < project.snapshot_version:
        warnings.append(
            f"Paquet basé sur l'instantané v{based_on} ; cette instance est "
            f"en v{project.snapshot_version} — les références disparues "
            "depuis partiront en quarantaine")

    author = _ensure_author_member(db, project, author_email,
                                   author_info.get("display_name") or "")

    # M5: the project HMAC only proves "someone holding the project passphrase",
    # which every member does — so it cannot stop a member from submitting a
    # package attributed to a colleague. The per-installation Ed25519 signature
    # can: bind the author to the key seen first, and refuse any later mismatch.
    from app.services.sync import signing
    author_ok, pubkey = signing.verify_author(payload)
    if author_ok is False:
        raise SnapshotError(
            "Signature d'auteur invalide — le paquet a été modifié après export")
    if author_ok is True:
        author_member = (db.query(ProjectMember)
                         .filter_by(project_id=project.id, user_id=author.id)
                         .first())
        accepted, note = signing.bind_author_key(author_member, pubkey)
        if not accepted:
            raise SnapshotError(note)
        if note:
            warnings.append(note)
    else:
        warnings.append(
            f"Paquet non signé par l'installation de {author_email} (version "
            "antérieure de LitUbik) — son authenticité ne peut pas être vérifiée")

    records = {r.uuid: r for r in
               db.query(Record).filter_by(project_id=project.id)}
    columns = {c.uuid: c for c in
               db.query(ExtractionColumn).filter_by(project_id=project.id)}
    configs = {c.uuid: c for c in
               db.query(ScreeningConfig).filter_by(project_id=project.id)}

    quarantined: list[dict] = []
    votes_count = {"new": 0, "updated": 0, "unchanged": 0}
    ai_count = {"added": 0, "skipped": 0}
    affected: dict[tuple[str, int], set[int]] = {}

    # chantier 9: studies the package addresses — matched by uuid, then by
    # (record, position); created with the package's uuid when missing. A v1
    # package names no study: its rows land on each article's first study.
    from app.models import ExtractionStudy
    from app.services.extraction import studies as ext_studies
    studies = {s.uuid: s for s in
               db.query(ExtractionStudy)
               .join(Record, Record.id == ExtractionStudy.record_id)
               .filter(Record.project_id == project.id)}
    by_pos = {(s.record_id, s.position): s for s in studies.values()}
    studies_created = 0
    for s in payload.get("extraction_studies", []):
        record = records.get(s.get("record"))
        if record is None or s.get("uuid") in studies:
            continue
        position = int(s.get("position") or 0)
        if (record.id, position) in by_pos:
            continue
        row = ExtractionStudy(record_id=record.id, uuid=s["uuid"],
                              label=s.get("label") or "Study 1",
                              position=position,
                              study_design=s.get("study_design"),
                              design_origin=s.get("design_origin"),
                              created_by=author.id)
        db.add(row)
        db.flush()
        studies[row.uuid] = row
        by_pos[(record.id, position)] = row
        studies_created += 1

    def study_of(record, entry) -> ExtractionStudy:
        row = studies.get(entry.get("study")) if entry.get("study") else None
        if row is None:
            row = by_pos.get((record.id, int(entry.get("study_position") or 0)))
        if row is None:
            row = ext_studies.ensure_default(db, record)
            studies[row.uuid] = row
            by_pos[(record.id, row.position)] = row
        return row

    for v in payload.get("votes", []):
        record = records.get(v.get("record"))
        if record is None:
            quarantined.append({"type": "vote", "record": v.get("record"),
                                "stage": v.get("stage"),
                                "email": author_email})
            continue
        stage, round_ = v["stage"], int(v.get("round", 1))
        if v.get("is_ai"):
            existing = (db.query(Vote)
                        .filter_by(record_id=record.id, stage=stage,
                                   round=round_, is_ai=True).first())
            if existing is not None:
                ai_count["skipped"] += 1
                continue
            db.add(Vote(project_id=project.id, record_id=record.id,
                        stage=stage, round=round_, voter_user_id=None,
                        is_ai=True, decision=v["decision"],
                        reasons=v.get("reasons") or [],
                        justification=v.get("justification", ""),
                        criteria_eval=v.get("criteria_eval") or {},
                        confidence=v.get("confidence"),
                        generated_by=v.get("generated_by") or author_email,
                        imported_from=provenance,
                        created_at=parse_dt(v.get("created_at")),
                        updated_at=parse_dt(v.get("updated_at"))))
            ai_count["added"] += 1
            continue
        affected.setdefault((stage, round_), set()).add(record.id)
        existing = (db.query(Vote)
                    .filter_by(record_id=record.id, stage=stage, round=round_,
                               voter_user_id=author.id, is_ai=False).first())
        package_dt = parse_dt(v.get("updated_at"))
        if existing is None:
            db.add(Vote(project_id=project.id, record_id=record.id,
                        stage=stage, round=round_, voter_user_id=author.id,
                        is_ai=False, decision=v["decision"],
                        reasons=v.get("reasons") or [],
                        justification=v.get("justification", ""),
                        criteria_eval=v.get("criteria_eval") or {},
                        confidence=v.get("confidence"),
                        imported_from=provenance,
                        created_at=parse_dt(v.get("created_at")),
                        updated_at=package_dt))
            votes_count["new"] += 1
        elif package_dt and (existing.updated_at is None
                             or as_utc(package_dt) > as_utc(existing.updated_at)):
            existing.decision = v["decision"]
            existing.reasons = v.get("reasons") or []
            existing.justification = v.get("justification", "")
            existing.criteria_eval = v.get("criteria_eval") or {}
            existing.imported_from = provenance
            existing.updated_at = package_dt
            votes_count["updated"] += 1
        else:
            votes_count["unchanged"] += 1

    jbi_count = {"new": 0, "updated": 0, "unchanged": 0}
    for j in payload.get("jbi", []):
        record = records.get(j.get("record"))
        if record is None:
            quarantined.append({"type": "jbi", "record": j.get("record"),
                                "email": author_email})
            continue
        study = study_of(record, j)
        existing = (db.query(JbiAppraisal)
                    .filter_by(study_id=study.id, user_id=author.id).first())
        package_dt = parse_dt(j.get("updated_at"))
        if existing is None:
            db.add(JbiAppraisal(record_id=record.id, study_id=study.id,
                                user_id=author.id,
                                design=j.get("design", ""),
                                instrument=j.get("instrument") or "jbi",
                                answers=j.get("answers") or {},
                                overall=j.get("overall", ""),
                                comment=j.get("comment", ""),
                                imported_from=provenance,
                                updated_at=package_dt))
            jbi_count["new"] += 1
        elif package_dt and (existing.updated_at is None
                             or as_utc(package_dt) > as_utc(existing.updated_at)):
            existing.design = j.get("design", "")
            existing.instrument = j.get("instrument") or "jbi"
            existing.answers = j.get("answers") or {}
            existing.overall = j.get("overall", "")
            existing.comment = j.get("comment", "")
            existing.imported_from = provenance
            existing.updated_at = package_dt
            jbi_count["updated"] += 1
        else:
            jbi_count["unchanged"] += 1

    values_count = {"new": 0, "updated": 0, "unchanged": 0}
    for v in payload.get("extraction_values", []):
        record = records.get(v.get("record"))
        column = columns.get(v.get("column"))
        if record is None or column is None:
            quarantined.append({"type": "extraction_value",
                                "record": v.get("record"),
                                "email": author_email})
            continue
        study = study_of(record, v)
        existing = (db.query(ExtractionValue)
                    .filter_by(study_id=study.id, column_id=column.id,
                               user_id=author.id).first())
        package_dt = parse_dt(v.get("updated_at"))
        if existing is None:
            db.add(ExtractionValue(record_id=record.id, study_id=study.id,
                                   column_id=column.id, user_id=author.id,
                                   value=v.get("value") or {},
                                   origin=v.get("origin", "human"),
                                   validated=v.get("validated", False),
                                   imported_from=provenance,
                                   updated_at=package_dt))
            values_count["new"] += 1
        elif package_dt and (existing.updated_at is None
                             or as_utc(package_dt) > as_utc(existing.updated_at)):
            existing.value = v.get("value") or {}
            existing.origin = v.get("origin", "human")
            existing.validated = v.get("validated", False)
            existing.imported_from = provenance
            existing.updated_at = package_dt
            values_count["updated"] += 1
        else:
            values_count["unchanged"] += 1

    # annotations: the package IS the author's set — replace wholesale
    db.query(PdfAnnotation).filter_by(project_id=project.id,
                                      user_id=author.id).delete(
        synchronize_session=False)
    annotations_count = 0
    for a in payload.get("annotations", []):
        record = records.get(a.get("record"))
        if record is None:
            quarantined.append({"type": "annotation",
                                "record": a.get("record"),
                                "email": author_email})
            continue
        db.add(PdfAnnotation(project_id=project.id, record_id=record.id,
                             user_id=author.id, page=a.get("page", 1),
                             rects=a.get("rects") or [],
                             quote=a.get("quote", ""), note=a.get("note", ""),
                             color=a.get("color", "yellow"),
                             imported_from=provenance,
                             created_at=parse_dt(a.get("created_at")),
                             updated_at=parse_dt(a.get("updated_at"))))
        annotations_count += 1

    skips_count = 0
    for s in payload.get("skips", []):
        config = configs.get(s.get("config"))
        record = records.get(s.get("record"))
        if config is None or record is None:
            continue
        assignment = (db.query(Assignment)
                      .filter_by(config_id=config.id, record_id=record.id,
                                 user_id=author.id).first())
        if assignment is not None:
            assignment.skipped_at = parse_dt(s.get("skipped_at"))
            skips_count += 1

    db.flush()

    # conflict detection: same path as a live vote, for every touched round
    conflicts_created = 0
    for (stage, round_), record_ids in affected.items():
        config = (db.query(ScreeningConfig)
                  .filter_by(project_id=project.id, stage=stage, round=round_)
                  .first())
        if config is None:
            continue
        before = {c.record_id for c in db.query(Conflict).filter_by(
            project_id=project.id, stage=stage, round=round_)}
        for record_id in record_ids:
            ensure_conflict(db, config, record_id)
        db.flush()
        after = {c.record_id for c in db.query(Conflict).filter_by(
            project_id=project.id, stage=stage, round=round_)}
        conflicts_created += len(after - before)

    # tag attachments: the package is the author's complete set —
    # replace-by-author (their removals propagate); an attachment already made
    # by someone else on the same (tag, record) is left as theirs
    tags_count = {"attached": 0, "removed": 0, "unchanged": 0}
    package_pairs: set[tuple[int, int]] = set()
    for tg in payload.get("tags", []):
        record = records.get(tg.get("record"))
        name = (tg.get("tag") or "").strip()
        if record is None or not name:
            if not record:
                quarantined.append({"type": "tag", "record": tg.get("record"),
                                    "email": author_email})
            continue
        tag = (db.query(Tag)
               .filter_by(project_id=project.id, name=name).first())
        if tag is None:
            tag = Tag(project_id=project.id, name=name, created_by=author.id)
            db.add(tag)
            db.flush()
        package_pairs.add((tag.id, record.id))
        existing = (db.query(RecordTag)
                    .filter_by(tag_id=tag.id, record_id=record.id).first())
        if existing is None:
            db.add(RecordTag(tag_id=tag.id, record_id=record.id,
                             created_by=author.id,
                             created_at=parse_dt(tg.get("created_at"))))
            tags_count["attached"] += 1
        else:
            tags_count["unchanged"] += 1
    for rt in (db.query(RecordTag)
               .join(Tag, Tag.id == RecordTag.tag_id)
               .filter(Tag.project_id == project.id,
                       RecordTag.created_by == author.id).all()):
        if (rt.tag_id, rt.record_id) not in package_pairs:
            db.delete(rt)
            tags_count["removed"] += 1
    db.flush()

    tickets_count = {"new": 0, "updated": 0, "unchanged": 0}
    comments_added = 0
    users_by_email = {u.email: u for u in db.query(User).all()}

    def comment_author(email):
        """Comment threads can involve other people (e.g. the coordinator's
        replies bounced back): map by email, shadow account if unknown."""
        if not email:
            return None
        user = users_by_email.get(email.lower())
        if user is None:
            user = User(email=email.lower(), password_hash="",
                        display_name=email.split("@")[0])
            db.add(user)
            db.flush()
            users_by_email[user.email] = user
        return user.id

    for t in payload.get("tickets", []):
        existing = db.query(Ticket).filter_by(uuid=t["uuid"]).first()
        package_dt = parse_dt(t.get("updated_at"))
        if existing is None:
            existing = Ticket(
                uuid=t["uuid"], created_by=author.id,
                project_id=project.id if t.get("project_linked") else None,
                title=t.get("title", ""), body=t.get("body", ""),
                kind=t.get("kind", "bug"), severity=t.get("severity", "minor"),
                page=t.get("page", ""), status=t.get("status", "open"),
                imported_from=provenance,
                created_at=parse_dt(t.get("created_at")),
                updated_at=package_dt)
            db.add(existing)
            db.flush()
            tickets_count["new"] += 1
        elif package_dt and (existing.updated_at is None
                             or as_utc(package_dt)
                             > as_utc(existing.updated_at)):
            existing.title = t.get("title", existing.title)
            existing.body = t.get("body", existing.body)
            existing.kind = t.get("kind", existing.kind)
            existing.severity = t.get("severity", existing.severity)
            existing.page = t.get("page", existing.page)
            # triage (status) stays this instance's authority; the author may
            # only propagate closing their own ticket — same rule as the API
            if t.get("status") == "closed":
                existing.status = "closed"
            existing.imported_from = provenance
            existing.updated_at = package_dt
            tickets_count["updated"] += 1
        else:
            tickets_count["unchanged"] += 1
        for c in t.get("comments", []):
            if db.query(TicketComment).filter_by(uuid=c["uuid"]).first():
                continue
            db.add(TicketComment(
                uuid=c["uuid"], ticket_id=existing.id,
                user_id=comment_author(c.get("email")),
                body=c.get("body", ""), imported_from=provenance,
                created_at=parse_dt(c.get("created_at"))))
            comments_added += 1
    db.flush()

    # AI-use journal: the package holds the author's complete set for this
    # project, so their rows are replaced wholesale — buckets keep growing on
    # the satellite and re-importing an older package must not double-count.
    (db.query(AiUsage)
     .filter_by(project_id=project.id, user_id=author.id)
     .delete(synchronize_session=False))
    reveals_count = {"added": 0, "skipped": 0}
    for r in payload.get("ai_reveals", []):
        record = records.get(r.get("record"))
        if record is None:
            continue  # the vote on it was quarantined above; the reveal follows
        stage, round_ = r["stage"], int(r.get("round", 1))
        if (db.query(AiReveal.id)
                .filter_by(record_id=record.id, stage=stage, round=round_,
                           user_id=author.id).first()) is not None:
            reveals_count["skipped"] += 1
            continue
        db.add(AiReveal(project_id=project.id, record_id=record.id,
                        stage=stage, round=round_, user_id=author.id,
                        revealed_at=parse_dt(r.get("revealed_at")),
                        imported_from=provenance))
        reveals_count["added"] += 1

    sessions_count = {"added": 0, "skipped": 0}
    for s in payload.get("work_sessions", []):
        if not s.get("uuid"):
            continue
        if db.query(WorkSession.id).filter_by(uuid=s["uuid"]).first() is not None:
            sessions_count["skipped"] += 1
            continue
        db.add(WorkSession(project_id=project.id, uuid=s["uuid"], user_id=author.id,
                           stage=s.get("stage", "ta"),
                           started_at=parse_dt(s.get("started_at")),
                           last_seen_at=parse_dt(s.get("last_seen_at")),
                           n_heartbeats=s.get("n_heartbeats", 0),
                           instance_id=s.get("instance_id") or "",
                           imported_from=provenance))
        sessions_count["added"] += 1

    ai_usage_count = 0
    for u in payload.get("ai_usage", []):
        db.add(AiUsage(
            project_id=project.id, feature=u.get("feature", ""),
            provider=u.get("provider", ""), model=u.get("model", ""),
            user_id=author.id, day=u.get("day", ""),
            n_calls=u.get("n_calls", 0), tokens_in=u.get("tokens_in", 0),
            tokens_out=u.get("tokens_out", 0), cost_usd=u.get("cost_usd", 0.0),
            first_at=parse_dt(u.get("first_at")),
            last_at=parse_dt(u.get("last_at")),
            imported_from=provenance))
        ai_usage_count += 1
    db.flush()

    credentials_counts = apply_credentials_blob(
        db, project, payload.get("credentials_enc"),
        replace_owner_emails={author_email}, warnings=warnings)

    counts = {"votes": votes_count, "ai_votes": ai_count, "jbi": jbi_count,
              "values": values_count, "annotations": annotations_count,
              "skips": skips_count, "conflicts_created": conflicts_created,
              "tickets": tickets_count, "ticket_comments": comments_added,
              "tags": tags_count, "ai_usage": ai_usage_count,
              "ai_reveals": reveals_count,
              "work_sessions": sessions_count,
              "credentials": credentials_counts}
    log_event(db, project.id, "import", "contributions",
              author_email=author_email,
              instance_id=author_info.get("instance_id") or "", seq=seq,
              based_on=based_on, counts=counts, warnings=warnings,
              user_id=importer.id)
    db.commit()

    return {
        "project_id": project.id,
        "project_name": project.name,
        "author": author_email,
        "seq": seq,
        "based_on_snapshot_version": based_on,
        **counts,
        "quarantined_count": len(quarantined),
        "quarantined_sample": quarantined[:20],
        "warnings": warnings,
    }


def _ensure_author_member(db: Session, project: Project, email: str,
                          display_name: str) -> User:
    """The package's author must belong to the project: an existing member, or
    an invited email (invitation converts, shadow account created if needed)."""
    author = db.query(User).filter_by(email=email).first()
    if author is not None:
        member = (db.query(ProjectMember)
                  .filter_by(project_id=project.id, user_id=author.id).first())
        if member is not None:
            return author
    invitation = (db.query(ProjectInvitation)
                  .filter_by(project_id=project.id, email=email).first())
    if invitation is None:
        raise SnapshotError(
            f"L'auteur du paquet ({email}) n'est pas membre du projet — "
            "ajoutez-le d'abord aux membres")
    if author is None:
        author = User(email=email, password_hash="",
                      display_name=display_name or email.split("@")[0])
        db.add(author)
        db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=author.id,
                         role=invitation.role))
    db.delete(invitation)
    db.flush()
    return author
