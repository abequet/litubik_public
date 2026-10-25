# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Refuse a zip whose contents would inflate past a bound, before reading it.

A few megabytes of deflate can expand to gigabytes (a "zip bomb"): uploaded
.docx/.xlsx files and sync archives are zips, and parsing one fully inflates
it in memory or on disk. Python's zipfile never inflates a member past the
size its header declares (a header that lies fails the CRC check instead), so
the declared sizes bound what reading the archive can cost, and checking them
needs no decompression at all.
"""
import io
import zipfile


class ZipTooLarge(ValueError):
    """The archive's declared contents exceed the allowed size."""


def check_unpacked_size(source, max_total: int,
                        member_limits: dict[str, int] | None = None) -> None:
    """Raise ZipTooLarge when the members of `source` (a path, a file object,
    raw bytes or an open ZipFile) add up to more than `max_total` bytes, or one
    named in `member_limits` exceeds its own limit. Not a zip: no-op — the
    caller's parser reports that in its own words."""
    if isinstance(source, zipfile.ZipFile):
        _check(source, max_total, member_limits or {})
        return
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    try:
        zf = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError):
        return
    with zf:
        _check(zf, max_total, member_limits or {})


def _check(zf: zipfile.ZipFile, max_total: int,
           member_limits: dict[str, int]) -> None:
    total = 0
    for info in zf.infolist():
        limit = member_limits.get(info.filename)
        if limit is not None and info.file_size > limit:
            raise ZipTooLarge(
                f"{info.filename} unpacks to {_mb(info.file_size)} "
                f"(max {_mb(limit)})")
        total += info.file_size
        if total > max_total:
            raise ZipTooLarge(
                f"The archive unpacks to more than {_mb(max_total)}")


def _mb(n: int) -> str:
    return f"{n // (1024 * 1024)} MB"
