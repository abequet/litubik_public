// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Shapes of GET /api/projects/{id}/prisma (services/prisma/compute.py). */

export interface SourceCount { source: string; n: number }

export interface ReasonCount { code: string; label: string; n: number }

export interface RoundCounts {
  round: number
  label: string
  kind?: 'initial' | 'snowballing' | 'update'
  n?: number
  sources: { source: string; type: string; n: number }[]
  identified: number
  duplicates_removed: number
  records_screened: number
  records_excluded: number | null
  records_excluded_auto: number | null
  reports_sought: number | null
  reports_not_retrieved: number | null
  reports_assessed: number | null
  reports_excluded: number | null
  reports_excluded_by_reason: ReasonCount[]
  studies_included: number | null
}

export interface ColumnFlow {
  identified: number
  duplicates_removed: number
  dedup_unresolved: number
  records_screened: number
  records_excluded: number | null
  records_excluded_auto: number | null
  reports_sought: number | null
  reports_not_retrieved: number | null
  reports_assessed: number | null
  reports_excluded: number | null
  reports_excluded_by_reason: ReasonCount[]
  studies_included: number | null
  sources?: { source: string; type: string; n: number }[]
}

export interface PrismaCounts {
  identified_databases: SourceCount[]
  n_databases: number
  identified_other: SourceCount[]
  n_other: number
  duplicates_removed: number
  dedup_unresolved: number
  records_screened: number
  records_excluded: number | null
  records_excluded_auto: number | null
  reports_sought: number | null
  reports_not_retrieved: number | null
  reports_assessed: number | null
  reports_excluded: number | null
  reports_excluded_by_reason?: ReasonCount[]
  studies_included: number | null
  // reports (articles) behind those studies — PRISMA 2020 tells the two apart
  reports_included: number | null
  via_databases: ColumnFlow
  via_other: ColumnFlow
  rounds: RoundCounts[]
  final_total_ready: boolean
}
