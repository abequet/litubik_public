// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type JobInfo, type Project, type User } from '../api'
import { useJobWatcher } from '../useJob'
import { usePdfWindow } from '../components/PdfWindow'
import {
  institutionsForRetrieve, InstitutionList, MyInstitutionsPanel,
  ServerInstitutionsEditor,
} from '../components/InstitutionAccess'
import { isSandbox, useInstance } from '../components/DemoBanner'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Stat } from '@/components/ui/stat'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

interface FullTextRow {
  record_id: number
  doi: string | null
  title: string
  authors: string[]
  year: number | null
  status: 'pending' | 'retrieved' | 'not_found' | 'manual'
  via: string
  filename: string
  oa_url: string
  error: string
  size_kb: number | null
  has_file: boolean
  updated_at: string
}

interface Summary {
  eligible: number
  retrieved: number
  not_found: number
  pending: number
}

interface InstitutionOut {
  name: string
  ezproxy_url: string
  username: string
  scope: string
  auth_type: string
  has_password: boolean
}

type Tab = 'retrieve' | 'settings'

export default function FulltextPage() {
  const { t } = useTranslation()
  const { projectId } = useParams()
  const pid = Number(projectId)
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<Tab>('retrieve')
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'], queryFn: () => api.get('/api/projects'),
  })
  // demo visitors: open-access sources only, no institutional settings
  const { data: me } = useQuery<User>({
    queryKey: ['me'], queryFn: () => api.get('/api/auth/me'),
  })
  const { data: instance } = useInstance()
  const sandbox = isSandbox(me, instance)
  const isAdmin = projects.find((p) => p.id === pid)?.my_role === 'admin'
  // the settings tab only holds institutional access and the Unpaywall e-mail
  const showSettings = isAdmin && !sandbox

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['fulltext', pid] })
    queryClient.invalidateQueries({ queryKey: ['fulltext-summary', pid] })
    queryClient.invalidateQueries({ queryKey: ['prisma', pid] })
  }

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('Full-text retrieval')}
      </h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {t('Downloads the PDFs of the records included after title/abstract screening, through a cascade of sources (open access → institutional → more). Not-found records can be uploaded by hand.')}
      </p>
      {sandbox && (
        <p className="mb-4 max-w-2xl rounded-md bg-warning/10 px-3 py-2 text-sm text-foreground">
          {t('Demo session: full texts are retrieved from open-access sources only, by direct download (at most 100 per run, one task at a time). You can also upload a PDF by hand.')}
        </p>
      )}
      {showSettings && (
        <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)} className="mb-6">
          <TabsList>
            <TabsTrigger value="retrieve">{t('Retrieve')}</TabsTrigger>
            <TabsTrigger value="settings">{t('Settings')}</TabsTrigger>
          </TabsList>
        </Tabs>
      )}
      {tab === 'settings' && showSettings
        ? <SettingsTab projectId={pid} />
        : <RetrieveTab projectId={pid} isAdmin={isAdmin} onChange={refresh}
                       sandbox={sandbox} />}
    </div>
  )
}

function RetrieveTab({ projectId, isAdmin, onChange, sandbox = false }: {
  projectId: number
  isAdmin: boolean
  onChange: () => void
  sandbox?: boolean
}) {
  const { t } = useTranslation()
  const job = useJobWatcher(onChange)
  // while a retrieval runs, poll so statuses flip live in the table
  const { data: summary } = useQuery<Summary>({
    queryKey: ['fulltext-summary', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/fulltext/summary`),
    refetchInterval: job.state ? 4_000 : false,
  })
  const { data: rows = [] } = useQuery<FullTextRow[]>({
    queryKey: ['fulltext', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/fulltext`),
    refetchInterval: job.state ? 4_000 : false,
  })
  const [error, setError] = useState('')

  // The retrieval job runs server-side: re-attach to it when (re)entering the
  // page so navigating away and back does not lose the progress display.
  const { data: activeJobs = [] } = useQuery<JobInfo[]>({
    queryKey: ['active-jobs', projectId],
    queryFn: () => api.get(`/api/jobs?project_id=${projectId}&active=true`),
    refetchOnMount: 'always',
  })
  const runningId = activeJobs.find((j) => j.type === 'fulltext_retrieve')?.id
  useEffect(() => {
    if (runningId !== undefined && !job.state) job.watch(runningId)
  }, [runningId])  // eslint-disable-line

  // M4b: any member retrieves, with their browser-held institutional
  // credentials attached (sent once, never stored server-side)
  const { data: me } = useQuery<User>({
    queryKey: ['me'], queryFn: () => api.get('/api/auth/me'),
  })
  const [showAccess, setShowAccess] = useState(false)
  const [accessVersion, setAccessVersion] = useState(0)
  const myInstitutions = me ? institutionsForRetrieve(me.id) : []
  void accessVersion // re-read localStorage after the panel saves

  const retrieve = async (force: boolean) => {
    setError('')
    try {
      const { job_id } = await api.post<{ job_id: number }>(
        `/api/projects/${projectId}/fulltext/retrieve`,
        { force, institutions: me && !sandbox ? institutionsForRetrieve(me.id) : [] })
      job.watch(job_id)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('Could not start retrieval'))
    }
  }

  return (
    <div>
      <Card className="mb-6 p-4">
        <div className="flex flex-wrap items-center gap-6">
          <Stat label={t('to retrieve')} value={summary?.eligible ?? '…'} />
          <Stat label={t('retrieved')} value={summary?.retrieved ?? '…'} tone="success" />
          <Stat label={t('not found')} value={summary?.not_found ?? '…'}
                tone={summary?.not_found ? 'warning' : undefined} />
          <Stat label={t('pending')} value={summary?.pending ?? '…'} />
          <span className="flex-1" />
          <div className="flex gap-2">
            <Button onClick={() => retrieve(false)} disabled={!!job.state}>
              {job.state || t('Retrieve missing PDFs')}
            </Button>
            {summary && summary.not_found > 0 && !job.state && (
              <Button variant="outline" onClick={() => retrieve(true)}>
                {t('Retry all')}
              </Button>
            )}
          </div>
        </div>
        {!sandbox && <div className="mt-3 border-t border-border pt-3">
          <button
            type="button"
            className="text-xs text-primary hover:underline"
            onClick={() => setShowAccess((v) => !v)}
          >
            {showAccess ? t('Hide my institutional access')
              : myInstitutions.length > 0
                ? t('My institutional access ({{count}} ready) — retrieval also tries it', { count: myInstitutions.length })
                : t('Add my institutional access (EZproxy/OpenAthens) to fetch paywalled PDFs')}
          </button>
          {showAccess && me && (
            <div className="mt-2 max-w-2xl">
              <MyInstitutionsPanel userId={me.id}
                                   onChanged={() => setAccessVersion((v) => v + 1)} />
            </div>
          )}
        </div>}
        {(error || job.error) && (
          <p className="mt-2 text-sm text-destructive">{error || job.error}</p>
        )}
        {job.state && (
          <p className="mt-2 text-xs text-muted-foreground">
            {t('Downloads run on the server (4 records at a time, each trying its sources in parallel) — you can navigate away, retrieval keeps going.')}
          </p>
        )}
        {job.log.length > 0 && (
          <ul className="mt-2 max-h-40 space-y-0.5 overflow-y-auto rounded-md border border-border bg-muted p-2 text-xs">
            {job.log.map((line, i) => (
              <li key={job.log.length - i}
                  className={line.startsWith('✓') ? 'text-success'
                    : line.startsWith('✗') ? 'text-warning' : 'text-muted-foreground'}>
                {line}
              </li>
            ))}
          </ul>
        )}
        {summary?.eligible === 0 && (
          <p className="mt-2 text-sm text-muted-foreground">
            {t('No record to retrieve yet — records enter here once they are included at title/abstract screening.')}
          </p>
        )}
      </Card>

      {isAdmin && (
        <BulkPdfImport projectId={projectId} rows={rows} onChange={onChange} />
      )}

      <Card className="overflow-hidden overflow-x-auto">
        <table className="w-full min-w-[40rem] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="p-3">{t('Status')}</th>
              <th className="p-3">{t('Title')}</th>
              <th className="p-3">{t('Source')}</th>
              <th className="p-3">{t('PDF')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <FullTextRowView key={row.record_id} projectId={projectId} row={row}
                               isAdmin={isAdmin} onChange={onChange} />
            ))}
          </tbody>
        </table>
        {rows.length === 0 && (
          <p className="p-6 text-sm text-muted-foreground">{t('Nothing here yet.')}</p>
        )}
      </Card>
    </div>
  )
}

// ---- bulk PDF import --------------------------------------------------------------

interface BulkCandidate {
  record_id: number
  title: string
  year: number | null
  score: number
}

interface BulkResult {
  filename: string
  status: 'linked' | 'already_has_pdf' | 'ambiguous' | 'unmatched' | 'error'
  record_id?: number
  title?: string
  method?: string
  reason?: string
  candidates?: BulkCandidate[]
}

const METHOD_LABELS: Record<string, string> = {
  doi_text: 'DOI found in the PDF',
  doi_name: 'DOI in the filename',
  title_text: 'title found in the PDF',
  title_name: 'filename matches the title',
}

/** Upload many PDFs at once; the server matches each file to a record (DOI in
 * the text, DOI in the filename, then title). Ambiguous files stay in the
 * browser and are assigned by hand through the per-record upload endpoint. */
function BulkPdfImport({ projectId, rows, onChange }: {
  projectId: number
  rows: FullTextRow[]
  onChange: () => void
}) {
  const { t } = useTranslation()
  const inputRef = useRef<HTMLInputElement>(null)
  const filesRef = useRef<Map<string, File>>(new Map())
  const [results, setResults] = useState<BulkResult[]>([])
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')

  const send = async (files: File[]) => {
    setError('')
    setResults([])
    filesRef.current = new Map(files.map((f) => [f.name, f]))
    const all: BulkResult[] = []
    const BATCH = 4
    for (let i = 0; i < files.length; i += BATCH) {
      const batch = files.slice(i, i + BATCH)
      setProgress(t('Analysing {{done}}/{{total}}…',
        { done: Math.min(i + BATCH, files.length), total: files.length }))
      const form = new FormData()
      for (const f of batch) form.append('files', f)
      form.append('overwrite', 'false')
      try {
        const res = await fetch(
          `/api/projects/${projectId}/fulltext/pdf-import`,
          { method: 'POST', credentials: 'include', body: form })
        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          throw new ApiError(res.status, data.detail ?? res.statusText)
        }
        const out = await res.json() as { results: BulkResult[] }
        all.push(...out.results)
        setResults([...all])
      } catch (e) {
        setError(e instanceof ApiError ? e.message : t('Import failed'))
        break
      }
    }
    setProgress('')
    onChange()
  }

  /** Manual assignment / replacement: the browser still holds the file — it
   * goes through the existing per-record upload endpoint. */
  const assign = async (filename: string, recordId: number) => {
    const file = filesRef.current.get(filename)
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    try {
      const res = await fetch(
        `/api/projects/${projectId}/fulltext/records/${recordId}/upload`,
        { method: 'POST', credentials: 'include', body: form })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new ApiError(res.status, data.detail ?? res.statusText)
      }
      const row = rows.find((r) => r.record_id === recordId)
      setResults((list) => list.map((x) => x.filename === filename
        ? { filename, status: 'linked', record_id: recordId,
            title: row?.title ?? x.title, method: 'manual' } : x))
      onChange()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('Upload failed'))
    }
  }

  const nLinked = results.filter((r) => r.status === 'linked').length
  const nPending = results.filter((r) =>
    r.status === 'ambiguous' || r.status === 'unmatched'
    || r.status === 'already_has_pdf').length

  return (
    <Card className="mb-6 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1">
          <h2 className="text-sm font-semibold text-foreground">
            {t('Bulk PDF import')}
          </h2>
          <p className="text-xs text-muted-foreground">
            {t('Drop a whole folder of PDFs (e.g. from the platform where the review started): each file is matched to its article by DOI or title, and unrecognized ones are assigned by hand below.')}
          </p>
        </div>
        <input ref={inputRef} type="file" multiple accept=".pdf,application/pdf"
               className="hidden"
               onChange={(e) => {
                 const files = Array.from(e.target.files ?? [])
                 if (files.length) send(files)
                 e.target.value = ''
               }} />
        <Button variant="outline" onClick={() => inputRef.current?.click()}
                disabled={!!progress}>
          {progress || t('Choose PDF files…')}
        </Button>
      </div>
      {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
      {results.length > 0 && (
        <div className="mt-3 space-y-1 border-t border-border pt-2">
          <p className="text-xs text-muted-foreground">
            {t('{{linked}} linked automatically, {{pending}} to review.',
               { linked: nLinked, pending: nPending })}
          </p>
          <ul className="max-h-72 space-y-1 overflow-y-auto">
            {results.map((r) => (
              <li key={r.filename}
                  className="flex flex-wrap items-center gap-2 text-xs">
                <span className="max-w-56 truncate font-mono text-muted-foreground"
                      title={r.filename}>{r.filename}</span>
                {r.status === 'linked' && (
                  <span className="text-success">
                    ✓ {r.title?.slice(0, 60)}
                    {r.method && r.method !== 'manual' && (
                      <span className="text-muted-foreground"> · {t(METHOD_LABELS[r.method] ?? r.method)}</span>
                    )}
                  </span>
                )}
                {r.status === 'error' && (
                  <span className="text-destructive">✗ {r.reason}</span>
                )}
                {r.status === 'already_has_pdf' && (
                  <>
                    <span className="text-warning">
                      {t('matches “{{title}}” which already has a PDF', { title: r.title?.slice(0, 50) })}
                    </span>
                    <Button variant="outline" size="sm"
                            className="h-6 px-2 text-xs"
                            onClick={() => assign(r.filename, r.record_id!)}>
                      {t('Replace it')}
                    </Button>
                  </>
                )}
                {(r.status === 'ambiguous' || r.status === 'unmatched') && (
                  <AssignPicker rows={rows} candidates={r.candidates ?? []}
                                onPick={(rid) => assign(r.filename, rid)} />
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  )
}

/** “Which article is this file?” — best candidates first, then the whole
 * library. Picking one uploads immediately. */
function AssignPicker({ rows, candidates, onPick }: {
  rows: FullTextRow[]
  candidates: BulkCandidate[]
  onPick: (recordId: number) => void
}) {
  const { t } = useTranslation()
  const candidateIds = new Set(candidates.map((c) => c.record_id))
  return (
    <Select onValueChange={(v) => onPick(Number(v))}>
      <SelectTrigger className="h-6 w-72 text-xs">
        <SelectValue placeholder={t('not recognized — pick the article…')} />
      </SelectTrigger>
      <SelectContent>
        {candidates.map((c) => (
          <SelectItem key={c.record_id} value={String(c.record_id)}>
            {`≈${c.score}% — ${c.title.slice(0, 70)}${c.year ? ` (${c.year})` : ''}`}
          </SelectItem>
        ))}
        {rows.filter((r) => !candidateIds.has(r.record_id)).map((r) => (
          <SelectItem key={r.record_id} value={String(r.record_id)}>
            {`${r.title.slice(0, 70)}${r.year ? ` (${r.year})` : ''}`}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

const STATUS_VARIANT: Record<string, 'success' | 'warning' | 'default' | 'outline'> = {
  retrieved: 'success',
  manual: 'default',
  not_found: 'warning',
  pending: 'outline',
}

function FullTextRowView({ projectId, row, isAdmin, onChange }: {
  projectId: number
  row: FullTextRow
  isAdmin: boolean
  onChange: () => void
}) {
  const { t } = useTranslation()
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState('')
  const openPdf = usePdfWindow()
  // cache-buster: the URL changes on every re-upload so the browser (and an
  // already-open viewer) never shows the pre-replacement copy (bug B2)
  const fileUrl = `/api/projects/${projectId}/fulltext/records/${row.record_id}/file`
    + (row.updated_at ? `?v=${encodeURIComponent(row.updated_at)}` : '')

  const upload = async (file: File) => {
    setBusy(t('Uploading…'))
    const form = new FormData()
    form.append('file', file)
    try {
      const res = await fetch(
        `/api/projects/${projectId}/fulltext/records/${row.record_id}/upload`,
        { method: 'POST', credentials: 'include', body: form })
      if (!res.ok) throw new ApiError(res.status, (await res.json()).detail)
      onChange()
    } catch (e) {
      setBusy(`✗ ${e instanceof ApiError ? e.message : t('Upload failed')}`)
      return
    }
    setBusy('')
  }
  const remove = useMutation({
    mutationFn: () => api.del(
      `/api/projects/${projectId}/fulltext/records/${row.record_id}`),
    onSuccess: onChange,
  })

  return (
    <tr className="border-b border-border align-top">
      <td className="p-3">
        <Badge variant={STATUS_VARIANT[row.status] ?? 'outline'}>
          {row.status === 'manual' ? t('uploaded') : t(row.status.replace('_', ' '))}
        </Badge>
      </td>
      <td className="p-3">
        <p className="text-foreground">{row.title}</p>
        <p className="text-xs text-muted-foreground">
          {row.authors.length > 0 && (
            <>{row.authors[0]}{row.authors.length > 1 ? ' et al.' : ''} · </>
          )}
          {row.year ?? ''}
          {row.doi && (
            <> · <a href={`https://doi.org/${row.doi}`} target="_blank" rel="noreferrer"
                    className="font-mono text-primary hover:underline">{row.doi}</a></>
          )}
        </p>
        {row.status === 'not_found' && (
          <p className="mt-0.5 text-xs text-warning">
            {row.error}
            {row.oa_url && (
              <> · <a href={row.oa_url} target="_blank" rel="noreferrer"
                      className="text-primary hover:underline">{t('open publisher page ↗')}</a></>
            )}
          </p>
        )}
      </td>
      <td className="p-3 text-xs text-muted-foreground">
        {row.via || '—'}
        {row.size_kb ? <span className="text-muted-foreground/70"> · {row.size_kb} kB</span> : ''}
      </td>
      <td className="p-3">
        <div className="flex items-center gap-2">
          {/* upload/replace is open to every member (a reviewer fixes a
              missing or wrong PDF on the spot); removal stays admin-only */}
          <input ref={inputRef} type="file" accept=".pdf,application/pdf"
                 className="hidden"
                 onChange={(e) => {
                   const f = e.target.files?.[0]
                   if (f) upload(f)
                   e.target.value = ''
                 }} />
          {row.has_file ? (
            <>
              <Button variant="outline" size="sm"
                      title={t('Open in the built-in viewer (search & annotations)')}
                      onClick={() => openPdf({ projectId,
                        recordId: row.record_id, title: row.title })}>
                {t('Open')}
              </Button>
              <Button asChild variant="outline" size="sm" title={t('Download PDF')}>
                <a href={fileUrl} download>↓</a>
              </Button>
              <Button variant="outline" size="sm"
                      onClick={() => inputRef.current?.click()}
                      title={t('Replace with another PDF (e.g. wrong or truncated file)')}>
                {t('Replace')}
              </Button>
              {isAdmin && (
                <Button variant="ghost" size="sm"
                        className="text-muted-foreground hover:text-destructive"
                        onClick={() => remove.mutate()} title={t('Remove PDF')}>✕</Button>
              )}
            </>
          ) : (
            <Button variant="outline" size="sm" onClick={() => inputRef.current?.click()}
                    title={t('Upload the PDF of this report from your computer')}>
              {t('Upload PDF')}
            </Button>
          )}
          {busy && <span className={cn('text-xs', busy.startsWith('✗')
            ? 'text-destructive' : 'text-muted-foreground')}>{busy}</span>}
        </div>
      </td>
    </tr>
  )
}

// ---- settings -------------------------------------------------------------------

function SettingsTab({ projectId }: { projectId: number }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: config } = useQuery<{
    unpaywall_email: string; institutions: InstitutionOut[]
    default_email: string; inherited_institutions: InstitutionOut[]
  }>({
    queryKey: ['fulltext-config', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/fulltext/config`),
  })
  const [email, setEmail] = useState('')
  const [institutions, setInstitutions] = useState<(InstitutionOut & { password?: string })[]>([])
  const [loaded, setLoaded] = useState(false)
  const [status, setStatus] = useState('')

  if (config && !loaded) {
    setEmail(config.unpaywall_email)
    setInstitutions(config.institutions)
    setLoaded(true)
  }

  const save = useMutation({
    mutationFn: () => api.put(`/api/projects/${projectId}/fulltext/config`, {
      unpaywall_email: email,
      institutions: institutions.map((i) => ({
        name: i.name, ezproxy_url: i.ezproxy_url, username: i.username,
        password: i.password ?? '', scope: i.scope, auth_type: i.auth_type })),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fulltext-config', projectId] })
      setStatus(t('✓ Saved'))
      setInstitutions((list) => list.map((i) => ({ ...i, password: '' })))
    },
    onError: (e) => setStatus(e instanceof ApiError ? e.message : t('Save failed')),
  })

  return (
    <Card className="max-w-2xl space-y-5 p-5">
      <div>
        <label className="mb-1 block text-sm font-medium text-foreground">
          {t('Unpaywall email')}
        </label>
        <Input
          type="email" value={email}
          placeholder={config?.default_email || 'you@lab.org'}
          onChange={(e) => setEmail(e.target.value)}
        />
        <p className="mt-1 text-xs text-muted-foreground">
          {t('Free, no signup. Required to query Unpaywall for legal open-access PDFs. Left empty, your LitUbik login email{{email}} is used.',
             { email: config?.default_email ? ` (${config.default_email})` : '' })}
        </p>
      </div>
      {config && config.inherited_institutions.length > 0 && (
        <div>
          <label className="mb-1 block text-sm font-medium text-foreground">
            {t('Shared institutions')} <span className="font-normal text-muted-foreground">
              {t('(global — used by every project)')}</span>
          </label>
          <InstitutionList items={config.inherited_institutions}
                           empty={t('None yet.')} />
          <p className="mt-1 text-xs text-muted-foreground">
            {t('Imported once from your existing setup; tried for every project. Add project-specific access below.')}
          </p>
        </div>
      )}
      <div>
        <label className="mb-1 block text-sm font-medium text-foreground">
          {t('Project-specific institutions (EZProxy / CAS)')}
        </label>
        <ServerInstitutionsEditor items={institutions} onChange={setInstitutions} />
        <p className="text-xs text-muted-foreground">
          {t('Passwords are stored encrypted and never displayed again. Tried in order, after open-access sources.')}
        </p>
      </div>
      <div className="flex items-center gap-3">
        <Button onClick={() => save.mutate()} disabled={save.isPending}>
          {t('Save settings')}
        </Button>
        {status && (
          <span className={cn('text-sm', status.startsWith('✓')
            ? 'text-success' : 'text-destructive')}>{status}</span>
        )}
      </div>
    </Card>
  )
}
