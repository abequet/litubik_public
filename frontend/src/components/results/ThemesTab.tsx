// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  api, ApiError, type TopicCluster, type TopicRun, type TopicsState,
} from '../../api'
import { useJobWatcher } from '../../useJob'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import LiveStatus from '../LiveStatus'
import RecordCard from '../RecordCard'
import { clusterColor } from './palette'
import TopicMap from './TopicMap'

type Scope = 'unique' | 'ta_included' | 'ft_included'

/** Thematic map of the corpus (chantier 11): run a clustering on a scope,
 * read the map, name the clusters (by hand or with the AI, suggestions are
 * marked), hide clusters, export PNG/CSV, and read the same assignment as a
 * table for keyboard and screen-reader users. */
export default function ThemesTab({ pid }: { pid: number }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [runId, setRunId] = useState<number | null>(null)
  const { data, isLoading } = useQuery<TopicsState>({
    queryKey: ['topics', pid, runId],
    queryFn: () => api.get(`/api/projects/${pid}/topics${runId ? `?run_id=${runId}` : ''}`),
  })
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['topics', pid] })
  const [scope, setScope] = useState<Scope>('unique')
  const [k, setK] = useState<string>('auto')
  const [hidden, setHidden] = useState<Set<number>>(new Set())
  const [highlight, setHighlight] = useState<number | null>(null)
  const [cardId, setCardId] = useState<number | null>(null)
  const [showTable, setShowTable] = useState(false)
  const watcher = useJobWatcher(() => { setRunId(null); invalidate() })
  const start = useMutation({
    mutationFn: () => api.post<{ job_id: number }>(`/api/projects/${pid}/topics/run`,
      { scope, k: k === 'auto' ? null : Number(k) }),
    onSuccess: ({ job_id }) => watcher.watch(job_id),
    onError: (e) => watcher.setError(e instanceof ApiError ? e.message : t('Run failed')),
  })
  const run = data?.run ?? null
  useEffect(() => { setHidden(new Set()); setHighlight(null) }, [run?.id])

  const scopeLabel: Record<Scope, string> = {
    unique: t('Unique records'),
    ta_included: t('Included at title/abstract'),
    ft_included: t('Included at full text'),
  }
  const sizes = data?.sizes
  const tooSmall = sizes ? sizes[scope] < (data?.min_docs ?? 6) : false

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground" htmlFor="topics-scope">
              {t('Corpus')}
            </label>
            <Select value={scope} onValueChange={(v) => setScope(v as Scope)}>
              <SelectTrigger id="topics-scope" className="h-8 w-64 text-sm"><SelectValue /></SelectTrigger>
              <SelectContent>
                {(['unique', 'ta_included', 'ft_included'] as Scope[]).map((s) => (
                  <SelectItem key={s} value={s}>
                    {scopeLabel[s]}{sizes ? ` (${sizes[s]})` : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground" htmlFor="topics-k">
              {t('Clusters')}
            </label>
            <Select value={k} onValueChange={setK}>
              <SelectTrigger id="topics-k" className="h-8 w-40 text-sm"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">{t('automatic (silhouette)')}</SelectItem>
                {Array.from({ length: 11 }, (_, i) => i + 2).map((n) => (
                  <SelectItem key={n} value={String(n)}>{n}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button size="sm" onClick={() => start.mutate()}
                  disabled={start.isPending || !!watcher.state || tooSmall}>
            {run ? t('Recompute the map') : t('Map the themes')}
          </Button>
          {watcher.state && <span className="text-xs text-muted-foreground">{watcher.state}</span>}
          {tooSmall && (
            <span className="text-xs text-muted-foreground">
              {t('At least {{count}} records are needed in this corpus.', { count: data?.min_docs ?? 6 })}
            </span>
          )}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          {t('Titles, abstracts and keywords are vectorised (TF-IDF, 1–2-grams, English and French stop words), reduced (SVD) and laid out in two dimensions (t-SNE up to 10,000 records, SVD beyond); the clusters are then formed on that map (k-means; k chosen by silhouette unless fixed), so each one is a contiguous region. Everything runs locally — nothing is sent to an AI unless you ask for cluster labels.')}
        </p>
        <LiveStatus tone="error" className="mt-2 text-xs">{watcher.error}</LiveStatus>
      </Card>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">{t('Loading…')}</p>
      ) : !run ? (
        <p className="text-sm text-muted-foreground">
          {t('No map yet — choose a corpus and run the clustering. It takes a few seconds for a few hundred records.')}
        </p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>
              {t('{{n}} records · {{k}} clusters · {{scope}} · {{projection}}', {
                n: run.n_docs, k: run.k, scope: scopeLabel[run.scope],
                projection: run.projection === 'tsne' ? 't-SNE' : 'SVD' })}
              {run.silhouette != null && ` · ${t('silhouette {{s}}', { s: run.silhouette.toFixed(2) })}`}
              {' · '}
              {t('by {{name}} on {{date}}', {
                name: run.created_by_name, date: new Date(run.created_at).toLocaleDateString() })}
            </span>
            {data && data.history.length > 1 && (
              <Select value={String(run.id)} onValueChange={(v) => setRunId(Number(v))}>
                <SelectTrigger className="h-7 w-auto text-xs" aria-label={t('Previous maps')}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {data.history.map((h) => (
                    <SelectItem key={h.id} value={String(h.id)}>
                      {new Date(h.created_at).toLocaleString()} — {scopeLabel[h.scope]}, k={h.k}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <span className="flex-1" />
            <Button asChild variant="outline" size="sm">
              <a href={`/api/projects/${pid}/topics/${run.id}/export.csv`}>⬇ CSV</a>
            </Button>
            <Button variant="outline" size="sm" aria-pressed={showTable}
                    onClick={() => setShowTable((v) => !v)}>
              {showTable ? t('Hide table') : t('Table')}
            </Button>
          </div>

          <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
            <TopicMap points={run.points} clusters={run.clusters} hidden={hidden}
                      highlight={highlight}
                      onOpenCard={setCardId} filename={`themes_run${run.id}.png`} />
            <ClusterLegend pid={pid} run={run} hidden={hidden} onHighlight={setHighlight}
                           onToggle={(id) => setHidden((h) => {
                             const next = new Set(h)
                             if (next.has(id)) next.delete(id); else next.add(id)
                             return next
                           })}
                           onChanged={invalidate} />
          </div>

          {showTable && <AssignmentTable run={run} onOpenCard={setCardId} />}
        </>
      )}

      {cardId !== null && (
        <RecordCard projectId={pid} recordId={cardId} onClose={() => setCardId(null)} />
      )}
    </div>
  )
}

function ClusterLegend({ pid, run, hidden, onToggle, onHighlight, onChanged }: {
  pid: number
  run: TopicRun
  hidden: Set<number>
  onToggle: (id: number) => void
  onHighlight: (id: number | null) => void
  onChanged: () => void
}) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const [cost, setCost] = useState('')
  const { data: estimate } = useQuery<{ cost: { cost_usd: number; model: string } | null }>({
    queryKey: ['topics-label-estimate', run.id],
    queryFn: () => api.get(`/api/projects/${pid}/topics/${run.id}/label-estimate`),
    staleTime: 60_000,
  })
  const rename = useMutation({
    mutationFn: ({ id, label }: { id: number; label: string }) =>
      api.put(`/api/projects/${pid}/topics/${run.id}/clusters/${id}`, { label }),
    onSuccess: () => { setEditing(null); setError(''); onChanged() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const aiLabel = useMutation({
    mutationFn: () => api.post<{ cost: { cost_usd: number; model: string } }>(
      `/api/projects/${pid}/topics/${run.id}/label`),
    onSuccess: (r) => {
      setError('')
      setCost(t('Labels suggested by {{model}} (${{cost}}) — edit any of them.', {
        model: r.cost.model, cost: r.cost.cost_usd.toFixed(4) }))
      onChanged()
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('AI labelling failed')),
  })
  const sorted = useMemo(() => [...run.clusters].sort((a, b) => a.id - b.id), [run.clusters])

  return (
    <Card className="p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">{t('Clusters')}</h3>
        <Button variant="outline" size="sm" onClick={() => aiLabel.mutate()}
                disabled={aiLabel.isPending || estimate?.cost === null}
                title={estimate?.cost
                  ? t('Estimated cost ${{cost}} with {{model}}', {
                      cost: estimate.cost.cost_usd.toFixed(4), model: estimate.cost.model })
                  : t('No AI provider configured')}>
          {aiLabel.isPending ? t('Labelling…') : t('Label with AI')}
        </Button>
      </div>
      <ul className="space-y-2">
        {sorted.map((c: TopicCluster) => (
          <li key={c.id} className="rounded-sm text-xs hover:bg-muted/60 focus-within:bg-muted/60"
              onMouseEnter={() => onHighlight(c.id)} onMouseLeave={() => onHighlight(null)}
              onFocus={() => onHighlight(c.id)} onBlur={() => onHighlight(null)}>
            <div className="flex items-start gap-2 p-1">
              <Checkbox checked={!hidden.has(c.id)} onCheckedChange={() => onToggle(c.id)}
                        aria-label={t('Show cluster {{n}}', { n: c.id + 1 })} className="mt-0.5" />
              <span className="mt-1 inline-block size-3 shrink-0 rounded-full"
                    style={{ background: clusterColor(c.id) }} aria-hidden="true" />
              <div className="min-w-0 flex-1">
                {editing === c.id ? (
                  <form className="flex gap-1" onSubmit={(e) => {
                    e.preventDefault(); rename.mutate({ id: c.id, label: draft })
                  }}>
                    <Input value={draft} onChange={(e) => setDraft(e.target.value)}
                           className="h-7 text-xs" maxLength={80} autoFocus
                           aria-label={t('Cluster label')} />
                    <Button type="submit" size="sm" className="h-7">{t('Save')}</Button>
                    <Button type="button" size="sm" variant="ghost" className="h-7"
                            onClick={() => setEditing(null)}>{t('Cancel')}</Button>
                  </form>
                ) : (
                  <button type="button" className="text-left font-medium text-foreground hover:underline"
                          onClick={() => { setEditing(c.id); setDraft(c.label) }}
                          title={t('Rename')}>
                    {c.id + 1} · {c.label || t('(unnamed — click to name)')}
                    {c.label && c.label_is_ai && (
                      <Badge variant="outline" className="ml-1 px-1 text-[10px]">{t('AI')}</Badge>
                    )}
                  </button>
                )}
                <p className="text-muted-foreground">
                  {c.size} · {c.terms.join(', ')}
                </p>
              </div>
            </div>
          </li>
        ))}
      </ul>
      <LiveStatus tone="error" className="mt-2">{error}</LiveStatus>
      <LiveStatus tone="info" className="mt-2">{cost}</LiveStatus>
    </Card>
  )
}

function AssignmentTable({ run, onOpenCard }: {
  run: TopicRun
  onOpenCard: (id: number) => void
}) {
  const { t } = useTranslation()
  const labels = new Map(run.clusters.map((c) => [c.id, c.label || c.terms.slice(0, 3).join(', ')]))
  const statusLabel = { include: t('included'), exclude: t('excluded'), undecided: t('undecided') }
  const rows = [...run.points].sort((a, b) => a.cluster - b.cluster || a.title.localeCompare(b.title))
  return (
    <Card className="overflow-x-auto p-3">
      <table className="w-full text-xs">
        <caption className="mb-2 text-left text-muted-foreground">
          {t('Cluster assignment of every record on the map (same data as the CSV).')}
        </caption>
        <thead>
          <tr className="text-left text-muted-foreground">
            <th scope="col" className="py-1 pr-3">{t('Cluster')}</th>
            <th scope="col" className="py-1 pr-3">{t('Title')}</th>
            <th scope="col" className="py-1 pr-3">{t('Year')}</th>
            <th scope="col" className="py-1 pr-3">{t('Screening')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.record_id} className="border-t">
              <td className="py-1 pr-3 whitespace-nowrap">
                <span className="mr-1 inline-block size-2 rounded-full"
                      style={{ background: clusterColor(p.cluster) }} aria-hidden="true" />
                {p.cluster + 1} · {labels.get(p.cluster)}
              </td>
              <td className="py-1 pr-3">
                <button type="button" className="text-left hover:underline"
                        onClick={() => onOpenCard(p.record_id)}>
                  {p.title}
                </button>
                <span className="text-muted-foreground"> — {p.author}</span>
              </td>
              <td className="py-1 pr-3">{p.year ?? ''}</td>
              <td className="py-1 pr-3">{statusLabel[p.status]}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}
