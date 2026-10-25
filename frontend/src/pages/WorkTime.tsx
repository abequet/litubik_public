// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type Project } from '../api'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Segmented } from '@/components/ui/segmented'
import { Stat } from '@/components/ui/stat'
import ChartCard from '@/components/results/ChartCard'
import BarChart from '@/components/results/BarChart'
import { useVizPalette } from '@/components/results/palette'
import { fmtDuration } from '@/lib/duration'

/** Reviewer work time (roadmap chantier 14) — project admin only.
 * Two sources: *measured* (heartbeats sent by the work pages) and
 * *estimated* (sessions reconstructed from the timestamps of votes, cells,
 * rulings…, for projects older than the measure and as a cross-check).
 * Aggregates only: reviewer × stage, week, median time per screened record. */

type Source = 'measured' | 'estimated'

interface StageCell { seconds: number; n_sessions: number; n_acts: number; n_records: number }

interface ReviewerRow {
  user_id: number
  display_name: string
  role: string | null
  total_seconds: number
  by_stage: Record<string, StageCell>
  per_record: { ta: number | null; ft: number | null }
}

interface Report {
  source: Source
  gap_s: number
  cap_s: number
  stages: string[]
  reviewers: ReviewerRow[]
  weeks: { week: string; by_user: Record<string, number> }[]
  n_sessions: number
  total_seconds: number
}

const STAGE_LABELS: Record<string, string> = {
  ta: 'Title/abstract',
  ft: 'Full text',
  conflicts: 'Conflicts',
  dedup: 'Dedup',
  extraction: 'Extraction',
  appraisal: 'Appraisal',
}

export default function WorkTimePage() {
  const { t } = useTranslation()
  const { projectId } = useParams()
  const pid = Number(projectId)
  const palette = useVizPalette()
  const [source, setSource] = useState<Source>('measured')
  const [gapMin, setGapMin] = useState(10)
  const [capMin, setCapMin] = useState(5)

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'], queryFn: () => api.get('/api/projects'),
  })
  const project = projects.find((p) => p.id === pid)

  const gap = Math.max(1, Math.min(120, gapMin)) * 60
  const cap = Math.max(1, Math.min(120, capMin)) * 60
  const query = `source=${source}&gap=${gap}&cap=${cap}`
  const { data: report, error } = useQuery<Report, ApiError>({
    queryKey: ['worktime', pid, source, gap, cap],
    queryFn: () => api.get(`/api/projects/${pid}/worktime/report?${query}`),
    retry: false,
  })

  if (error) {
    return (
      <p className="text-sm text-muted-foreground">
        {error.status === 403
          ? t('Only the project admin can see the work time of the reviewers.')
          : error.message}
      </p>
    )
  }

  const stages = report?.stages ?? []
  const weeks = report?.weeks ?? []
  const weekItems = weeks.map((w) => ({
    label: w.week,
    n: Math.round(Object.values(w.by_user).reduce((a, b) => a + b, 0) / 60),
  }))
  const nameOf = (uid: string) =>
    report?.reviewers.find((r) => String(r.user_id) === uid)?.display_name ?? uid

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('Work time')}{project ? ` — ${project.name}` : ''}
      </h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {t('Active time per reviewer and per stage. Measured: the work pages report every 30 s while the tab is visible and in use. Estimated: sessions rebuilt from the timestamps of votes, rulings, cells and appraisals — for work done before the measure existed, and as a cross-check. Aggregates only: nothing here is attached to an individual reference. Every member can see their own total on the Members panel.')}
      </p>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Segmented
          value={source}
          onChange={setSource}
          options={[
            { value: 'measured' as Source, label: t('Measured') },
            { value: 'estimated' as Source, label: t('Estimated') },
          ]}
        />
        {source === 'estimated' && (
          <>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              {t('Inactivity cut-off (min)')}
              <Input type="number" min={1} max={120} value={gapMin}
                     onChange={(e) => setGapMin(Number(e.target.value) || 1)}
                     className="h-8 w-20" />
            </label>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              {t('Max time per act (min)')}
              <Input type="number" min={1} max={120} value={capMin}
                     onChange={(e) => setCapMin(Number(e.target.value) || 1)}
                     className="h-8 w-20" />
            </label>
          </>
        )}
        <span className="flex-1" />
        <Button asChild variant="outline" size="sm">
          <a href={`/api/projects/${pid}/worktime/export.csv?${query}`} download>
            ⤓ {t('Export CSV')}
          </a>
        </Button>
      </div>

      {!report ? <p className="text-muted-foreground">{t('Loading…')}</p> : (
        <>
          <Card className="mb-4 flex flex-wrap gap-8 p-4">
            <Stat value={fmtDuration(report.total_seconds)} label={t('Total active time')} />
            <Stat value={report.n_sessions} label={t('Sessions')} />
            <Stat value={report.reviewers.filter((r) => r.total_seconds > 0).length}
                  label={t('Reviewers with time logged')} />
          </Card>

          <Card className="mb-4 overflow-x-auto p-4">
            <table className="w-full text-xs">
              <caption className="sr-only">{t('Active time per reviewer and stage')}</caption>
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th className="py-1 pr-3 font-medium">{t('Reviewer')}</th>
                  {stages.map((s) => (
                    <th key={s} className="py-1 pr-3 text-right font-medium">{t(STAGE_LABELS[s] ?? s)}</th>
                  ))}
                  <th className="py-1 pr-3 text-right font-medium">{t('Total')}</th>
                  <th className="py-1 pr-3 text-right font-medium"
                      title={t('Median time between two of the reviewer’s votes, from the vote timestamps (same for both sources)')}>
                    {t('Median / record (T/A)')}
                  </th>
                  <th className="py-1 text-right font-medium">{t('Median / record (FT)')}</th>
                </tr>
              </thead>
              <tbody className="text-foreground">
                {report.reviewers.map((r) => (
                  <tr key={r.user_id} className="border-t border-border">
                    <td className="py-1.5 pr-3">
                      {r.display_name}
                      {r.role === null && (
                        <span className="ml-1 text-muted-foreground">({t('former member')})</span>
                      )}
                    </td>
                    {stages.map((s) => {
                      const cell = r.by_stage[s]
                      return (
                        <td key={s} className="py-1.5 pr-3 text-right tabular-nums"
                            title={cell.n_sessions
                              ? t('{{count}} sessions', { count: cell.n_sessions }) : undefined}>
                          {cell.seconds ? fmtDuration(cell.seconds)
                            : <span className="text-muted-foreground">—</span>}
                        </td>
                      )
                    })}
                    <td className="py-1.5 pr-3 text-right font-medium tabular-nums">
                      {fmtDuration(r.total_seconds)}
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">
                      {r.per_record.ta !== null
                        ? `${r.per_record.ta} s`
                        : <span className="text-muted-foreground">—</span>}
                      {r.by_stage.ta?.n_records
                        ? <span className="text-muted-foreground"> · n={r.by_stage.ta.n_records}</span> : null}
                    </td>
                    <td className="py-1.5 text-right tabular-nums">
                      {r.per_record.ft !== null
                        ? `${r.per_record.ft} s`
                        : <span className="text-muted-foreground">—</span>}
                      {r.by_stage.ft?.n_records
                        ? <span className="text-muted-foreground"> · n={r.by_stage.ft.n_records}</span> : null}
                    </td>
                  </tr>
                ))}
                {report.reviewers.length === 0 && (
                  <tr><td className="py-2 text-muted-foreground" colSpan={stages.length + 4}>
                    {t('No activity yet.')}
                  </td></tr>
                )}
              </tbody>
            </table>
          </Card>

          {weekItems.length > 0 && (
            <ChartCard title={t('Active minutes per week')}
                       subtitle={source === 'measured'
                         ? t('Heartbeats of the work pages, every reviewer')
                         : t('Estimated from activity timestamps, every reviewer')}
                       filename={`worktime-weeks-${source}`}
                       tableData={weeks.flatMap((w) =>
                         Object.entries(w.by_user).map(([uid, s]) => ({
                           label: `${w.week} · ${nameOf(uid)}`, value: fmtDuration(s) })))}>
              <BarChart items={weekItems} color={palette.blue}
                        ariaLabel={t('Active minutes per week')} />
            </ChartCard>
          )}
        </>
      )}
    </div>
  )
}
