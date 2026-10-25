// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useTranslation } from 'react-i18next'
import BarChart, { type BarItem } from './BarChart'
import type { NumericStats, YearCount } from '@/api'

/** Continuous year axis: every year from min to max, gaps at 0. When a
 * cross-filter is active, `totals` carries the unfiltered counts (ghost bars
 * + full axis range) and `onSelectYear` makes each bar a year filter. */
export function YearHistogram({ counts, totals, color, onSelectYear,
                                activeYear, ariaLabel }: {
  counts: YearCount[]
  totals?: YearCount[]
  color?: string
  onSelectYear?: (year: number) => void
  /** the single year currently pinned by a bar click (marks it active) */
  activeYear?: number | null
  ariaLabel?: string
}) {
  const { t } = useTranslation()
  const byYear = new Map(counts.map((c) => [c.year, c.n]))
  const totalByYear = totals ? new Map(totals.map((c) => [c.year, c.n])) : null
  const years = [...counts.map((c) => c.year),
                 ...(totals ?? []).map((c) => c.year)]
  if (years.length === 0) return null
  const min = Math.min(...years)
  const max = Math.max(...years)
  const items: BarItem[] = []
  for (let y = min; y <= max; y++) {
    const n = byYear.get(y) ?? 0
    const total = totalByYear?.get(y)
    items.push({
      label: String(y),
      n,
      total: totalByYear ? (total ?? 0) : undefined,
      key: String(y),
      active: activeYear === y,
      title: totalByYear && total !== n
        ? t('{{year}} — {{filtered}} / {{total}} studies',
            { year: y, filtered: n, total: total ?? 0 })
        : t('{{year}} — {{count}} studies', { year: y, count: n }),
    })
  }
  return <BarChart items={items} color={color} ariaLabel={ariaLabel}
                   onSelect={onSelectYear
                     ? (item) => onSelectYear(Number(item.key))
                     : undefined} />
}

/** ~10 equal-width bins over a sorted numeric sample (sample sizes, doses…),
 * with a median line + IQR band tying the summary stats to the shape. */
export function NumericHistogram({ values, stats, color, ariaLabel }: {
  values: number[]
  stats?: NumericStats | null
  color?: string
  ariaLabel?: string
}) {
  const { t } = useTranslation()
  const min = values[0]
  const max = values[values.length - 1]
  if (min === max) {
    return <BarChart items={[{ label: String(min), n: values.length }]}
                     color={color} ariaLabel={ariaLabel} />
  }
  const nBins = Math.min(10, Math.max(4, Math.ceil(Math.sqrt(values.length))))
  const step = (max - min) / nBins
  const fmt = (x: number) =>
    Math.abs(x) >= 100 ? String(Math.round(x)) : String(Math.round(x * 10) / 10)
  const items: BarItem[] = Array.from({ length: nBins }, (_, i) => ({
    label: `${fmt(min + i * step)}–${fmt(min + (i + 1) * step)}`,
    n: 0,
  }))
  for (const v of values) {
    const i = Math.min(nBins - 1, Math.floor((v - min) / step))
    items[i].n += 1
  }
  const frac = (v: number) => Math.min(1, Math.max(0, (v - min) / (max - min)))
  const markers = stats ? {
    median01: frac(stats.median),
    iqr01: [frac(stats.q1), frac(stats.q3)] as [number, number],
    label: t('median'),
  } : undefined
  return <BarChart items={items} color={color} markers={markers}
                   ariaLabel={ariaLabel} />
}
