# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Full-text retrieval: eligible records, settings, per-record download, storage."""
import re
import unicodedata
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.models import FulltextConfig, Record, ScreeningConfig
from app.services.screening.core import screening_outcomes

# a stem longer than this would push a deep Windows path over MAX_PATH once the
# user unzips it somewhere nested
MAX_STEM = 110


def pdf_dir(project_id: int) -> Path:
    path = get_settings().storage_dir / str(project_id) / "pdfs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ascii_words(text: str) -> list[str]:
    """Transliterate to ASCII and split on anything that is not a word char —
    accents, punctuation and the characters Windows forbids all disappear."""
    folded = (unicodedata.normalize("NFKD", str(text or ""))
              .encode("ascii", "ignore").decode("ascii"))
    return re.findall(r"\w+", folded)


def _first_author_family(authors: list) -> str:
    """Family name of the first author, best effort across the formats the
    importers produce ('Dupont, Jean' / 'Jean Dupont' / 'Dupont J')."""
    first = str((authors or [""])[0] or "").strip()
    if "," in first:
        return first.split(",", 1)[0]
    parts = first.split()
    if not parts:
        return ""
    # trailing initials ('Dupont J', 'Dupont JB') — there the family name leads
    return parts[0] if len(parts[-1].replace(".", "")) <= 2 else parts[-1]


def export_filename(record: Record, taken: set[str] | None = None) -> str:
    """`Author_Year_five_first_title_words.pdf` — the convention reviewers use
    when they file PDFs by hand, so an exported zip drops straight into their
    own folders. `taken` collects the names already used in this export and
    suffixes the collisions (two papers by the same author, same year, same
    opening words)."""
    author = "_".join(ascii_words(_first_author_family(record.authors))) or "anonymous"
    year = record.year or "ND"
    title = "_".join(ascii_words(record.title)[:5]) or "untitled"
    stem = f"{author}_{year}_{title}"[:MAX_STEM]
    if taken is not None:
        base, n = stem, 1
        while stem.lower() in taken:
            n += 1
            stem = f"{base}_{n}"
        taken.add(stem.lower())
    return f"{stem}.pdf"


def included_record_ids(db: Session, project_id: int) -> list[int]:
    """Records included after title/abstract screening — the retrieval targets.
    Aggregates every round (snowballing rounds add their own T/A pass). Falls
    back to all unique records if T/A screening was never started. Records
    imported at the extraction stage (external review import,
    ft_forced_included) are always part of the corpus even though they were
    never T/A-screened here."""
    forced = {rid for (rid,) in db.query(Record.id).filter_by(
        project_id=project_id, ft_forced_included=True)}
    configs = (db.query(ScreeningConfig)
               .filter_by(project_id=project_id, stage="ta", status="active")
               .order_by(ScreeningConfig.round).all())
    if configs:
        included: set[int] = set(forced)
        for ta in configs:
            outcomes = screening_outcomes(db, ta)
            included |= {rid for rid, decision in outcomes.items()
                         if decision == "include"}
        return sorted(included)
    return sorted({rid for (rid,) in db.query(Record.id)
                   .filter_by(project_id=project_id, dedup_status="unique")}
                  | forced)


def _decrypt_institutions(config: FulltextConfig | None) -> list[dict]:
    out = []
    for inst in (config.institutions if config else None) or []:
        entry = {k: v for k, v in inst.items() if k != "password_encrypted"}
        encrypted = inst.get("password_encrypted")
        entry["password"] = (decrypt_secret(encrypted) or "") if encrypted else ""
        out.append(entry)
    return out


def resolve_config(db: Session, project_id: int, fallback_email: str = "",
                   sandbox: bool = False) -> dict:
    """Retrieval settings for process_doi. Global institutions/settings
    (project_id NULL) are merged with the project's own; the Unpaywall email
    falls back to the requesting user's login email when unset.

    `sandbox` (a demo visitor's project): open sources only — no institution
    at all, and the Unpaywall address is the operator's, never the visitor's."""
    if sandbox:
        from app.core.polite import contact_email
        return {"email": contact_email(), "institutions": []}
    project_cfg = db.query(FulltextConfig).filter_by(project_id=project_id).first()
    global_cfg = db.query(FulltextConfig).filter_by(project_id=None).first()
    email = ((project_cfg and project_cfg.unpaywall_email)
             or (global_cfg and global_cfg.unpaywall_email)
             or fallback_email or "")
    institutions = _decrypt_institutions(global_cfg) + _decrypt_institutions(project_cfg)
    return {"email": email, "institutions": institutions}


def seed_global_institutions(db: Session, institutions: list[dict],
                             unpaywall_email: str = "") -> int:
    """Insert/replace the GLOBAL institutions (passwords encrypted). Used to
    import pre-existing EZProxy/CAS credentials once. Returns the count."""
    global_cfg = db.query(FulltextConfig).filter_by(project_id=None).first()
    if global_cfg is None:
        global_cfg = FulltextConfig(project_id=None)
        db.add(global_cfg)
    stored = []
    for inst in institutions:
        entry = {"name": inst.get("name", ""),
                 "ezproxy_url": inst.get("ezproxy_url", ""),
                 "username": inst.get("username", ""),
                 "scope": inst.get("scope", ""),
                 "auth_type": inst.get("auth_type", "")}
        if inst.get("password"):
            entry["password_encrypted"] = encrypt_secret(inst["password"])
        stored.append(entry)
    global_cfg.institutions = stored
    if unpaywall_email:
        global_cfg.unpaywall_email = unpaywall_email
    db.commit()
    return len(stored)


def _pdf_is_blank(pdf_bytes: bytes) -> bool:
    """True for bogus tiny PDFs with no text and no images on any page — e.g.
    a blank interstitial printed by the EZProxy page.pdf() fallback."""
    if len(pdf_bytes) >= 10 * 1024:
        return False
    import fitz

    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            return not any(page.get_text().strip() or page.get_images()
                           for page in doc)
    except Exception:
        return True


def retrieve_one(db: Session, project_id: int, record: Record, settings: dict) -> dict:
    """Download one record's PDF via the vendored pipeline; write it to disk and
    return {status, via, filename, oa_url, size_kb, error}."""
    from app.services.fulltext.downloader import process_doi

    if not record.doi:
        return {"status": "not_found", "via": "", "filename": "", "oa_url": "",
                "size_kb": None, "error": "No DOI — upload the PDF manually"}

    result, pdf_bytes = process_doi(
        record.doi,
        email=settings.get("email", ""),
        # None = the legacy institutions.json fallback; a demo visitor's
        # project gets an explicit empty list — no institution whatsoever
        institutions=([] if settings.get("sandbox")
                      else settings.get("institutions") or None),
        use_extensions=settings.get("use_extensions", True),
        # a visitor's run makes plain HTTP downloads only: no headless browser
        # per record on a shared public server (other runs: the default)
        **({"browser": False} if settings.get("sandbox") else {}),
    )
    if pdf_bytes and _pdf_is_blank(pdf_bytes):
        return {"status": "not_found", "via": "", "filename": "", "oa_url":
                result.get("oa_url") or "", "size_kb": None,
                "error": f"Blank/empty PDF discarded "
                         f"(source: {result.get('source') or 'unknown'})"}
    if pdf_bytes:
        target = pdf_dir(project_id) / f"{record.id}.pdf"
        target.write_bytes(pdf_bytes)
        return {
            "status": "retrieved",
            "via": result.get("source") or "",
            "filename": result.get("filename") or f"{record.id}.pdf",
            "oa_url": result.get("oa_url") or "",
            "size_kb": round(len(pdf_bytes) / 1024),
            "error": "",
        }
    return {
        "status": "not_found",
        "via": "",
        "filename": "",
        "oa_url": result.get("oa_url") or "",
        "size_kb": None,
        "error": result.get("error") or "No PDF found",
    }
