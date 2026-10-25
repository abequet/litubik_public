// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  api, ApiError,
  type DatabaseInfo, type Equation, type ImportRow, type JobInfo, type Project,
  type RecordsPage, type ZoteroCollection, type ZoteroStatus,
} from '../api'
import { useJobWatcher } from '../useJob'
import { DraftBadge } from './Equations'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import LiveStatus from '../components/LiveStatus'
import SearchUpdates from '../components/SearchUpdates'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { Segmented } from '@/components/ui/segmented'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'

export default function SearchPage() {
  const { t } = useTranslation()
  const { projectId } = useParams()
  const pid = Number(projectId)
  const queryClient = useQueryClient()
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'], queryFn: () => api.get('/api/projects'),
  })
  const project = projects.find((p) => p.id === pid)
  const isAdmin = project?.my_role === 'admin'

  // Same key AND same cached shape as the Equations page — caching a different
  // shape under ['databases', pid] crashed this page on client-side navigation.
  const { data: dbInfo } = useQuery<{ databases: DatabaseInfo[] }>({
    queryKey: ['databases', pid],
    queryFn: () => api.get(`/api/projects/${pid}/equations/databases`),
  })
  const databases = dbInfo?.databases ?? []
  const { data: equations = [] } = useQuery<Equation[]>({
    queryKey: ['equations', pid],
    queryFn: () => api.get(`/api/projects/${pid}/equations`),
  })
  const [equationId, setEquationId] = useState<number | null>(null)
  const [scopeAll, setScopeAll] = useState(false)
  const frozen = equations.filter((e) => e.status === 'frozen')
  const selectedId = equationId
    ?? frozen[frozen.length - 1]?.id
    ?? equations[equations.length - 1]?.id
    ?? null
  const equation = equations.find((e) => e.id === selectedId) ?? null
  // tables below show the selected equation's results unless "whole project"
  const equationFilter = scopeAll ? null : selectedId
  const { data: imports = [] } = useQuery<ImportRow[]>({
    queryKey: ['imports', pid],
    queryFn: () => api.get(`/api/projects/${pid}/imports`),
  })
  const lastImportFor = (databaseId: string): ImportRow | undefined =>
    imports.find((i) => i.source_name === databaseId && i.equation_id === selectedId)

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['imports', pid] })
    queryClient.invalidateQueries({ queryKey: ['records', pid] })
    // a new source (e.g. scopus) must appear in the records source filter
    queryClient.invalidateQueries({ queryKey: ['record-sources', pid] })
    queryClient.invalidateQueries({ queryKey: ['active-jobs', pid] })
  }

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('Search & imports')}{project ? ` — ${project.name}` : ''}
      </h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {t('Run the frozen equation on the open APIs, follow the assisted instructions for closed databases, or import any reference file. Every import is traced for the PRISMA counts.')}
        {' '}
        {t('A database missing from the list below?')}{' '}
        {isAdmin ? (
          <Link to={`/projects/${pid}/settings`} className="text-primary hover:underline">
            {t('Add it in Project settings → Database keys.')}
          </Link>
        ) : t('A project admin can add it in Project settings → Database keys.')}
      </p>

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <label className="text-sm text-muted-foreground">{t('Equation:')}</label>
        <Select
          value={selectedId !== null ? String(selectedId) : undefined}
          onValueChange={(v) => setEquationId(Number(v))}
        >
          <SelectTrigger className="h-8 w-auto min-w-52 text-sm" aria-label={t('Equation:')}>
            <SelectValue placeholder={t('Select an equation')} />
          </SelectTrigger>
          <SelectContent>
            {equations.map((e) => (
              <SelectItem key={e.id} value={String(e.id)}>
                {e.label} {e.status === 'frozen' ? t('(frozen)') : t('(draft)')}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {equation && equation.status !== 'frozen' && (
          <Badge variant="warning">
            {t('not frozen yet — freeze the final equation before the real search')}
          </Badge>
        )}
        {equation && isAdmin && (
          <DraftMissingButton projectId={pid} equation={equation} databases={databases}
                              onStarted={refresh} />
        )}
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <Checkbox checked={scopeAll}
                    onCheckedChange={(v) => setScopeAll(!!v)} />
          {t('show whole project (all equations)')}
        </label>
        <span className="flex-1" />
        <a
          href={`/api/projects/${pid}/search-report`} target="_blank" rel="noreferrer"
          className="text-sm text-primary hover:underline"
        >
          {t('Search report (PRISMA-S) ↗')}
        </a>
      </div>

      <ActiveJobsBanner projectId={pid} onDone={refresh} />

      {equations.length === 0 ? (
        <Card className="mb-6 p-6 text-sm text-muted-foreground">
          {t('No equation yet — build one on the Equations page first.')}
        </Card>
      ) : (
        <div className="mb-6 grid gap-4 md:grid-cols-2">
          {databases.map((db) => (
            <DatabaseCard key={db.id} projectId={pid} db={db} equation={equation}
                          isAdmin={isAdmin} onImported={refresh}
                          lastImport={lastImportFor(db.id)} />
          ))}
          {isAdmin && <FreeImportCard projectId={pid} onImported={refresh} />}
          {isAdmin && <ZoteroImportCard projectId={pid} onImported={refresh} />}
        </div>
      )}

      {equations.length > 0 && (
        <SearchUpdates projectId={pid} isAdmin={isAdmin} databases={databases}
                       equations={equations} onChange={refresh} />
      )}
      <ImportsTable projectId={pid} isAdmin={isAdmin} onChange={refresh}
                    equationFilter={equationFilter} />
      <RecordsTable projectId={pid} equationFilter={equationFilter} />
    </div>
  )
}

/** A typed (raw) variant whose searched databases are not all written yet:
 * one AI call per missing database, from the first database with a text the
 * team wrote itself. The drafts land on the cards below, marked until a
 * human validates them. */
function DraftMissingButton({ projectId, equation, databases, onStarted }: {
  projectId: number
  equation: Equation
  databases: DatabaseInfo[]
  onStarted: () => void
}) {
  const { t } = useTranslation()
  const [error, setError] = useState('')
  const queryOf = (id: string) =>
    (equation.translations.overrides[id] ?? equation.translations.auto[id] ?? '').trim()
  const missing = databases.filter((d) => !queryOf(d.id))
  const source = databases.find((d) => queryOf(d.id) && !equation.translations.drafts?.[d.id])
    ?? databases.find((d) => queryOf(d.id))
  const start = useMutation({
    mutationFn: () => api.post<{ job_id: number | null }>(
      `/api/projects/${projectId}/equations/${equation.id}/translations/draft-all`,
      { from_db: source!.id, mode: 'missing' }),
    onSuccess: () => { setError(''); onStarted() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Draft failed')),
  })
  if (equation.mode !== 'raw' || equation.status === 'frozen' || missing.length === 0 || !source) return null
  return (
    <span className="inline-flex items-center gap-2">
      <Button variant="outline" size="sm" onClick={() => start.mutate()} disabled={start.isPending}
              title={t('One AI call per database without a query, drafted from the {{database}} text; each draft stays marked until you review it', { database: source.label })}>
        {t('Draft {{count}} missing by AI', { count: missing.length })}
      </Button>
      {error && <span className="text-xs text-destructive">{error}</span>}
    </span>
  )
}

function ActiveJobsBanner({ projectId, onDone }: {
  projectId: number
  onDone: () => void
}) {
  const { t } = useTranslation()
  const { data: jobs = [] } = useQuery<JobInfo[]>({
    queryKey: ['active-jobs', projectId],
    queryFn: () => api.get(`/api/jobs?project_id=${projectId}&active=true`),
    refetchOnMount: 'always',
  })
  const searches = jobs.filter((j) => j.type === 'search_fetch' || j.type === 'search_update'
    || j.type === 'zotero_import' || j.type === 'equation_draft_all')
  if (searches.length === 0) return null
  return (
    <Card className="mb-6 space-y-1 p-3">
      <p className="text-xs font-medium text-foreground">
        {t('Searches running in the background (you can navigate away — they keep going):')}
      </p>
      {searches.map((j) => <ActiveJobRow key={j.id} job={j} onDone={onDone} />)}
    </Card>
  )
}

function ActiveJobRow({ job, onDone }: { job: JobInfo; onDone: () => void }) {
  const { t } = useTranslation()
  const watcher = useJobWatcher(onDone)
  useEffect(() => { watcher.watch(job.id) }, [job.id])  // eslint-disable-line
  const database = job.type === 'search_update'
    ? t('search update')
    : job.type === 'zotero_import'
      ? t('Zotero import')
      : job.type === 'equation_draft_all'
        ? t('AI drafts of the database syntaxes')
        : String(job.params?.database ?? 'search')
  return (
    <p className="text-xs text-muted-foreground">
      <span className="font-medium text-foreground">{database}</span>
      {': '}
      {watcher.error
        ? <span className="text-destructive">{watcher.error}</span>
        : (watcher.state || t('running…'))}
    </p>
  )
}

function DatabaseCard({ projectId, db, equation, isAdmin, onImported, lastImport }: {
  projectId: number
  db: DatabaseInfo
  equation: Equation | null
  isAdmin: boolean
  onImported: () => void
  lastImport?: ImportRow
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [cap, setCap] = useState('5000')
  const [error, setError] = useState('')
  const query = equation
    ? (equation.translations.overrides[db.id] ?? equation.translations.auto[db.id] ?? '')
    : ''
  const aiDraft = equation?.translations.drafts?.[db.id]
  const validate = useMutation({
    mutationFn: () => api.post(
      `/api/projects/${projectId}/equations/${equation!.id}/translations/validate`,
      { database: db.id }),
    onSuccess: () => {
      setError('')
      queryClient.invalidateQueries({ queryKey: ['equations', projectId] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })

  const fetchNow = async () => {
    if (!equation) return
    setError('')
    try {
      await api.post<{ job_id: number }>(
        `/api/projects/${projectId}/search/fetch`,
        { equation_id: equation.id, database: db.id, cap: Number(cap) || 5000 })
      onImported()  // the active-jobs banner picks up and follows the job
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('Fetch failed'))
    }
  }

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2">
        <h3 className="flex-1 text-sm font-semibold text-foreground">{db.label}</h3>
        {lastImport && (
          <Badge
            variant="success"
            title={t('Last import for this equation: {{filename}}', { filename: lastImport.filename })}
          >
            ✓ {t('{{count}} records', { count: lastImport.n_records })} · {new Date(lastImport.imported_at).toLocaleDateString()}
          </Badge>
        )}
        <Badge variant={db.count === 'api' ? 'default' : 'outline'}>
          {db.count === 'api' ? 'API' : t('assisted manual')}
        </Badge>
      </div>
      {aiDraft && (
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <DraftBadge draft={aiDraft} />
          {!aiDraft.validated && (
            <>
              <span>{t('read the query on the Equations page, or here, before running it')}</span>
              {isAdmin && (
                <Button variant="outline" size="sm" className="h-6 px-2 text-xs"
                        onClick={() => validate.mutate()} disabled={validate.isPending}>
                  {t('Validate draft')}
                </Button>
              )}
            </>
          )}
        </div>
      )}

      {db.count === 'api' && isAdmin && (
        <div className="mt-3 flex items-center gap-2">
          <Button size="sm" onClick={fetchNow} disabled={!equation}>
            {t('Fetch now')}
          </Button>
          <label className="text-xs text-muted-foreground">{t('cap')}</label>
          <Input
            type="number" min={1} max={20000} value={cap}
            onChange={(e) => setCap(e.target.value)}
            className="h-7 w-20 px-2 text-xs"
          />
        </div>
      )}

      {db.count === 'manual' && (
        <div className="mt-3">
          <Button variant="link" size="sm" className="h-auto p-0"
                  onClick={() => setOpen((v) => !v)}>
            {open ? t('Hide instructions') : t('Show query & instructions')}
          </Button>
          {open && (
            <div className="mt-2 space-y-2">
              <Textarea
                readOnly value={query || t('(no query — select an equation)')}
                rows={Math.min(30, Math.max(3, query.split('\n').length + 1))}
                className="bg-muted font-mono text-xs"
              />
              <div className="flex gap-2">
                <Button variant="outline" size="sm"
                        onClick={() => navigator.clipboard.writeText(query)}>
                  {t('Copy query')}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                {t(db.instructions)}
                {db.key_required && db.count === 'manual'
                  && ` ${t('Add an API key in the Database keys settings to fetch counts and records automatically.')}`}
                {db.url && (
                  <>
                    {' '}
                    <a href={db.url} target="_blank" rel="noreferrer"
                       className="text-primary hover:underline">
                      {t('Open the database ↗')}
                    </a>
                  </>
                )}
              </p>
              <p className="text-xs text-muted-foreground">
                {t('Then export the results (.ris, .nbib, .bib or .csv) and drop the file below — it is traced under the “{{source}}” source.', { source: db.id })}
              </p>
              {isAdmin && (
                <UploadForm projectId={projectId} sourceName={db.id}
                            sourceType="database" equationId={equation?.id ?? null}
                            onImported={onImported} />
              )}
            </div>
          )}
        </div>
      )}

      <LiveStatus className="mt-2 text-xs">{error}</LiveStatus>
    </Card>
  )
}

function UploadForm({ projectId, sourceName, sourceType, equationId, onImported }: {
  projectId: number
  sourceName: string
  sourceType: 'database' | 'manual'
  equationId: number | null
  onImported: () => void
}) {
  const { t } = useTranslation()
  const inputRef = useRef<HTMLInputElement>(null)
  const [status, setStatus] = useState('')
  // PRISMA-S provenance declared with the file: the day the search ran on
  // the database and the hit count it displayed (the export may be capped)
  const [searchedAt, setSearchedAt] = useState('')
  const [declaredHits, setDeclaredHits] = useState('')
  const [roundMode, setRoundMode] = useState<'initial' | 'update'>('initial')
  // PRISMA-S limits: were the equation's date range / disciplines applied on
  // the database? '' = not declared
  const [dateLimit, setDateLimit] = useState<'' | 'yes' | 'no'>('')
  const [disciplineLimit, setDisciplineLimit] = useState<'' | 'yes' | 'no'>('')
  const [disciplines, setDisciplines] = useState('')
  const [docTypeLimit, setDocTypeLimit] = useState<'' | 'yes' | 'no'>('')
  const [docTypes, setDocTypes] = useState('')
  // the fields the query ran on; none ticked = not declared
  const [searchFields, setSearchFields] = useState<string[]>([])

  const upload = async (file: File) => {
    setStatus(t('Importing…'))
    const form = new FormData()
    form.append('file', file)
    form.append('source_name', sourceName)
    form.append('source_type', sourceType)
    if (equationId != null) form.append('equation_id', String(equationId))
    if (searchedAt) form.append('searched_at', searchedAt)
    if (declaredHits.trim()) form.append('declared_hits', declaredHits.trim())
    form.append('round_mode', roundMode)
    if (dateLimit) form.append('date_restricted', dateLimit === 'yes' ? 'true' : 'false')
    if (disciplineLimit)
      form.append('discipline_restricted', disciplineLimit === 'yes' ? 'true' : 'false')
    if (disciplineLimit === 'yes' && disciplines.trim())
      form.append('disciplines', disciplines.trim())
    if (docTypeLimit)
      form.append('doc_type_restricted', docTypeLimit === 'yes' ? 'true' : 'false')
    if (docTypeLimit === 'yes' && docTypes.trim())
      form.append('doc_types', docTypes.trim())
    if (searchFields.length) form.append('search_fields', searchFields.join(','))
    try {
      const res = await fetch(`/api/projects/${projectId}/imports/upload`,
        { method: 'POST', credentials: 'include', body: form })
      const body = await res.json()
      if (!res.ok) throw new ApiError(res.status, body.detail ?? res.statusText)
      setStatus(body.round > 1
        ? t('✓ {{count}} records imported as search update (round {{round}}), {{unique}} new unique', { count: body.n_records, round: body.round, unique: body.n_new_unique ?? 0 })
        : t('✓ {{count}} records imported', { count: body.n_records }))
      onImported()
    } catch (e) {
      setStatus(`✗ ${e instanceof ApiError ? e.message : t('Import failed')}`)
    }
  }

  return (
    <div className="space-y-2">
      {sourceType === 'database' && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <label className="inline-flex items-center gap-1">
            {t('Searched on')}
            <Input type="date" value={searchedAt} onChange={(e) => setSearchedAt(e.target.value)}
                   className="h-7 w-36 px-2 text-xs" aria-label={t('Searched on')} />
          </label>
          <label className="inline-flex items-center gap-1">
            {t('Hits shown')}
            <Input type="number" min={0} value={declaredHits} placeholder="—"
                   onChange={(e) => setDeclaredHits(e.target.value)}
                   className="h-7 w-24 px-2 text-xs tabular-nums" aria-label={t('Hits shown')}
                   title={t('The result count the database displayed — an export may be capped below it')} />
          </label>
          <label className="inline-flex items-center gap-1">
            {t('Round')}
            <select
              value={roundMode} onChange={(e) => setRoundMode(e.target.value as typeof roundMode)}
              aria-label={t('Round')}
              className="h-7 rounded-md border border-input bg-background px-1 text-xs"
              title={t('initial search: the export joins the original search (and the active screening round, if any); search update: a re-run of the search, with its own round')}
            >
              <option value="initial">{t('initial search')}</option>
              <option value="update">{t('search update')}</option>
            </select>
          </label>
        </div>
      )}
      {/* PRISMA-S limits — for database exports and free imports alike */}
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {([
          ['date', t('Date limits'), dateLimit, setDateLimit,
           t('Was a date range applied when searching this source? Reported in the search report (PRISMA-S limits)')],
          ['discipline', t('Discipline limits'), disciplineLimit, setDisciplineLimit,
           t('Was the search limited to some disciplines / subject areas? Reported in the search report (PRISMA-S limits)')],
          ['doc_type', t('Document type limits'), docTypeLimit, setDocTypeLimit,
           t('Was the search limited to some document types (articles, reviews…)? Reported in the search report (PRISMA-S limits)')],
        ] as const).map(([key, label, value, set, title]) => (
          <label key={key} className="inline-flex items-center gap-1">
            {label}
            <select value={value} aria-label={label} title={title}
                    onChange={(e) => set(e.target.value as '' | 'yes' | 'no')}
                    className="h-7 rounded-md border border-input bg-background px-1 text-xs">
              <option value="">{t('not declared')}</option>
              <option value="yes">{t('applied')}</option>
              <option value="no">{t('not applied')}</option>
            </select>
          </label>
        ))}
        {disciplineLimit === 'yes' && (
          <Input value={disciplines} onChange={(e) => setDisciplines(e.target.value)}
                 placeholder={t('Disciplines included in the search, comma-separated')}
                 aria-label={t('Disciplines included in the search, comma-separated')}
                 className="h-7 min-w-72 flex-1 px-2 text-xs" />
        )}
        {docTypeLimit === 'yes' && (
          <Input value={docTypes} onChange={(e) => setDocTypes(e.target.value)}
                 placeholder={t('Document types included in the search, comma-separated')}
                 aria-label={t('Document types included in the search, comma-separated')}
                 className="h-7 min-w-72 flex-1 px-2 text-xs" />
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground"
           title={t('The fields the query ran on in this source. Leave all unticked if not known. Reported in the search report (PRISMA-S)')}>
        <span>{t('Searched in')}</span>
        {searchFieldOptions(t).map(([id, label]) => (
          <label key={id} className="inline-flex items-center gap-1">
            <input type="checkbox" checked={searchFields.includes(id)}
                   onChange={(e) => setSearchFields((cur) => e.target.checked
                     ? [...cur, id] : cur.filter((f) => f !== id))} />
            {label}
          </label>
        ))}
      </div>
      <div>
        <input
          ref={inputRef} type="file" accept=".ris,.nbib,.bib,.csv,.txt" className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) upload(file)
            e.target.value = ''
          }}
        />
        <Button variant="outline" size="sm" onClick={() => inputRef.current?.click()}>
          {t('Import export file…')}
        </Button>
        {status && (
          <span className={cn('ml-2 text-xs',
            status.startsWith('✗') ? 'text-destructive' : 'text-muted-foreground')}>
            {status}
          </span>
        )}
      </div>
    </div>
  )
}

function FreeImportCard({ projectId, onImported }: {
  projectId: number
  onImported: () => void
}) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  return (
    <Card className="border-dashed p-4">
      <h3 className="mb-2 text-sm font-semibold text-foreground">
        {t('Other source')} <span className="font-normal text-muted-foreground">{t('(free import)')}</span>
      </h3>
      <Input
        value={name} placeholder={t('Source name (e.g. hand search, expert list)')}
        onChange={(e) => setName(e.target.value)}
        className="mb-2"
      />
      {name.trim() && (
        <UploadForm projectId={projectId} sourceName={name.trim()}
                    sourceType="manual" equationId={null} onImported={onImported} />
      )}
    </Card>
  )
}

const WHOLE_LIBRARY = '__all__'

/** Pull a collection of the admin's own Zotero library into the project
 * (chantier 4). The user picks the collection, whether it counts as a
 * database search or an "other source" for PRISMA, and whether attached
 * PDFs come along into the full-text library. Runs as a background job. */
function ZoteroImportCard({ projectId, onImported }: {
  projectId: number
  onImported: () => void
}) {
  const { t } = useTranslation()
  const { data: status } = useQuery<ZoteroStatus>({
    queryKey: ['zotero-status'], queryFn: () => api.get('/api/integrations/zotero'),
  })
  const configured = !!status?.configured
  const { data: collections = [], isError: collectionsFailed } = useQuery<ZoteroCollection[]>({
    queryKey: ['zotero-collections'],
    queryFn: () => api.get('/api/integrations/zotero/collections'),
    enabled: configured,
    staleTime: 60_000,
  })
  const [collection, setCollection] = useState<string>(WHOLE_LIBRARY)
  const [sourceType, setSourceType] = useState<'database' | 'manual'>('manual')
  const [withPdfs, setWithPdfs] = useState(false)
  const watcher = useJobWatcher(onImported)
  const selected = collections.find((c) => c.key === collection)
  const start = useMutation({
    mutationFn: () => api.post<{ job_id: number }>(`/api/projects/${projectId}/zotero/import`, {
      collection_key: collection === WHOLE_LIBRARY ? null : collection,
      collection_name: selected?.name ?? 'library',
      source_type: sourceType, with_pdfs: withPdfs,
    }),
    onSuccess: ({ job_id }) => watcher.watch(job_id),
    onError: (e) => watcher.setError(e instanceof ApiError ? e.message : t('Import failed')),
  })

  return (
    <Card className="border-dashed p-4">
      <h3 className="mb-2 text-sm font-semibold text-foreground">
        {t('Zotero library')}{' '}
        <span className="font-normal text-muted-foreground">
          {configured && status
            ? `(${status.library_type === 'user' ? t('My library') : status.library_name})`
            : t('(import a collection)')}
        </span>
      </h3>
      {status && !configured ? (
        <p className="text-xs text-muted-foreground">
          {t('Connect your Zotero library to import one of its collections here.')}{' '}
          <Link to="/settings/integrations" className="text-primary hover:underline">
            {t('My integrations')}
          </Link>
        </p>
      ) : (
        <div className="space-y-2">
          <Select value={collection} onValueChange={setCollection}>
            <SelectTrigger className="h-8 w-full text-sm" aria-label={t('Zotero collection')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={WHOLE_LIBRARY}>{t('Whole library')}</SelectItem>
              {collections.map((c) => (
                <SelectItem key={c.key} value={c.key}>
                  {' '.repeat(c.depth * 3)}{c.name} ({c.n_items})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {collectionsFailed && (
            <p className="text-xs text-destructive">{t('Could not list your Zotero collections.')}</p>
          )}
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>{t('Counts as:')}</span>
            <Segmented size="sm" value={sourceType} onChange={setSourceType} options={[
              { value: 'manual', label: t('other source'),
                title: t('PRISMA: records identified through other methods (hand search, expert list…)') },
              { value: 'database', label: t('database search'),
                title: t('PRISMA: records identified from databases — e.g. a search you ran elsewhere and saved in Zotero') },
            ]} />
          </div>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <Checkbox checked={withPdfs} onCheckedChange={(v) => setWithPdfs(!!v)} />
            {t('Also fetch the attached PDFs into the full-text library')}
          </label>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => start.mutate()}
                    disabled={start.isPending || !!watcher.state}>
              {t('Import from Zotero')}
            </Button>
            {watcher.state && <span className="text-xs text-muted-foreground">{watcher.state}</span>}
          </div>
          <LiveStatus tone="error" className="text-xs">{watcher.error}</LiveStatus>
        </div>
      )}
    </Card>
  )
}

function ImportsTable({ projectId, isAdmin, onChange, equationFilter }: {
  projectId: number
  isAdmin: boolean
  onChange: () => void
  equationFilter: number | null
}) {
  const { t } = useTranslation()
  const { data: allImports = [] } = useQuery<ImportRow[]>({
    queryKey: ['imports', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/imports`),
  })
  const imports = equationFilter === null
    ? allImports
    : allImports.filter((i) => i.equation_id === equationFilter || i.equation_id === null)
  const del = useMutation({
    mutationFn: (id: number) => api.del(`/api/projects/${projectId}/imports/${id}`),
    onSuccess: onChange,
  })
  if (imports.length === 0) return null
  return (
    <Card className="mb-6 p-4">
      <h2 className="mb-3 text-sm font-semibold text-foreground">
        {t('Imports')}
        {equationFilter !== null && (
          <span className="font-normal text-muted-foreground"> {t('— selected equation + other sources')}</span>
        )}
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="pb-1 pr-3">{t('Source')}</th>
              <th className="pb-1 pr-3">{t('Type')}</th>
              <th className="pb-1 pr-3">{t('Round')}</th>
              <th className="pb-1 pr-3">{t('Equation')}</th>
              <th className="pb-1 pr-3">{t('Searched')}</th>
              <th className="pb-1 pr-3">{t('Imported')}</th>
              <th className="pb-1 pr-3">{t('By')}</th>
              <th className="pb-1 pr-3 text-right" title={t('The result count the database displayed — an export may be capped below it')}>{t('Hits')}</th>
              <th className="pb-1 pr-3 text-right">{t('Records')}</th>
              <th className="pb-1 pr-3" title={t('PRISMA-S limits applied to this run: the date range, discipline and document-type restrictions and the fields searched (declared with an upload, set by an API fetch)')}>{t('Limits')}</th>
              {isAdmin && <th className="w-8 pb-1"><span className="sr-only">{t('Actions')}</span></th>}
            </tr>
          </thead>
          <tbody>
            {imports.map((i) => (
              <tr key={i.id} className="border-t border-border text-muted-foreground">
                <td className="py-1.5 pr-3 font-medium text-foreground">{i.source_name}</td>
                <td className="py-1.5 pr-3">{i.source_type}</td>
                <td className="py-1.5 pr-3 tabular-nums">r{i.round}</td>
                <td className="py-1.5 pr-3">{i.equation_label ?? '—'}</td>
                <td className="py-1.5 pr-3">{i.searched_at ? new Date(i.searched_at).toLocaleDateString() : '—'}</td>
                <td className="py-1.5 pr-3">{new Date(i.imported_at).toLocaleString()}</td>
                <td className="py-1.5 pr-3">{i.imported_by ?? 'job'}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{i.declared_hits ?? '—'}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{i.n_records}</td>
                <td className="max-w-64 truncate py-1.5 pr-3" title={limitsLabel(t, i)}>{limitsLabel(t, i)}</td>
                {isAdmin && (
                  <td className="py-1.5">
                    <Button
                      variant="ghost" size="icon"
                      className="size-7 text-muted-foreground hover:text-destructive"
                      title={t('Delete import')}
                      onClick={() => {
                        if (confirm(t('Delete this {{source}} import and its {{count}} records?', { source: i.source_name, count: i.n_records })))
                          del.mutate(i.id)
                      }}
                    >✕</Button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

/** The fields an uploader may declare a search ran on (ids as the backend stores them). */
function searchFieldOptions(t: (k: string) => string): [string, string][] {
  return [['title', t('title')], ['abstract', t('abstract')], ['keywords', t('keywords')],
    ['fulltext', t('full text')], ['all', t('all fields')]]
}

/** "dates ✓ · disciplines ✗" — only the declared limits, "—" when none is. */
function limitsLabel(t: (k: string) => string, i: ImportRow): string {
  const parts: string[] = []
  if (i.date_restricted !== null && i.date_restricted !== undefined)
    parts.push(`${t('dates')} ${i.date_restricted ? '✓' : '✗'}`)
  if (i.discipline_restricted !== null && i.discipline_restricted !== undefined)
    parts.push(`${t('disciplines')} ${i.discipline_restricted ? '✓' : '✗'}`
      + (i.disciplines?.length ? ` (${i.disciplines.join(', ')})` : ''))
  if (i.doc_type_restricted !== null && i.doc_type_restricted !== undefined)
    parts.push(`${t('doc types')} ${i.doc_type_restricted ? '✓' : '✗'}`
      + (i.doc_types?.length ? ` (${i.doc_types.join(', ')})` : ''))
  if (i.search_fields?.length) {
    const labels = Object.fromEntries(searchFieldOptions(t))
    parts.push(`${t('in')} ${i.search_fields.map((f) => labels[f] ?? f).join(', ')}`)
  }
  return parts.length ? parts.join(' · ') : '—'
}

function pageNumbers(current: number, pages: number): (number | '…')[] {
  if (pages <= 9) return Array.from({ length: pages }, (_, i) => i + 1)
  const window = [current - 2, current - 1, current, current + 1, current + 2]
    .filter((p) => p > 1 && p < pages)
  const out: (number | '…')[] = [1]
  if (window[0] > 2) out.push('…')
  out.push(...window)
  if (window[window.length - 1] < pages - 1) out.push('…')
  out.push(pages)
  return out
}

function RecordsTable({ projectId, equationFilter }: {
  projectId: number
  equationFilter: number | null
}) {
  const { t } = useTranslation()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [q, setQ] = useState('')
  const [applied, setApplied] = useState('')
  const [source, setSource] = useState('')
  const [sort, setSort] = useState('recent')
  const [dedup, setDedup] = useState('')
  useEffect(() => { setPage(1) }, [equationFilter])
  const { data: sourceNames } = useQuery<{ sources: string[] }>({
    queryKey: ['record-sources', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/records/sources`),
  })
  const { data } = useQuery<RecordsPage>({
    queryKey: ['records', projectId, page, pageSize, applied, source, sort,
               dedup, equationFilter],
    queryFn: () => api.get(
      `/api/projects/${projectId}/records?page=${page}&page_size=${pageSize}` +
      `&q=${encodeURIComponent(applied)}&source=${encodeURIComponent(source)}&sort=${sort}` +
      `&dedup=${dedup}` +
      (equationFilter !== null ? `&equation_id=${equationFilter}` : '')),
  })
  const total = data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / pageSize))

  const pager = pages > 1 && (
    <div className="flex flex-wrap items-center gap-1 text-xs">
      <Button variant="outline" size="icon" className="size-7"
              disabled={page <= 1} onClick={() => setPage(page - 1)}>←</Button>
      {pageNumbers(page, pages).map((p, i) =>
        p === '…' ? (
          <span key={`e${i}`} className="px-1 text-muted-foreground">…</span>
        ) : (
          <Button
            key={p} onClick={() => setPage(p)}
            variant={p === page ? 'default' : 'outline'}
            size="icon" className="size-7 tabular-nums"
          >
            {p}
          </Button>
        ))}
      <Button variant="outline" size="icon" className="size-7"
              disabled={page >= pages} onClick={() => setPage(page + 1)}>→</Button>
    </div>
  )

  return (
    <Card className="p-4">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h2 className="text-sm font-semibold text-foreground">
          {t('Records')} <span className="font-normal text-muted-foreground">
            ({total}{equationFilter !== null ? ` ${t('— selected equation + other sources')}` : ''})
          </span>
        </h2>
        <form
          onSubmit={(e) => { e.preventDefault(); setPage(1); setApplied(q) }}
          className="flex gap-1"
        >
          <Input
            value={q} placeholder={t('Search title / DOI…')}
            onChange={(e) => setQ(e.target.value)}
            className="h-8 w-56 text-xs"
          />
          <Button type="submit" variant="outline" size="sm">{t('Search')}</Button>
        </form>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          {t('source')}
          <Select value={source || 'all'}
                  onValueChange={(v) => { setSource(v === 'all' ? '' : v); setPage(1) }}>
            <SelectTrigger className="h-8 w-auto min-w-24 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('all')}</SelectItem>
              {sourceNames?.sources.map((s) => (
                <SelectItem key={s} value={s}>{s}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          {t('dedup')}
          <Select value={dedup || 'all'}
                  onValueChange={(v) => { setDedup(v === 'all' ? '' : v); setPage(1) }}>
            <SelectTrigger className="h-8 w-auto min-w-24 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('all')}</SelectItem>
              <SelectItem value="unique">{t('unique')}</SelectItem>
              <SelectItem value="duplicate">{t('duplicate')}</SelectItem>
              <SelectItem value="uncertain">{t('uncertain')}</SelectItem>
              <SelectItem value="pending">{t('not checked')}</SelectItem>
            </SelectContent>
          </Select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          {t('sort')}
          <Select value={sort}
                  onValueChange={(v) => { setSort(v); setPage(1) }}>
            <SelectTrigger className="h-8 w-auto min-w-28 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="recent">{t('newest import')}</SelectItem>
              <SelectItem value="source">{t('source')}</SelectItem>
              <SelectItem value="year">{t('year ↓')}</SelectItem>
              <SelectItem value="title">{t('title A→Z')}</SelectItem>
            </SelectContent>
          </Select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          {t('per page')}
          <Select value={String(pageSize)}
                  onValueChange={(v) => { setPageSize(Number(v)); setPage(1) }}>
            <SelectTrigger className="h-8 w-auto min-w-16 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {[25, 50, 100, 200].map((n) => (
                <SelectItem key={n} value={String(n)}>{n}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <span className="flex-1" />
        {pager}
      </div>
      {total === 0 ? (
        <p className="text-sm text-muted-foreground">{t('No records yet.')}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="pb-1 pr-3">DOI</th>
                <th className="pb-1 pr-3">{t('Authors')}</th>
                <th className="pb-1 pr-3">{t('Year')}</th>
                <th className="pb-1 pr-3">{t('Title')}</th>
                <th className="pb-1 pr-3">{t('Source')}</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((r) => (
                <tr key={r.id} className="border-t border-border align-top text-muted-foreground">
                  <td className="py-1.5 pr-3 font-mono text-xs whitespace-nowrap">
                    {r.doi ? (
                      <a href={`https://doi.org/${r.doi}`} target="_blank" rel="noreferrer"
                         className="text-primary hover:underline">{r.doi}</a>
                    ) : '—'}
                  </td>
                  <td className="max-w-40 truncate py-1.5 pr-3"
                      title={r.authors.join('; ')}>
                    {r.authors.slice(0, 2).join('; ')}{r.authors.length > 2 ? '…' : ''}
                  </td>
                  <td className="py-1.5 pr-3 tabular-nums">{r.year ?? '—'}</td>
                  <td className="py-1.5 pr-3 text-foreground" title={r.abstract}>
                    {r.title}
                    {r.dedup_status === 'duplicate' && (
                      <Badge variant="outline" className="ml-1.5">dup</Badge>
                    )}
                    {r.dedup_status === 'uncertain' && (
                      <Badge variant="warning" className="ml-1.5">?</Badge>
                    )}
                  </td>
                  <td className="py-1.5 pr-3 text-xs">{r.source_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-3 flex justify-end">{pager}</div>
        </div>
      )}
    </Card>
  )
}
