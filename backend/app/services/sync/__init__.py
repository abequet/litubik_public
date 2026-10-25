# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cross-instance sync (docs/SYNC_IMPLEMENTATION_PLAN.md).

Phase 1: project snapshot — a zip archive of the complete project state
(structural tables + every reviewer's contributions + stored files) that a
coordinator exports and a satellite imports. Doubles as the OSF-ready
replication archive of milestone M11.
"""
