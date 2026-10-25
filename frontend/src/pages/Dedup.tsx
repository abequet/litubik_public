// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useWorkHeartbeat } from '../useWorkHeartbeat'
import { api, ApiError, type Project } from '../api'
import { useJobWatcher } from '../useJob'
import { Button } from '@/components/ui/button'
import LiveStatus from '../components/LiveStatus'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Stat } from '@/components/ui/stat'
import {
  TranslateControl, useRecordTranslation, type Translations,
} from '../components/RecordTranslation'

interface RecordSide {
  id: number
  doi: string | null
  title: string
  authors: string[]
  year: number | null
  journal: string
  abstract: string
  translations?: Translations
  sources: string[]
}

interface Pair {
  id: number
  score: number
  reason: string
  record: RecordSide
  canonical: RecordSide
}

interface Merged {
  pair_id: number | null
  reason: string
  score: number | null
  manual: boolean
  duplicate: RecordSide
  canonical: RecordSide
}

interface Summary {
  total: number
  pending: number
  unique: number
  duplicate: number
  uncertain: number
  per_source: { source: string; n: number }[]
  pending_pairs: number
}

export default function DedupPage() {
  const { t } = useTranslation()
  const { projectId } = useParams()
  const pid = Number(projectId)
  useWorkHeartbeat(pid, 'dedup')
  const queryClient = useQueryClient()
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'], queryFn: () => api.get('/api/projects'),
  })
  const isAdmin = projects.find((p) => p.id === pid)?.my_role === 'admin'

  const { data: summary } = useQuery<Summary>({
    queryKey: ['dedup-summary', pid],
    queryFn: () => api.get(`/api/projects/${pid}/dedup/summary`),
  })
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['dedup-summary', pid] })
    queryClient.invalidateQueries({ queryKey: ['dedup-pairs', pid] })
    queryClient.invalidateQueries({ queryKey: ['dedup-merged', pid] })
    queryClient.invalidateQueries({ queryKey: ['records', pid] })
  }
  const job = useJobWatcher(refresh)
  const [error, setError] = useState('')

  const run = async () => {
    setError('')
    try {
      const { job_id } = await api.post<{ job_id: number }>(
        `/api/projects/${pid}/dedup/run`)
      job.watch(job_id)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('Could not start deduplication'))
    }
  }

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">{t('Deduplication')}</h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {t('Exact DOI and exact-title duplicates are merged automatically; near-identical titles (same year ±1, same first author) too. Ambiguous pairs are never merged automatically — they wait for your decision below. Re-run after every new import.')}
      </p>

      <Card className="mb-6 p-4">
        <div className="flex flex-wrap items-center gap-6">
          <Stat label={t('records')} value={summary?.total ?? '…'} />
          <Stat label={t('unique')} value={summary?.unique ?? '…'} tone="success" />
          <Stat label={t('duplicates removed')} value={summary?.duplicate ?? '…'} />
          <Stat label={t('awaiting arbitration')} value={summary?.pending_pairs ?? '…'}
                tone={summary?.pending_pairs ? 'warning' : undefined} />
          <Stat label={t('not checked yet')} value={summary?.pending ?? '…'}
                tone={summary?.pending ? 'warning' : undefined} />
          <span className="flex-1" />
          {isAdmin && (
            <Button onClick={run} disabled={!!job.state}>
              {job.state || t('Run deduplication')}
            </Button>
          )}
        </div>
        {summary && summary.per_source.length > 0 && (
          <p className="mt-3 text-xs text-muted-foreground">
            {t('Identified per source:')}{' '}
            {summary.per_source.map((s) => `${s.source} ${s.n}`).join(' · ')}
          </p>
        )}
        {(error || job.error) && (
          <p className="mt-2 text-sm text-destructive">{error || job.error}</p>
        )}
      </Card>

      <ArbitrationQueue projectId={pid} isAdmin={isAdmin} onResolved={refresh} />
      <MergedList projectId={pid} />
    </div>
  )
}

const REASON_LABELS: Record<string, string> = {
  doi: 'same DOI',
  title_exact: 'identical title',
  fuzzy_title: 'fuzzy title',
  auto: 'automatic',
}

function MergedList({ projectId }: { projectId: number }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const { data: merged = [] } = useQuery<Merged[]>({
    queryKey: ['dedup-merged', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/dedup/duplicates`),
  })
  if (merged.length === 0) return null
  return (
    <Card className="mt-6 p-4">
      <button onClick={() => setOpen((v) => !v)}
              className="text-sm font-semibold text-foreground hover:text-primary">
        {open ? '▾' : '▸'} {t('Merged duplicates ({{count}})', { count: merged.length })}
      </button>
      {open && (
        <ul className="mt-3 divide-y divide-border">
          {merged.map((m, i) => (
            <li key={i} className="py-2 text-xs">
              <div className="mb-1 flex items-center gap-2">
                <Badge variant={m.manual ? 'default' : 'outline'}>
                  {m.manual ? t('manual decision') : t(REASON_LABELS[m.reason] ?? m.reason)}
                  {m.score != null && m.reason === 'fuzzy_title'
                    ? ` ${m.score.toFixed(1)} %` : ''}
                </Badge>
              </div>
              <p className="text-muted-foreground">
                <span className="line-through decoration-muted-foreground/40">
                  {m.duplicate.title}
                </span>
                <span className="text-muted-foreground/70">
                  {' '}[{m.duplicate.sources.join(', ')}
                  {m.duplicate.year ? ` · ${m.duplicate.year}` : ''}]
                </span>
              </p>
              <p className="text-foreground">
                → {t('kept:')} <span className="font-medium">{m.canonical.title}</span>
                <span className="text-muted-foreground/70">
                  {' '}[{m.canonical.sources.join(', ')}
                  {m.canonical.year ? ` · ${m.canonical.year}` : ''}]
                </span>
                {m.canonical.doi && (
                  <a href={`https://doi.org/${m.canonical.doi}`} target="_blank"
                     rel="noreferrer"
                     className="ml-1 font-mono text-primary hover:underline">
                    {m.canonical.doi}
                  </a>
                )}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function ArbitrationQueue({ projectId, isAdmin, onResolved }: {
  projectId: number
  isAdmin: boolean
  onResolved: () => void
}) {
  const { t } = useTranslation()
  const { data: pairs = [] } = useQuery<Pair[]>({
    queryKey: ['dedup-pairs', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/dedup/pairs`),
  })
  if (pairs.length === 0) {
    return (
      <Card className="p-6 text-sm text-muted-foreground">
        {t('No pair awaiting arbitration.')}
      </Card>
    )
  }
  return (
    <section className="space-y-4">
      <h2 className="text-sm font-semibold text-foreground">
        {t('Uncertain pairs — your call ({{count}})', { count: pairs.length })}
      </h2>
      {pairs.map((pair) => (
        <PairCard key={pair.id} projectId={projectId} pair={pair}
                  isAdmin={isAdmin} onResolved={onResolved} />
      ))}
    </section>
  )
}

function PairCard({ projectId, pair, isAdmin, onResolved }: {
  projectId: number
  pair: Pair
  isAdmin: boolean
  onResolved: () => void
}) {
  const { t } = useTranslation()
  const [error, setError] = useState('')
  const resolve = useMutation({
    mutationFn: (decision: 'merge' | 'distinct') =>
      api.post(`/api/projects/${projectId}/dedup/pairs/${pair.id}/resolve`,
        { decision }),
    onSuccess: onResolved,
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Failed')),
  })

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <Badge variant="warning">
          {t('title similarity {{score}} %', { score: pair.score.toFixed(1) })}
        </Badge>
        <span className="flex-1" />
        {isAdmin && (
          <>
            <Button size="sm" onClick={() => resolve.mutate('merge')}
                    disabled={resolve.isPending}>
              {t('Same article — merge')}
            </Button>
            <Button variant="outline" size="sm" onClick={() => resolve.mutate('distinct')}
                    disabled={resolve.isPending}>
              {t('Different — keep both')}
            </Button>
          </>
        )}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <SideCard projectId={projectId} side={pair.canonical} tag={t('kept either way')} />
        <SideCard projectId={projectId} side={pair.record} tag={t('merged if same')} />
      </div>
      <LiveStatus className="mt-2 text-sm">{error}</LiveStatus>
    </Card>
  )
}

function SideCard({ projectId, side, tag }: {
  projectId: number
  side: RecordSide
  tag: string
}) {
  // pairs come by the dozen: translation here is on request only
  const translation = useRecordTranslation({
    projectId, recordId: side.id, translations: side.translations,
    autoAllowed: false,
  })
  return (
    <div className="rounded-lg border border-border bg-muted p-3 text-sm">
      <p className="mb-1 text-xs text-muted-foreground">
        #{side.id} · {side.sources.join(', ')} · <em>{tag}</em>
      </p>
      <p className="font-medium text-foreground">
        {translation.shown?.title || side.title}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        {side.authors.slice(0, 4).join('; ')}{side.authors.length > 4 ? '…' : ''}
        {side.year ? ` · ${side.year}` : ''}
        {side.journal ? ` · ${side.journal}` : ''}
      </p>
      {side.doi && (
        <a href={`https://doi.org/${side.doi}`} target="_blank" rel="noreferrer"
           className="font-mono text-xs text-primary hover:underline">{side.doi}</a>
      )}
      {side.abstract && (
        <p className="mt-2 line-clamp-4 text-xs text-muted-foreground">
          {translation.shown?.abstract || side.abstract}
        </p>
      )}
      <TranslateControl control={translation.control} withAuto={false}
                        className="mt-2" />
    </div>
  )
}
