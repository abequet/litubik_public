// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { Card } from '@/components/ui/card'

/** Dashboard blocks shared by the title/abstract and full-text screening
 * pages: per-reviewer progress and the reviewers' vote cross-matrices. */

// ---- per reviewer ------------------------------------------------------------------

export interface ReviewerStat {
  user_id: number
  display_name: string
  assigned: number
  done: number
  include: number
  exclude: number
  maybe: number
  /** assigned records the AI title triage excluded globally (admin mode) */
  triage_excluded?: number
  /** the reviewer's own exclude votes cast by validating the triage list */
  triage_votes?: number
}

// hatching marks the share nobody screened by hand, so it never relies on
// colour alone to stand apart from the two solid segments
const HATCH = 'repeating-linear-gradient(135deg, var(--muted-foreground) 0 2px, transparent 2px 5px)'

export function ReviewerProgress({ reviewers, showMaybe }: {
  reviewers: ReviewerStat[]
  showMaybe: boolean
}) {
  const { t } = useTranslation()
  const rows = reviewers.map((r) => {
    const triageVotes = r.triage_votes ?? 0
    const ai = (r.triage_excluded ?? 0) + triageVotes
    const byHand = r.done - triageVotes
    // what the reviewer really has to read: the assignment minus the triage
    const total = r.assigned - ai
    return { r, ai, byHand, total, left: Math.max(total - byHand, 0),
             excluded: r.exclude - triageVotes }
  })
  const anyAi = rows.some((row) => row.ai > 0)
  return (
    <Card className="p-4">
      <h3 className="mb-1 text-sm font-semibold text-foreground">{t('Per reviewer')}</h3>
      {anyAi && (
        <p className="mb-3 text-xs text-muted-foreground">
          {t('Counts and bars show what each reviewer really has to screen: the titles excluded via AI triage are hatched and left out of the total.')}
        </p>
      )}
      <div className={anyAi ? undefined : 'mt-3'}>
        {rows.map(({ r, ai, byHand, total, left, excluded }) => (
          <div key={r.user_id} className="mb-3">
            <div className="mb-1 flex flex-wrap justify-between gap-x-3 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{r.display_name}</span>
              <span className="tabular-nums">
                {byHand}/{total} · {showMaybe
                  ? t('{{include}} in / {{exclude}} out / {{maybe}} maybe',
                      { include: r.include, exclude: excluded, maybe: r.maybe })
                  : t('{{include}} in / {{exclude}} out',
                      { include: r.include, exclude: excluded })}
                {ai > 0 && <> · {t('{{count}} via AI triage', { count: ai })}</>}
              </span>
            </div>
            <div className="flex h-2 w-full gap-0.5 overflow-hidden rounded-full">
              {byHand > 0 && (
                <div className="h-full bg-primary" style={{ flexGrow: byHand }}
                     title={`${t('Screened by hand')}: ${byHand}`} />
              )}
              {(left > 0 || r.assigned === 0) && (
                <div className="h-full bg-muted" style={{ flexGrow: left || 1 }}
                     title={`${t('Left to screen')}: ${left}`} />
              )}
              {/* last, so that done + left — the real workload — stay contiguous */}
              {ai > 0 && (
                <div className="h-full bg-muted" title={`${t('Excluded via AI title triage')}: ${ai}`}
                     style={{ flexGrow: ai, backgroundImage: HATCH }} />
              )}
            </div>
          </div>
        ))}
      </div>
      {anyAi && (
        <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-4 rounded-sm bg-primary" />
            {t('Screened by hand')}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-4 rounded-sm border border-border bg-muted" />
            {t('Left to screen')}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-4 rounded-sm bg-muted"
                  style={{ backgroundImage: HATCH }} />
            {t('Excluded via AI title triage')}
          </span>
        </p>
      )}
    </Card>
  )
}

// ---- vote cross-matrices -----------------------------------------------------------

export interface PairMatrix {
  rows_user_id: number
  cols_user_id: number
  rows_name: string
  cols_name: string
  cells: Record<string, Record<string, number>>
  n_records: number
  kappa: number | null
  percent: number
}

const CATEGORIES = ['include', 'exclude', 'maybe']
// beyond this many reviewer pairs the grid starts folded
const PAIRS_SHOWN = 6

/** One 3×3 cross-tab per pair of reviewers, each with both names on its axes.
 * Small multiples rather than a 3D view: a cube hides its back cells and stops
 * at three reviewers, while a pair of names reads the same at any team size. */
export function AgreementMatrices({ title, pairs, unit, hideEmptyMaybe, maybeAsInclude }: {
  title: string
  pairs: PairMatrix[]
  unit: 'records' | 'reports'
  /** full text rarely uses “maybe”: drop its row and column when empty */
  hideEmptyMaybe?: boolean
  /** the κ and raw agreement were computed with “maybe” folded into “include” */
  maybeAsInclude?: boolean
}) {
  const { t } = useTranslation()
  const [showAll, setShowAll] = useState(false)
  if (pairs.length === 0) return null
  const maybeUsed = pairs.some((p) => CATEGORIES.some((c) =>
    (p.cells.maybe?.[c] ?? 0) + (p.cells[c]?.maybe ?? 0) > 0))
  const categories = hideEmptyMaybe && !maybeUsed
    ? CATEGORIES.filter((c) => c !== 'maybe') : CATEGORIES
  const single = pairs.length === 1
  const shown = showAll ? pairs : pairs.slice(0, PAIRS_SHOWN)
  return (
    <Card className="p-4">
      <h3 className="mb-1 text-sm font-semibold text-foreground">{title}</h3>
      <p className="mb-3 text-xs text-muted-foreground">
        {single
          ? t('Each cell counts the papers on which the reviewer in rows and the reviewer in columns voted that way.')
          : t('One matrix per pair of reviewers, over the papers both screened — first name in rows, second in columns.')}
        {maybeAsInclude && (
          <> {t('κ and raw agreement count “maybe” as “include” (both send the record on to full text); the matrix keeps the three votes apart.')}</>
        )}
      </p>
      <div className={single ? undefined : 'grid gap-4 sm:grid-cols-2'}>
        {shown.map((p) => (
          <PairTable key={`${p.rows_user_id}-${p.cols_user_id}`} pair={p}
                     categories={categories} unit={unit} boxed={!single} />
        ))}
      </div>
      {pairs.length > PAIRS_SHOWN && (
        <button onClick={() => setShowAll((v) => !v)}
                className="mt-3 text-xs text-primary hover:underline">
          {showAll ? t('Show fewer pairs')
            : t('Show all {{count}} pairs', { count: pairs.length })}
        </button>
      )}
      <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-sm"
                style={{ background: tint('success', 0.5) }} />
          {t('agreement (diagonal)')}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-sm"
                style={{ background: tint('warning', 0.5) }} />
          {t('disagreement')}
        </span>
        <span>{t('Darker = more papers.')}</span>
      </p>
    </Card>
  )
}

/** Cell fill: the hue says agree/disagree, the depth says how many. */
function tint(token: 'success' | 'warning', share: number): string {
  return `color-mix(in oklab, var(--${token}) ${Math.round(14 + 36 * share)}%, transparent)`
}

function PairTable({ pair, categories, unit, boxed }: {
  pair: PairMatrix
  categories: string[]
  unit: 'records' | 'reports'
  boxed: boolean
}) {
  const { t } = useTranslation()
  const n = pair.n_records
  const cell = (row: string, col: string) => pair.cells[row]?.[col] ?? 0
  const rowTotal = (row: string) => categories.reduce((s, c) => s + cell(row, c), 0)
  const colTotal = (col: string) => categories.reduce((s, r) => s + cell(r, col), 0)
  const head = 'px-2 pb-1 text-xs font-medium text-muted-foreground'
  const total = 'px-2 py-1 text-center text-xs tabular-nums text-muted-foreground'
  return (
    <div className={cn('min-w-0', boxed && 'rounded-md border border-border p-3')}>
      <table className="border-separate border-spacing-0.5 text-sm tabular-nums">
        <thead>
          <tr>
            <td aria-hidden />
            <th colSpan={categories.length}
                className="max-w-0 truncate border-b border-border px-2 pb-1 text-center text-xs font-semibold text-foreground"
                title={pair.cols_name}>
              {pair.cols_name}
            </th>
            <td aria-hidden />
          </tr>
          <tr>
            <th className="max-w-32 truncate pr-2 pb-1 text-left text-xs font-semibold text-foreground"
                title={pair.rows_name}>
              {pair.rows_name}
            </th>
            {categories.map((c) => <th key={c} className={head}>{t(c)}</th>)}
            <th className={head}>{t('total')}</th>
          </tr>
        </thead>
        <tbody>
          {categories.map((row) => (
            <tr key={row}>
              <th className="pr-2 text-left text-xs font-medium text-muted-foreground">
                {t(row)}
              </th>
              {categories.map((col) => {
                const count = cell(row, col)
                const pct = n ? Math.round((count / n) * 100) : 0
                return (
                  <td key={col}
                      title={t('{{rows}}: {{a}} · {{cols}}: {{b}} — {{count}} ({{pct}} %)',
                        { rows: pair.rows_name, a: t(row), cols: pair.cols_name,
                          b: t(col), count, pct })}
                      className={cn('min-w-14 rounded px-2 py-1 text-center',
                        count === 0 && 'text-muted-foreground/40')}
                      style={count > 0 ? {
                        background: tint(row === col ? 'success' : 'warning',
                                         n ? count / n : 0),
                      } : undefined}>
                    <span className={cn('block leading-tight',
                      count > 0 && 'font-medium text-foreground')}>{count}</span>
                    {count > 0 && (
                      <span className="block text-xs leading-tight text-muted-foreground">
                        {pct} %
                      </span>
                    )}
                  </td>
                )
              })}
              <td className={total}>{rowTotal(row)}</td>
            </tr>
          ))}
          <tr>
            <th className="pr-2 text-left text-xs font-medium text-muted-foreground">
              {t('total')}
            </th>
            {categories.map((col) => (
              <td key={col} className={total}>{colTotal(col)}</td>
            ))}
            <td className={cn(total, 'font-medium text-foreground')}>{n}</td>
          </tr>
        </tbody>
      </table>
      <p className="mt-2 text-xs tabular-nums text-muted-foreground">
        Cohen's κ {pair.kappa != null ? pair.kappa.toFixed(2) : '—'}
        {' · '}{t('{{pct}} % raw agreement', { pct: (pair.percent * 100).toFixed(0) })}
        {' · '}{unit === 'reports'
          ? t('{{count}} reports', { count: n })
          : t('{{count}} records', { count: n })}
      </p>
    </div>
  )
}
