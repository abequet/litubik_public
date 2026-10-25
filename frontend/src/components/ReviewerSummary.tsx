// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import { Card } from '@/components/ui/card'
import ChartCard from '@/components/results/ChartCard'
import StackedBar from '@/components/results/StackedBar'
import { useVizPalette } from '@/components/results/palette'

interface StageCounts {
  assigned: number
  done: number
  include: number
  exclude: number
  maybe: number
  triage_excluded: number
  triage_votes: number
}

interface ReviewerRow {
  user_id: number
  display_name: string
  role: string | null
  ta: StageCounts
  ft: StageCounts
  conflicts_resolved: { ta: number; ft: number }
  dedup_decisions: number
  extraction: { records: number; cells: number }
  appraisals: number
}

interface PooledPair {
  rows_user_id: number
  cols_user_id: number
  rows_name: string
  cols_name: string
  n_records: number
  kappa: number | null
  percent: number
}

interface StageAgreement {
  n_records: number
  percent: number | null
  pairs: PooledPair[]
  maybe_as_include: boolean
  n_rounds: number
}

export interface ReviewerSummaryData {
  /** anonymous reviewers: the table is withheld while a round runs */
  withheld: boolean
  reviewers: ReviewerRow[]
  agreement: { ta: StageAgreement; ft: StageAgreement }
  rounds: { ta: number[]; ft: number[] }
}

type Stage = 'ta' | 'ft'

const hasActivity = (r: ReviewerRow) =>
  r.ta.done + r.ft.done + r.conflicts_resolved.ta + r.conflicts_resolved.ft
    + r.dedup_decisions + r.extraction.cells + r.appraisals > 0

/** Who did what over the whole review (every T/A and full-text round
 * folded, plus duplicate rulings, conflict resolutions, extraction and
 * appraisal). Lives under the PRISMA diagram: the flow says how many
 * records went through, this says who took them through. */
export default function ReviewerSummary({ projectId }: { projectId: number }) {
  const { t } = useTranslation()
  const { data } = useQuery<ReviewerSummaryData>({
    queryKey: ['prisma-reviewers', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/prisma/reviewers`),
    refetchOnMount: 'always',
    refetchInterval: 15_000,
  })
  if (!data) return null
  const active = data.reviewers.filter(hasActivity)
  const nRounds = data.rounds.ta.length + data.rounds.ft.length
  return (
    <div className="max-w-3xl mt-8">
      <h2 className="text-sm font-semibold text-foreground mb-1">
        {t('Reviewer activity over the whole review')}
      </h2>
      <p className="text-xs text-muted-foreground mb-3">
        {nRounds > 1
          ? t('Every title/abstract and full-text round is folded together — the initial search and each snowballing iteration. Human work only: AI suggestions are not counted, and what the AI title triage took off a reviewer is shown apart.')
          : t('Human work only: AI suggestions are not counted, and what the AI title triage took off a reviewer is shown apart.')}
      </p>
      {data.withheld ? (
        <p className="text-sm text-muted-foreground">
          {t('Hidden while a screening round with anonymous reviewers is in progress — the table comes back once that round is complete.')}
        </p>
      ) : active.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {t('No reviewer activity yet — the table fills in as screening starts.')}
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          <ActivityTable rows={data.reviewers} />
          <DecisionChart stage="ta" rows={data.reviewers} />
          <DecisionChart stage="ft" rows={data.reviewers} />
          <PooledAgreement data={data} />
        </div>
      )}
    </div>
  )
}

function ActivityTable({ rows }: { rows: ReviewerRow[] }) {
  const { t } = useTranslation()
  const screened = (s: StageCounts) => {
    const ai = s.triage_excluded + s.triage_votes
    const byHand = s.done - s.triage_votes
    const total = s.assigned - ai
    if (s.assigned === 0 && s.done === 0) return '—'
    return `${byHand}/${total}`
  }
  const anyTriage = rows.some((r) => r.ta.triage_excluded + r.ta.triage_votes > 0)
  const roleLabel = (role: string | null) =>
    role === 'admin' ? t('admin') : role === 'reviewer' ? t('reviewer') : t('former member')
  return (
    <Card className="p-4 overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-muted-foreground">
            <th className="py-1 pr-3 font-medium">{t('Reviewer')}</th>
            <th className="py-1 pr-3 font-medium">{t('Title/abstract screened')}</th>
            <th className="py-1 pr-3 font-medium">{t('Full texts screened')}</th>
            <th className="py-1 pr-3 font-medium">{t('Conflicts settled')}</th>
            <th className="py-1 pr-3 font-medium">{t('Duplicates ruled')}</th>
            <th className="py-1 pr-3 font-medium">{t('Records extracted')}</th>
            <th className="py-1 pr-3 font-medium">{t('Appraisals')}</th>
          </tr>
        </thead>
        <tbody className="text-foreground">
          {rows.map((r) => {
            const triage = r.ta.triage_excluded + r.ta.triage_votes
            const conflicts = r.conflicts_resolved.ta + r.conflicts_resolved.ft
            return (
              <tr key={r.user_id} className="border-t border-border">
                <td className="py-1.5 pr-3">
                  <span className="font-medium">{r.display_name}</span>
                  <span className="ml-1 text-muted-foreground">({roleLabel(r.role)})</span>
                </td>
                <td className="py-1.5 pr-3 tabular-nums whitespace-nowrap">
                  {screened(r.ta)}
                  {triage > 0 && (
                    <span className="text-muted-foreground"> · {t('{{count}} via AI triage', { count: triage })}</span>
                  )}
                </td>
                <td className="py-1.5 pr-3 tabular-nums">{screened(r.ft)}</td>
                <td className="py-1.5 pr-3 tabular-nums">
                  {conflicts || '—'}
                  {conflicts > 0 && r.conflicts_resolved.ft > 0 && (
                    <span className="text-muted-foreground"> ({t('{{ta}} T/A · {{ft}} full text', { ta: r.conflicts_resolved.ta, ft: r.conflicts_resolved.ft })})</span>
                  )}
                </td>
                <td className="py-1.5 pr-3 tabular-nums">{r.dedup_decisions || '—'}</td>
                <td className="py-1.5 pr-3 tabular-nums">
                  {r.extraction.records || '—'}
                  {r.extraction.records > 0 && (
                    <span className="text-muted-foreground"> ({t('{{count}} cells', { count: r.extraction.cells })})</span>
                  )}
                </td>
                <td className="py-1.5 pr-3 tabular-nums">{r.appraisals || '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted-foreground">
        {t('Screened = records voted on by hand / records allocated to the reviewer.')}
        {anyTriage && <> {t('Titles excluded via the validated AI triage are left out of both numbers.')}</>}
      </p>
    </Card>
  )
}

/** 100 % stacked bar of each reviewer's votes at one stage, with the team
 * pooled on top. Same colours and hatching as the appraisal chart so
 * include / exclude / maybe read the same way across the app. */
function DecisionChart({ stage, rows }: { stage: Stage; rows: ReviewerRow[] }) {
  const { t } = useTranslation()
  const palette = useVizPalette()
  const voters = rows.filter((r) => r[stage].done > 0)
  if (voters.length === 0) return null
  const counts = (r: ReviewerRow) => {
    const s = r[stage]
    // the triage-validated exclusions are not reads: keep them out of the
    // decision mix so the bar shows how the reviewer judged what they read
    return [s.include, s.exclude - s.triage_votes, s.maybe]
  }
  const segments = [
    { label: t('include'), color: palette.teal },
    { label: t('exclude'), color: palette.orange },
    { label: t('maybe'), color: palette.mutedForeground, pattern: 'hatch' as const },
  ]
  const chartRows = voters.map((r) => ({ label: r.display_name, values: counts(r) }))
  const pooled = {
    label: t('Whole team'),
    values: chartRows.reduce((acc, r) => acc.map((v, i) => v + r.values[i]), [0, 0, 0]),
  }
  const nVotes = pooled.values.reduce((a, b) => a + b, 0)
  const title = stage === 'ta'
    ? t('Title/abstract decisions per reviewer')
    : t('Full-text decisions per reviewer')
  const filename = stage === 'ta' ? 'reviewers-title-abstract.png' : 'reviewers-full-text.png'
  const tableData = [pooled, ...chartRows].map((r) => ({
    label: r.label,
    value: t('{{include}} in / {{exclude}} out / {{maybe}} maybe',
             { include: r.values[0], exclude: r.values[1], maybe: r.values[2] }),
  }))
  return (
    <ChartCard title={title} n={nVotes} filename={filename} tableData={tableData}
               subtitle={t('Share of include / exclude / maybe among the votes each reviewer cast by hand, every round folded.')}>
      <StackedBar rows={chartRows} segments={segments} pooled={pooled}
                  ariaLabel={title} />
    </ChartCard>
  )
}

function PooledAgreement({ data }: { data: ReviewerSummaryData }) {
  const { t } = useTranslation()
  const stages = (['ta', 'ft'] as const).filter((s) => data.agreement[s].pairs.length > 0)
  if (stages.length === 0) return null
  const fmtK = (k: number | null) => (k === null ? '—' : k.toFixed(2))
  const fmtPct = (p: number) => `${Math.round(p * 100)} %`
  return (
    <Card className="p-4">
      <h3 className="text-sm font-semibold text-foreground mb-1">
        {t('Agreement between reviewers, every round pooled')}
      </h3>
      <p className="text-xs text-muted-foreground mb-3">
        {t("Cohen's kappa per pair over every record both reviewers voted on, across the rounds. At title/abstract a \"maybe\" counts as \"include\" (both send the record to full text).")}
      </p>
      <div className="flex flex-col gap-3">
        {stages.map((stage) => {
          const a = data.agreement[stage]
          return (
            <div key={stage}>
              <p className="text-xs font-medium text-foreground mb-1">
                {stage === 'ta' ? t('Title/abstract') : t('Full text')}
                <span className="ml-2 font-normal text-muted-foreground tabular-nums">
                  {t('{{count}} double-screened records', { count: a.n_records })}
                  {a.n_rounds > 1 && <> · {t('{{count}} rounds', { count: a.n_rounds })}</>}
                </span>
              </p>
              <ul className="text-xs text-foreground">
                {a.pairs.map((p) => (
                  <li key={`${p.rows_user_id}-${p.cols_user_id}`}
                      className="flex flex-wrap gap-x-3 border-t border-border py-1 tabular-nums">
                    <span className="min-w-48">{p.rows_name} × {p.cols_name}</span>
                    <span>κ = {fmtK(p.kappa)}</span>
                    <span className="text-muted-foreground">
                      {t('{{pct}} agreement on {{count}} records',
                         { pct: fmtPct(p.percent), count: p.n_records })}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>
    </Card>
  )
}
