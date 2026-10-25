// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'
import {
  api, ApiError, type CostInfo, type ReportSectionInfo,
} from '@/api'
import { Button } from '../ui/button'
import { Card, CardContent } from '../ui/card'
import { Segmented } from '../ui/segmented'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader,
  DialogTitle,
} from '../ui/dialog'
import SectionOutput from './SectionOutput'

/** Shape of the audit dossier, narrowed to what this panel displays.
 * The full object is much larger — it is the model's input, not the UI's. */
interface Dossier {
  tool: { name: string; version: string; url: string }
  protocol: { imported: boolean; validated: boolean; n_include: number
              n_exclude: number }
  search: { frozen_equation: string | null
            imports: { source: string; n_records: number }[] }
  dedup: { n_records: number; n_duplicates: number; n_unique: number }
  screening: Record<string, { round: number; n_reviewers: number
                              n_decided: number
                              agreement: { kappa: number | null } }[]>
  snowballing: { n_iterations: number }
  extraction: { n_columns: number; jbi: { n_appraised: number } }
  prisma: { studies_included: number | null }
}

export default function MethodsPanel({ pid }: { pid: number }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const base = `/api/projects/${pid}/reporting`
  const [lang, setLang] = useState<'en' | 'fr'>('en')
  const [error, setError] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [wantEstimate, setWantEstimate] = useState(false)

  const { data: sections, isLoading } = useQuery<
    Record<string, ReportSectionInfo | null>>({
    queryKey: ['reporting-sections', pid],
    queryFn: () => api.get(`${base}/sections`),
  })
  const { data: dossier } = useQuery<Dossier>({
    queryKey: ['reporting-dossier', pid],
    queryFn: () => api.get(`${base}/dossier`),
  })
  const { data: estimate } = useQuery<{ cost: CostInfo | null }>({
    queryKey: ['reporting-estimate', pid, 'methods', lang],
    queryFn: () => api.get(`${base}/methods/estimate?lang=${lang}`),
    enabled: wantEstimate,
    staleTime: 60_000,
  })
  const generate = useMutation({
    mutationFn: () =>
      api.post<ReportSectionInfo>(`${base}/methods/generate`, { lang }),
    onSuccess: () => {
      setError('')
      queryClient.invalidateQueries({ queryKey: ['reporting-sections', pid] })
      queryClient.invalidateQueries({ queryKey: ['project-progress', pid] })
    },
    onError: (e) =>
      setError(e instanceof ApiError ? e.message : t('Generation failed')),
  })

  if (isLoading) return <p className="text-muted-foreground">{t('Loading…')}</p>
  const section = sections?.methods ?? null
  const cost = estimate?.cost ?? null

  const generateButton = (label: string) => (
    <Button
      onClick={() => (section ? setConfirmOpen(true) : generate.mutate())}
      onMouseEnter={() => setWantEstimate(true)}
      disabled={generate.isPending}
      title={cost
        ? t('Estimated ≈ {{cost}} ({{model}})',
            { cost: cost.cost_label, model: cost.model })
        : t('Generate with the configured AI provider')}
      className="gap-1.5"
    >
      <Sparkles className="size-4" />
      {generate.isPending ? t('Generating…') : label}
      {cost && !generate.isPending && (
        <span className="text-xs opacity-70">≈{cost.cost_label}</span>
      )}
    </Button>
  )

  const ta = dossier?.screening?.ta ?? []
  const kappa = ta.map((r) => r.agreement?.kappa).filter(
    (k): k is number => typeof k === 'number')

  return (
    <div className="flex flex-col gap-4">
      {error && <p className="text-sm text-destructive">{error}</p>}

      <p className="max-w-3xl text-sm text-muted-foreground">
        {t('The Methods paragraph is written from this project\'s audit trail — the settings and counts the pipeline recorded as the work happened, not from anything typed in here. Check the facts below, pick a language, generate, then edit the text you will paste into the manuscript.')}
      </p>

      {dossier && (
        <Card>
          <CardContent className="py-4">
            <p className="mb-2.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              {t('What it will be written from')}
            </p>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
              <Fact label={t('Protocol')}
                    value={dossier.protocol.imported
                      ? t('{{include}} inclusion / {{exclude}} exclusion criteria',
                          { include: dossier.protocol.n_include,
                            exclude: dossier.protocol.n_exclude })
                      : t('not imported')} />
              <Fact label={t('Frozen equation')}
                    value={dossier.search.frozen_equation || t('none')} />
              <Fact label={t('Sources searched')}
                    value={String(new Set(dossier.search.imports
                      .map((i) => i.source)).size)} />
              <Fact label={t('Records after dedup')}
                    value={`${dossier.dedup.n_unique} / ${dossier.dedup.n_records}`} />
              <Fact label={t('T/A screening rounds')}
                    value={ta.length
                      ? t('{{n}} round(s), {{reviewers}} reviewer(s)',
                          { n: ta.length, reviewers: ta[0].n_reviewers })
                      : t('none')} />
              <Fact label={t('Agreement (κ)')}
                    value={kappa.length
                      ? kappa.map((k) => k.toFixed(2)).join(', ')
                      : t('not computed')} />
              <Fact label={t('Snowballing iterations')}
                    value={String(dossier.snowballing.n_iterations)} />
              <Fact label={t('Extraction columns')}
                    value={String(dossier.extraction.n_columns)} />
              <Fact label={t('Studies included')}
                    value={dossier.prisma.studies_included === null
                      ? t('not settled yet')
                      : String(dossier.prisma.studies_included)} />
            </dl>
            <p className="mt-3 text-xs text-muted-foreground">
              {t('The generated text credits {{tool}} v{{version}} as the software the review was conducted in.',
                 { tool: dossier.tool.name, version: dossier.tool.version })}
            </p>
          </CardContent>
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm text-muted-foreground">{t('Language')}</span>
        <Segmented
          value={lang}
          onChange={(v) => setLang(v)}
          options={[{ value: 'en' as const, label: 'English' },
                    { value: 'fr' as const, label: 'Français' }]}
        />
        {generateButton(section ? t('Regenerate') : t('Generate the Methods section'))}
      </div>

      {section
        ? <SectionOutput pid={pid} kind="methods" section={section} />
        : (
          <Card>
            <CardContent className="py-8 text-sm text-muted-foreground">
              {t('Nothing generated yet.')}
            </CardContent>
          </Card>
        )}

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('Regenerate the Methods section?')}</DialogTitle>
            <DialogDescription>
              {t('The generated text will be replaced for the whole team. Your own edited version is kept.')}
              {cost ? ' ' + t('The call costs ≈ {{cost}}.', { cost: cost.cost_label }) : ''}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              {t('Cancel')}
            </Button>
            <Button onClick={() => { setConfirmOpen(false); generate.mutate() }}>
              {t('Regenerate')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-medium tabular-nums text-foreground">{value}</dd>
    </div>
  )
}
