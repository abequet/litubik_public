// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import type {
  AnswerCounts, AppraisalDomainBlock, ColumnAggregate, CountItem,
  JbiStudySummary, ResultsAggregates, StudyRow,
} from '@/api'

/** Per-study appraisal rows -> one block per study design, answers pooled.
 *
 * The twin of `fold()` in services/appraisal/summary.py: the server folds the
 * whole corpus, this folds whatever the cross-filter kept, and the two must
 * agree on an unfiltered view. `design_label` is left as the raw key — the
 * page renders design names through its own translated designLabel(). */
function foldDomains(perStudy: JbiStudySummary[]): AppraisalDomainBlock[] {
  const blank = (): AnswerCounts => ({ yes: 0, no: 0, unclear: 0, na: 0 })
  const byDesign = new Map<string, JbiStudySummary[]>()
  for (const s of perStudy) {
    if (!s.domains) continue
    const list = byDesign.get(s.domains.design) ?? []
    list.push(s)
    byDesign.set(s.domains.design, list)
  }
  const out: AppraisalDomainBlock[] = []
  for (const [design, studies] of byDesign) {
    const merged = new Map<string, AppraisalDomainBlock['rows'][number]>()
    for (const study of studies) {
      for (const row of study.domains!.rows) {
        let target = merged.get(row.label)
        if (!target) {
          target = { label: row.label, counts: blank(),
                     n_questions: row.n_questions, n_studies: 0 }
          merged.set(row.label, target)
        }
        for (const key of ['yes', 'no', 'unclear', 'na'] as const) {
          target.counts[key] += row.counts[key]
        }
        if (row.answered) target.n_studies += 1
      }
    }
    out.push({
      design,
      design_label: design,
      granularity: studies[0].domains!.granularity,
      n_studies: studies.length,
      rows: [...merged.values()],
    })
  }
  return out.sort((a, b) => b.n_studies - a.n_studies)
}

/** Cross-filters applied to every Results chart at once. */
export interface ResultsFilters {
  /** inclusive publication-year range; null = all years (unknown years kept) */
  years: [number, number] | null
  /** study designs to keep (null = "not qualified"); empty = all */
  designs: (string | null)[]
  /** ISO alpha-3 countries to keep (any-match); empty = all */
  countries: string[]
}

export const NO_FILTERS: ResultsFilters = {
  years: null, designs: [], countries: [],
}

export function isFiltering(f: ResultsFilters): boolean {
  return f.years !== null || f.designs.length > 0 || f.countries.length > 0
}

export function applyFilters(studies: StudyRow[],
                             f: ResultsFilters): StudyRow[] {
  return studies.filter((s) => {
    if (f.years &&
        (s.year === null || s.year < f.years[0] || s.year > f.years[1])) {
      return false
    }
    if (f.designs.length && !f.designs.includes(s.design || null)) return false
    if (f.countries.length &&
        !s.countries.some((c) => f.countries.includes(c))) {
      return false
    }
    return true
  })
}

// linear interpolation between closest ranks — same result as Python's
// statistics.quantiles(method="inclusive") used on the backend
function quantile(sorted: number[], p: number): number {
  const idx = (sorted.length - 1) * p
  const lo = Math.floor(idx)
  const hi = Math.ceil(idx)
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo)
}

const r2 = (x: number) => Math.round(x * 100) / 100
const r3 = (x: number) => Math.round(x * 1000) / 1000

function numericStats(values: number[]) {
  if (!values.length) return null
  const n = values.length
  return {
    n,
    min: values[0],
    max: values[n - 1],
    mean: r2(values.reduce((s, v) => s + v, 0) / n),
    median: n % 2 ? values[(n - 1) / 2]
      : (values[n / 2 - 1] + values[n / 2]) / 2,
    q1: r2(quantile(values, 0.25)),
    q3: r2(quantile(values, 0.75)),
  }
}

// counts per bucket: declared options keep their order, stray values follow
// most-frequent first (mirror of compute._distribution)
function distribution(consensus: unknown[], col: ColumnAggregate): CountItem[] {
  const counts = new Map<string, number>()
  for (const value of consensus) {
    const buckets = Array.isArray(value) ? value : [value]
    const keys = new Set(buckets.map((b) =>
      typeof b === 'boolean' ? (b ? 'yes' : 'no') : String(b)))
    for (const k of keys) counts.set(k, (counts.get(k) ?? 0) + 1)
  }
  const declared = col.col_type === 'bool' ? ['yes', 'no'] : col.options
  const out: CountItem[] = []
  for (const o of declared) {
    const n = counts.get(o)
    if (n !== undefined) {
      out.push({ value: o, n })
      counts.delete(o)
    }
  }
  out.push(...[...counts.entries()].sort((a, b) => b[1] - a[1])
    .map(([value, n]) => ({ value, n })))
  return out
}

/** Recompute every chart block over the filtered subset of study rows — the
 * TS twin of the backend's compute.aggregates() (same consensus rows, same
 * ordering rules), so an empty filter shows exactly the server's numbers. */
export function filteredAggregates(data: ResultsAggregates,
                                   filters: ResultsFilters): ResultsAggregates {
  if (!isFiltering(filters)) return data
  const studies = applyFilters(data.studies, filters)
  const kept = new Set(studies.map((s) => s.study_id))

  const yearCounts = new Map<number, number>()
  for (const s of studies) {
    if (s.year) yearCounts.set(s.year, (yearCounts.get(s.year) ?? 0) + 1)
  }
  const yearList = [...yearCounts.keys()].sort((a, b) => a - b)
  const years = {
    counts: yearList.map((y) => ({ year: y, n: yearCounts.get(y)! })),
    unknown: studies.filter((s) => !s.year).length,
    min: yearList[0] ?? null,
    max: yearList[yearList.length - 1] ?? null,
  }

  const designCounts = new Map<string | null, number>()
  for (const s of studies) {
    const d = s.design || null
    designCounts.set(d, (designCounts.get(d) ?? 0) + 1)
  }
  const designs = [...designCounts.entries()]
    .sort((a, b) =>
      Number(a[0] === null) - Number(b[0] === null) || b[1] - a[1])
    .map(([design, n]) => ({ design, n }))

  const names = new Map(data.countries.counts.map((c) => [c.iso3, c.name]))
  const countryCounts = new Map<string, number>()
  const unmatchedCounts = new Map<string, number>()
  let withCountry = 0
  let multi = 0
  let missing = 0
  if (data.countries.column_id !== null) {
    for (const s of studies) {
      if (!s.countries.length && !s.countries_unmatched.length) {
        missing += 1
        continue
      }
      for (const iso3 of s.countries) {
        countryCounts.set(iso3, (countryCounts.get(iso3) ?? 0) + 1)
      }
      for (const raw of s.countries_unmatched) {
        unmatchedCounts.set(raw, (unmatchedCounts.get(raw) ?? 0) + 1)
      }
      if (s.countries.length) {
        withCountry += 1
        if (s.countries.length > 1) multi += 1
      }
    }
  }
  const countries = {
    ...data.countries,
    counts: [...countryCounts.entries()].sort((a, b) => b[1] - a[1])
      .map(([iso3, n]) => ({ iso3, name: names.get(iso3) ?? iso3, n })),
    n_studies_with_country: withCountry,
    n_multi_country: multi,
    unmatched: [...unmatchedCounts.entries()].sort((a, b) => b[1] - a[1])
      .map(([value, n]) => ({ value, n })),
    missing,
  }

  const columns = data.columns.map((col) => {
    const consensus: unknown[] = []
    let nMissing = 0
    let nConflicts = 0
    for (const s of studies) {
      const cell = s.values[String(col.id)]
      if (!cell || cell.s === 'empty') nMissing += 1
      else if (cell.s === 'conflict') nConflicts += 1
      else consensus.push(cell.v)
    }
    const block: ColumnAggregate = {
      ...col, n_missing: nMissing, n_conflicts: nConflicts,
    }
    if (col.col_type === 'number') {
      const numbers = consensus
        .filter((v): v is number => typeof v === 'number')
        .sort((a, b) => a - b)
      block.stats = numericStats(numbers)
      block.values = numbers
    } else {
      block.distribution = distribution(consensus, col)
    }
    return block
  })

  const perStudy = data.jbi.per_study.filter((s) => kept.has(s.study_id))
  const byDesign = new Map<string | null, number[]>()
  for (const s of perStudy) {
    const list = byDesign.get(s.design) ?? []
    list.push(s.pct_yes)
    byDesign.set(s.design, list)
  }
  const jbi = {
    ...data.jbi,
    per_study: perStudy,
    // same fold as services/appraisal/summary.py fold(), re-run over the kept
    // studies so the domain chart follows the cross-filter
    by_domain: foldDomains(perStudy),
    n_from_consensus: perStudy.filter((s) => s.source === 'consensus').length,
    avg_pct_yes: perStudy.length
      ? r3(perStudy.reduce((x, s) => x + s.pct_yes, 0) / perStudy.length)
      : null,
    by_design: [...byDesign.entries()]
      .sort((a, b) => b[1].length - a[1].length)
      .map(([design, v]) => ({
        design,
        n_studies: v.length,
        avg_pct_yes: r3(v.reduce((x, y) => x + y, 0) / v.length),
      })),
    n_appraised: perStudy.length,
  }

  return {
    ...data,
    n_included: studies.length,
    years, designs, countries, columns, jbi, studies,
  }
}
