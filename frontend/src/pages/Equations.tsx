// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Sparkles } from 'lucide-react'
import {
  api, ApiError,
  type Concept, type CostInfo, type DatabaseInfo, type DatabasesInfo,
  type Equation, type GoldenRef, type IdLabel, type Project, type ProposeResult,
  type RecallRow, type TranslationDraft,
} from '../api'
import { useJobWatcher } from '../useJob'
import { findFramework, useFramings } from '@/components/framing'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { Segmented } from '@/components/ui/segmented'

interface DraftEstimate {
  n_targets: number
  available: boolean
  reason?: string
  provider?: string
  model?: string
  cost_label?: string
  targets: string[]
}

/** Rows for a query editor: every line of the text plus one, bounded — a
 * raw protocol equation is 50 lines long and must be readable in full. */
function editorRows(text: string, min = 2, max = 40): number {
  const lines = text.split('\n').reduce((n, l) => n + Math.max(1, Math.ceil(l.length / 100)), 0)
  return Math.min(max, Math.max(min, lines + 1))
}

const LANGUAGES = ['en', 'fr', 'de', 'es', 'it', 'pt', 'nl']
const FIELD_OPTIONS = [
  { id: 'title', label: 'Title' },
  { id: 'abstract', label: 'Abstract' },
  { id: 'keywords', label: 'Keywords' },
]

export default function EquationsPage() {
  const { t } = useTranslation()
  const { projectId } = useParams()
  const pid = Number(projectId)
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'], queryFn: () => api.get('/api/projects'),
  })
  const project = projects.find((p) => p.id === pid)
  const isAdmin = project?.my_role === 'admin'

  const { data: dbInfo } = useQuery<DatabasesInfo>({
    queryKey: ['databases', pid],
    queryFn: () => api.get(`/api/projects/${pid}/equations/databases`),
  })
  const databases = dbInfo?.databases ?? []

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('Search equations')}{project ? ` — ${project.name}` : ''}
      </h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {t('Define concepts and their keywords, build equation variants (OR inside a block, AND between blocks — put two concepts in the same block to OR them), compare result counts across databases, then freeze the final equation.')}
        {' '}
        {t('An equation already written in your protocol can be pasted as is (typed per database) and checked against the golden set on every database.')}
      </p>
      <ResearchQuestionCard project={project} isAdmin={isAdmin} />
      <div className="grid gap-6 xl:grid-cols-[380px_1fr]">
        <div className="space-y-6">
          <ConceptsPanel projectId={pid} isAdmin={isAdmin} />
          <GoldenPanel projectId={pid} isAdmin={isAdmin} />
        </div>
        <VariantsPanel projectId={pid} isAdmin={isAdmin} databases={databases}
                       docTypes={dbInfo?.doc_types ?? []}
                       disciplines={dbInfo?.disciplines ?? []} />
      </div>
    </div>
  )
}

function ResearchQuestionCard({ project, isAdmin }: {
  project: Project | undefined
  isAdmin: boolean
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const projectId = project?.id
  const value = draft ?? project?.research_question ?? ''

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['projects'] })
    queryClient.invalidateQueries({ queryKey: ['concepts', projectId] })
  }
  const save = useMutation({
    mutationFn: () => api.put(`/api/projects/${projectId}`,
      { research_question: value }),
    onSuccess: () => { invalidate(); setDraft(null); setError('') },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const propose = useMutation({
    mutationFn: () =>
      api.post<ProposeResult>(`/api/projects/${projectId}/concepts/propose`),
    onSuccess: (r) => {
      invalidate()
      setDraft(null)
      setError('')
      const costTag = r.cost ? ` ${t('(cost {{cost}})', { cost: r.cost.cost_label })}` : ''
      const parts = []
      if (r.created.length) {
        parts.push(t('AI proposed {{count}} concept(s): {{names}}',
          { count: r.created.length, names: r.created.map((c) => c.name).join(', ') }))
      }
      if (r.enriched.length) {
        parts.push(t('and added keywords to {{names}}',
          { names: r.enriched.map((c) => c.name).join(', ') }))
      }
      setNotice((parts.length
        ? `${parts.join(' ')} — ${t('review and edit below.')}`
        : t('AI updated the research question (nothing to add to the concepts).')) + costTag)
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('AI proposal failed')),
  })

  if (!project) return null

  return (
    <Card className="mb-6 p-4">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-foreground">{t('Research question')}</h2>
        {isAdmin && (
          <div className="flex gap-2">
            <Button
              variant="outline" size="sm"
              onClick={() => propose.mutate()}
              disabled={propose.isPending}
              title={t('Extract the research question from the protocol and pre-identify concepts')}
            >
              {propose.isPending ? t('Asking AI…')
                : <><Sparkles className="size-3.5 text-primary" />{t('Propose from protocol')}</>}
            </Button>
            {draft !== null && draft !== project.research_question && (
              <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
                {t('Save')}
              </Button>
            )}
          </div>
        )}
      </div>
      <Textarea
        value={value}
        readOnly={!isAdmin}
        onChange={(e) => setDraft(e.target.value)}
        placeholder={isAdmin
          ? t('State the research question guiding the equation — or let the AI propose it from the protocol.')
          : t('Not set yet.')}
        rows={2}
      />
      {notice && <p className="mt-1 text-xs text-success">{notice}</p>}
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
    </Card>
  )
}

// ---- concepts -----------------------------------------------------------------

function ConceptsPanel({ projectId, isAdmin }: { projectId: number; isAdmin: boolean }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: concepts = [] } = useQuery<Concept[]>({
    queryKey: ['concepts', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/concepts`),
  })
  const [newName, setNewName] = useState('')
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['concepts', projectId] })

  // the blocks of the equation are not the framework's elements, but naming
  // the framework and its first elements is the cheapest way to orient someone
  // starting from an empty list
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'], queryFn: () => api.get('/api/projects'),
  })
  const { data: framings } = useFramings()
  const framework = findFramework(
    framings, projects.find((p) => p.id === projectId)?.question_framework)
  const examples = (framework?.slots ?? []).slice(0, 3)
    .map((s) => t(s.label)).join(', ')

  const create = useMutation({
    mutationFn: () => api.post(`/api/projects/${projectId}/concepts`,
      { name: newName, keywords: [] }),
    onSuccess: () => { invalidate(); setNewName('') },
  })

  return (
    <Card className="p-4">
      <h2 className="mb-3 text-sm font-semibold text-foreground">
        {t('Concepts')}{' '}
        <span className="font-normal text-muted-foreground">
          {framework && framework.key !== 'free'
            ? t('({{framework}} blocks)', { framework: framework.short })
            : t('(concept blocks)')}
        </span>
      </h2>
      <div className="space-y-3">
        {concepts.map((c) => (
          <ConceptCard key={c.id} projectId={projectId} concept={c}
                       isAdmin={isAdmin} onChange={invalidate} />
        ))}
        {concepts.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {examples
              ? t('No concepts yet — e.g. {{examples}}.', { examples })
              : t('No concepts yet.')}
          </p>
        )}
      </div>
      {isAdmin && (
        <form
          onSubmit={(e) => { e.preventDefault(); create.mutate() }}
          className="mt-3 flex gap-2"
        >
          <Input
            required value={newName} placeholder={t('New concept name')}
            onChange={(e) => setNewName(e.target.value)}
            className="min-w-0 flex-1"
          />
          <Button type="submit" disabled={create.isPending}>{t('Add')}</Button>
        </form>
      )}
    </Card>
  )
}

function ConceptCard({ projectId, concept, isAdmin, onChange }: {
  projectId: number
  concept: Concept
  isAdmin: boolean
  onChange: () => void
}) {
  const { t } = useTranslation()
  const base = `/api/projects/${projectId}/concepts/${concept.id}`
  const [kw, setKw] = useState('')
  const [meshQ, setMeshQ] = useState('')
  const [meshTerms, setMeshTerms] = useState<string[] | null>(null)
  const [error, setError] = useState('')

  const save = useMutation({
    mutationFn: (keywords: string[]) =>
      api.put(base, { name: concept.name, description: concept.description, keywords }),
    onSuccess: onChange,
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const [suggestCost, setSuggestCost] = useState<CostInfo | null>(null)
  const suggest = useMutation({
    mutationFn: () => api.post<{ cost?: CostInfo }>(`${base}/suggest`),
    onSuccess: (r) => { setError(''); setSuggestCost(r.cost ?? null); onChange() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Suggestion failed')),
  })
  const remove = useMutation({ mutationFn: () => api.del(base), onSuccess: onChange })

  const addKeyword = (value: string) => {
    const v = value.trim()
    if (v) save.mutate([...concept.keywords, v])
  }
  const mesh = async () => {
    setMeshTerms(null)
    try {
      const r = await api.get<{ terms: string[] }>(
        `/api/projects/${projectId}/concepts/mesh/lookup?q=${encodeURIComponent(meshQ)}`)
      setMeshTerms(r.terms)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('MeSH lookup failed'))
    }
  }

  return (
    <div className="rounded-lg border border-border p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium text-foreground">{concept.name}</span>
        {isAdmin && (
          <div className="flex items-center gap-2">
            <button onClick={() => suggest.mutate()} disabled={suggest.isPending}
                    title={suggestCost ? t('Last AI synonyms call cost {{cost}} ({{model}})', { cost: suggestCost.cost_label, model: suggestCost.model }) : undefined}
                    className="inline-flex items-center gap-1 text-xs text-primary hover:underline disabled:opacity-50">
              {suggest.isPending ? t('Asking AI…')
                : <><Sparkles className="size-3.5" />{t('AI synonyms')}</>}
              {suggestCost && <span className="text-muted-foreground"> {suggestCost.cost_label}</span>}
            </button>
            <button onClick={() => remove.mutate()}
                    className="text-muted-foreground hover:text-destructive" title={t('Delete concept')}>✕</button>
          </div>
        )}
      </div>
      <div className="mb-2 flex flex-wrap gap-1">
        {concept.keywords.map((k) => (
          <Badge key={k} variant="default" className="gap-1">
            {k}
            {isAdmin && (
              <button
                onClick={() => save.mutate(concept.keywords.filter((x) => x !== k))}
                className="text-muted-foreground hover:text-destructive"
              >×</button>
            )}
          </Badge>
        ))}
        {concept.keywords.length === 0 && (
          <span className="text-xs text-muted-foreground">{t('no keywords yet')}</span>
        )}
      </div>
      {isAdmin && (
        <>
          <form onSubmit={(e) => { e.preventDefault(); addKeyword(kw); setKw('') }}
                className="mb-1 flex gap-1">
            <Input
              value={kw} placeholder={t('Add keyword…')}
              onChange={(e) => setKw(e.target.value)}
              className="h-8 min-w-0 flex-1 text-xs"
            />
            <Button type="submit" variant="outline" size="sm">+</Button>
          </form>
          <form onSubmit={(e) => { e.preventDefault(); mesh() }} className="flex gap-1">
            <Input
              value={meshQ} placeholder={t('MeSH lookup…')}
              onChange={(e) => setMeshQ(e.target.value)}
              className="h-8 min-w-0 flex-1 text-xs"
            />
            <Button type="submit" variant="outline" size="sm"
                    disabled={meshQ.trim().length < 3}>
              MeSH
            </Button>
          </form>
          {meshTerms && (
            <div className="mt-1 flex flex-wrap gap-1">
              {meshTerms.length === 0 && <span className="text-xs text-muted-foreground">{t('no match')}</span>}
              {meshTerms.map((t) => (
                <button key={t} onClick={() => addKeyword(t)}
                        className="rounded-full border border-input px-2 py-0.5 text-xs text-foreground hover:bg-accent">
                  + {t}
                </button>
              ))}
            </div>
          )}
        </>
      )}
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
    </div>
  )
}

// ---- golden set -----------------------------------------------------------------

function GoldenPanel({ projectId, isAdmin }: { projectId: number; isAdmin: boolean }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: refs = [] } = useQuery<GoldenRef[]>({
    queryKey: ['golden', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/golden`),
  })
  const [identifier, setIdentifier] = useState('')
  const [bulk, setBulk] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['golden', projectId] })

  const add = useMutation({
    mutationFn: () => api.post(`/api/projects/${projectId}/golden`, { identifier }),
    onSuccess: () => { invalidate(); setIdentifier(''); setError('') },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Add failed')),
  })
  const addBulk = useMutation({
    mutationFn: () => api.post<{ added: number; rejected: string[] }>(
      `/api/projects/${projectId}/golden/bulk`, { identifiers: bulk }),
    onSuccess: (r) => {
      invalidate(); setBulk(''); setError('')
      setNotice(r.rejected.length
        ? t('{{count}} added — not recognised: {{rejected}}', { count: r.added, rejected: r.rejected.join(', ') })
        : t('{{count}} added', { count: r.added }))
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Add failed')),
  })

  return (
    <Card className="p-4">
      <h2 className="mb-1 text-sm font-semibold text-foreground">{t('Golden set')}</h2>
      <p className="mb-3 text-xs text-muted-foreground">
        {t('Reference articles every good equation should retrieve, by DOI or PMID — each variant is checked against them on every database (API where it supports it, otherwise on the records you import).')}
      </p>
      <ul className="mb-3 space-y-2">
        {refs.map((r) => (
          <li key={r.id} className="flex items-start justify-between text-xs text-muted-foreground">
            <span>
              {r.apa || r.title || <span className="font-mono">{r.doi ?? r.pmid}</span>}
              {(r.apa || r.title) && (
                <span className="font-mono text-muted-foreground/70"> {r.doi ?? ''}{r.pmid ? ` PMID ${r.pmid}` : ''}</span>
              )}
            </span>
            {isAdmin && (
              <button
                onClick={() => api.del(`/api/projects/${projectId}/golden/${r.id}`).then(invalidate)}
                className="ml-2 shrink-0 text-muted-foreground hover:text-destructive"
                title={t('Remove reference')}
              >✕</button>
            )}
          </li>
        ))}
        {refs.length === 0 && <li className="text-xs text-muted-foreground">{t('empty')}</li>}
      </ul>
      {isAdmin && (
        <>
          <form onSubmit={(e) => { e.preventDefault(); add.mutate() }} className="flex gap-1">
            <Input
              required value={identifier} placeholder={t('DOI or PMID')}
              onChange={(e) => setIdentifier(e.target.value)}
              className="h-8 min-w-0 flex-1 font-mono text-xs"
              aria-label={t('DOI or PMID')}
            />
            <Button type="submit" variant="outline" size="sm" disabled={add.isPending}>
              {t('Add')}
            </Button>
          </form>
          <details className="mt-2 text-xs">
            <summary className="cursor-pointer text-muted-foreground">{t('Add several at once')}</summary>
            <form onSubmit={(e) => { e.preventDefault(); addBulk.mutate() }} className="mt-1 space-y-1">
              <Textarea
                value={bulk} rows={4} placeholder={t('One DOI or PMID per line')}
                onChange={(e) => setBulk(e.target.value)}
                className="font-mono text-xs"
                aria-label={t('One DOI or PMID per line')}
              />
              <Button type="submit" variant="outline" size="sm"
                      disabled={addBulk.isPending || !bulk.trim()}>
                {addBulk.isPending ? t('Adding…') : t('Add all')}
              </Button>
            </form>
          </details>
        </>
      )}
      {notice && <p className="mt-1 text-xs text-success">{notice}</p>}
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
    </Card>
  )
}

// ---- variants -------------------------------------------------------------------

function VariantsPanel({ projectId, isAdmin, databases, docTypes, disciplines }: {
  projectId: number
  isAdmin: boolean
  databases: DatabaseInfo[]
  docTypes: IdLabel[]
  disciplines: IdLabel[]
}) {
  const queryClient = useQueryClient()
  const { data: equations = [] } = useQuery<Equation[]>({
    queryKey: ['equations', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/equations`),
  })
  const { data: concepts = [] } = useQuery<Concept[]>({
    queryKey: ['concepts', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/concepts`),
  })
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['equations', projectId] })

  return (
    <section className="space-y-4">
      {isAdmin && <NewVariantForm projectId={projectId} concepts={concepts}
                                  databases={databases}
                                  docTypes={docTypes} disciplines={disciplines}
                                  onCreated={invalidate} />}
      {isAdmin && equations.length >= 1 && <AdviceCard projectId={projectId} />}
      {equations.map((eq) => (
        <VariantCard key={eq.id} projectId={projectId} equation={eq}
                     databases={databases} isAdmin={isAdmin} onChange={invalidate} />
      ))}
      {equations.length === 0 && (
        <Card className="p-6 text-sm text-muted-foreground">
          <NoVariantNotice />
        </Card>
      )}
    </section>
  )
}

function NoVariantNotice() {
  const { t } = useTranslation()
  return <>{t('No equation variant yet — add concepts with keywords, then create a variant.')}</>
}

interface Advice {
  recommended_label: string
  rationale: string
  per_variant: { label: string; verdict: string }[]
  improvements: string[]
  cost?: CostInfo | null
}

/** One LLM call on the search strategy, available from the FIRST variant:
 * critiques a lone variant (or compares several), mining the golden
 * references' titles/abstracts for missing terminology — with the refs each
 * variant missed at its golden check. Advice only — nothing is changed. */
function AdviceCard({ projectId }: { projectId: number }) {
  const { t } = useTranslation()
  const [advice, setAdvice] = useState<Advice | null>(null)
  const [error, setError] = useState('')
  const ask = useMutation({
    mutationFn: () => api.post<Advice>(`/api/projects/${projectId}/equations/advise`),
    onSuccess: (r) => { setAdvice(r); setError('') },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Advice failed')),
  })

  return (
    <Card className="p-4">
      <div className="flex items-center gap-3">
        <h2 className="flex-1 text-sm font-semibold text-foreground">
          {t('AI advice on the strategy')}
          <span className="font-normal text-muted-foreground">
            {' '}{t('— from your first variant on: critique & improvements, or a comparison once several are tested, mining the golden references (incl. the ones your equation misses) for terminology')}
          </span>
        </h2>
        <Button variant="outline" size="sm" onClick={() => ask.mutate()} disabled={ask.isPending}>
          {ask.isPending ? t('Analysing…')
            : <><Sparkles className="size-3.5 text-primary" />{t('Get advice')}</>}
        </Button>
        {advice?.cost && (
          <span className="text-xs text-muted-foreground"
                title={`${advice.cost.model} · ${advice.cost.tokens_in} in / ${advice.cost.tokens_out} out`}>
            {t('cost {{cost}}', { cost: advice.cost.cost_label })}
          </span>
        )}
      </div>
      {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
      {advice && (
        <div className="mt-3 space-y-2 rounded-md border border-border border-l-2 border-l-primary bg-accent p-3 text-sm">
          {advice.recommended_label && (
            <p className="font-medium text-foreground">
              {t('Recommended: “{{label}}”', { label: advice.recommended_label })}
            </p>
          )}
          <p className="text-foreground">{advice.rationale}</p>
          {advice.per_variant.length > 0 && (
            <ul className="space-y-1">
              {advice.per_variant.map((v) => (
                <li key={v.label} className="text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">{v.label}:</span> {v.verdict}
                </li>
              ))}
            </ul>
          )}
          {advice.improvements.length > 0 && (
            <div className="text-xs text-muted-foreground">
              <p className="font-medium text-foreground">{t('Suggested improvements:')}</p>
              <ul className="ml-4 list-disc space-y-0.5">
                {advice.improvements.map((s, i) => <li key={i}>{s}</li>)}
              </ul>
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            {t('Advice only — self-assessed by the model, verify against your own testing before freezing.')}
          </p>
        </div>
      )}
    </Card>
  )
}

function NewVariantForm({ projectId, concepts, databases, docTypes, disciplines, onCreated }: {
  projectId: number
  concepts: Concept[]
  databases: DatabaseInfo[]
  docTypes: IdLabel[]
  disciplines: IdLabel[]
  onCreated: () => void
}) {
  const { t } = useTranslation()
  const [mode, setMode] = useState<'concepts' | 'raw'>('concepts')
  const [label, setLabel] = useState('')
  // raw mode: the protocol's own query, typed for one database to start with
  // (the other databases are typed or AI-drafted on the variant card)
  const [rawDb, setRawDb] = useState('pubmed')
  const [rawQuery, setRawQuery] = useState('')
  const [rawError, setRawError] = useState('')
  // the other databases the review searches are AI-drafted right after
  // creation (one call each, in the background) unless unticked
  const [autoDraft, setAutoDraft] = useState(true)
  const otherDbs = databases.filter((d) => d.id !== rawDb)
  const { data: estimate } = useQuery<DraftEstimate>({
    queryKey: ['draft-estimate', projectId, rawDb, Math.round(rawQuery.length / 200)],
    queryFn: () => api.get(`/api/projects/${projectId}/equations/draft-estimate?from_db=${rawDb}&chars=${rawQuery.length}`),
    enabled: mode === 'raw' && autoDraft && rawQuery.trim().length > 0,
    staleTime: 60_000,
  })
  const draftJob = useJobWatcher(onCreated)
  const createRaw = useMutation({
    mutationFn: async () => {
      const eq = await api.post<Equation>(`/api/projects/${projectId}/equations`, {
        label, mode: 'raw', translations: { [rawDb]: rawQuery },
      })
      if (autoDraft && otherDbs.length > 0) {
        const r = await api.post<{ job_id: number | null }>(
          `/api/projects/${projectId}/equations/${eq.id}/translations/draft-all`,
          { from_db: rawDb, mode: 'missing' })
        if (r.job_id != null) draftJob.watch(r.job_id)
      }
    },
    onSuccess: () => { onCreated(); setLabel(''); setRawQuery(''); setRawError('') },
    onError: (e) => setRawError(e instanceof ApiError ? e.message : t('Creation failed')),
  })
  if (mode === 'raw') {
    return (
      <Card className="p-4">
        <form onSubmit={(e) => { e.preventDefault(); createRaw.mutate() }} className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-sm font-semibold text-foreground">{t('New variant')}</h2>
            <ModeToggle mode={mode} onChange={setMode} />
          </div>
          <p className="text-xs text-muted-foreground">
            {t('Paste the equation exactly as your protocol states it for one database. The concept builder is not used: what you type is what runs, is counted, and is quoted in the search report.')}
          </p>
          <div className="flex flex-wrap gap-2">
            <Input
              required value={label} placeholder={t('Label (e.g. "Eq. 6")')}
              onChange={(e) => setLabel(e.target.value)}
              className="min-w-40 flex-1"
            />
            <select
              value={rawDb} onChange={(e) => setRawDb(e.target.value)}
              aria-label={t('Database of this query')}
              className="h-9 rounded-md border border-input bg-background px-2 text-sm"
            >
              {databases.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
            </select>
          </div>
          <Textarea
            required value={rawQuery}
            onChange={(e) => setRawQuery(e.target.value)}
            rows={editorRows(rawQuery, 8)}
            placeholder={t('("emergency driving"[tiab] OR …) AND (stress[tiab] OR …)')}
            className="font-mono text-xs"
            aria-label={t('Query')}
          />
          {otherDbs.length > 0 && (
            <label className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <Checkbox checked={autoDraft} onCheckedChange={(v) => setAutoDraft(!!v)} />
              {t('Pre-fill the other databases by AI ({{count}} databases, one call each)', { count: otherDbs.length })}
              {autoDraft && estimate && (
                <span className="text-muted-foreground/80">
                  {estimate.available
                    ? t('— about {{cost}} with {{model}}; every draft stays marked until you review it', { cost: estimate.cost_label, model: estimate.model })
                    : t('— no AI provider configured: the other databases will stay empty')}
                </span>
              )}
            </label>
          )}
          <Button type="submit" disabled={createRaw.isPending || !rawQuery.trim()}>
            {t('Create variant')}
          </Button>
          {draftJob.state && <p className="text-xs text-muted-foreground">{draftJob.state}</p>}
          {draftJob.error && <p className="text-xs text-destructive">{draftJob.error}</p>}
          {rawError && <p className="text-sm text-destructive">{rawError}</p>}
        </form>
      </Card>
    )
  }
  return <ConceptVariantForm projectId={projectId} concepts={concepts} docTypes={docTypes}
                             disciplines={disciplines} onCreated={onCreated}
                             mode={mode} onMode={setMode} />
}

function ModeToggle({ mode, onChange }: {
  mode: 'concepts' | 'raw'
  onChange: (m: 'concepts' | 'raw') => void
}) {
  const { t } = useTranslation()
  return (
    <Segmented size="sm" value={mode} onChange={onChange} options={[
      { value: 'concepts', label: t('from concepts'),
        title: t('Build the equation from the concept blocks; every database syntax is generated') },
      { value: 'raw', label: t('typed per database'),
        title: t('Paste an equation written elsewhere (e.g. in the protocol); one text per database') },
    ]} />
  )
}

function ConceptVariantForm({ projectId, concepts, docTypes, disciplines, onCreated, mode, onMode }: {
  projectId: number
  concepts: Concept[]
  docTypes: IdLabel[]
  disciplines: IdLabel[]
  onCreated: () => void
  mode: 'concepts' | 'raw'
  onMode: (m: 'concepts' | 'raw') => void
}) {
  const { t } = useTranslation()
  const [label, setLabel] = useState('')
  // concept id -> block number (0 = not in the equation). Concepts sharing a
  // block are OR-ed together; blocks are AND-ed.
  const [blockOf, setBlockOf] = useState<Record<number, number>>({})
  const [yearFrom, setYearFrom] = useState('')
  const [yearTo, setYearTo] = useState('')
  const [languages, setLanguages] = useState<string[]>([])
  const [fields, setFields] = useState<string[]>(['title', 'abstract'])
  const [selectedTypes, setSelectedTypes] = useState<string[]>([])
  const [selectedDisciplines, setSelectedDisciplines] = useState<string[]>([])
  const [error, setError] = useState('')

  // include newly created concepts by default, each in its own block
  useEffect(() => {
    setBlockOf(Object.fromEntries(concepts.map((c, i) => [c.id, i + 1])))
  }, [concepts.length])  // eslint-disable-line

  // blocks in ascending order, each holding the ids assigned to it (block
  // numbers can be sparse after de-selecting a concept — the UI numbers them
  // by position, so the user always sees "block 1, 2, 3…")
  const blockNumbers = [...new Set(concepts.map((c) => blockOf[c.id] ?? 0))]
    .filter((n) => n > 0).sort((a, b) => a - b)
  const groups = blockNumbers.map((n) =>
    concepts.filter((c) => blockOf[c.id] === n).map((c) => c.id))
  const nextBlock = Math.max(0, ...concepts.map((c) => blockOf[c.id] ?? 0)) + 1
  const preview = groups
    .map((ids) => {
      const names = ids.map((id) => concepts.find((c) => c.id === id)?.name ?? '')
      return names.length > 1 ? `(${names.join(' OR ')})` : names[0]
    })
    .join(' AND ')

  const create = useMutation({
    mutationFn: () => api.post(`/api/projects/${projectId}/equations`, {
      label,
      groups,
      params: {
        year_from: yearFrom ? Number(yearFrom) : null,
        year_to: yearTo ? Number(yearTo) : null,
        languages,
        fields,
        doc_types: selectedTypes,
        disciplines: selectedDisciplines,
      },
    }),
    onSuccess: () => { onCreated(); setLabel(''); setError('') },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Creation failed')),
  })

  const optionRow = 'flex items-center gap-1.5 text-sm text-muted-foreground'

  return (
    <Card className="p-4">
      <form
        onSubmit={(e) => { e.preventDefault(); create.mutate() }}
        className="space-y-3"
      >
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-sm font-semibold text-foreground">{t('New variant')}</h2>
          <ModeToggle mode={mode} onChange={onMode} />
        </div>
        <div className="flex flex-wrap gap-2">
          <Input
            required value={label} placeholder={t('Label (e.g. "standard", "broad")')}
            onChange={(e) => setLabel(e.target.value)}
            className="min-w-40 flex-1"
          />
          <Input
            type="number" value={yearFrom} placeholder={t('From year')}
            onChange={(e) => setYearFrom(e.target.value)}
            className="w-28"
          />
          <Input
            type="number" value={yearTo} placeholder={t('To year')}
            onChange={(e) => setYearTo(e.target.value)}
            className="w-28"
          />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs text-muted-foreground"
                title={t('Concepts in the same block are OR-ed; blocks are AND-ed')}>
            {t('Concepts:')}
          </span>
          {concepts.map((c) => (
            <span key={c.id} className={optionRow}>
              <Checkbox
                checked={(blockOf[c.id] ?? 0) > 0}
                onCheckedChange={(v) =>
                  setBlockOf({ ...blockOf, [c.id]: v ? nextBlock : 0 })}
              />
              {c.name}
              {(blockOf[c.id] ?? 0) > 0 && (
                <select
                  value={blockOf[c.id]}
                  onChange={(e) =>
                    setBlockOf({ ...blockOf, [c.id]: Number(e.target.value) })}
                  title={t('Block this concept belongs to — same block = OR')}
                  className="h-6 rounded border border-border bg-background px-1 text-xs"
                >
                  {blockNumbers.map((n, i) => (
                    <option key={n} value={n}>{t('block {{n}}', { n: i + 1 })}</option>
                  ))}
                  {groups.some((ids) => ids.length > 1 && ids.includes(c.id)) && (
                    <option value={nextBlock}>{t('own block')}</option>
                  )}
                </select>
              )}
            </span>
          ))}
          <span className="text-xs text-border">|</span>
          <span className="text-xs text-muted-foreground" title={t('Where the equation searches — syntax adapted per database')}>
            {t('Search in:')}
          </span>
          {FIELD_OPTIONS.map((f) => (
            <label key={f.id} className={optionRow}>
              <Checkbox
                checked={fields.includes(f.id)}
                onCheckedChange={(v) =>
                  setFields(v
                    ? [...fields, f.id]
                    : fields.filter((x) => x !== f.id))}
              />
              {t(f.label)}
            </label>
          ))}
          <span className="text-xs text-border">|</span>
          <span className="text-xs text-muted-foreground">{t('Languages:')}</span>
          {LANGUAGES.map((l) => (
            <label key={l} className={optionRow}>
              <Checkbox
                checked={languages.includes(l)}
                onCheckedChange={(v) =>
                  setLanguages(v
                    ? [...languages, l]
                    : languages.filter((x) => x !== l))}
              />
              {l}
            </label>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs text-muted-foreground"
                title={t('Applied where the database supports it (PubMed, OpenAlex, S2, Crossref, WoS, Scopus)')}>
            {t('Doc types:')}
          </span>
          {docTypes.map((t) => (
            <label key={t.id} className={optionRow}>
              <Checkbox
                checked={selectedTypes.includes(t.id)}
                onCheckedChange={(v) =>
                  setSelectedTypes(v
                    ? [...selectedTypes, t.id]
                    : selectedTypes.filter((x) => x !== t.id))}
              />
              {t.label}
            </label>
          ))}
          <span className="text-xs text-muted-foreground">{t('(none = all types)')}</span>
        </div>
        <details className="text-sm">
          <summary className="cursor-pointer text-muted-foreground">
            {t('Disciplines to prioritize')}
            {selectedDisciplines.length > 0 && (
              <Badge variant="default" className="ml-1">
                {selectedDisciplines.length}
              </Badge>
            )}
            <span className="ml-2 text-xs text-muted-foreground">
              {t('(OpenAlex/S2/Scopus/WoS where supported; none = all)')}
            </span>
          </summary>
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
            {disciplines.map((d) => (
              <label key={d.id} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Checkbox
                  checked={selectedDisciplines.includes(d.id)}
                  onCheckedChange={(v) =>
                    setSelectedDisciplines(v
                      ? [...selectedDisciplines, d.id]
                      : selectedDisciplines.filter((x) => x !== d.id))}
                />
                {d.label}
              </label>
            ))}
          </div>
        </details>
        {preview && (
          <p className="font-mono text-xs text-muted-foreground">{preview}</p>
        )}
        <Button
          type="submit"
          disabled={create.isPending || groups.length === 0 || fields.length === 0}
        >
          {t('Create variant')}
        </Button>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </form>
    </Card>
  )
}

function VariantCard({ projectId, equation, databases, isAdmin, onChange }: {
  projectId: number
  equation: Equation
  databases: DatabaseInfo[]
  isAdmin: boolean
  onChange: () => void
}) {
  const { t } = useTranslation()
  const base = `/api/projects/${projectId}/equations/${equation.id}`
  const jobs = useJobWatcher(onChange)
  const [error, setError] = useState('')
  const frozen = equation.status === 'frozen'
  const editable = isAdmin && !frozen

  const latestCounts: Record<string, { count: number; method: string }> = {}
  for (const c of equation.counts) {
    latestCounts[c.database_name] = { count: c.count, method: c.method }
  }

  const act = async (fn: () => Promise<unknown>) => {
    try { await fn(); setError('') } catch (e) {
      setError(e instanceof ApiError ? e.message : t('Action failed'))
    }
  }
  const runCounts = () => act(async () => {
    const { job_id } = await api.post<{ job_id: number }>(`${base}/counts`, {})
    jobs.watch(job_id)
  })
  const goldenCheck = () => act(async () => {
    const { job_id } = await api.post<{ job_id: number }>(`${base}/golden-check`, {})
    jobs.watch(job_id)
  })
  const duplicate = () => act(() => api.post(`${base}/duplicate`).then(onChange))

  const golden = equation.golden_results
  const raw = equation.mode === 'raw'
  const concepts = equation.structure.concepts ?? []
  const recall = equation.recall ?? []
  const recallFor = (dbId: string) => recall.filter((r) => r.database_name === dbId)
  // raw variant: which searched databases still have no query, and the
  // database to draft them from (the first one with a typed query)
  const queryOf = (id: string) =>
    (equation.translations.overrides[id] ?? equation.translations.auto[id] ?? '').trim()
  const missing = raw ? databases.filter((d) => !queryOf(d.id)) : []
  const sourceDb = raw ? databases.find((d) => queryOf(d.id) && !equation.translations.drafts?.[d.id]) ?? databases.find((d) => queryOf(d.id)) : undefined
  const draftMissing = () => act(async () => {
    const r = await api.post<{ job_id: number | null }>(
      `${base}/translations/draft-all`, { from_db: sourceDb!.id, mode: 'missing' })
    if (r.job_id != null) jobs.watch(r.job_id)
  })

  return (
    <Card className="p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="font-semibold text-foreground">{equation.label}</h3>
        <Badge variant={frozen ? 'default' : 'outline'}>
          {frozen ? t('frozen {{date}}', { date: new Date(equation.frozen_at!).toLocaleDateString() }) : t('draft')}
        </Badge>
        {raw && (
          <Badge variant="outline" title={t('Typed per database — the concept builder is not used')}>
            {t('typed')}
          </Badge>
        )}
        <span className="text-xs text-muted-foreground">
          {concepts
            .map((c) => ((c.members?.length ?? 1) > 1 ? `(${c.name})` : c.name))
            .join(' AND ')}
          {equation.params.year_from || equation.params.year_to
            ? ` · ${equation.params.year_from ?? '…'}-${equation.params.year_to ?? '…'}` : ''}
          {equation.params.languages?.length ? ` · ${equation.params.languages.join(',')}` : ''}
          {!raw && equation.params.fields?.length ? ` · in: ${equation.params.fields.join('+')}` : ''}
          {equation.params.doc_types?.length ? ` · types: ${equation.params.doc_types.join(',')}` : ''}
          {equation.params.disciplines?.length ? ` · disc: ${equation.params.disciplines.join(',').toUpperCase()}` : ''}
        </span>
        <span className="flex-1" />
        {isAdmin && (
          <>
            <Button variant="outline" size="sm" onClick={runCounts} disabled={!!jobs.state}>
              {t('Run API counts')}
            </Button>
            <Button variant="outline" size="sm" onClick={goldenCheck} disabled={!!jobs.state}
                    title={t('Golden-set recall on every database: asked through the API where it supports it, looked up in your imports elsewhere')}>
              {t('Check recall')}
            </Button>
            <Button variant="outline" size="sm" onClick={duplicate}
                    title={t('A new draft with the same queries (e.g. "Eq. 6 bis" from "Eq. 6")')}>
              {t('Duplicate')}
            </Button>
            {editable && missing.length > 0 && sourceDb && (
              <Button variant="outline" size="sm" onClick={draftMissing} disabled={!!jobs.state}
                      title={t('One AI call per database without a query, drafted from the {{database}} text; each draft stays marked until you review it', { database: sourceDb.label })}>
                <Sparkles className="size-3.5 text-primary" />
                {t('Draft {{count}} missing by AI', { count: missing.length })}
              </Button>
            )}
            {!frozen && (
              <Button size="sm"
                      onClick={() => act(() => api.post(`${base}/freeze`).then(onChange))}>
                {t('Freeze')}
              </Button>
            )}
            {!frozen && (
              <button
                onClick={() => act(() => api.del(base).then(onChange))}
                className="text-muted-foreground hover:text-destructive" title={t('Delete variant')}
              >✕</button>
            )}
          </>
        )}
      </div>

      {recall.length > 0 ? (
        <RecallSummary recall={recall} />
      ) : golden && (
        <p className="mb-2 text-xs text-muted-foreground">
          {t('Golden set:')} <span className={cn('font-medium tabular-nums',
            golden.found === golden.total ? 'text-success' : 'text-warning')}>
            {t('{{found}}/{{total}} found', { found: golden.found, total: golden.total })}
          </span>{' '}
          <span className="text-muted-foreground">
            (OpenAlex, {new Date(golden.checked_at).toLocaleString()})
          </span>
          {golden.found_refs && golden.found_refs.length > 0 && (
            <span className="text-muted-foreground"> {t('— retrieved: {{refs}}', { refs: golden.found_refs.map((r) => r.citation).join('; ') })}</span>
          )}
          {golden.missing.length > 0 && (
            <span className="text-muted-foreground"> {t('— missing: {{dois}}', { dois: golden.missing.join(', ') })}</span>
          )}
        </p>
      )}
      {jobs.state && <p className="mb-2 text-xs text-muted-foreground">{jobs.state}</p>}
      {(error || jobs.error) && (
        <p className="mb-2 text-xs text-destructive">{error || jobs.error}</p>
      )}

      <div className="divide-y divide-border">
        {databases.map((db) => (
          <DatabaseRow key={db.id} base={base} db={db} equation={equation}
                       databases={databases}
                       latest={latestCounts[db.id]} recall={recallFor(db.id)}
                       editable={editable} isAdmin={isAdmin} onChange={onChange} />
        ))}
      </div>
    </Card>
  )
}

/** "AI draft, not reviewed" (amber) or "AI draft, reviewed" (muted): the
 * provenance of a query the model wrote from another database's text. */
export function DraftBadge({ draft }: { draft: TranslationDraft }) {
  const { t } = useTranslation()
  return (
    <Badge variant={draft.validated ? 'outline' : 'warning'}
           title={`${t('drafted by {{model}} from {{database}}', { model: draft.model, database: draft.from_db })} · ${new Date(draft.at).toLocaleString()}`}>
      {draft.validated ? t('AI draft, reviewed') : t('AI draft, not reviewed')}
    </Badge>
  )
}

/** One chip per (database, method): "3/3" green, "2/3" amber, with the
 * missed references in the tooltip — the protocol's acceptance test. */
function RecallChip({ row }: { row: RecallRow }) {
  const { t } = useTranslation()
  const missed = row.missing.map((m) => m.citation || m.doi || m.pmid).join('; ')
  return (
    <span
      className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs tabular-nums',
        row.found === row.total ? 'border-success/40 text-success' : 'border-warning/40 text-warning')}
      title={`${row.method === 'api' ? t('asked through the API') : t('looked up in the imported records')} · ${new Date(row.checked_at).toLocaleString()}${missed ? ` · ${t('missing: {{refs}}', { refs: missed })}` : ''}`}
    >
      {row.found}/{row.total}
      <span className="text-muted-foreground">{row.method === 'api' ? 'API' : t('import')}</span>
    </span>
  )
}

function RecallSummary({ recall }: { recall: RecallRow[] }) {
  const { t } = useTranslation()
  return (
    <div className="mb-2 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
      <span>{t('Golden set:')}</span>
      {recall.map((r) => (
        <span key={`${r.database_name}-${r.method}`} className="inline-flex items-center gap-1">
          <span className="text-foreground">{r.database_name}</span>
          <RecallChip row={r} />
        </span>
      ))}
    </div>
  )
}

function DatabaseRow({ base, db, equation, databases, latest, recall, editable, isAdmin, onChange }: {
  base: string
  db: DatabaseInfo
  equation: Equation
  databases: DatabaseInfo[]
  latest?: { count: number; method: string }
  recall: RecallRow[]
  editable: boolean
  isAdmin: boolean
  onChange: () => void
}) {
  const { t } = useTranslation()
  const raw = equation.mode === 'raw'
  const auto = equation.translations.auto[db.id] ?? ''
  const override = equation.translations.overrides[db.id]
  const effective = override ?? auto
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<string | null>(null)
  const [manualCount, setManualCount] = useState('')
  const [error, setError] = useState('')
  const [notes, setNotes] = useState<string[]>([])
  // databases with a query this one could be drafted from (raw mode)
  const sources = databases.filter((d) => d.id !== db.id
    && (equation.translations.overrides[d.id] ?? equation.translations.auto[d.id] ?? '').trim())
  const [fromDb, setFromDb] = useState('')
  const source = sources.find((d) => d.id === fromDb) ?? sources[0]

  const saveOverride = useMutation({
    mutationFn: (query: string) => api.put(`${base}/override`, { database: db.id, query }),
    onSuccess: () => { setDraft(null); setError(''); setNotes([]); onChange() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const aiDraft = equation.translations.drafts?.[db.id]
  const validate = useMutation({
    mutationFn: () => api.post(`${base}/translations/validate`, { database: db.id }),
    onSuccess: () => { setError(''); onChange() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const saveManual = useMutation({
    mutationFn: () => api.post(`${base}/counts/manual`,
      { database: db.id, count: Number(manualCount) }),
    onSuccess: () => { setManualCount(''); setError(''); onChange() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const draftWithAi = useMutation({
    mutationFn: () => api.post<{ query: string; notes: string[]; cost?: CostInfo | null }>(
      `${base}/translations/draft`, { from_db: source!.id, to_db: db.id }),
    onSuccess: (r) => {
      setDraft(r.query); setError('')
      setNotes([...r.notes, ...(r.cost ? [t('cost {{cost}}', { cost: r.cost.cost_label })] : [])])
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Draft failed')),
  })

  return (
    <div className="py-2">
      <div className="flex items-center gap-2">
        <button onClick={() => setOpen((v) => !v)}
                className="text-sm font-medium text-foreground hover:text-primary">
          {open ? '▾' : '▸'} {db.label}
        </button>
        {override !== undefined && !raw && (
          <Badge variant="warning">{t('edited')}</Badge>
        )}
        {raw && !effective.trim() && (
          <span className="text-xs text-muted-foreground">{t('not typed yet')}</span>
        )}
        {aiDraft && <DraftBadge draft={aiDraft} />}
        {recall.map((r) => <RecallChip key={r.method} row={r} />)}
        <span className="flex-1" />
        {latest ? (
          <span className="text-sm text-foreground tabular-nums">
            {latest.count.toLocaleString()}
            <span className="text-xs text-muted-foreground"> ({latest.method})</span>
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">{t('no count')}</span>
        )}
      </div>
      {open && (
        <div className="mt-2 space-y-2">
          <Textarea
            value={draft ?? effective}
            readOnly={!editable}
            onChange={(e) => setDraft(e.target.value)}
            rows={editorRows(draft ?? effective, 2, raw ? 40 : 12)}
            className="font-mono text-xs"
            aria-label={t('{{database}} query', { database: db.label })}
          />
          {(notes.length > 0 || (aiDraft?.notes.length ?? 0) > 0) && (
            <ul className="text-xs text-muted-foreground">
              {(notes.length ? notes : aiDraft!.notes).map((n, i) => <li key={i}>• {n}</li>)}
            </ul>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline" size="sm"
              onClick={() => navigator.clipboard.writeText(draft ?? effective)}
            >
              {t('Copy')}
            </Button>
            {isAdmin && aiDraft && !aiDraft.validated && draft === null && (
              <Button size="sm" onClick={() => validate.mutate()} disabled={validate.isPending}
                      title={t('You read this AI draft and keep it as the query of this database')}>
                {t('Validate draft')}
              </Button>
            )}
            {editable && draft !== null && draft !== effective && (
              <Button size="sm" onClick={() => saveOverride.mutate(draft)}>
                {t('Save edit')}
              </Button>
            )}
            {editable && override !== undefined && !raw && (
              <Button variant="outline" size="sm" onClick={() => saveOverride.mutate('')}>
                {t('Reset to auto')}
              </Button>
            )}
            {editable && raw && source && (
              <span className="inline-flex items-center gap-1">
                <Button variant="outline" size="sm" onClick={() => draftWithAi.mutate()}
                        disabled={draftWithAi.isPending}
                        title={t('The AI rewrites the query of another database in this syntax — a draft to check by hand, nothing is saved until you do')}>
                  {draftWithAi.isPending ? t('Drafting…')
                    : <><Sparkles className="size-3.5 text-primary" />{t('Draft with AI from')}</>}
                </Button>
                <select
                  value={source.id} onChange={(e) => setFromDb(e.target.value)}
                  aria-label={t('Database to translate from')}
                  className="h-8 rounded-md border border-input bg-background px-1 text-xs"
                >
                  {sources.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
                </select>
              </span>
            )}
            {db.count === 'manual' && isAdmin && (
              <form
                onSubmit={(e) => { e.preventDefault(); saveManual.mutate() }}
                className="ml-auto flex items-center gap-1"
              >
                <Input
                  type="number" min={0} required value={manualCount}
                  placeholder={t('count')}
                  onChange={(e) => setManualCount(e.target.value)}
                  className="h-8 w-24 text-xs tabular-nums"
                />
                <Button type="submit" variant="outline" size="sm" disabled={saveManual.isPending}>
                  {t('Save count')}
                </Button>
              </form>
            )}
          </div>
          {db.instructions && (
            <p className="text-xs text-muted-foreground">
              {t(db.instructions)}
              {db.key_required && db.count === 'manual'
                && ` ${t('Add an API key in the Database keys settings to fetch counts and records automatically.')}`}
            </p>
          )}
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
      )}
    </div>
  )
}
