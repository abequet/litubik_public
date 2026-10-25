# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""CSV/spreadsheet formula-injection neutralisation (M4).

Record titles/abstracts and extraction values are attacker-controllable (any
reviewer can type them). Written verbatim into a .csv/.xlsx, a cell beginning
with a formula metacharacter (= + - @, or a leading tab/carriage return) is
executed when another user opens the file in Excel/LibreOffice — enabling DDE
command execution and data exfiltration via WEBSERVICE/HYPERLINK. We prefix any
such string cell with an apostrophe, forcing it to be treated as text.
"""
_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value):
    """Return `value` unchanged unless it is a string starting with a formula
    metacharacter, in which case it is prefixed with a single quote."""
    if isinstance(value, str) and value and value[0] in _DANGEROUS_PREFIXES:
        return "'" + value
    return value


def safe_row(row):
    """Neutralise every cell of a row (list/tuple)."""
    return [csv_safe(cell) for cell in row]
