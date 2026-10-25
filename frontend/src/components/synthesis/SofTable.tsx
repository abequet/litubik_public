// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, type SofTable as SofTableData } from '@/api'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'

const API = (pid: number) => `/api/projects/${pid}/synthesis`

const TONE: Record<string, string> = {
  high: 'text-success',
  moderate: 'text-primary',
  low: 'text-warning',
  very_low: 'text-destructive',
}

/** The Summary of Findings table — one row per reported result, with the
 * studies behind it and the certainty of it.
 *
 * Every column is read from the project; nothing is typed in here. An
 * unrated row says "not rated" rather than showing an empty cell, because an
 * empty certainty column reads as a confident one. */
export default function SofTable({ pid }: { pid: number }) {
  const { t } = useTranslation()
  const { data } = useQuery<SofTableData>({
    queryKey: ['synthesis-sof', pid],
    queryFn: () => api.get(`${API(pid)}/sof`),
  })

  if (!data) return <p className="text-sm text-muted-foreground">{t('Loading…')}</p>
  if (data.rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t('Declare at least one result above and this table fills itself.')}
      </p>
    )
  }

  return (
    <Card className="max-w-5xl p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-foreground">
            {t('Summary of Findings')}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {t('{{rated}} of {{total}} results carry a certainty rating.', {
              rated: data.n_rated, total: data.rows.length })}
            {data.participants_column
              ? ` ${t('Participants are totalled from the “{{col}}” extraction column.', { col: data.participants_column })}`
              : ` ${t('No numeric extraction column named for participant counts, so that column stays empty.')}`}
          </p>
        </div>
        <Button asChild variant="outline" size="sm">
          <a href={`${API(pid)}/sof.csv`}>⬇ CSV</a>
        </Button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[48rem] text-left text-xs">
          <thead className="border-b border-border text-muted-foreground">
            <tr>
              <th className="py-1.5 pr-3 font-medium">{t('Result')}</th>
              <th className="py-1.5 pr-3 font-medium">{t('Studies')}</th>
              <th className="py-1.5 pr-3 font-medium">{t('Participants')}</th>
              <th className="py-1.5 pr-3 font-medium">{t('Method')}</th>
              <th className="py-1.5 pr-3 font-medium">{t('Certainty')}</th>
              <th className="py-1.5 font-medium">{t('What it says')}</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.outcome_id} className="border-b border-border/60 align-top">
                <td className="py-2 pr-3">
                  {r.comparison && (
                    <span className="block text-muted-foreground">{r.comparison}</span>
                  )}
                  <span className="text-foreground">{r.outcome}</span>
                  {r.metric && (
                    <span className="block text-muted-foreground">{r.metric}</span>
                  )}
                </td>
                <td className="py-2 pr-3 tabular-nums text-muted-foreground">
                  {r.n_studies}
                </td>
                <td className="py-2 pr-3 tabular-nums text-muted-foreground">
                  {r.n_participants ?? '—'}
                </td>
                <td className="py-2 pr-3 text-muted-foreground">
                  {t(r.synthesis_method)}
                  <span className="mt-0.5 block text-xs">
                    {t(r.question_answered)}
                  </span>
                </td>
                <td className={cn('py-2 pr-3 font-medium',
                  r.rated ? TONE[r.certainty] : 'text-muted-foreground')}>
                  {r.rated ? t(r.certainty_label) : t('not rated')}
                </td>
                <td className="py-2 text-muted-foreground">
                  {r.statement_md || r.finding_md || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
