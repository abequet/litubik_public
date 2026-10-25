// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { usePdfWindow } from './PdfWindow'
import TagChips from './TagChips'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Segmented } from '@/components/ui/segmented'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'

/** "Paper card" modal: metadata, provenance, screening outcomes per round,
 * PDF state, and the article's snowballing story — how it was discovered and,
 * when it served as a seed, what its own backward/forward crawls found.
 * Clicking any listed article navigates the card to that paper. */

interface CardArticle {
  id: number
  title: string
  authors: string[]
  year: number | null
  doi: string | null
  status?: 'seed' | 'included' | 'excluded' | 'pending'
  direction?: 'backward' | 'forward'
  round?: number
}

interface CardData {
  id: number
  title: string
  authors: string[]
  year: number | null
  journal: string
  doi: string | null
  abstract: string
  sources: { type: string; name: string; round: number }[]
  screening: { stage: 'ta' | 'ft'; round: number; outcome: string
    reason: { code: string; label: string } | null }[]
  has_pdf: boolean
  fulltext_status: string | null
  discovered_by: CardArticle[]
  as_seed: { n_backward: number; n_forward: number
    backward: CardArticle[]; forward: CardArticle[] } | null
}

/** Status dots mirror the CitationGraph data-viz palette (Okabe-Ito), so they
 * use the reserved --viz-* tokens rather than the monochrome/vote tokens. */
const STATUS_STYLE: Record<string, { color: string; label: string }> = {
  seed: { color: 'var(--viz-blue)', label: 'seed' },
  included: { color: 'var(--viz-teal)', label: 'included' },
  excluded: { color: 'var(--viz-orange)', label: 'excluded' },
  pending: { color: 'var(--muted-foreground)', label: 'to screen' },
}

export default function RecordCard({ projectId, recordId, onClose }: {
  projectId: number
  recordId: number
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [rid, setRid] = useState(recordId)
  const [tab, setTab] = useState<'backward' | 'forward'>('backward')
  const openPdf = usePdfWindow()
  const { data, isLoading } = useQuery<CardData>({
    queryKey: ['record-card', projectId, rid],
    queryFn: () => api.get(`/api/projects/${projectId}/records/${rid}/card`),
  })

  const seed = data?.as_seed

  const articleLine = (a: CardArticle) => (
    <li key={`${a.id}-${a.direction ?? ''}`} className="text-xs">
      <button onClick={() => setRid(a.id)}
              title={t("Open this paper's card")}
              className="text-left text-foreground hover:text-primary hover:underline">
        {a.title}
      </button>
      <span className="text-muted-foreground">
        {' — '}{a.authors[0] ?? '?'}{a.authors.length > 1 ? ' et al.' : ''}
        {a.year ? `, ${a.year}` : ''}
        {a.direction
          ? ` · ${a.direction === 'backward'
              ? t('found backward (r{{round}})', { round: a.round })
              : t('found forward (r{{round}})', { round: a.round })}`
          : ''}
      </span>
      {a.status && (
        <span className="ml-1 inline-flex items-center gap-1 text-xs text-muted-foreground">
          <span className="inline-block h-2 w-2 rounded-full"
                style={{ background: STATUS_STYLE[a.status].color }} />
          {t(STATUS_STYLE[a.status].label)}
        </span>
      )}
    </li>
  )

  return (
    <Dialog open onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="flex max-h-[85vh] max-w-3xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b border-border px-5 py-3 pr-10">
          <DialogTitle className="text-sm font-semibold leading-snug text-foreground">
            {data?.title ?? t('Loading…')}
          </DialogTitle>
          {data ? (
            <DialogDescription className="mt-0.5 text-xs text-muted-foreground">
              {data.authors.slice(0, 6).join('; ')}
              {data.authors.length > 6 ? '…' : ''}
              {data.year ? ` · ${data.year}` : ''}
              {data.journal ? ` · ${data.journal}` : ''}
            </DialogDescription>
          ) : (
            <DialogDescription className="sr-only">{t('Record details')}</DialogDescription>
          )}
        </DialogHeader>

        <div className="flex-1 space-y-4 overflow-y-auto p-5 text-sm">
          {isLoading && <p className="text-xs text-muted-foreground">{t('Loading…')}</p>}
          {data && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                {data.doi && (
                  <Button variant="link" size="sm" asChild
                          className="h-auto p-0 font-mono text-xs">
                    <a href={`https://doi.org/${data.doi}`} target="_blank" rel="noreferrer"
                       className="break-all">
                      {data.doi} ↗
                    </a>
                  </Button>
                )}
                {data.has_pdf && (
                  <Button variant="outline" size="sm"
                          onClick={() => openPdf({ projectId, recordId: data.id,
                            title: data.title })}>
                    {t('📄 Open PDF')}
                  </Button>
                )}
                {data.sources.map((s) => (
                  <Badge key={`${s.name}-${s.round}`} variant="outline"
                         title={t('Source (round {{round}})', { round: s.round })}>
                    {s.name}
                  </Badge>
                ))}
              </div>

              <TagChips projectId={projectId} recordId={data.id} />

              {data.screening.length > 0 && (
                <div>
                  <p className="mb-1 text-xs font-semibold text-muted-foreground">{t('Screening')}</p>
                  <ul className="space-y-0.5">
                    {data.screening.map((s) => (
                      <li key={`${s.stage}-${s.round}`} className="text-xs text-muted-foreground">
                        {s.stage === 'ta' ? t('Title/abstract') : t('Full text')} (r{s.round}):{' '}
                        <span className={cn('font-medium',
                          s.outcome === 'include' ? 'text-success'
                            : s.outcome === 'exclude' ? 'text-destructive'
                              : 'text-warning')}>
                          {t(s.outcome)}
                        </span>
                        {s.reason && ` — ${s.reason.code}: ${s.reason.label}`}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {data.abstract && (
                <details>
                  <summary className="cursor-pointer text-xs font-semibold text-muted-foreground">
                    {t('Abstract')}
                  </summary>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                    {data.abstract}
                  </p>
                </details>
              )}

              {data.discovered_by.length > 0 && (
                <div>
                  <p className="mb-1 text-xs font-semibold text-muted-foreground">
                    {t('Discovered by snowballing from')}
                  </p>
                  <ul className="space-y-1">{data.discovered_by.map(articleLine)}</ul>
                </div>
              )}

              {seed && (
                <div>
                  <p className="mb-1 text-xs font-semibold text-muted-foreground">
                    {t('As a seed, its crawls found')}
                  </p>
                  <Segmented
                    className="mb-2"
                    value={tab}
                    onChange={setTab}
                    options={[
                      { value: 'backward',
                        label: t('Backward — its references ({{count}})', { count: seed.n_backward }) },
                      { value: 'forward',
                        label: t('Forward — citing it ({{count}})', { count: seed.n_forward }) },
                    ]}
                  />
                  <ul className="max-h-56 space-y-1 overflow-y-auto">
                    {(tab === 'backward' ? seed.backward : seed.forward)
                      .map(articleLine)}
                    {(tab === 'backward' ? seed.backward : seed.forward)
                      .length === 0 && (
                      <li className="text-xs text-muted-foreground">{t('Nothing found.')}</li>
                    )}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
