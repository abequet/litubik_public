// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  api, ApiError, type CertaintyView, type SynthesisCatalogue,
} from '@/api'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

const API = (pid: number) => `/api/projects/${pid}/synthesis`

type Draft = {
  starting_point: string
  starting_rationale: string
  domains: Record<string, { judgement: string; note: string }>
  upgrades: Record<string, { applied: boolean; note: string }>
  final: string
  statement_md: string
}

const EMPTY: Draft = {
  starting_point: 'low', starting_rationale: '', domains: {}, upgrades: {},
  final: '', statement_md: '',
}

/** The five GRADE steps for one outcome.
 *
 * The app's job here is to put the evidence for each judgement in front of the
 * assessor — the designs behind the starting point, the appraisals behind risk
 * of bias, the search behind publication bias — and then get out of the way.
 * It proposes a level arithmetically and never applies it: GRADE expects two
 * half-serious concerns in different domains to be able to cost one level
 * between them, which no formula reproduces. */
export default function CertaintyPanel({ pid, outcomeId, catalogue }: {
  pid: number
  outcomeId: number
  catalogue: SynthesisCatalogue | undefined
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [consensusMode, setConsensusMode] = useState(false)
  const [draft, setDraft] = useState<Draft>(EMPTY)
  const [error, setError] = useState('')

  const { data } = useQuery<CertaintyView>({
    queryKey: ['certainty', pid, outcomeId],
    queryFn: () => api.get(`${API(pid)}/outcomes/${outcomeId}/certainty`),
  })

  useEffect(() => {
    if (!data) return
    const source = consensusMode ? data.consensus : data.mine
    setDraft(source ? {
      starting_point: source.starting_point,
      starting_rationale: source.starting_rationale,
      domains: source.domains, upgrades: source.upgrades,
      final: source.final, statement_md: source.statement_md,
    } : {
      ...EMPTY,
      // seeded from the proposal so the assessor starts where the evidence
      // points, and edits from there
      starting_point: data.suggestions.starting_point.starting_point,
      starting_rationale: data.suggestions.starting_point.rationale,
    })
  }, [data, consensusMode])

  const save = useMutation({
    mutationFn: () => api.put(`${API(pid)}/outcomes/${outcomeId}/certainty`,
                              { ...draft, is_consensus: consensusMode }),
    onSuccess: () => {
      setError('')
      queryClient.invalidateQueries({ queryKey: ['certainty', pid, outcomeId] })
      queryClient.invalidateQueries({ queryKey: ['synthesis-outcomes', pid] })
      queryClient.invalidateQueries({ queryKey: ['synthesis-sof', pid] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })

  const draftStatement = useMutation({
    mutationFn: (final: string) => api.get<{ statement: string }>(
      `${API(pid)}/outcomes/${outcomeId}/statement?final=${final}`),
    onSuccess: (r) => setDraft((d) => ({ ...d, statement_md: r.statement })),
  })

  if (!data || !catalogue) {
    return <p className="text-sm text-muted-foreground">{t('Loading…')}</p>
  }
  const g = catalogue.grade
  const setDomain = (key: string, patch: Partial<{ judgement: string; note: string }>) =>
    setDraft((d) => {
      const entry = d.domains[key] ?? { judgement: 'none', note: '' }
      return { ...d, domains: { ...d.domains, [key]: { ...entry, ...patch } } }
    })
  const setUpgrade = (key: string, patch: Partial<{ applied: boolean; note: string }>) =>
    setDraft((d) => {
      const entry = d.upgrades[key] ?? { applied: false, note: '' }
      return { ...d, upgrades: { ...d.upgrades, [key]: { ...entry, ...patch } } }
    })

  const current = consensusMode ? data.consensus : data.mine

  return (
    <div className="space-y-4">
      {data.certainty_warning && (
        <p className="rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
          {data.certainty_warning}
        </p>
      )}

      {data.can_write_consensus && (
        <div className="flex gap-1.5">
          <Button size="sm" variant={consensusMode ? 'outline' : 'default'}
                  className="h-7 px-2 text-xs"
                  onClick={() => setConsensusMode(false)}>
            {t('My rating')}
          </Button>
          <Button size="sm" variant={consensusMode ? 'default' : 'outline'}
                  className="h-7 px-2 text-xs"
                  onClick={() => setConsensusMode(true)}>
            {t('The agreed rating')}
          </Button>
        </div>
      )}

      {data.assessments.length > 1 && !consensusMode && (
        <p className="text-xs text-muted-foreground">
          {t('{{count}} assessor(s) have rated this result.', { count: data.assessments.length })}
        </p>
      )}

      {/* Step 3 --------------------------------------------------------- */}
      <section>
        <h4 className="text-xs font-semibold text-foreground">
          {t('Step 3 — Where the rating starts')}
        </h4>
        <div className="mt-1.5 rounded-md border border-border bg-muted/40 p-2 text-xs">
          <p className="text-foreground">
            {t('From the designs of the contributing studies:')}{' '}
            <span className="font-medium">
              {t(g.starting_points.find((s) => s.key === data.suggestions.starting_point.starting_point)?.label ?? '')}
            </span>
          </p>
          <p className="mt-0.5 text-muted-foreground">
            {data.suggestions.starting_point.rationale}
          </p>
          <p className="mt-1 text-muted-foreground">
            {data.suggestions.starting_point.design_counts
              .map((d) => `${t(d.label)} × ${d.n}`).join(' · ')}
          </p>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {g.starting_points.map((s) => (
            <button key={s.key} type="button"
                    onClick={() => setDraft((d) => ({ ...d, starting_point: s.key }))}
                    className={cn('rounded border px-2 py-1 text-xs',
                      draft.starting_point === s.key
                        ? 'border-foreground bg-accent text-foreground'
                        : 'border-border text-muted-foreground hover:bg-accent')}>
              {t(s.label)}
            </button>
          ))}
        </div>
      </section>

      {/* Step 4 — downgrades -------------------------------------------- */}
      <section>
        <h4 className="text-xs font-semibold text-foreground">
          {t('Step 4 — What lowers the certainty')}
        </h4>
        <div className="mt-1.5 space-y-2">
          {g.downgrade_domains.map((d) => (
            <div key={d.key} className="rounded-md border border-border p-2">
              <p className="text-xs font-medium text-foreground">{t(d.label)}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{t(d.help)}</p>

              {d.key === 'risk_of_bias' && (
                <EvidenceBox note={data.suggestions.risk_of_bias.note}>
                  {data.suggestions.risk_of_bias.studies.map((s) => (
                    <li key={s.study_id}>
                      {s.title.slice(0, 90)}
                      {' — '}
                      {s.appraised
                        ? `${s.n_yes}/${s.n_questions}${s.source === 'consensus' ? ` · ${t('agreed')}` : ''}`
                        : t('not appraised')}
                    </li>
                  ))}
                </EvidenceBox>
              )}
              {d.key === 'publication_bias' && (
                <EvidenceBox note={data.suggestions.publication_bias.note} />
              )}

              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {g.judgements.map((j) => (
                  <button key={j.key} type="button"
                          onClick={() => setDomain(d.key, { judgement: j.key })}
                          className={cn('rounded border px-2 py-0.5 text-xs',
                            (draft.domains[d.key]?.judgement ?? 'none') === j.key
                              ? 'border-foreground bg-accent text-foreground'
                              : 'border-border text-muted-foreground hover:bg-accent')}>
                    {t(j.label)}
                  </button>
                ))}
              </div>
              <Textarea className="mt-1.5" rows={2}
                        placeholder={t('Why — this is the transparency GRADE asks for')}
                        value={draft.domains[d.key]?.note ?? ''}
                        onChange={(e) => setDomain(d.key, { note: e.target.value })} />
            </div>
          ))}
        </div>
      </section>

      {/* Step 4 — upgrades ---------------------------------------------- */}
      <section>
        <h4 className="text-xs font-semibold text-foreground">
          {t('Step 4 — What can raise it')}
        </h4>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {t('Usually considered only when the body of evidence is observational, and only when nothing was rated down.')}
        </p>
        <div className="mt-1.5 space-y-2">
          {g.upgrade_domains.map((u) => (
            <div key={u.key} className="rounded-md border border-border p-2">
              <label className="flex items-start gap-2 text-xs">
                <input type="checkbox" className="mt-0.5"
                       checked={draft.upgrades[u.key]?.applied ?? false}
                       onChange={(e) => setUpgrade(u.key, { applied: e.target.checked })} />
                <span className="font-medium text-foreground">
                  {t(u.label)}
                  <span className="block font-normal text-muted-foreground">{t(u.help)}</span>
                </span>
              </label>
              {draft.upgrades[u.key]?.applied && (
                <Textarea className="mt-1.5" rows={2}
                          value={draft.upgrades[u.key]?.note ?? ''}
                          onChange={(e) => setUpgrade(u.key, { note: e.target.value })} />
              )}
            </div>
          ))}
        </div>
      </section>

      {/* Step 5 --------------------------------------------------------- */}
      <section>
        <h4 className="text-xs font-semibold text-foreground">
          {t('Step 5 — The certainty you settle on')}
        </h4>
        {current && (
          <p className="mt-1 text-xs text-muted-foreground">
            {t('Arithmetic from your judgements:')}{' '}
            <span className="text-foreground">{t(current.suggested_label)}</span>
            {current.diverges && (
              <span className="ml-1 text-warning">
                {t('— you decided otherwise, which GRADE allows: two less-than-serious concerns in different domains can cost one level between them.')}
              </span>
            )}
          </p>
        )}
        <div className="mt-2 flex flex-wrap gap-1.5">
          {g.levels.map((l) => (
            <button key={l.key} type="button"
                    onClick={() => {
                      setDraft((d) => ({ ...d, final: l.key }))
                      draftStatement.mutate(l.key)
                    }}
                    className={cn('rounded border px-2 py-1 text-xs',
                      draft.final === l.key
                        ? 'border-foreground bg-accent text-foreground'
                        : 'border-border text-muted-foreground hover:bg-accent')}>
              {t(l.label)}
            </button>
          ))}
        </div>

        <label className="mt-3 mb-1 block text-xs font-medium text-muted-foreground">
          {t('Plain-language statement (GRADE guidelines 26)')}
        </label>
        <Textarea rows={2} value={draft.statement_md}
                  onChange={(e) => setDraft((d) => ({ ...d, statement_md: e.target.value }))} />
        <p className="mt-1 text-xs text-muted-foreground">
          {t('The certainty belongs in the verb — “probably reduces” is the moderate-certainty sentence, not a hedge bolted onto a confident one. Picking a level above drafts it; edit it into your own prose.')}
        </p>
      </section>

      <div className="flex items-center gap-2">
        <Button size="sm" disabled={save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? t('Saving…')
            : consensusMode ? t('Record the agreed rating') : t('Save my rating')}
        </Button>
        {current?.updated_at && (
          <span className="text-xs text-muted-foreground">
            {t('Last saved {{when}}', { when: current.updated_at.slice(0, 16).replace('T', ' ') })}
          </span>
        )}
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  )
}


/** What the app already knows, shown next to the judgement it informs. */
function EvidenceBox({ note, children }: {
  note: string
  children?: React.ReactNode
}) {
  return (
    <div className="mt-1.5 rounded-md border border-border bg-muted/40 p-2 text-xs">
      <p className="text-muted-foreground">{note}</p>
      {children && (
        <ul className="mt-1 space-y-0.5 text-muted-foreground">{children}</ul>
      )}
    </div>
  )
}
