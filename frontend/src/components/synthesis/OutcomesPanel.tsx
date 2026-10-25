// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  api, ApiError, type SynthesisCatalogue, type SynthesisOutcomeInfo,
} from '@/api'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import CertaintyPanel from './CertaintyPanel'
import EffectsPanel from './EffectsPanel'

const API = (pid: number) => `/api/projects/${pid}/synthesis`

const BLANK = {
  label: '', comparison: '', intent: 'association', target: 'any_effect',
  thresholds_md: '', direction: 'unclear', metric: '', metric_rationale: '',
  synthesis_method: 'narrative', method_rationale: '', study_ids: [] as number[],
  finding_md: '',
}

/** One study of the included corpus (chantier 9: an article may report
 * several — `label` tells them apart when `n_studies` > 1). */
interface EligibleStudy {
  study_id: number
  record_id: number
  label: string
  n_studies: number
  title: string
  year: number | null
  design: string | null
}

const CERTAINTY_TONE: Record<string, string> = {
  high: 'border-success/40 bg-success/10 text-success',
  moderate: 'border-primary/40 bg-primary/10 text-primary',
  low: 'border-warning/40 bg-warning/10 text-warning',
  very_low: 'border-destructive/40 bg-destructive/10 text-destructive',
}

/** The reported results of the review, one row each.
 *
 * This is the object LitUbik never had. Before it, the included corpus was
 * structured by nothing but extraction columns, so there was no unit to
 * declare a synthesis method for and nothing to rate certainty *of* — GRADE
 * is per outcome, over the studies contributing to that outcome, not over the
 * corpus. */
export default function OutcomesPanel({ pid, isAdmin, catalogue, framework }: {
  pid: number
  isAdmin: boolean
  catalogue: SynthesisCatalogue | undefined
  framework: string
}) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState<number | 'new' | null>(null)
  const [certaintyFor, setCertaintyFor] = useState<number | null>(null)
  const [effectsFor, setEffectsFor] = useState<number | null>(null)
  const { data } = useQuery<{ outcomes: SynthesisOutcomeInfo[] }>({
    queryKey: ['synthesis-outcomes', pid],
    queryFn: () => api.get(`${API(pid)}/outcomes`),
  })
  const outcomes = data?.outcomes ?? []
  const outcomeWord = catalogue?.outcome_slot ?? 'Outcome'

  return (
    <div className="max-w-4xl space-y-4">
      <Card className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-foreground">
              {t('Reported results')}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {t('One row per result the review reports. Each carries the studies that contribute to it, the method used to synthesise them, and — if the project rates certainty — how certain the review is of it.')}
            </p>
          </div>
          {isAdmin && (
            <Button size="sm" variant="outline"
                    onClick={() => setEditing(editing === 'new' ? null : 'new')}>
              {t('Add a result')}
            </Button>
          )}
        </div>

        {outcomes.length === 0 && editing !== 'new' && (
          <p className="mt-3 text-sm text-muted-foreground">
            {t('No result declared yet.')}
          </p>
        )}

        <ul className="mt-3 space-y-2">
          {outcomes.map((o) => (
            <li key={o.id} className="rounded-md border border-border p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground">
                    {o.comparison && (
                      <span className="text-muted-foreground">{o.comparison} — </span>
                    )}
                    {o.label}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {t('{{count}} contributing study(ies)', { count: o.n_studies })}
                    {' · '}{t(o.synthesis_method_label)}
                    {o.metric && ` · ${o.metric}`}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    <span className="text-foreground">{t('Answers:')}</span>{' '}
                    {t(o.synthesis_method_question)}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  {o.certainty?.final ? (
                    <span className={cn('rounded border px-1.5 py-0.5 text-xs',
                      CERTAINTY_TONE[o.certainty.final] ?? '')}>
                      {t(o.certainty.label)}
                    </span>
                  ) : framework !== 'none' ? (
                    <span className="rounded border border-border px-1.5 py-0.5 text-xs text-muted-foreground">
                      {t('not rated')}
                    </span>
                  ) : null}
                  {framework !== 'none' && (
                    <Button size="sm" variant="outline"
                            className="h-6 px-2 text-xs"
                            onClick={() => setCertaintyFor(
                              certaintyFor === o.id ? null : o.id)}>
                      {t('Certainty')}
                    </Button>
                  )}
                  <Button size="sm" variant="outline"
                          className="h-6 px-2 text-xs"
                          aria-expanded={effectsFor === o.id}
                          title={t('Per-study effect sizes and the exports towards R/metafor or RevMan Web')}
                          onClick={() => setEffectsFor(effectsFor === o.id ? null : o.id)}>
                    {o.effect_spec?.measure ? `${t('Effect sizes')} · ${o.effect_spec.measure}` : t('Effect sizes')}
                  </Button>
                  {isAdmin && (
                    <Button size="sm" variant="outline"
                            className="h-6 px-2 text-xs"
                            onClick={() => setEditing(editing === o.id ? null : o.id)}>
                      {t('Edit')}
                    </Button>
                  )}
                </div>
              </div>

              {o.certainty?.statement_md && (
                <p className="mt-2 border-l-2 border-border pl-2 text-xs italic text-muted-foreground">
                  {o.certainty.statement_md}
                </p>
              )}

              {editing === o.id && (
                <OutcomeForm pid={pid} catalogue={catalogue} outcome={o}
                             onDone={() => setEditing(null)} />
              )}
              {certaintyFor === o.id && (
                <div className="mt-3 border-t border-border pt-3">
                  <CertaintyPanel pid={pid} outcomeId={o.id}
                                  catalogue={catalogue} />
                </div>
              )}
              {effectsFor === o.id && (
                <div className="mt-3 border-t border-border pt-3">
                  <EffectsPanel pid={pid} outcomeId={o.id} isAdmin={isAdmin} />
                </div>
              )}
            </li>
          ))}
        </ul>

        {editing === 'new' && (
          <OutcomeForm pid={pid} catalogue={catalogue} outcome={null}
                       onDone={() => setEditing(null)} />
        )}
      </Card>
      <p className="text-xs text-muted-foreground">
        {t('“{{word}}” is the word your question framework uses; change the framework in the project settings if it is not the right one.', { word: outcomeWord })}
      </p>
    </div>
  )
}


function OutcomeForm({ pid, catalogue, outcome, onDone }: {
  pid: number
  catalogue: SynthesisCatalogue | undefined
  outcome: SynthesisOutcomeInfo | null
  onDone: () => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [form, setForm] = useState({ ...BLANK })
  const [error, setError] = useState('')
  const { data: eligible } = useQuery<{ studies: EligibleStudy[] }>({
    queryKey: ['synthesis-eligible', pid],
    queryFn: () => api.get(`${API(pid)}/eligible-records`),
  })

  useEffect(() => {
    if (outcome) {
      setForm({
        label: outcome.label, comparison: outcome.comparison,
        intent: outcome.intent, target: outcome.target,
        thresholds_md: outcome.thresholds_md, direction: outcome.direction,
        metric: outcome.metric, metric_rationale: outcome.metric_rationale,
        synthesis_method: outcome.synthesis_method,
        method_rationale: outcome.method_rationale,
        study_ids: outcome.study_ids, finding_md: outcome.finding_md,
      })
    } else {
      setForm({ ...BLANK })
    }
  }, [outcome?.id])  // eslint-disable-line

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['synthesis-outcomes', pid] })
    queryClient.invalidateQueries({ queryKey: ['synthesis-sof', pid] })
  }
  const save = useMutation({
    mutationFn: () => outcome
      ? api.put(`${API(pid)}/outcomes/${outcome.id}`, form)
      : api.post(`${API(pid)}/outcomes`, form),
    onSuccess: () => { invalidate(); onDone() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const remove = useMutation({
    mutationFn: () => api.del(`${API(pid)}/outcomes/${outcome!.id}`),
    onSuccess: () => { invalidate(); onDone() },
  })

  const patch = (p: Partial<typeof BLANK>) => setForm({ ...form, ...p })
  const method = catalogue?.methods.find((m) => m.key === form.synthesis_method)
  const comparisonSlot = catalogue?.comparison_slot ?? ''
  const outcomeSlot = catalogue?.outcome_slot ?? 'Outcome'
  const toggleStudy = (id: number) => patch({
    study_ids: form.study_ids.includes(id)
      ? form.study_ids.filter((x) => x !== id)
      : [...form.study_ids, id],
  })

  return (
    <div className="mt-3 space-y-3 rounded-md border border-border bg-muted/40 p-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            {t(outcomeSlot)}
          </label>
          <Input value={form.label} onChange={(e) => patch({ label: e.target.value })} />
        </div>
        {/* SPIDER and PEO define no comparator; asking for one is how a tool
            teaches people to write "n/a" */}
        {comparisonSlot && (
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t(comparisonSlot)}
            </label>
            <Input value={form.comparison}
                   onChange={(e) => patch({ comparison: e.target.value })} />
          </div>
        )}
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium text-muted-foreground">
          <span className="mr-1.5 rounded bg-muted px-1 py-0.5 font-mono text-xs text-foreground">
            SWiM 3
          </span>
          {t('Synthesis method')}
        </label>
        <Select value={form.synthesis_method}
                onValueChange={(v) => patch({ synthesis_method: v })}>
          <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
          <SelectContent>
            {(catalogue?.methods ?? []).map((m) => (
              <SelectItem key={m.key} value={m.key}>{t(m.label)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {method && (
          <div className="mt-1.5 rounded-md border border-border bg-background p-2 text-xs">
            <p className="text-foreground">{t('This method answers:')}</p>
            <p className="mt-0.5 text-muted-foreground">{t(method.question)}</p>
            {method.minimum_data && (
              <p className="mt-1 text-muted-foreground">
                <span className="text-foreground">{t('Needs:')}</span>{' '}
                {t(method.minimum_data)}
              </p>
            )}
          </div>
        )}
        <Textarea className="mt-2" rows={2}
                  placeholder={t('Why this method — SWiM item 3 asks for the justification, not only the name')}
                  value={form.method_rationale}
                  onChange={(e) => patch({ method_rationale: e.target.value })} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            <span className="mr-1.5 rounded bg-muted px-1 py-0.5 font-mono text-xs text-foreground">
              SWiM 2
            </span>
            {t('Standardised metric')}
          </label>
          <Input value={form.metric} placeholder={t('Risk ratio, direction of effect…')}
                 onChange={(e) => patch({ metric: e.target.value })} />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            {t('Direction of the observed effect')}
          </label>
          <Select value={form.direction}
                  onValueChange={(v) => patch({ direction: v })}>
            <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              {(catalogue?.directions ?? []).map((d) => (
                <SelectItem key={d.key} value={d.key}>{t(d.label)}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <Textarea rows={2}
                placeholder={t('Why this metric, and how study results were converted to it')}
                value={form.metric_rationale}
                onChange={(e) => patch({ metric_rationale: e.target.value })} />

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            {t('Intent of the question (GRADE step 1)')}
          </label>
          <Select value={form.intent} onValueChange={(v) => patch({ intent: v })}>
            <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              {(catalogue?.grade.intents ?? []).map((i) => (
                <SelectItem key={i.key} value={i.key}>{t(i.label)}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            {t('Target of the rating (GRADE step 2)')}
          </label>
          <Select value={form.target} onValueChange={(v) => patch({ target: v })}>
            <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              {(catalogue?.grade.targets ?? []).map((x) => (
                <SelectItem key={x.key} value={x.key}>{t(x.label)}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <Textarea rows={2}
                placeholder={t('The thresholds you pre-specified, and what justifies them — GRADE asks for these before the rating, not after it')}
                value={form.thresholds_md}
                onChange={(e) => patch({ thresholds_md: e.target.value })} />

      <div>
        <label className="mb-1 block text-xs font-medium text-muted-foreground">
          {t('What the synthesis found')}
        </label>
        <Textarea rows={2} value={form.finding_md}
                  onChange={(e) => patch({ finding_md: e.target.value })} />
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium text-muted-foreground">
          {t('Contributing studies ({{n}} selected)', { n: form.study_ids.length })}
        </label>
        <p className="mb-1.5 text-xs text-muted-foreground">
          {t('Certainty is rated over these studies alone, not over the whole corpus — a review commonly has six studies behind one result and fourteen behind another.')}
        </p>
        <div className="max-h-56 space-y-1 overflow-y-auto rounded-md border border-border bg-background p-2">
          {(eligible?.studies ?? []).map((s) => (
            <button key={s.study_id} type="button"
                    onClick={() => toggleStudy(s.study_id)}
                    className={cn('block w-full rounded border px-2 py-1 text-left text-xs',
                      form.study_ids.includes(s.study_id)
                        ? 'border-foreground bg-accent text-foreground'
                        : 'border-transparent text-muted-foreground hover:bg-accent')}>
              {s.title.slice(0, 90)}{s.title.length > 90 ? '…' : ''}
              {s.year ? ` (${s.year})` : ''}
              {s.n_studies > 1 && <span className="font-medium"> – {s.label}</span>}
            </button>
          ))}
        </div>
      </div>

      <div className="flex gap-2">
        <Button size="sm" disabled={save.isPending || !form.label.trim()}
                onClick={() => save.mutate()}>
          {save.isPending ? t('Saving…') : t('Save')}
        </Button>
        <Button size="sm" variant="outline" onClick={onDone}>{t('Cancel')}</Button>
        {outcome && (
          <Button size="sm" variant="outline" onClick={() => remove.mutate()}>
            {t('Delete')}
          </Button>
        )}
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  )
}
