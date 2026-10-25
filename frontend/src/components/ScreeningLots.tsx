// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError } from '../api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'

/** Allocation in weighted lots with rotating pairs:
 * settings block, editable preview before the start, dashboard blocks. */

export interface Member { user_id: number; display_name: string }

export interface LotPlan {
  index: number
  size: number
  user_ids: number[]
  due_at: string | null
}

export interface Share {
  user_id: number
  target_pct: number
  assigned: number
  effective_pct: number
}

export interface LotRow extends LotPlan {
  id: number
  done: { user_id: number; done: number }[]
  status: 'open' | 'closed'
}

interface Preview {
  n_records: number
  lot_size: number
  pairs: number[][]
  lots: LotPlan[]
  shares: Share[]
}

export function evenWeights(reviewers: number[]): Record<string, number> {
  const out: Record<string, number> = {}
  if (reviewers.length === 0) return out
  const base = Math.floor(100 / reviewers.length)
  reviewers.forEach((uid, i) => {
    out[String(uid)] = base + (i < 100 - base * reviewers.length ? 1 : 0)
  })
  return out
}

export function weightsTotal(weights: Record<string, number>, reviewers: number[]): number {
  return reviewers.reduce((s, uid) => s + (Number(weights[String(uid)]) || 0), 0)
}

// ---- settings ----------------------------------------------------------------------

export function LotSettings({ members, reviewers, weights, onWeights, lotSize,
                              onLotSize, disabled }: {
  members: Member[]
  reviewers: number[]
  weights: Record<string, number>
  onWeights: (w: Record<string, number>) => void
  lotSize: number
  onLotSize: (n: number) => void
  disabled: boolean
}) {
  const { t } = useTranslation()
  return (
    <div className="ml-6 space-y-3 rounded-md border border-border p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <span>{t('Records per lot')}</span>
        <Input type="number" min={1} max={10000} value={lotSize} disabled={disabled}
               onChange={(e) => onLotSize(Math.max(1, Number(e.target.value) || 1))}
               className="h-7 w-20 px-2 text-xs" />
      </div>
      <WeightsEditor members={members} reviewers={reviewers} weights={weights}
                     onWeights={onWeights} disabled={disabled}
                     label={t('Share of the work per reviewer (%)')} />
    </div>
  )
}

/** Shares in % over a set of reviewers, with the running total. */
export function WeightsEditor({ members, reviewers, weights, onWeights, disabled, label }: {
  members: Member[]
  reviewers: number[]
  weights: Record<string, number>
  onWeights: (w: Record<string, number>) => void
  disabled: boolean
  label: string
}) {
  const { t } = useTranslation()
  const total = weightsTotal(weights, reviewers)
  const ok = Math.abs(total - 100) < 0.05
  const name = (uid: number) => members.find((m) => m.user_id === uid)?.display_name ?? `#${uid}`
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">{label}</p>
        <button type="button" disabled={disabled}
                onClick={() => onWeights(evenWeights(reviewers))}
                className="text-xs text-primary hover:underline disabled:opacity-50">
          {t('Spread evenly')}
        </button>
      </div>
      {reviewers.length === 0 && (
        <p className="text-xs text-muted-foreground">{t('Tick the reviewers first.')}</p>
      )}
      <div className="grid gap-1.5 sm:grid-cols-2">
        {reviewers.map((uid) => (
          <label key={uid} className="flex items-center gap-2 text-sm text-muted-foreground">
            <Input type="number" min={0} max={100} step={1} disabled={disabled}
                   value={weights[String(uid)] ?? 0}
                   aria-label={t('Share of {{name}} (%)', { name: name(uid) })}
                   onChange={(e) => onWeights({ ...weights, [String(uid)]: Number(e.target.value) })}
                   className="h-7 w-20 px-2 text-xs" />
            <span className="truncate">{name(uid)}</span>
          </label>
        ))}
      </div>
      {reviewers.length > 0 && (
        <p className={cn('mt-1 text-xs tabular-nums', ok ? 'text-muted-foreground' : 'text-destructive')}
           aria-live="polite">
          {t('Total: {{total}} %', { total })}
          {!ok && <> — {t('the shares must add up to 100 %')}</>}
        </p>
      )}
    </div>
  )
}

/** allocation = lead: the lead reviewer screens every record, the other
 * reviewers share the corpus (equal shares or declared %). */
export function LeadSettings({ members, reviewers, lead, onLead, weights, onWeights,
                               disabled }: {
  members: Member[]
  reviewers: number[]
  lead: number | null
  onLead: (uid: number) => void
  weights: Record<string, number>
  onWeights: (w: Record<string, number>) => void
  disabled: boolean
}) {
  const { t } = useTranslation()
  const name = (uid: number) => members.find((m) => m.user_id === uid)?.display_name ?? `#${uid}`
  const co = reviewers.filter((uid) => uid !== lead)
  return (
    <div className="ml-6 space-y-3 rounded-md border border-border p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <span>{t('Lead reviewer (screens every record)')}</span>
        <Select value={lead != null && reviewers.includes(lead) ? String(lead) : ''}
                disabled={disabled} onValueChange={(v) => onLead(Number(v))}>
          <SelectTrigger className="h-7 w-52 text-xs"
                         aria-label={t('Lead reviewer (screens every record)')}>
            <SelectValue placeholder={t('Pick a reviewer')} />
          </SelectTrigger>
          <SelectContent>
            {reviewers.map((uid) => (
              <SelectItem key={uid} value={String(uid)}>{name(uid)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {reviewers.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t('Tick the reviewers first.')}</p>
      ) : co.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          {t('Tick at least one other reviewer: they share the records between them, each one paired with the lead.')}
        </p>
      ) : co.length === 1 ? (
        <p className="text-xs text-muted-foreground">
          {t('With a single co-reviewer, both screen every record.')}
        </p>
      ) : (
        <WeightsEditor members={members} reviewers={co} weights={weights}
                       onWeights={onWeights} disabled={disabled}
                       label={t('Share of the co-reviewers (%)')} />
      )}
    </div>
  )
}

/** Effective share of the assignments per reviewer against the declared one. */
export function SharesCard({ shares, members, description }: {
  shares: Share[]
  members: Member[]
  description: string
}) {
  const { t } = useTranslation()
  const name = (uid: number) => members.find((m) => m.user_id === uid)?.display_name ?? `#${uid}`
  return (
    <Card className="p-4">
      <h3 className="mb-1 text-sm font-semibold text-foreground">{t('Share per reviewer')}</h3>
      <p className="mb-3 text-xs text-muted-foreground">{description}</p>
      <ul className="space-y-1.5">
        {shares.map((s) => (
          <li key={s.user_id} className="text-xs">
            <div className="mb-0.5 flex justify-between tabular-nums text-muted-foreground">
              <span className="font-medium text-foreground">{name(s.user_id)}</span>
              <span>{t('{{effective}} % (target {{target}} %) · {{count}} assignments',
                       { effective: s.effective_pct.toFixed(1), target: s.target_pct,
                         count: s.assigned })}</span>
            </div>
            <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div className="h-full bg-primary"
                   style={{ width: `${Math.min(s.effective_pct, 100)}%` }} />
            </div>
          </li>
        ))}
      </ul>
    </Card>
  )
}

// ---- preview before the start -------------------------------------------------------

/** One CSV cell: quoted, and defused when a spreadsheet would read it as a
 *  formula (same rule as the server's allocation.csv). */
function csvCell(value: string | number): string {
  let s = String(value)
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`
  return `"${s.replace(/"/g, '""')}"`
}

/** The edited plan as the allocation CSV the server publishes after the start
 *  (same columns), so it can be deposited with the protocol beforehand. */
function downloadPlanCsv(lots: LotPlan[], name: (uid: number) => string,
                         round: number) {
  const lines = [['Lot', 'Size', 'Reviewer A', 'Reviewer B', 'Due', 'Status']]
    .concat(lots.map((l) => [String(l.index), String(l.size), name(l.user_ids[0]),
                             name(l.user_ids[1]), (l.due_at ?? '').slice(0, 10),
                             'planned']))
    .map((row) => row.map(csvCell).join(','))
  const blob = new Blob(['﻿' + lines.join('\n') + '\n'],
                        { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `allocation_plan_r${round}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
}

export function LotPreview({ projectId, round, members, saveConfig, onStarted }: {
  projectId: number
  round: number
  members: Member[]
  /** saves the settings form first — the preview reads the saved config */
  saveConfig: () => Promise<unknown>
  onStarted: () => void
}) {
  const { t } = useTranslation()
  const [preview, setPreview] = useState<Preview | null>(null)
  const [lots, setLots] = useState<LotPlan[]>([])
  const [error, setError] = useState('')
  const name = (uid: number) => members.find((m) => m.user_id === uid)?.display_name ?? `#${uid}`
  const fail = (e: unknown, fallback: string) =>
    setError(e instanceof ApiError ? e.message : fallback)

  const load = useMutation({
    mutationFn: async () => {
      await saveConfig()
      return api.post<Preview>(
        `/api/projects/${projectId}/screening/lots/preview?round=${round}`)
    },
    onSuccess: (p) => { setPreview(p); setLots(p.lots); setError('') },
    onError: (e) => fail(e, t('Lot preview failed')),
  })
  const start = useMutation({
    mutationFn: () => api.post(
      `/api/projects/${projectId}/screening/start?round=${round}`, { lots }),
    onSuccess: () => { setError(''); onStarted() },
    onError: (e) => fail(e, t('Start failed')),
  })

  const setPair = (index: number, slot: 0 | 1, uid: number) =>
    setLots(lots.map((l) => l.index !== index ? l : {
      ...l, user_ids: slot === 0 ? [uid, l.user_ids[1]] : [l.user_ids[0], uid] }))
  const setDue = (index: number, value: string) =>
    setLots(lots.map((l) => l.index !== index ? l
      : { ...l, due_at: value ? `${value}T00:00:00Z` : null }))

  // effective share from the edited plan, so edits show their effect at once
  const counts: Record<number, number> = {}
  for (const l of lots) for (const u of l.user_ids) counts[u] = (counts[u] ?? 0) + l.size
  const totalAssigned = Object.values(counts).reduce((s, n) => s + n, 0)
  const reviewers = preview?.shares.map((s) => s.user_id) ?? []
  const invalid = lots.some((l) => l.user_ids[0] === l.user_ids[1])

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={() => load.mutate()} disabled={load.isPending}>
          {preview ? t('Recompute the lots') : t('Preview the lots')}
        </Button>
        {preview && (
          <Button onClick={() => start.mutate()} disabled={start.isPending || invalid}>
            {t('Start screening with these lots')}
          </Button>
        )}
        {preview && (
          <Button variant="outline" onClick={() => downloadPlanCsv(lots, name, round)}>
            ⬇ {t('Export the plan (CSV)')}
          </Button>
        )}
      </div>
      {preview && (
        <Card className="space-y-3 p-4">
          <p className="text-xs text-muted-foreground">
            {t('{{records}} records in {{lots}} lots of {{size}}. Change the pair of a lot or set its deadline, then start: the plan below is what gets published.',
               { records: preview.n_records, lots: lots.length, size: preview.lot_size })}
          </p>
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-muted-foreground">
            {preview.shares.map((s) => {
              const assigned = counts[s.user_id] ?? 0
              const pct = totalAssigned ? (100 * assigned) / totalAssigned : 0
              return (
                <li key={s.user_id}>
                  <span className="font-medium text-foreground">{name(s.user_id)}</span>
                  {' '}{t('{{effective}} % (target {{target}} %)',
                          { effective: pct.toFixed(0), target: s.target_pct })}
                </li>
              )
            })}
          </ul>
          <div className="max-h-96 overflow-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr>
                  <th className="px-2 py-1 text-left font-medium">{t('Lot')}</th>
                  <th className="px-2 py-1 text-right font-medium">{t('Size')}</th>
                  <th className="px-2 py-1 text-left font-medium">{t('Reviewer A')}</th>
                  <th className="px-2 py-1 text-left font-medium">{t('Reviewer B')}</th>
                  <th className="px-2 py-1 text-left font-medium">{t('Deadline')}</th>
                </tr>
              </thead>
              <tbody>
                {lots.map((l) => (
                  <tr key={l.index} className="border-t border-border">
                    <td className="px-2 py-1 tabular-nums">{l.index}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{l.size}</td>
                    {([0, 1] as const).map((slot) => (
                      <td key={slot} className="px-2 py-1">
                        <Select value={String(l.user_ids[slot])}
                                onValueChange={(v) => setPair(l.index, slot, Number(v))}>
                          <SelectTrigger className="h-7 min-w-28 text-xs"
                                         aria-label={slot === 0
                                           ? t('Reviewer A of lot {{index}}', { index: l.index })
                                           : t('Reviewer B of lot {{index}}', { index: l.index })}>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {reviewers.map((uid) => (
                              <SelectItem key={uid} value={String(uid)}>{name(uid)}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </td>
                    ))}
                    <td className="px-2 py-1">
                      <Input type="date" value={l.due_at ? l.due_at.slice(0, 10) : ''}
                             aria-label={t('Deadline of lot {{index}}', { index: l.index })}
                             onChange={(e) => setDue(l.index, e.target.value)}
                             className="h-7 w-36 px-2 text-xs" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {invalid && (
            <p className="text-xs text-destructive">{t('A lot needs two different reviewers.')}</p>
          )}
        </Card>
      )}
      {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
    </div>
  )
}

// ---- dashboard -----------------------------------------------------------------------

export function LotsDashboard({ projectId, round, stage, lots, shares, members }: {
  projectId: number
  round: number
  stage: 'ta' | 'ft'
  lots: LotRow[]
  shares: Share[]
  members: Member[]
}) {
  const { t } = useTranslation()
  const name = (uid: number) => members.find((m) => m.user_id === uid)?.display_name ?? `#${uid}`
  const today = new Date().toISOString().slice(0, 10)
  return (
    <>
      <SharesCard shares={shares} members={members}
                  description={t('Effective share of the assignments against the share declared in the settings. Late lots (snowballing, update passes) are counted.')} />
      <Card className="p-4">
        <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-foreground">
            {t('Lots ({{count}})', { count: lots.length })}
          </h3>
          <a className="text-xs text-primary hover:underline"
             href={`/api/projects/${projectId}/screening/allocation.csv?stage=${stage}&round=${round}`}>
            ⬇ {t('Allocation CSV')}
          </a>
        </div>
        <p className="mb-3 text-xs text-muted-foreground">
          {t('One line per lot: its pair, the progress of each reviewer, the deadline. The CSV is the allocation to deposit with the protocol.')}
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr>
                <th className="px-2 py-1 text-left font-medium">{t('Lot')}</th>
                <th className="px-2 py-1 text-right font-medium">{t('Size')}</th>
                <th className="px-2 py-1 text-left font-medium">{t('Pair')}</th>
                <th className="px-2 py-1 text-left font-medium">{t('Progress')}</th>
                <th className="px-2 py-1 text-left font-medium">{t('Deadline')}</th>
                <th className="px-2 py-1 text-left font-medium">{t('Status')}</th>
              </tr>
            </thead>
            <tbody>
              {lots.map((l) => {
                const late = l.status === 'open' && !!l.due_at && l.due_at.slice(0, 10) < today
                return (
                  <tr key={l.id} className="border-t border-border align-top">
                    <td className="px-2 py-1 tabular-nums">{l.index}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{l.size}</td>
                    <td className="px-2 py-1">{l.user_ids.map(name).join(' + ')}</td>
                    <td className="px-2 py-1">
                      {l.done.map((d) => (
                        <div key={d.user_id} className="flex items-center gap-2 text-xs tabular-nums">
                          <span className="w-24 truncate text-muted-foreground">{name(d.user_id)}</span>
                          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted"
                               title={`${d.done}/${l.size}`}>
                            <div className="h-full bg-primary"
                                 style={{ width: `${l.size ? (100 * d.done) / l.size : 0}%` }} />
                          </div>
                          <span>{d.done}/{l.size}</span>
                        </div>
                      ))}
                    </td>
                    <td className={cn('px-2 py-1 tabular-nums', late && 'text-warning')}>
                      {l.due_at ? l.due_at.slice(0, 10) : '—'}
                    </td>
                    <td className="px-2 py-1">
                      {l.status === 'closed' ? t('closed') : late ? t('late') : t('open')}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  )
}
