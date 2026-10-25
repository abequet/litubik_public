// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type DatabaseInfo, type Equation, type UpdatePlan, type UpdateRun } from '../api'
import { useJobWatcher } from '../useJob'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Switch } from '@/components/ui/switch'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import LiveStatus from './LiveStatus'

/** Living review (chantier 5): the update plan (cadence, databases, frozen
 * equation), "run an update now", and the history of update passes — each
 * pass is a round of its own (new T/A screening round, PRISMA column). */
export default function SearchUpdates({ projectId, isAdmin, databases, equations, onChange }: {
  projectId: number
  isAdmin: boolean
  databases: DatabaseInfo[]
  equations: Equation[]
  onChange: () => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: plan } = useQuery<UpdatePlan>({
    queryKey: ['update-plan', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/search/update-plan`),
  })
  const { data: runs = [] } = useQuery<UpdateRun[]>({
    queryKey: ['update-runs', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/search/updates`),
  })
  const apiDatabases = databases.filter((d) => d.count === 'api')
  const frozen = equations.filter((e) => e.status === 'frozen')

  const [enabled, setEnabled] = useState(false)
  const [interval, setInterval] = useState(30)
  const [selected, setSelected] = useState<string[]>([])
  const [equationId, setEquationId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [dirty, setDirty] = useState(false)
  useEffect(() => {
    if (!plan || dirty) return
    setEnabled(plan.enabled)
    setInterval(plan.interval_days)
    setSelected(plan.databases)
    setEquationId(plan.equation_id)
  }, [plan, dirty])

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['update-plan', projectId] })
    queryClient.invalidateQueries({ queryKey: ['update-runs', projectId] })
    onChange()
  }
  const save = useMutation({
    mutationFn: () => api.put(`/api/projects/${projectId}/search/update-plan`, {
      enabled, interval_days: interval, databases: selected, equation_id: equationId }),
    onSuccess: () => { setError(''); setDirty(false); refresh() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const watcher = useJobWatcher(refresh)
  const running = watcher.state !== ''
  const runNow = useMutation({
    mutationFn: () => api.post<{ job_id: number }>(
      `/api/projects/${projectId}/search/updates/run`,
      { databases: selected, equation_id: equationId }),
    onSuccess: (r) => { setError(''); watcher.watch(r.job_id) },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Could not start the update')),
  })
  const del = useMutation({
    mutationFn: (round: number) => api.del(`/api/projects/${projectId}/search/updates/${round}`),
    onSuccess: refresh,
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Delete failed')),
  })

  const toggle = (id: string) => {
    setDirty(true)
    setSelected((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id])
  }
  const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : '—')
  const triggerLabel: Record<string, string> = {
    schedule: 'scheduled', manual: 'manual', fetch: 'fetch',
  }

  return (
    <Card className="mb-6 p-4">
      <h2 className="text-sm font-semibold text-foreground">{t('Living review — search updates')}</h2>
      <p className="mt-1 mb-3 max-w-2xl text-xs text-muted-foreground">
        {t('An update pass re-runs the frozen equation on the selected API databases, restricted to what they indexed since the previous pass. New records are deduplicated against the corpus and open a new title/abstract screening round with the same rules; every pass keeps its own PRISMA column, and members are notified.')}
      </p>

      {isAdmin && (
        <div className="mb-4 grid gap-3 md:grid-cols-2">
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm text-foreground">
              <Switch checked={enabled}
                      onCheckedChange={(v) => { setDirty(true); setEnabled(v) }} />
              {t('Scheduled updates')}
            </label>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              {t('Every')}
              <Select value={String(interval)}
                      onValueChange={(v) => { setDirty(true); setInterval(Number(v)) }}>
                <SelectTrigger className="h-8 w-28 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {(plan?.intervals ?? [7, 14, 30, 90]).map((d) => (
                    <SelectItem key={d} value={String(d)}>{t('{{count}} days', { count: d })}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              {t('Equation')}
              <Select value={equationId !== null ? String(equationId) : 'latest'}
                      onValueChange={(v) => { setDirty(true); setEquationId(v === 'latest' ? null : Number(v)) }}>
                <SelectTrigger className="h-8 w-56 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="latest">{t('latest frozen equation')}</SelectItem>
                  {frozen.map((e) => (
                    <SelectItem key={e.id} value={String(e.id)}>{e.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            {plan?.next_run_at && plan.enabled && (
              <p className="text-xs text-muted-foreground">
                {t('Next pass: {{date}}', { date: fmt(plan.next_run_at) })}
                {plan.last_run_at && ` · ${t('last pass: {{date}}', { date: fmt(plan.last_run_at) })}`}
              </p>
            )}
          </div>
          <div>
            <p className="mb-1 text-xs text-muted-foreground">{t('Databases to re-run')}</p>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {apiDatabases.map((d) => (
                <label key={d.id} className="flex items-center gap-1.5 text-xs text-foreground">
                  <Checkbox checked={selected.includes(d.id)} onCheckedChange={() => toggle(d.id)} />
                  {d.label}
                </label>
              ))}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button size="sm" variant="secondary" onClick={() => save.mutate()}
                      disabled={save.isPending || !dirty}>
                {t('Save plan')}
              </Button>
              <Button size="sm" variant="outline" onClick={() => runNow.mutate()}
                      disabled={runNow.isPending || selected.length === 0 || running}
                      title={t('Run an update pass now on the selected databases')}>
                {running ? t('Updating…') : t('Run an update now')}
              </Button>
              {running && (
                <span className="text-xs text-muted-foreground">{watcher.state}</span>
              )}
            </div>
          </div>
        </div>
      )}
      <LiveStatus className="mb-2 text-xs">{error || watcher.error}</LiveStatus>

      {runs.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-muted-foreground">
                <th className="pb-1 pr-3 font-medium">{t('Pass')}</th>
                <th className="pb-1 pr-3 font-medium">{t('Date')}</th>
                <th className="pb-1 pr-3 font-medium">{t('Since')}</th>
                <th className="pb-1 pr-3 font-medium">{t('Databases')}</th>
                <th className="pb-1 pr-3 text-right font-medium">{t('Fetched')}</th>
                <th className="pb-1 pr-3 text-right font-medium">{t('New unique')}</th>
                <th className="pb-1 pr-3 font-medium">{t('Trigger')}</th>
                {isAdmin && <th className="w-8 pb-1"><span className="sr-only">{t('Actions')}</span></th>}
              </tr>
            </thead>
            <tbody className="text-foreground">
              {runs.map((r) => (
                <tr key={r.id} className="border-t border-border">
                  <td className="py-1.5 pr-3 font-medium">
                    {t('Search update {{n}}', { n: r.n ?? r.round })}
                    <span className="text-muted-foreground"> · r{r.round}</span>
                  </td>
                  <td className="py-1.5 pr-3">{fmt(r.finished_at)}</td>
                  <td className="py-1.5 pr-3">{r.since_at ? fmt(r.since_at) : t('full run')}</td>
                  <td className="py-1.5 pr-3">
                    {r.databases.join(', ')}
                    {Object.keys(r.errors).length > 0 && (
                      <span className="text-destructive"
                            title={Object.entries(r.errors).map(([k, v]) => `${k}: ${v}`).join('\n')}>
                        {' '}· {t('{{count}} failed', { count: Object.keys(r.errors).length })}
                      </span>
                    )}
                  </td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{r.n_fetched}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums font-medium">{r.n_new_unique}</td>
                  <td className="py-1.5 pr-3">{t(triggerLabel[r.triggered_by] ?? r.triggered_by)}</td>
                  {isAdmin && (
                    <td className="py-1.5">
                      {r.deletable && (
                        <Button variant="ghost" size="icon"
                                className="size-7 text-muted-foreground hover:text-destructive"
                                title={t('Delete this pass (its records, their screening and the run row)')}
                                onClick={() => {
                                  if (confirm(t('Delete search update {{n}} and its {{count}} fetched records?', { n: r.n ?? r.round, count: r.n_fetched })))
                                    del.mutate(r.round)
                                }}>✕</Button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">{t('No update pass yet.')}</p>
      )}
    </Card>
  )
}
