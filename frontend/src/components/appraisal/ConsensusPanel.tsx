// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError } from '@/api'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

const API = (pid: number) => `/api/projects/${pid}/appraisal`

interface ConflictRow {
  record_id: number
  study_id: number
  study_label: string
  n_studies: number
  title: string
  year: number | null
  design: string | null
  conflicts: string[]
}

interface AppraisalView {
  user_id: number
  user: string
  design: string
  answers: Record<string, { answer: string; comment: string }>
  overall: string
  comment: string
}

interface ConsensusView {
  record_id: number
  title: string
  design: string | null
  instrument: { key: string; label: string; builtin: boolean
                overall: boolean; score: boolean }
  checklist: {
    key: string
    options: string[]
    option_labels?: Record<string, string>
    domains: { label: string; questions: { id: string; text: string }[] }[]
  } | null
  conflicts: string[]
  appraisals: AppraisalView[]
  consensus: {
    answers: Record<string, { answer: string; comment: string }>
    overall: string
    comment: string
    resolved_by: string
    resolved_at: string
  } | null
  can_resolve: boolean
}

const OVERALL_LABELS: Record<string, string> = {
  include: '✓ Include', exclude: '✗ Exclude', seek_info: '? Seek further info',
}

/** The disagreements two assessors left behind, and the appraisal they settle
 * on. Nothing here edits what either of them said: the individual appraisals
 * stay side by side above the form, because a reader of the review is entitled
 * to know the two did not agree. */
export default function ConsensusPanel({ pid }: { pid: number }) {
  const { t } = useTranslation()
  const [selected, setSelected] = useState<ConflictRow | null>(null)
  const { data } = useQuery<{ dual: boolean; conflicts: ConflictRow[] }>({
    queryKey: ['appraisal-conflicts', pid],
    queryFn: () => api.get(`${API(pid)}/conflicts`),
  })

  if (!data?.dual) {
    return (
      <p className="text-sm text-muted-foreground">
        {t('This project appraises with a single assessor, so there is no disagreement to settle. Two independent assessors can be required in the project settings, under Appraisal.')}
      </p>
    )
  }
  const rows = data.conflicts

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[22rem_1fr]">
      <Card className="max-h-[75vh] overflow-y-auto p-3">
        <p className="mb-2 text-xs font-medium text-muted-foreground">
          {rows.length === 0
            ? t('No open disagreement')
            : t('{{count}} study(ies) where the assessors disagree', { count: rows.length })}
        </p>
        <ul className="space-y-1">
          {rows.map((r) => (
            <li key={r.study_id}>
              <button onClick={() => setSelected(r)}
                      className={cn('w-full rounded-md border px-2 py-1.5 text-left text-xs',
                        selected?.study_id === r.study_id
                          ? 'border-border bg-accent'
                          : 'border-transparent hover:bg-accent')}>
                <p className="leading-snug text-foreground">
                  {r.title.slice(0, 80)}{r.title.length > 80 ? '…' : ''}
                  {r.n_studies > 1 && <span className="font-medium"> – {r.study_label}</span>}
                </p>
                <p className="text-xs text-muted-foreground">
                  {r.conflicts.includes('overall')
                    ? t('overall judgement')
                    : t('{{count}} question(s)', { count: r.conflicts.length })}
                </p>
              </button>
            </li>
          ))}
        </ul>
      </Card>
      {selected === null ? (
        <p className="py-10 text-center text-sm text-muted-foreground">
          {rows.length === 0
            ? t('Every appraised study is either agreed on or already settled.')
            : t('Pick a study on the left to compare the two appraisals.')}
        </p>
      ) : (
        <ConsensusForm key={selected.study_id} pid={pid}
                       recordId={selected.record_id} studyId={selected.study_id} />
      )}
    </div>
  )
}

function ConsensusForm({ pid, recordId, studyId }: {
  pid: number
  recordId: number
  studyId: number
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data } = useQuery<ConsensusView>({
    queryKey: ['appraisal-consensus', pid, studyId],
    queryFn: () => api.get(`${API(pid)}/records/${recordId}/consensus?study_id=${studyId}`),
  })
  const [answers, setAnswers] = useState<Record<string, { answer: string; comment: string }>>({})
  const [overall, setOverall] = useState('')
  const [comment, setComment] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!data) return
    setAnswers(data.consensus?.answers ?? {})
    setOverall(data.consensus?.overall ?? '')
    setComment(data.consensus?.comment ?? '')
  }, [data])

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['appraisal-conflicts', pid] })
    queryClient.invalidateQueries({ queryKey: ['appraisal-consensus', pid, recordId] })
    queryClient.invalidateQueries({ queryKey: ['results', pid] })
  }
  const save = useMutation({
    mutationFn: () => api.put(`${API(pid)}/records/${recordId}/consensus?study_id=${studyId}`,
                              { answers, overall, comment }),
    onSuccess: () => { setError(''); invalidate() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const reopen = useMutation({
    mutationFn: () => api.del(`${API(pid)}/records/${recordId}/consensus?study_id=${studyId}`),
    onSuccess: invalidate,
  })

  if (!data) return <p className="text-sm text-muted-foreground">{t('Loading…')}</p>
  const questions = (data.checklist?.domains ?? [])
    .flatMap((d) => d.questions.map((q) => ({ ...q, domain: d.label })))
  const options = data.checklist?.options ?? []
  const disagrees = new Set(data.conflicts)
  // an answer in the instrument's own words (MMAT: unclear -> "Can't tell")
  const label = (o: string) => t(data.checklist?.option_labels?.[o] ?? o)
  const text = (s: string) => (data.instrument.builtin ? t(s) : s)

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-semibold text-foreground">{data.title}</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          {t('What each assessor concluded, kept as they wrote it:')}
        </p>
        <div className="mt-2 flex flex-wrap gap-3">
          {data.appraisals.map((a) => (
            <div key={a.user_id}
                 className="rounded-md border border-border px-3 py-2 text-xs">
              <p className="font-medium text-foreground">{a.user}</p>
              {data.instrument.overall && (
                <p className="text-muted-foreground">
                  {a.overall ? t(OVERALL_LABELS[a.overall] ?? a.overall) : t('no conclusion')}
                </p>
              )}
              {a.comment && <p className="mt-1 max-w-xs text-muted-foreground">{a.comment}</p>}
            </div>
          ))}
        </div>
      </Card>

      {!data.can_resolve && (
        <p className="rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
          {t('You cannot settle this one — the project reserves it for an arbiter.')}
        </p>
      )}

      <Card className="p-4">
        <h3 className="text-sm font-semibold text-foreground">
          {t('The appraisal you settle on')}
        </h3>
        <p className="mt-1 mb-3 text-xs text-muted-foreground">
          {t('This is what the results and the Summary of Findings will count. It replaces neither appraisal above.')}
        </p>
        <div className="space-y-3">
          {questions.map((q) => (
            <div key={q.id}
                 className={cn('rounded-md border p-2',
                   disagrees.has(q.id) ? 'border-warning/50 bg-warning/5' : 'border-border')}>
              <p className="text-xs text-foreground">
                {disagrees.has(q.id) && (
                  <span className="mr-1 font-medium text-warning">
                    {t('disagreed')}
                  </span>
                )}
                {text(q.text)}
              </p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {options.map((o) => (
                  <button key={o} type="button" disabled={!data.can_resolve}
                          onClick={() => setAnswers((a) => ({
                            ...a,
                            [q.id]: { answer: o, comment: a[q.id]?.comment ?? '' },
                          }))}
                          className={cn('rounded border px-2 py-0.5 text-xs',
                            answers[q.id]?.answer === o
                              ? 'border-foreground bg-accent text-foreground'
                              : 'border-border text-muted-foreground hover:bg-accent')}>
                    {label(o)}
                  </button>
                ))}
                {data.appraisals.map((a) => (
                  a.answers[q.id]?.answer ? (
                    <span key={a.user_id}
                          className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                      {a.user}: {label(a.answers[q.id].answer)}
                    </span>
                  ) : null
                ))}
              </div>
            </div>
          ))}
        </div>

        {data.instrument.overall && (
        <div className="mt-4">
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            {t('Overall')}
          </label>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(OVERALL_LABELS).map(([value, label]) => (
              <button key={value} type="button" disabled={!data.can_resolve}
                      onClick={() => setOverall(value)}
                      className={cn('rounded border px-2 py-1 text-xs',
                        overall === value
                          ? 'border-foreground bg-accent text-foreground'
                          : 'border-border text-muted-foreground hover:bg-accent')}>
                {t(label)}
              </button>
            ))}
          </div>
        </div>
        )}

        <div className="mt-3">
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            {t('How the disagreement was settled')}
          </label>
          <Textarea value={comment} disabled={!data.can_resolve}
                    onChange={(e) => setComment(e.target.value)} />
        </div>

        {data.can_resolve && (
          <div className="mt-3 flex items-center gap-2">
            <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
              {save.isPending ? t('Saving…') : t('Record this appraisal')}
            </Button>
            {data.consensus && (
              <Button size="sm" variant="outline" onClick={() => reopen.mutate()}>
                {t('Reopen')}
              </Button>
            )}
            {data.consensus && (
              <span className="text-xs text-muted-foreground">
                {t('Settled by {{name}}', { name: data.consensus.resolved_by })}
              </span>
            )}
          </div>
        )}
        {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
      </Card>
    </div>
  )
}
