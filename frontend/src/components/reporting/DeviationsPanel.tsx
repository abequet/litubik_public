// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError } from '@/api'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'

const API = (pid: number) => `/api/projects/${pid}/reporting/deviations`

interface Signal {
  signal: string
  stage: string
  occurred_at: string | null
  summary: string
}

interface Deviation {
  id: number
  uuid: string
  stage: string
  stage_label: string
  kind: 'detected' | 'declared'
  signal: string | null
  summary: string
  rationale: string
  occurred_at: string | null
  dismissed: boolean
  dismiss_note: string
  declared_at: string | null
}

interface Register {
  signals: Signal[]
  deviations: Deviation[]
  stages: { key: string; label: string }[]
  n_undeclared_signals: number
}

const day = (iso: string | null) => (iso ? iso.slice(0, 10) : '')

/** Amendments to the planned methods — PRISMA item 24c, SWiM item 1b, and the
 * consistency check editorial triage runs on any review that references a
 * protocol.
 *
 * A detected signal is a question, never a verdict: amending a protocol is
 * legitimate, and the reason is the part only the team has. Nothing here is
 * promoted to a deviation without someone writing that reason. */
export default function DeviationsPanel({ pid }: { pid: number }) {
  const { t } = useTranslation()
  const { data } = useQuery<Register>({
    queryKey: ['deviations', pid],
    queryFn: () => api.get(API(pid)),
  })

  if (!data) return <p className="text-sm text-muted-foreground">{t('Loading…')}</p>

  return (
    <div className="max-w-3xl space-y-4">
      <p className="text-sm text-muted-foreground">
        {t('A review is allowed to change its mind — what a reader needs is the change and its reason. LitUbik flags what its own tables saw happen out of order; you say whether it was a deviation and why. Only what you declare reaches the Methods draft.')}
      </p>

      {data.signals.length > 0 && (
        <Card className="border-warning/40 p-4">
          <h2 className="text-sm font-semibold text-foreground">
            {t('{{count}} thing(s) the pipeline noticed', { count: data.signals.length })}
          </h2>
          <ul className="mt-3 space-y-3">
            {data.signals.map((s) => (
              <SignalCard key={s.signal} pid={pid} signal={s} stages={data.stages} />
            ))}
          </ul>
        </Card>
      )}

      <Card className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-foreground">
              {t('Declared amendments')}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {t('Including the ones no table could see — a regrouping decided in a meeting, a synthesis method abandoned.')}
            </p>
          </div>
          <NewDeviationButton pid={pid} stages={data.stages} />
        </div>

        {data.deviations.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">
            {t('Nothing declared. If the review followed its protocol throughout, say so in the Methods draft rather than leaving the question open.')}
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {data.deviations.map((d) => (
              <DeviationRow key={d.id} pid={pid} deviation={d}
                            stages={data.stages} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}


function SignalCard({ pid, signal, stages }: {
  pid: number
  signal: Signal
  stages: { key: string; label: string }[]
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<'idle' | 'declare' | 'dismiss'>('idle')
  const [text, setText] = useState('')
  const [error, setError] = useState('')

  const invalidate = () => queryClient.invalidateQueries({
    queryKey: ['deviations', pid] })
  const declare = useMutation({
    mutationFn: () => api.post(API(pid), {
      stage: signal.stage, signal: signal.signal, summary: signal.summary,
      rationale: text, occurred_at: signal.occurred_at }),
    onSuccess: invalidate,
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const dismiss = useMutation({
    mutationFn: () => api.post(`${API(pid)}/dismiss`, {
      signal: signal.signal, summary: signal.summary, note: text,
      occurred_at: signal.occurred_at }),
    onSuccess: invalidate,
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })

  const stage = stages.find((s) => s.key === signal.stage)
  return (
    <li className="rounded-md border border-border p-3">
      <p className="text-xs text-muted-foreground">
        {t(stage?.label ?? signal.stage)}
        {signal.occurred_at && ` · ${day(signal.occurred_at)}`}
      </p>
      <p className="mt-1 text-sm text-foreground">{signal.summary}</p>

      {mode === 'idle' ? (
        <div className="mt-2 flex gap-2">
          <Button size="sm" onClick={() => { setMode('declare'); setText('') }}>
            {t('It was a change — explain why')}
          </Button>
          <Button size="sm" variant="outline"
                  onClick={() => { setMode('dismiss'); setText('') }}>
            {t('It was not a change')}
          </Button>
        </div>
      ) : (
        <div className="mt-2 space-y-2">
          <Textarea rows={2} value={text}
                    placeholder={mode === 'declare'
                      ? t('Why the methods changed. A change reported without its reason reads as one the findings drove.')
                      : t('Why this is not a deviation — recorded so nobody re-litigates it later.')}
                    onChange={(e) => setText(e.target.value)} />
          <div className="flex gap-2">
            <Button size="sm"
                    disabled={declare.isPending || dismiss.isPending}
                    onClick={() => (mode === 'declare' ? declare : dismiss).mutate()}>
              {t('Record')}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setMode('idle')}>
              {t('Cancel')}
            </Button>
          </div>
        </div>
      )}
      {error && <p className="mt-1 text-sm text-destructive">{error}</p>}
    </li>
  )
}


function NewDeviationButton({ pid, stages }: {
  pid: number
  stages: { key: string; label: string }[]
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [stage, setStage] = useState('protocol')
  const [summary, setSummary] = useState('')
  const [rationale, setRationale] = useState('')

  const save = useMutation({
    mutationFn: () => api.post(API(pid), { stage, summary, rationale }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deviations', pid] })
      setOpen(false); setSummary(''); setRationale('')
    },
  })

  if (!open) {
    return (
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        {t('Declare an amendment')}
      </Button>
    )
  }
  return (
    <div className="w-full space-y-2 rounded-md border border-border bg-muted/40 p-3">
      <Select value={stage} onValueChange={setStage}>
        <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
        <SelectContent>
          {stages.map((s) => (
            <SelectItem key={s.key} value={s.key}>{t(s.label)}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Textarea rows={2} value={summary} placeholder={t('What changed')}
                onChange={(e) => setSummary(e.target.value)} />
      <Textarea rows={2} value={rationale} placeholder={t('Why')}
                onChange={(e) => setRationale(e.target.value)} />
      <div className="flex gap-2">
        <Button size="sm" disabled={!summary.trim() || save.isPending}
                onClick={() => save.mutate()}>{t('Record')}</Button>
        <Button size="sm" variant="outline" onClick={() => setOpen(false)}>
          {t('Cancel')}
        </Button>
      </div>
    </div>
  )
}


function DeviationRow({ pid, deviation, stages }: {
  pid: number
  deviation: Deviation
  stages: { key: string; label: string }[]
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [summary, setSummary] = useState(deviation.summary)
  const [rationale, setRationale] = useState(deviation.rationale)

  const invalidate = () => queryClient.invalidateQueries({
    queryKey: ['deviations', pid] })
  const save = useMutation({
    mutationFn: () => api.put(`${API(pid)}/${deviation.id}`, {
      stage: deviation.stage, summary, rationale }),
    onSuccess: () => { invalidate(); setEditing(false) },
  })
  const remove = useMutation({
    mutationFn: () => api.del(`${API(pid)}/${deviation.id}`),
    onSuccess: invalidate,
  })

  return (
    <li className="rounded-md border border-border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          {t(stages.find((s) => s.key === deviation.stage)?.label ?? deviation.stage)}
          {deviation.occurred_at && ` · ${day(deviation.occurred_at)}`}
          {deviation.dismissed && ` · ${t('not a deviation')}`}
          {deviation.kind === 'detected' && !deviation.dismissed
            && ` · ${t('spotted by the pipeline')}`}
        </p>
        <div className="flex gap-1">
          {!deviation.dismissed && (
            <Button size="sm" variant="outline" className="h-6 px-2 text-xs"
                    onClick={() => setEditing(!editing)}>{t('Edit')}</Button>
          )}
          <Button size="sm" variant="outline" className="h-6 px-2 text-xs"
                  onClick={() => remove.mutate()}>{t('Delete')}</Button>
        </div>
      </div>

      {editing ? (
        <div className="mt-2 space-y-2">
          <Textarea rows={2} value={summary}
                    onChange={(e) => setSummary(e.target.value)} />
          <Textarea rows={2} value={rationale} placeholder={t('Why')}
                    onChange={(e) => setRationale(e.target.value)} />
          <Button size="sm" onClick={() => save.mutate()}>{t('Save')}</Button>
        </div>
      ) : (
        <>
          <p className="mt-1 text-sm text-foreground">{deviation.summary}</p>
          {deviation.dismissed ? (
            <p className="mt-1 text-xs italic text-muted-foreground">
              {deviation.dismiss_note}
            </p>
          ) : deviation.rationale ? (
            <p className="mt-1 text-xs text-muted-foreground">
              <span className="text-foreground">{t('Why:')}</span>{' '}
              {deviation.rationale}
            </p>
          ) : (
            <p className="mt-1 text-xs text-warning">
              {t('No reason recorded — the Methods draft will report the change without one.')}
            </p>
          )}
        </>
      )}
    </li>
  )
}
