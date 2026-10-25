// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { api, ApiError, type Project } from '../api'
import CitationGraph, { type GraphEdge, type GraphNode } from '../components/snowball/CitationGraph'
import { usePdfWindow } from '../components/PdfWindow'
import RecordCard from '../components/RecordCard'
import { useJobWatcher } from '../useJob'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Segmented } from '@/components/ui/segmented'
import { Stat } from '@/components/ui/stat'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'

interface StageStat { decided: number; included: number }

interface RunRow {
  round: number
  n_seeds: number
  n_backward: number
  n_forward: number
  n_new_records: number
  n_new_unique: number
  created_at: string
  ta: StageStat | null
  ft: StageStat | null
}

interface Status {
  runs: RunRow[]
  pending_seeds: number
  total_ft_included: number
  n_edges: number
  saturated: boolean
  missing_abstracts: number
}

interface SeedRow {
  id: number
  title: string
  doi: string | null
  year: number | null
  authors: string[]
}

interface SBArticle {
  id: number
  title: string
  authors: string[]
  year: number | null
  doi: string | null
  status: 'seed' | 'included' | 'excluded' | 'pending'
}

interface ContributionRow {
  id: number
  title: string
  doi: string | null
  year: number | null
  author: string
  authors: string[]
  round: number
  n_backward: number
  n_forward: number
  backward: SBArticle[]
  forward: SBArticle[]
}

export default function SnowballingPage() {
  const { t } = useTranslation()
  const { projectId } = useParams()
  const pid = Number(projectId)
  const queryClient = useQueryClient()
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'], queryFn: () => api.get('/api/projects'),
  })
  const project = projects.find((p) => p.id === pid)
  const { data: status } = useQuery<Status>({
    queryKey: ['snowball-status', pid],
    queryFn: () => api.get(`/api/projects/${pid}/snowballing/status`),
  })
  const { data: seeds = [] } = useQuery<SeedRow[]>({
    queryKey: ['snowball-seeds', pid],
    queryFn: () => api.get(`/api/projects/${pid}/snowballing/seeds`),
  })
  const { data: graph } = useQuery<{ nodes: GraphNode[]; edges: GraphEdge[] }>({
    queryKey: ['snowball-graph', pid],
    queryFn: () => api.get(`/api/projects/${pid}/snowballing/graph`),
  })
  const { data: contributions = [] } = useQuery<ContributionRow[]>({
    queryKey: ['snowball-contributions', pid],
    queryFn: () => api.get(`/api/projects/${pid}/snowballing/contributions`),
  })
  const openPdf = usePdfWindow()
  const [cardId, setCardId] = useState<number | null>(null)

  const refresh = () => {
    for (const k of ['snowball-status', 'snowball-seeds', 'snowball-graph',
                     'snowball-contributions'])
      queryClient.invalidateQueries({ queryKey: [k, pid] })
    queryClient.invalidateQueries({ queryKey: ['records', pid] })
    queryClient.invalidateQueries({ queryKey: ['prisma', pid] })
    queryClient.invalidateQueries({ queryKey: ['screening-config', pid] })
    queryClient.invalidateQueries({ queryKey: ['ftscreen-config', pid] })
  }
  const watcher = useJobWatcher(refresh)
  const [error, setError] = useState('')

  const run = useMutation({
    mutationFn: () => api.post<{ job_id: number }>(
      `/api/projects/${pid}/snowballing/run`, {}),
    onSuccess: (r) => { setError(''); watcher.watch(r.job_id) },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Run failed')),
  })
  const enrich = useMutation({
    mutationFn: () => api.post<{ job_id: number }>(
      `/api/projects/${pid}/snowballing/enrich-abstracts`),
    onSuccess: (r) => { setError(''); watcher.watch(r.job_id) },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Enrich failed')),
  })
  const removeIteration = useMutation({
    mutationFn: (round: number) => api.del(
      `/api/projects/${pid}/snowballing/iterations/${round}`),
    onSuccess: () => { setError(''); refresh() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Delete failed')),
  })

  const lastRun = status?.runs[status.runs.length - 1]
  const latestRound = lastRun?.round ?? null

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('Snowballing')}{project ? ` — ${project.name}` : ''}
      </h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {t('Each iteration crawls the references (backward) and the citing articles (forward) of every full-text-included paper — via Crossref, OpenAlex, Semantic Scholar, OpenCitations and the DOIs found in the stored PDFs — then feeds the new records through dedup and a new screening round. Iterate until saturation (no new included paper).')}
      </p>

      {status?.saturated && (
        <div className="mb-4 rounded-md border border-success/30 bg-success/10 px-4 py-3 text-sm text-success">
          {t('✓ Saturation reached — the last iteration added nothing new and every full-text-included article has been crawled. The snowballing loop is complete.')}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2 items-start mb-4">
        {/* run card */}
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold text-foreground">{t('Next iteration')}</h2>
          <div className="mb-3 flex flex-wrap gap-6">
            <Stat label={t('FT-included (total)')} value={status?.total_ft_included ?? '—'} />
            <Stat label={t('new seeds to crawl')} value={status?.pending_seeds ?? '—'} />
            <Stat label={t('citation edges')} value={status?.n_edges ?? '—'} />
          </div>
          {seeds.length > 0 && (
            <details className="mb-3">
              <summary className="cursor-pointer text-xs text-muted-foreground">
                {t('Seeds for the next run ({{count}})', { count: seeds.length })}
              </summary>
              <ul className="mt-1 max-h-40 space-y-0.5 overflow-y-auto">
                {seeds.map((s) => (
                  <li key={s.id} className="text-xs text-muted-foreground">
                    {s.title.slice(0, 70)}{s.title.length > 70 ? '…' : ''}
                    <span className="text-muted-foreground">
                      {' '}{s.authors[0] ?? ''}{s.year ? ` · ${s.year}` : ''}
                      {!s.doi && ` · ${t('no DOI (PDF refs only)')}`}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}
          <Button
            onClick={() => run.mutate()}
            disabled={run.isPending || !!watcher.state || !status?.pending_seeds}>
            {watcher.state ? t('Running…') : t('❄ Run snowballing')}
          </Button>
          {!status?.pending_seeds && !status?.saturated && (
            <p className="mt-2 text-xs text-muted-foreground">
              {t('No new seed — every full-text-included article has been crawled. Finish screening the last round to enable the next iteration.')}
            </p>
          )}
          {watcher.state && (
            <p className="mt-2 text-xs text-muted-foreground">{watcher.state}</p>
          )}
          {(error || watcher.error) && (
            <p className="mt-2 text-xs text-destructive">{error || watcher.error}</p>
          )}
          {status && status.missing_abstracts > 0 && (
            <div className="mt-3 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
              {t('{{count}} record(s) have no abstract — snowballing finds papers without one, which cripples title/abstract screening. Fetches from OpenAlex, Semantic Scholar, PubMed, then the publisher pages (slower — uses a browser for the protected ones).', { count: status.missing_abstracts })}
              <Button
                variant="outline" size="sm"
                onClick={() => enrich.mutate()}
                disabled={enrich.isPending || !!watcher.state}
                className="ml-2 h-6 px-2 text-xs">
                {t('Fetch missing abstracts')}
              </Button>
            </div>
          )}
          {lastRun && !watcher.state && (
            <p className="mt-3 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
              {t('Last run (round {{round}}): {{seeds}} seed(s) → {{backward}} backward + {{forward}} forward → {{unique}} new unique record(s) to screen.',
                 { round: lastRun.round, seeds: lastRun.n_seeds,
                   backward: lastRun.n_backward, forward: lastRun.n_forward,
                   unique: lastRun.n_new_unique })}
              {lastRun.n_new_unique > 0 && (
                <> {' '}<Link className="text-primary hover:underline"
                       to={`/projects/${pid}/screening`}>
                  {t('Screen round {{round}} →', { round: lastRun.round })}
                </Link></>
              )}
            </p>
          )}
        </Card>

        {/* iteration history */}
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold text-foreground">{t('Iterations')}</h2>
          {!status?.runs.length ? (
            <p className="text-xs text-muted-foreground">
              {t('No iteration yet — run snowballing once full-text screening has included papers.')}
            </p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th className="py-1 pr-2 font-medium">{t('round')}</th>
                  <th className="py-1 pr-2 font-medium">{t('seeds')}</th>
                  <th className="py-1 pr-2 font-medium">{t('back / fwd')}</th>
                  <th className="py-1 pr-2 font-medium">{t('new unique')}</th>
                  <th className="py-1 pr-2 font-medium">{t('T/A')}</th>
                  <th className="py-1 font-medium">{t('FT (incl.)')}</th>
                  <th className="py-1 pl-2 font-medium"><span className="sr-only">{t('Actions')}</span></th>
                </tr>
              </thead>
              <tbody>
                {status.runs.map((r) => (
                  <tr key={r.round} className="border-t border-border text-muted-foreground">
                    <td className="py-1.5 pr-2 font-medium">r{r.round}</td>
                    <td className="py-1.5 pr-2 tabular-nums">{r.n_seeds}</td>
                    <td className="py-1.5 pr-2 tabular-nums">
                      {r.n_backward} / {r.n_forward}
                    </td>
                    <td className="py-1.5 pr-2 tabular-nums">{r.n_new_unique}</td>
                    <td className="py-1.5 pr-2 tabular-nums">
                      {r.ta ? t('{{decided}} decided · {{included}} in', { decided: r.ta.decided, included: r.ta.included }) : '—'}
                    </td>
                    <td className="py-1.5 tabular-nums">
                      {r.ft ? t('{{decided}} decided · {{included}} in', { decided: r.ft.decided, included: r.ft.included }) : '—'}
                    </td>
                    <td className="py-1.5 pl-2 text-right">
                      {r.round === latestRound && (
                        <button
                          type="button"
                          title={t('Delete this iteration (undo the round)')}
                          disabled={removeIteration.isPending || !!watcher.state}
                          onClick={() => {
                            if (confirm(t('Delete snowballing round r{{round}}? It removes the {{count}} record(s) this round imported, their title/abstract & full-text screening, and its citation links — as if the round never ran. This cannot be undone.', { round: r.round, count: r.n_new_records })))
                              removeIteration.mutate(r.round)
                          }}
                          className="text-muted-foreground hover:text-destructive disabled:cursor-not-allowed disabled:opacity-40">
                          ✕
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      {/* manual backward/forward additions (crawl APIs miss references) */}
      {contributions.length > 0 && (
        <ManualAddCard pid={pid} seeds={contributions} onDone={refresh} />
      )}

      {/* per-round seed contributions with the discovered article lists */}
      {contributions.length > 0 && (
        <Card className="mb-4 p-4">
          <h2 className="mb-1 text-sm font-semibold text-foreground">
            {t('Seed contributions by round')}
          </h2>
          <p className="mb-2 text-xs text-muted-foreground">
            {t('Distinct papers each seed contributed to the citation graph (after dedup, self-references excluded). Click a seed to list what its backward (references) and forward (citing papers) crawls found.')}
          </p>
          <ContributionsTable contributions={contributions}
                              onOpenCard={(id) => setCardId(id)} />
        </Card>
      )}

      {/* network graph */}
      <Card className="p-4">
        <div className="mb-3 flex items-center gap-3">
          <h2 className="flex-1 text-sm font-semibold text-foreground">
            {t('Citation network')}
            {graph ? <span className="font-normal text-muted-foreground">
              {' '}{t('({{articles}} articles, {{links}} links)', { articles: graph.nodes.length, links: graph.edges.length })}
            </span> : null}
          </h2>
        </div>
        {!graph || graph.nodes.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            {t('The citation network appears after the first snowballing run.')}
          </p>
        ) : (
          <CitationGraph nodes={graph.nodes} edges={graph.edges}
                         onOpenPdf={(n) => openPdf({ projectId: pid,
                           recordId: n.id, title: n.title })}
                         onOpenCard={(n) => setCardId(n.id)} />
        )}
      </Card>

      {cardId !== null && (
        <RecordCard projectId={pid} recordId={cardId}
                    onClose={() => setCardId(null)} />
      )}
    </div>
  )
}

interface ManualAddResult {
  round: number
  requested: number
  already_known: number
  created: number
  edges_added: number
  unresolved: string[]
}

/** Paste the DOIs a crawl missed: they join the seed's round (metadata from
 * OpenAlex, dedup, citation edges, screening round updated). */
function ManualAddCard({ pid, seeds, onDone }: {
  pid: number
  seeds: ContributionRow[]
  onDone: () => void
}) {
  const { t } = useTranslation()
  const [seedId, setSeedId] = useState<number | ''>('')
  const [direction, setDirection] = useState<'backward' | 'forward'>('backward')
  const [dois, setDois] = useState('')
  const [message, setMessage] = useState('')

  const add = useMutation({
    mutationFn: () => api.post<ManualAddResult>(
      `/api/projects/${pid}/snowballing/manual`, {
        seed_record_id: seedId, direction,
        dois: dois.split(/[\s,;]+/).filter(Boolean),
      }),
    onSuccess: (r) => {
      setDois('')
      setMessage(t('✓ Round {{round}}: {{created}} article(s) added, {{known}} already in the base, {{edges}} link(s) drawn.',
                   { round: r.round, created: r.created,
                     known: r.already_known, edges: r.edges_added })
        + (r.unresolved.length
          ? ' ' + t('No metadata found for: {{dois}} (kept, fill by hand).', { dois: r.unresolved.join(', ') })
          : ''))
      onDone()
    },
    onError: (e) => setMessage(`✗ ${e instanceof ApiError ? e.message : t('Add failed')}`),
  })

  return (
    <details className="mb-4 rounded-lg border border-border bg-card p-4">
      <summary className="cursor-pointer text-sm font-semibold text-foreground">
        {t('Add missed articles by hand')}
        <span className="font-normal text-muted-foreground">
          {' '}{t('— when the crawl did not find everything')}
        </span>
      </summary>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div className="space-y-2">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t('Seed article (whose references/citations were missed)')}
            </label>
            <Select value={seedId === '' ? undefined : String(seedId)}
                    onValueChange={(v) => setSeedId(Number(v))}>
              <SelectTrigger>
                <SelectValue placeholder={t('Choose a crawled seed…')} />
              </SelectTrigger>
              <SelectContent>
                {seeds.map((s) => (
                  <SelectItem key={s.id} value={String(s.id)}>
                    r{s.round} · {(s.author || '?')}{s.year ? ` ${s.year}` : ''} — {s.title.slice(0, 70)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <RadioGroup value={direction} className="flex gap-4"
                      onValueChange={(v) => setDirection(v as 'backward' | 'forward')}>
            <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <RadioGroupItem value="backward" />
              {t('Backward — the seed cites them')}
            </label>
            <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <RadioGroupItem value="forward" />
              {t('Forward — they cite the seed')}
            </label>
          </RadioGroup>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            {t('DOIs (one per line, or separated by commas/spaces)')}
          </label>
          <Textarea value={dois} onChange={(e) => setDois(e.target.value)} rows={3}
                    placeholder={'10.1016/j.example.2020.01.001\n10.1177/0018720819876543'}
                    className="font-mono" />
          <Button onClick={() => add.mutate()}
                  disabled={!seedId || !dois.trim() || add.isPending}
                  className="mt-1">
            {add.isPending ? t('Adding…') : t('Add to the round')}
          </Button>
        </div>
      </div>
      {message && (
        <p className={cn('mt-2 text-xs',
          message.startsWith('✗') ? 'text-destructive' : 'text-success')}>
          {message}
        </p>
      )}
    </details>
  )
}

// Same colorblind-safe hues as the graph; the label always spells the status.
const SB_STATUS: Record<SBArticle['status'], { color: string; label: string }> = {
  seed: { color: 'var(--viz-blue)', label: 'seed' },
  included: { color: 'var(--viz-teal)', label: 'included' },
  excluded: { color: 'var(--viz-orange)', label: 'excluded' },
  pending: { color: 'var(--muted-foreground)', label: 'to screen' },
}
const sbStatusLabel = (status: SBArticle['status']) => i18n.t(SB_STATUS[status].label)

/** Per-round audit table: each crawled seed with its metadata, expandable into
 * Backward (its references) / Forward (papers citing it) article lists. */
function ContributionsTable({ contributions, onOpenCard }: {
  contributions: ContributionRow[]
  onOpenCard: (recordId: number) => void
}) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState<number | null>(null)
  const [tab, setTab] = useState<'backward' | 'forward'>('backward')
  const rounds = [...new Set(contributions.map((c) => c.round))].sort((a, b) => a - b)
  const open = (id: number, preferred: 'backward' | 'forward') => {
    if (expanded === id) { setExpanded(null); return }
    setExpanded(id)
    setTab(preferred)
  }
  return (
    <div className="max-h-[32rem] overflow-y-auto">
      <table className="w-full text-xs">
        <thead className="sticky top-0 z-10 bg-card">
          <tr className="text-left text-muted-foreground">
            <th className="py-1 pr-2 font-medium">{t('seed article')}</th>
            <th className="py-1 pr-2 font-medium">{t('year')}</th>
            <th className="py-1 pr-2 font-medium">DOI</th>
            <th className="py-1 pr-2 font-medium text-right">{t('backward')}</th>
            <th className="py-1 font-medium text-right">{t('forward')}</th>
          </tr>
        </thead>
        <tbody>
          {rounds.map((r) => {
            const seeds = contributions.filter((c) => c.round === r)
            const found = seeds.reduce((s, c) => s + c.n_backward + c.n_forward, 0)
            return [
              <tr key={`round-${r}`} className="border-t border-border bg-muted">
                <td colSpan={5} className="px-2 py-1.5 font-medium text-muted-foreground">
                  {t('Round r{{round}} — {{seeds}} seed(s) crawled, {{found}} paper(s) found',
                     { round: r, seeds: seeds.length, found })}
                </td>
              </tr>,
              ...seeds.map((c) => {
                const isOpen = expanded === c.id
                const list = tab === 'backward' ? c.backward : c.forward
                return [
                  <tr key={c.id}
                      onClick={() => open(c.id, c.n_backward > 0 ? 'backward' : 'forward')}
                      className={cn('cursor-pointer border-t border-border text-muted-foreground hover:bg-accent',
                        isOpen && 'bg-accent')}>
                    <td className="py-1.5 pr-2">
                      <span className="mr-1 text-muted-foreground">{isOpen ? '▾' : '▸'}</span>
                      {c.title.slice(0, 80)}{c.title.length > 80 ? '…' : ''}
                      <span className="text-muted-foreground/70">
                        {' '}— {c.authors[0] ?? c.author}
                        {c.authors.length > 1 ? ' et al.' : ''}
                      </span>
                    </td>
                    <td className="py-1.5 pr-2 tabular-nums">{c.year ?? '—'}</td>
                    <td className="py-1.5 pr-2">
                      {c.doi ? (
                        <a href={`https://doi.org/${c.doi}`} target="_blank" rel="noreferrer"
                           onClick={(e) => e.stopPropagation()}
                           className="font-mono text-primary hover:underline">
                          {c.doi.slice(0, 28)}{c.doi.length > 28 ? '…' : ''}
                        </a>
                      ) : <span className="text-muted-foreground/50">—</span>}
                    </td>
                    <td className="py-1.5 pr-2 tabular-nums text-right">{c.n_backward}</td>
                    <td className="py-1.5 tabular-nums text-right">{c.n_forward}</td>
                  </tr>,
                  isOpen && (
                    <tr key={`${c.id}-detail`} className="bg-muted/50">
                      <td colSpan={5} className="px-3 pb-3 pt-1">
                        <Segmented
                          value={tab}
                          onChange={setTab}
                          className="mb-2"
                          options={[
                            { value: 'backward',
                              label: t('Backward — references ({{count}})', { count: c.n_backward }) },
                            { value: 'forward',
                              label: t('Forward — citing papers ({{count}})', { count: c.n_forward }) },
                          ]}
                        />
                        {list.length === 0 ? (
                          <p className="text-muted-foreground">
                            {t('Nothing found on this side for this seed.')}
                          </p>
                        ) : (
                          <ul className="space-y-1">
                            {list.map((a) => (
                              <li key={a.id} className="flex items-start gap-1.5">
                                <span className="mt-1 inline-block h-2 w-2 shrink-0 rounded-full"
                                      title={sbStatusLabel(a.status)}
                                      style={{ background: SB_STATUS[a.status].color }} />
                                <span className="text-muted-foreground">
                                  <button onClick={() => onOpenCard(a.id)}
                                          title={t("Open this paper's card")}
                                          className="text-left hover:text-primary hover:underline">
                                    {a.title}
                                  </button>
                                  <span className="text-muted-foreground/70">
                                    {' — '}{a.authors[0] ?? '?'}
                                    {a.authors.length > 1 ? ' et al.' : ''}
                                    {a.year ? `, ${a.year}` : ''}
                                    {' · '}{sbStatusLabel(a.status)}
                                  </span>
                                  {a.doi && (
                                    <>
                                      {' · '}
                                      <a href={`https://doi.org/${a.doi}`} target="_blank"
                                         rel="noreferrer"
                                         className="font-mono text-primary hover:underline">
                                        {a.doi}
                                      </a>
                                    </>
                                  )}
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </td>
                    </tr>
                  ),
                ]
              }),
            ]
          })}
        </tbody>
      </table>
    </div>
  )
}
