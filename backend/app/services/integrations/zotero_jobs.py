# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Background jobs for the Zotero integration: pull a collection into a
project (records + optional PDF attachments), push a project's references
into a Zotero collection (creating or updating items)."""
import json
import logging

from app.core.crypto import decrypt_secret
from app.core.db import SessionLocal
from app.models import (
    Project, Record, RecordExternalLink, RecordTag, Tag, User, UserIntegration,
)
from app.services.connectors.jobs import archive_raw, get_or_create_source, store_import
from app.services.dedup.core import run_dedup
from app.services.integrations.zotero import (
    ZoteroClient, ZoteroError, item_to_record, record_to_item,
)
from app.workers.runner import register_handler

logger = logging.getLogger(__name__)
PROVIDER = "zotero"


def library_prefix(config: dict) -> str:
    return f"{'groups' if config.get('library_type') == 'group' else 'users'}/" \
           f"{config.get('library_id')}"


def load_integration(db, user_id: int) -> tuple[UserIntegration, str, str]:
    """(row, decrypted key, library prefix) or a ZoteroError."""
    row = (db.query(UserIntegration)
           .filter_by(user_id=user_id, provider=PROVIDER).first())
    if row is None:
        raise ZoteroError("Connect your Zotero library first (My integrations)")
    key = decrypt_secret(row.api_key_encrypted)
    if not key:
        raise ZoteroError("The stored Zotero key cannot be decrypted — enter it again")
    config = row.config or {}
    if not config.get("library_id"):
        raise ZoteroError("Choose a Zotero library first (My integrations)")
    return row, key, library_prefix(config)


# -- import ---------------------------------------------------------------------

@register_handler("zotero_import")
def zotero_import_handler(job_id: int, params: dict, progress) -> dict:
    project_id = int(params["project_id"])
    user_id = int(params["user_id"])
    collection_key = params.get("collection_key") or None
    collection_name = params.get("collection_name") or "library"
    source_type = params.get("source_type") or "manual"
    source_name = (params.get("source_name") or f"zotero:{collection_name}")[:100]
    with_pdfs = bool(params.get("with_pdfs"))
    cap = params.get("cap")

    with SessionLocal() as db:
        _, api_key, prefix = load_integration(db, user_id)
    client = ZoteroClient(api_key)

    progress(0, 0, "Listing the Zotero items...")

    def list_progress(done: int, total: int):
        progress(done, total, f"Fetching Zotero items ({done}/{total})...")

    items = client.items(prefix, collection_key, progress=list_progress, cap=cap)
    if not items:
        raise ZoteroError("This Zotero collection holds no bibliographic item")

    records = [item_to_record(it) for it in items]
    keys = [it["key"] for it in items]
    progress(len(records), len(records), "Archiving the raw Zotero export...")
    filename = archive_raw(project_id, f"zotero_{collection_name}.json",
                           json.dumps(items, ensure_ascii=False).encode("utf-8"))

    with SessionLocal() as db:
        source = get_or_create_source(db, project_id, source_type, source_name)
        imp = store_import(db, project_id=project_id, source_id=source.id,
                           equation_id=params.get("equation_id"), filename=filename,
                           records=records, user_id=user_id)
        db.flush()
        rows = (db.query(Record).filter_by(import_id=imp.id)
                .order_by(Record.id).all())
        for record, key in zip(rows, keys):
            db.add(RecordExternalLink(record_id=record.id, provider=PROVIDER,
                                      library=prefix, external_key=key))
        db.commit()
        import_id = imp.id
        record_ids = [r.id for r in rows]

    def dedup_progress(done: int, total: int):
        progress(done, total, f"Deduplicating ({done}/{total})...")

    with SessionLocal() as db:
        run_dedup(db, project_id, dedup_progress)

    from app.services.connectors.abstracts import schedule_backfill
    schedule_backfill(project_id, [import_id], user_id)

    n_pdfs = 0
    if with_pdfs:
        from app.services.fulltext.bulk_import import store_pdf
        for i, (record_id, key) in enumerate(zip(record_ids, keys), start=1):
            progress(i, len(keys), f"Fetching attached PDFs ({i}/{len(keys)})...")
            try:
                attachments = client.pdf_attachments(prefix, key)
                data = None
                for att in attachments:
                    data = client.download_file(prefix, att["key"])
                    if data:
                        break
            except ZoteroError as e:
                logger.info("Zotero attachment skipped for %s: %s", key, e)
                continue
            if not data:
                continue
            with SessionLocal() as db:
                record = db.get(Record, record_id)
                if record is None:
                    continue
                name = (att.get("data") or {}).get("filename") or f"{key}.pdf"
                store_pdf(db, project_id, record, name, data, via="zotero")
                db.commit()
            n_pdfs += 1

    progress(len(records), len(records), "Done")
    return {"n_records": len(records), "import_id": import_id,
            "archived": filename, "n_pdfs": n_pdfs, "source_name": source_name}


# -- export ---------------------------------------------------------------------

def _record_tags(db, record_ids: list[int]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    if not record_ids:
        return out
    rows = (db.query(RecordTag.record_id, Tag.name)
            .join(Tag, Tag.id == RecordTag.tag_id)
            .filter(RecordTag.record_id.in_(record_ids))
            .order_by(Tag.name).all())
    for rid, name in rows:
        out.setdefault(rid, []).append(name)
    return out


@register_handler("zotero_export")
def zotero_export_handler(job_id: int, params: dict, progress) -> dict:
    from app.api.export import _scoped_records
    project_id = int(params["project_id"])
    user_id = int(params["user_id"])
    scope = params.get("scope") or "all"
    collection_key = params.get("collection_key") or None
    new_name = (params.get("collection_name") or "").strip()

    with SessionLocal() as db:
        _, api_key, prefix = load_integration(db, user_id)
        project = db.get(Project, project_id)
        rows = _scoped_records(db, project_id, scope)
        # detach plain values: the session closes before the network work
        records = [(r, status) for r, status in rows]
        db.expunge_all()
        tags = _record_tags(db, [r.id for r, _ in records])
        links = {
            link.record_id: link.external_key
            for link in db.query(RecordExternalLink)
            .filter(RecordExternalLink.provider == PROVIDER,
                    RecordExternalLink.library == prefix,
                    RecordExternalLink.record_id.in_([r.id for r, _ in records]))
            .all()} if records else {}
        project_name = project.name if project else "project"

    if not records:
        raise ZoteroError("Nothing to send in this scope")

    client = ZoteroClient(api_key)
    status_label = {"include": "included", "exclude": "excluded"}

    progress(0, len(records), "Choosing the Zotero collection...")
    collection_name = new_name or f"LitUbik – {project_name}"
    if not collection_key:
        existing = {c["name"]: c["key"] for c in client.collections(prefix)}
        collection_key = existing.get(collection_name) \
            or client.create_collection(prefix, collection_name)
    else:
        names = {c["key"]: c["name"] for c in client.collections(prefix)}
        collection_name = names.get(collection_key, collection_name)

    progress(0, len(records), "Checking the items already in Zotero...")
    known = client.items_by_key(prefix, list(links.values())) if links else {}

    items, meta = [], []
    for record, status in records:
        label = status_label.get(status, "undecided")
        existing = known.get(links.get(record.id, ""))
        items.append(record_to_item(record, status=label,
                                    tags=tags.get(record.id, []),
                                    collection_key=collection_key,
                                    existing=existing))
        meta.append((record.id, existing is not None))

    created = updated = 0
    failures: list[str] = []
    for start in range(0, len(items), 50):
        progress(start, len(items), f"Sending to Zotero ({start}/{len(items)})...")
        chunk = items[start:start + 50]
        res = client.write_items(prefix, chunk)
        with SessionLocal() as db:
            for i in range(len(chunk)):
                record_id, was_update = meta[start + i]
                if i in res["failed"]:
                    failures.append(f"{records[start + i][0].title[:60]}: "
                                    f"{res['failed'][i]}")
                    continue
                key = res["keys"].get(i) or links.get(record_id)
                if not key:
                    continue
                link = (db.query(RecordExternalLink)
                        .filter_by(record_id=record_id, provider=PROVIDER,
                                   library=prefix).first())
                if link is None:
                    db.add(RecordExternalLink(record_id=record_id, provider=PROVIDER,
                                              library=prefix, external_key=key))
                else:
                    link.external_key = key
                if was_update:
                    updated += 1
                else:
                    created += 1
            db.commit()

    progress(len(items), len(items), "Done")
    return {"created": created, "updated": updated, "failed": len(failures),
            "failures": failures[:20], "collection_key": collection_key,
            "collection_name": collection_name, "library": prefix,
            "scope": scope}
