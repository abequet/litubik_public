# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plain-text extraction from uploaded protocol files (PDF/DOCX/MD/TXT)."""
import io
from pathlib import PurePosixPath, PureWindowsPath

from app.core.zipguard import ZipTooLarge, check_unpacked_size

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".md", ".txt"}

# A .docx is a zip, inflated whole to be parsed. Three times the largest upload
# (30 MB), so a real document — images included — is never refused, while a
# zip bomb is, before a byte of it is decompressed.
MAX_DOCX_UNPACKED_BYTES = 100 * 1024 * 1024

# Cap what we send to the LLM: protocols are short documents; anything beyond
# this is almost certainly the wrong file, and it keeps us inside every
# provider's context window (~75k tokens).
MAX_TEXT_CHARS = 300_000


class ProtocolFileError(Exception):
    pass


def file_extension(filename: str) -> str:
    # PureWindowsPath handles both / and \ separators in client-sent names
    return PurePosixPath(PureWindowsPath(filename).name).suffix.lower()


def extract_text(filename: str, data: bytes) -> str:
    """Return the plain text of an uploaded protocol file.

    Raises ProtocolFileError for unsupported types, unreadable files or
    files with no extractable text (e.g. scanned PDFs).
    """
    ext = file_extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise ProtocolFileError(
            f"Unsupported file type '{ext or filename}' — use PDF, DOCX, MD or TXT")

    if ext == ".pdf":
        text = _extract_pdf(data)
    elif ext == ".docx":
        text = _extract_docx(data)
    else:  # .md / .txt
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")

    text = _normalize_whitespace(text)
    if not text:
        raise ProtocolFileError(
            "No text could be extracted from this file (scanned PDF without OCR?)")
    return text[:MAX_TEXT_CHARS]


def _extract_pdf(data: bytes) -> str:
    import pymupdf

    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return "\n\n".join(page.get_text() for page in doc)
    except pymupdf.FileDataError as e:
        raise ProtocolFileError(f"Could not read PDF: {e}") from e


def _extract_docx(data: bytes) -> str:
    import docx
    from docx.opc.exceptions import PackageNotFoundError

    try:
        check_unpacked_size(data, MAX_DOCX_UNPACKED_BYTES)
    except ZipTooLarge as e:
        raise ProtocolFileError(f"Could not read DOCX: {e}") from e
    try:
        document = docx.Document(io.BytesIO(data))
    except (PackageNotFoundError, KeyError, ValueError) as e:
        raise ProtocolFileError(f"Could not read DOCX: {e}") from e
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append("\t".join(cell.text for cell in row.cells))
    return "\n".join(parts)


def _normalize_whitespace(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    out: list[str] = []
    blank = 0
    for line in lines:
        blank = blank + 1 if not line else 0
        if blank <= 2:
            out.append(line)
    return "\n".join(out).strip()
