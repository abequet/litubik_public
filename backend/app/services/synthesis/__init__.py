# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The synthesis stage: what the review synthesised, how, and how certain it is.

Split three ways because the standards are three:
- `methods.py` — SWiM table 2, the synthesis methods and the question each one
  can actually answer;
- `grade.py` — the five GRADE steps and the informative statements;
- `core.py` / `sof.py` — reading it all back, and the Summary of Findings table.
"""
from app.services.synthesis import core, grade, methods, sof

__all__ = ["core", "grade", "methods", "sof"]
