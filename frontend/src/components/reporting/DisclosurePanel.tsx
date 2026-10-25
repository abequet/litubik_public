// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Sparkles } from 'lucide-react'
import {
  api, ApiError, type AiDossier, type CostInfo, type DisclosureForm,
  type ReportSectionInfo,
} from '@/api'
import { Button } from '../ui/button'
import { Card, CardContent } from '../ui/card'
import { Input } from '../ui/input'
import { Segmented } from '../ui/segmented'
import { Textarea } from '../ui/textarea'
import SectionOutput from './SectionOutput'

const LEVELS = ['none', 'low', 'medium', 'high'] as const
type Level = (typeof LEVELS)[number]

/** AI disclosure tab.
 *
 * The form comes first and the button second, on purpose: the structured
 * answers are what make a disclosure complete, and the phrasing is a separate
 * problem (Ahmetoglu et al., CHIWORK '26). Here the answers arrive
 * pre-filled from the project's AI-use journal, so the author checks and
 * corrects rather than remembers. */
export default function DisclosurePanel({ pid }: { pid: number }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const base = `/api/projects/${pid}/reporting`
  const [lang, setLang] = useState<'en' | 'fr'>('en')
  const [error, setError] = useState('')
  const [wantEstimate, setWantEstimate] = useState(false)
  const [form, setForm] = useState<DisclosureForm | null>(null)

  const { data: sections, isLoading } = useQuery<
    Record<string, ReportSectionInfo | null>>({
    queryKey: ['reporting-sections', pid],
    queryFn: () => api.get(`${base}/sections`),
  })
  const { data: dossier } = useQuery<AiDossier>({
    queryKey: ['reporting-ai-usage', pid],
    queryFn: () => api.get(`${base}/ai-usage`),
  })
  const { data: estimate } = useQuery<{ cost: CostInfo | null }>({
    queryKey: ['reporting-estimate', pid, 'ai_disclosure', lang],
    queryFn: () => api.get(`${base}/ai_disclosure/estimate?lang=${lang}`),
    enabled: wantEstimate,
    staleTime: 60_000,
  })

  const section = sections?.ai_disclosure ?? null

  // the form the author last generated with wins over the freshly pre-filled
  // one: their corrections must survive a page reload
  useEffect(() => {
    if (form !== null) return
    const stored = section?.form
    if (stored && 'activities' in stored) setForm(stored as DisclosureForm)
    else if (dossier) setForm(dossier.form)
  }, [dossier, section, form])

  const generate = useMutation({
    mutationFn: () =>
      api.post<ReportSectionInfo>(`${base}/ai_disclosure/generate`,
                                  { lang, form }),
    onSuccess: () => {
      setError('')
      queryClient.invalidateQueries({ queryKey: ['reporting-sections', pid] })
      queryClient.invalidateQueries({ queryKey: ['project-progress', pid] })
    },
    onError: (e) =>
      setError(e instanceof ApiError ? e.message : t('Generation failed')),
  })

  if (isLoading || !dossier || !form) {
    return <p className="text-muted-foreground">{t('Loading…')}</p>
  }
  const cost = estimate?.cost ?? null
  const setActivity = (key: string, patch: Partial<{ level: Level; note: string }>) =>
    setForm({ ...form,
              activities: form.activities.map((a) =>
                a.key === key ? { ...a, ...patch } : a) })

  const screening = dossier.evidence.screening
  const ext = dossier.evidence.extraction

  return (
    <div className="flex flex-col gap-4">
      {error && <p className="text-sm text-destructive">{error}</p>}

      <p className="max-w-3xl text-sm text-muted-foreground">
        {t('This statement covers the use of AI in conducting the review — searching, selection, appraisal, extraction, synthesis. It does not cover the writing of your manuscript, which does not happen here. The answers below are pre-filled from this project\'s AI-use journal: every call the app made is recorded, so you are correcting a record rather than reconstructing one from memory.')}
      </p>

      {dossier.journal.incomplete && (
        <p className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>
            {t('This project used AI before the AI-use journal existed, so the counts below start later than the actual use. Check every activity and correct the levels by hand before generating.')}
          </span>
        </p>
      )}

      {/* ---- the journal ------------------------------------------------- */}
      <Card>
        <CardContent className="py-4">
          <p className="mb-2.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {t('AI-use journal')}
          </p>
          {dossier.usage.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t('No AI call was made in this project. The statement will declare that no AI tools were used to conduct the review.')}
            </p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[34rem] text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs text-muted-foreground">
                      <th className="py-1.5 pr-3 font-medium">{t('AI helper')}</th>
                      <th className="py-1.5 pr-3 text-right font-medium">{t('Calls')}</th>
                      <th className="py-1.5 pr-3 font-medium">{t('Model')}</th>
                      <th className="py-1.5 pr-3 font-medium">{t('By')}</th>
                      <th className="py-1.5 text-right font-medium">{t('Cost')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dossier.usage.map((u) => (
                      <tr key={u.feature} className="border-b border-border/50">
                        <td className="py-1.5 pr-3">{t(u.label)}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">{u.n_calls}</td>
                        <td className="py-1.5 pr-3 text-xs text-muted-foreground">
                          {u.models.map((m) => m.model).join(', ')}
                        </td>
                        <td className="py-1.5 pr-3 text-xs text-muted-foreground">
                          {u.users.join(', ') || '—'}
                        </td>
                        <td className="py-1.5 text-right tabular-nums text-xs text-muted-foreground">
                          {u.cost_label}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {t('{{calls}} calls in total, {{cost}}, between {{from}} and {{to}}.',
                   { calls: dossier.totals.n_calls,
                     cost: dossier.totals.cost_label,
                     from: dossier.totals.first_at
                       ? new Date(dossier.totals.first_at).toLocaleDateString() : '?',
                     to: dossier.totals.last_at
                       ? new Date(dossier.totals.last_at).toLocaleDateString() : '?' })}
              </p>
            </>
          )}
        </CardContent>
      </Card>

      {/* ---- what humans did with it -------------------------------------- */}
      {dossier.usage.length > 0 && (
        <Card>
          <CardContent className="py-4">
            <p className="mb-2.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              {t('What the reviewers did with it')}
            </p>
            <ul className="flex flex-col gap-1 text-sm text-foreground">
              {Object.entries(screening).map(([stage, s]) => (
                s.n_ai_suggestions > 0 && (
                  <li key={stage}>
                    {stage === 'ft' ? t('Full-text screening') : t('Title/abstract screening')}:{' '}
                    {t('{{n}} AI suggestions, {{compared}} comparable with the final human decision — {{agreed}} agreed, {{overruled}} overruled.',
                       { n: s.n_ai_suggestions, compared: s.n_compared,
                         agreed: s.n_agreed, overruled: s.n_overruled })}
                    {s.reveal_modes?.includes('after_vote') && (
                      <>{' '}{t("Suggestions were shown after the vote; {{n}} vote(s) followed a reviewer's deliberate early look.",
                                { n: s.n_revealed_before_vote ?? 0 })}</>
                    )}
                  </li>
                )
              ))}
              {dossier.evidence.triage.n_validated_exclusions > 0 && (
                <li>
                  {t('Bulk title triage: {{n}} proposed exclusions were validated one by one by a reviewer.',
                     { n: dossier.evidence.triage.n_validated_exclusions })}
                </li>
              )}
              {ext.n_ai_cells > 0 && (
                <li>
                  {t('Extraction: {{n}} cells were AI-prefilled, {{validated}} of them validated by an extractor.',
                     { n: ext.n_ai_cells, validated: ext.n_ai_cells_validated })}
                </li>
              )}
              {dossier.evidence.protocol.ai_extracted && (
                <li>
                  {dossier.evidence.protocol.validated_by_human
                    ? t('Protocol: structured by AI, then validated by a human before any other stage used it.')
                    : t('Protocol: structured by AI, not yet validated by a human.')}
                </li>
              )}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* ---- the DAISY-style form ----------------------------------------- */}
      <Card>
        <CardContent className="py-4">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {t('Disclosure form')}
          </p>
          <p className="mb-3 text-xs text-muted-foreground">
            {t('Level of AI support per review activity, pre-answered from the journal. Adjust anything that does not match how you worked.')}
          </p>
          <div className="flex flex-col gap-3">
            {form.activities.map((a) => (
              <div key={a.key}
                   className="rounded-md border border-border px-3 py-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground">{t(a.label)}</p>
                    <p className="text-xs text-muted-foreground">
                      {a.n_calls > 0
                        ? t('{{n}} AI calls — {{features}}',
                            { n: a.n_calls,
                              features: a.features.map((f) => t(f)).join(', ') })
                        : t('no AI call recorded')}
                    </p>
                  </div>
                  <Segmented
                    size="sm"
                    value={a.level}
                    onChange={(v) => setActivity(a.key, { level: v })}
                    options={[
                      { value: 'none' as Level, label: t('None') },
                      { value: 'low' as Level, label: t('Low') },
                      { value: 'medium' as Level, label: t('Medium') },
                      { value: 'high' as Level, label: t('High') },
                    ]}
                  />
                </div>
                {a.level !== 'none' && (
                  <>
                    <Input
                      className="mt-2 h-8 text-xs"
                      placeholder={t('Optional: what the AI did and where (your words)')}
                      value={a.note}
                      onChange={(e) => setActivity(a.key, { note: e.target.value })}
                    />
                    <p className="mt-1.5 text-xs text-muted-foreground">
                      ↳ {t(a.control)}
                    </p>
                  </>
                )}
              </div>
            ))}
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <Field label={t('Tools and versions')}
                   value={form.tools.join(', ')}
                   onChange={(v) => setForm({ ...form,
                                              tools: v.split(',').map((s) => s.trim())
                                                .filter(Boolean) })} />
            <Field label={t('Material sent to the providers')}
                   value={form.inputs_shared.join('; ')}
                   onChange={(v) => setForm({ ...form,
                                              inputs_shared: v.split(';').map((s) => s.trim())
                                                .filter(Boolean) })} />
          </div>
          <div className="mt-3 flex flex-col gap-3">
            <div>
              <label className="text-xs text-muted-foreground">
                {t('Safeguards you applied (provider settings, training opt-out, data retention…)')}
              </label>
              <Textarea rows={2} value={form.safeguards}
                        placeholder={t('The app cannot know this — describe what you configured on the provider side, or leave empty.')}
                        onChange={(e) => setForm({ ...form, safeguards: e.target.value })} />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">
                {t('Anything to add about human validation')}
              </label>
              <Textarea rows={2} value={form.human_validation_note}
                        onChange={(e) => setForm({ ...form,
                                                   human_validation_note: e.target.value })} />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">
                {t('Authorship boundary')}
              </label>
              <Textarea rows={2} value={form.authorship}
                        onChange={(e) => setForm({ ...form, authorship: e.target.value })} />
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm text-muted-foreground">{t('Language')}</span>
        <Segmented
          value={lang}
          onChange={(v) => setLang(v)}
          options={[{ value: 'en' as const, label: 'English' },
                    { value: 'fr' as const, label: 'Français' }]}
        />
        <Button
          onClick={() => generate.mutate()}
          onMouseEnter={() => setWantEstimate(true)}
          disabled={generate.isPending}
          title={cost
            ? t('Estimated ≈ {{cost}} ({{model}})',
                { cost: cost.cost_label, model: cost.model })
            : t('Generate with the configured AI provider')}
          className="gap-1.5"
        >
          <Sparkles className="size-4" />
          {generate.isPending
            ? t('Generating…')
            : section ? t('Regenerate from the form') : t('Generate the disclosure statement')}
          {cost && !generate.isPending && (
            <span className="text-xs opacity-70">≈{cost.cost_label}</span>
          )}
        </Button>
      </div>

      {section
        ? <SectionOutput pid={pid} kind="ai_disclosure" section={section} />
        : (
          <Card>
            <CardContent className="py-8 text-sm text-muted-foreground">
              {t('Nothing generated yet.')}
            </CardContent>
          </Card>
        )}

      <p className="max-w-3xl text-xs text-muted-foreground">
        {t('The structure of this form — activities, level of support, tools, material shared, human validation, authorship boundary, and an editable generated statement — follows DAISY:')}{' '}
        <span className="italic">
          Ahmetoglu, Y., Constantinides, M., &amp; Cox, A. (2026). AI Disclosure
          with DAISY. <span className="not-italic">CHIWORK ’26</span>.
        </span>{' '}
        <a href="https://doi.org/10.1145/3808045.3808056" target="_blank"
           rel="noreferrer" className="underline underline-offset-2">
          doi:10.1145/3808045.3808056
        </a>{' '}
        {t('Their study found that structured disclosure produced more complete statements without making authors less comfortable with them, and that authors preferred generated statements they could edit — which is why the form is filled in first and the text stays yours to rewrite.')}
      </p>
    </div>
  )
}

function Field({ label, value, onChange }: {
  label: string; value: string; onChange: (v: string) => void
}) {
  return (
    <div>
      <label className="text-xs text-muted-foreground">{label}</label>
      <Input className="h-8 text-xs" value={value}
             onChange={(e) => onChange(e.target.value)} />
    </div>
  )
}
