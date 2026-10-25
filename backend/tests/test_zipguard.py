"""Zip bombs: a few hundred kilobytes that inflate to gigabytes are refused
from their headers, before anything is decompressed, and real files pass."""
import io
import json
import zipfile

import pytest

from app.core.zipguard import ZipTooLarge, check_unpacked_size

BIG = 101 * 1024 * 1024  # just over the 100 MB .docx/.xlsx ceiling


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture(scope="module")
def bomb() -> bytes:
    """101 MB of zeros, about 100 KB once deflated."""
    return _zip({"word/document.xml": bytes(BIG)})


def test_check_unpacked_size(bomb):
    assert len(bomb) < 1024 * 1024
    with pytest.raises(ZipTooLarge):
        check_unpacked_size(bomb, 100 * 1024 * 1024)
    check_unpacked_size(_zip({"a.xml": b"<a/>" * 1000}), 100 * 1024 * 1024)
    with pytest.raises(ZipTooLarge, match="manifest.json"):
        check_unpacked_size(_zip({"manifest.json": b"{}" * 1000}), 10 ** 9,
                            {"manifest.json": 100})
    check_unpacked_size(b"not a zip at all", 1)  # left to the parser


def test_a_docx_bomb_is_refused_before_parsing(bomb):
    from app.services.protocol.extract_text import ProtocolFileError, extract_text
    with pytest.raises(ProtocolFileError, match="unpacks to"):
        extract_text("protocol.docx", bomb)


def test_an_xlsx_bomb_is_refused_before_parsing(bomb):
    from app.services.extraction.import_table import ImportTableError, parse_xlsx
    with pytest.raises(ImportTableError, match="unpacks to"):
        parse_xlsx(bomb)


def test_a_real_workbook_still_imports():
    from openpyxl import Workbook

    from app.services.extraction.import_table import parse_xlsx
    wb = Workbook()
    wb.active.append(["Title", "Sample size"])
    wb.active.append(["A study", 42])
    buf = io.BytesIO()
    wb.save(buf)
    headers, rows = parse_xlsx(buf.getvalue())
    assert headers == ["Title", "Sample size"] and rows == [["A study", 42]]


def test_a_snapshot_bomb_is_refused_before_reading(tmp_path, bomb):
    from app.services.sync.snapshot import (
        MAX_MANIFEST_BYTES, SnapshotError, read_manifest,
    )
    path = tmp_path / "snap.zip"
    path.write_bytes(_zip({
        "manifest.json": json.dumps({"format": "x"}).encode()
                         + b" " * (MAX_MANIFEST_BYTES + 1),
        "data.json": b"{}"}))
    with pytest.raises(SnapshotError, match="manifest.json"):
        read_manifest(path)
