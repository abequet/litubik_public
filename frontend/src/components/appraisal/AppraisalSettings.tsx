// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError } from '@/api'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'

const API = (pid: number) => `/api/projects/${pid}/appraisal`

interface AppraisalConfig {
  status: 'draft' | 'active'
  instrument: string
  instrument_label: string
  n_assessors: number
  assessor_ids: number[]
  conflict_scope: 'overall' | 'per_question'
  conflict_resolution: 'consensus' | 'arbiter'
  dual: boolean
}

interface InstrumentInfo {
  key: string
  label: string
  citation: string
  url: string
  builtin: boolean
  overall: boolean
  score: boolean
  designs: string[]
  checklists: {
    key: string
    label: string
    options: string[]
    domains: { label: string; questions: { id: string; text: string }[] }[]
  }[]
}

interface Catalogue {
  instruments: InstrumentInfo[]
  designs: { key: string; label: string }[]
  option_sets: Record<string, string[]>
}

/** Which instrument the project appraises with, and whether two assessors are
 * required. Off by default: a project that never opens this tab keeps the
 * historical behaviour — any member appraises, no disagreement is computed. */
export default function AppraisalSettings({ pid, members, disabled }: {
  pid: number
  members: { user_id: number; display_name: string }[]
  disabled: boolean
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: config } = useQuery<AppraisalConfig>({
    queryKey: ['appraisal-config', pid],
    queryFn: () => api.get(`${API(pid)}/config`),
  })
  const { data: catalogue } = useQuery<Catalogue>({
    queryKey: ['appraisal-instruments', pid],
    queryFn: () => api.get(`${API(pid)}/instruments`),
  })

  const [form, setForm] = useState<AppraisalConfig | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { if (config) setForm(config) }, [config])

  const save = useMutation({
    mutationFn: (next: AppraisalConfig) => api.put(`${API(pid)}/config`, {
      status: next.status, instrument: next.instrument,
      n_assessors: next.n_assessors, assessor_ids: next.assessor_ids,
      conflict_scope: next.conflict_scope,
      conflict_resolution: next.conflict_resolution,
    }),
    onSuccess: () => {
      setError('')
      queryClient.invalidateQueries({ queryKey: ['appraisal-config', pid] })
      queryClient.invalidateQueries({ queryKey: ['jbi-checklists', pid] })
      queryClient.invalidateQueries({ queryKey: ['results', pid] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })

  if (!form || !catalogue) {
    return <p className="text-sm text-muted-foreground">{t('Loading…')}</p>
  }
  const patch = (p: Partial<AppraisalConfig>) => setForm({ ...form, ...p })
  const toggleAssessor = (id: number) => patch({
    assessor_ids: form.assessor_ids.includes(id)
      ? form.assessor_ids.filter((x) => x !== id)
      : [...form.assessor_ids, id],
  })

  return (
    <div className="max-w-3xl space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-semibold text-foreground">
          {t('How studies are appraised')}
        </h2>
        <p className="mt-1 mb-3 text-sm text-muted-foreground">
          {t('Left off, any member appraises any study and nothing is compared — the way LitUbik has always worked. Turned on, this makes appraisal a two-assessor process with a recorded disagreement, which is what editors look for.')}
        </p>

        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t('Appraisal process')}
            </label>
            <Select value={form.status} disabled={disabled}
                    onValueChange={(v) => patch({ status: v as 'draft' | 'active' })}>
              <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="draft">{t('Off — anyone appraises, nothing compared')}</SelectItem>
                <SelectItem value="active">{t('On — named assessors, disagreements tracked')}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t('Instrument')}
            </label>
            <Select value={form.instrument} disabled={disabled}
                    onValueChange={(v) => patch({ instrument: v })}>
              <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
              <SelectContent>
                {catalogue.instruments.map((i) => (
                  <SelectItem key={i.key} value={i.key}>
                    {i.builtin ? t(i.label) : i.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="mt-1 text-xs text-muted-foreground">
              {t('LitUbik ships the JBI checklists and the MMAT 2018, two tools whose terms allow it. Redistributing another organisation’s appraisal tool is a licensing decision, so a team using any other declares its own instrument below.')}
            </p>
            {(() => {
              const chosen = catalogue.instruments.find((i) => i.key === form.instrument)
              if (!chosen) return null
              const covered = chosen.designs.map((d) => t(
                catalogue.designs.find((x) => x.key === d)?.label ?? d)).join(', ')
              return (
                <p className="mt-1 text-xs text-muted-foreground">
                  {t('Covers: {{designs}}.', { designs: covered })}{' '}
                  {chosen.overall
                    ? t('Each appraisal ends with an overall include/exclude judgement.')
                    : t('No overall judgement and no score: each criterion is reported on its own, as the tool requires.')}
                </p>
              )
            })()}
          </div>

          {form.status === 'active' && (
            <>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">
                  {t('Assessors per study')}
                </label>
                <Select value={String(form.n_assessors)} disabled={disabled}
                        onValueChange={(v) => patch({ n_assessors: Number(v) })}>
                  <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1">{t('1 — one assessor per study')}</SelectItem>
                    <SelectItem value="2">{t('2 — independent duplicate appraisal')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">
                  {t('Who appraises')}
                </label>
                <div className="flex flex-wrap gap-1.5">
                  {members.map((m) => (
                    <button key={m.user_id} type="button" disabled={disabled}
                            onClick={() => toggleAssessor(m.user_id)}
                            className={cn('rounded border px-2 py-1 text-xs',
                              form.assessor_ids.includes(m.user_id)
                                ? 'border-foreground bg-accent text-foreground'
                                : 'border-border text-muted-foreground hover:bg-accent')}>
                      {m.display_name}
                    </button>
                  ))}
                </div>
              </div>

              {form.n_assessors >= 2 && (
                <>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-muted-foreground">
                      {t('What counts as a disagreement')}
                    </label>
                    <Select value={form.conflict_scope} disabled={disabled}
                            onValueChange={(v) => patch({
                              conflict_scope: v as 'overall' | 'per_question' })}>
                      <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="overall">{t('The overall judgement only')}</SelectItem>
                        <SelectItem value="per_question">{t('Any individual question')}</SelectItem>
                      </SelectContent>
                    </Select>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {t('Per question is stricter and much noisier: two assessors routinely differ on one item while agreeing on the study.')}
                    </p>
                  </div>

                  <div>
                    <label className="mb-1 block text-xs font-medium text-muted-foreground">
                      {t('Who settles it')}
                    </label>
                    <Select value={form.conflict_resolution} disabled={disabled}
                            onValueChange={(v) => patch({
                              conflict_resolution: v as 'consensus' | 'arbiter' })}>
                      <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="consensus">{t('Consensus — the assessors themselves')}</SelectItem>
                        <SelectItem value="arbiter">{t('Arbiter — a project admin')}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </>
              )}
            </>
          )}
        </div>

        {!disabled && (
          <Button className="mt-4" size="sm" disabled={save.isPending}
                  onClick={() => save.mutate(form)}>
            {save.isPending ? t('Saving…') : t('Save changes')}
          </Button>
        )}
        {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
      </Card>

      <InstrumentBuilder pid={pid} catalogue={catalogue} disabled={disabled}
                         inUse={form.instrument} />
    </div>
  )
}

// ---- declaring an instrument ------------------------------------------------

/** One design's checklist, in the shape the builder edits: a flat text area
 * per domain. Writing questions as lines is deliberately low-ceremony — the
 * alternative (a nested form with add/remove buttons at three levels) makes
 * transcribing a published checklist slower than retyping it. */
interface DraftDomain {
  label: string
  questions: string
}

function InstrumentBuilder({ pid, catalogue, disabled, inUse }: {
  pid: number
  catalogue: Catalogue
  disabled: boolean
  inUse: string
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<string | null>(null)
  const [key, setKey] = useState('')
  const [label, setLabel] = useState('')
  const [citation, setCitation] = useState('')
  const [url, setUrl] = useState('')
  const [design, setDesign] = useState('other')
  const [options, setOptions] = useState('ynun')
  const [domains, setDomains] = useState<DraftDomain[]>([{ label: '', questions: '' }])
  const [error, setError] = useState('')

  const custom = catalogue.instruments.filter((i) => !i.builtin)

  const reset = () => {
    setEditing(null); setKey(''); setLabel(''); setCitation(''); setUrl('')
    setDesign('other'); setOptions('ynun')
    setDomains([{ label: '', questions: '' }]); setError('')
  }

  const load = (inst: InstrumentInfo) => {
    const checklist = inst.checklists[0]
    setEditing(inst.key); setKey(inst.key); setLabel(inst.label)
    setCitation(inst.citation); setUrl(inst.url)
    setDesign(checklist?.key ?? 'other')
    setOptions(checklist && checklist.options.length === 3 ? 'ynu' : 'ynun')
    setDomains((checklist?.domains ?? []).map((d) => ({
      label: d.label, questions: d.questions.map((q) => q.text).join('\n'),
    })))
    setError('')
  }

  const save = useMutation({
    mutationFn: () => {
      // ids are generated from position and never reused across a rename:
      // an answer is stored under its question id, so a stable id is what
      // keeps an already-filled appraisal attached to its question
      let n = 0
      const payloadDomains = domains
        .map((d) => ({
          label: d.label.trim(),
          questions: d.questions.split('\n').map((line) => line.trim())
            .filter(Boolean)
            .map((text) => ({ id: `q${++n}`, text })),
        }))
        .filter((d) => d.questions.length > 0)
      return api.put(`${API(pid)}/instruments/${key.trim()}`, {
        key: key.trim(), label, citation, url,
        checklists: { [design]: { options, domains: payloadDomains } },
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['appraisal-instruments', pid] })
      queryClient.invalidateQueries({ queryKey: ['jbi-checklists', pid] })
      reset()
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })

  const remove = useMutation({
    mutationFn: (k: string) => api.del(`${API(pid)}/instruments/${k}`),
    onSuccess: () => queryClient.invalidateQueries({
      queryKey: ['appraisal-instruments', pid] }),
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Delete failed')),
  })

  return (
    <Card className="p-4">
      <h2 className="text-sm font-semibold text-foreground">
        {t('Instruments declared by this project')}
      </h2>
      <p className="mt-1 mb-3 text-sm text-muted-foreground">
        {t('One checklist per study design, its questions grouped in domains. Write the instrument your field actually uses — the appraisal form, the per-domain chart and the Methods draft all read it the same way they read JBI.')}
      </p>

      {custom.length > 0 && (
        <ul className="mb-3 space-y-1">
          {custom.map((i) => (
            <li key={i.key}
                className="flex items-center justify-between rounded-md border border-border px-2 py-1.5 text-xs">
              <span>
                <span className="font-medium text-foreground">{i.label}</span>
                <span className="text-muted-foreground">
                  {' · '}{i.designs.map((d) => t(
                    catalogue.designs.find((x) => x.key === d)?.label ?? d)).join(', ')}
                  {i.key === inUse && ` · ${t('in use')}`}
                </span>
              </span>
              {!disabled && (
                <span className="flex gap-1">
                  <Button size="sm" variant="outline" className="h-6 px-2 text-xs"
                          onClick={() => load(i)}>{t('Edit')}</Button>
                  <Button size="sm" variant="outline" className="h-6 px-2 text-xs"
                          onClick={() => remove.mutate(i.key)}>{t('Delete')}</Button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {disabled ? null : (
        <div className="space-y-3 rounded-md border border-border bg-muted/40 p-3">
          <p className="text-xs font-medium text-muted-foreground">
            {editing ? t('Editing “{{name}}”', { name: editing }) : t('New instrument')}
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                {t('Short key (lowercase, no spaces)')}
              </label>
              <Input value={key} disabled={!!editing}
                     onChange={(e) => setKey(e.target.value)} placeholder="lab-tool" />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                {t('Name')}
              </label>
              <Input value={label} onChange={(e) => setLabel(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                {t('Citation')}
              </label>
              <Input value={citation} onChange={(e) => setCitation(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                {t('URL')}
              </label>
              <Input type="url" value={url} onChange={(e) => setUrl(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                {t('For which study design')}
              </label>
              <Select value={design} onValueChange={setDesign}>
                <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {catalogue.designs.map((d) => (
                    <SelectItem key={d.key} value={d.key}>{t(d.label)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                {t('Answer options')}
              </label>
              <Select value={options} onValueChange={setOptions}>
                <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="ynu">{t('yes / no / unclear')}</SelectItem>
                  <SelectItem value="ynun">{t('yes / no / unclear / n-a')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {domains.map((d, i) => (
            <div key={i} className="rounded-md border border-border bg-background p-2">
              <Input value={d.label} placeholder={t('Domain name (leave empty for a flat checklist)')}
                     onChange={(e) => setDomains(domains.map((x, j) =>
                       j === i ? { ...x, label: e.target.value } : x))} />
              <Textarea className="mt-2" rows={4}
                        placeholder={t('One question per line')}
                        value={d.questions}
                        onChange={(e) => setDomains(domains.map((x, j) =>
                          j === i ? { ...x, questions: e.target.value } : x))} />
            </div>
          ))}
          <Button size="sm" variant="outline"
                  onClick={() => setDomains([...domains, { label: '', questions: '' }])}>
            {t('Add a domain')}
          </Button>

          <div className="flex gap-2">
            <Button size="sm" disabled={save.isPending || !key.trim() || !label.trim()}
                    onClick={() => save.mutate()}>
              {save.isPending ? t('Saving…') : t('Save instrument')}
            </Button>
            {editing && (
              <Button size="sm" variant="outline" onClick={reset}>{t('Cancel')}</Button>
            )}
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <p className="text-xs text-muted-foreground">
            {t('Editing an instrument renumbers its questions. Answers already recorded are keyed by question number, so reorder or rename with care once appraisals have started.')}
          </p>
        </div>
      )}
    </Card>
  )
}
