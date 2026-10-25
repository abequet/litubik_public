// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import ReactMarkdown from 'react-markdown'
import { X } from 'lucide-react'
import {
  api, ApiError,
  type CostInfo, type Criterion, type JobInfo, type OsfCandidate,
  type OsfImportResult, type Project, type ProtocolDetail, type ProtocolSummary,
} from '../api'
import { cn } from '@/lib/utils'
import { findFramework, useFramings } from '@/components/framing'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Segmented } from '@/components/ui/segmented'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'

export default function ProtocolPage() {
  const { t } = useTranslation()
  const { projectId } = useParams()
  const pid = Number(projectId)
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: () => api.get('/api/projects'),
  })
  const project = projects.find((p) => p.id === pid)
  const isAdmin = project?.my_role === 'admin'
  const { data: framings } = useFramings()
  const framework = findFramework(framings, project?.question_framework)

  const { data: versions = [], isLoading } = useQuery<ProtocolSummary[]>({
    queryKey: ['protocols', pid],
    queryFn: () => api.get(`/api/projects/${pid}/protocols`),
  })
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const currentId = selectedId ?? versions[0]?.id ?? null

  if (isLoading) return <p className="text-muted-foreground">{t('Loading protocol…')}</p>

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('Protocol')}{project ? ` — ${project.name}` : ''}
      </h1>
      <p className="mb-2 mt-1 max-w-2xl text-sm text-muted-foreground">
        {t('Upload the pre-registered protocol (PDF, DOCX, MD or TXT) — or write/paste it directly — then let the AI extract a structured protocol.md with coded criteria (I1…, E1…), review it, and validate. The validated version is injected into every AI prompt of the pipeline.')}
      </p>
      {framework && (
        <p className="mb-6 max-w-2xl text-xs text-muted-foreground">
          <Badge variant="outline" className="mr-2">{framework.short}</Badge>
          {t('The AI will structure the extraction on:')}{' '}
          <span className="text-foreground">
            {framework.slots.map((s) => t(s.label)).join(' · ')}
          </span>
          {'. '}
          {t('Change it in the project settings — it applies to the next extraction.')}
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
        <aside aria-label={t('Protocol side panel')}>
          {isAdmin && <UploadCard projectId={pid} onUploaded={setSelectedId} />}
          <ul className="space-y-1">
            {versions.map((v) => (
              <li key={v.id}>
                <button
                  onClick={() => setSelectedId(v.id)}
                  className={cn('w-full rounded-md border px-3 py-2 text-left text-sm transition-colors',
                    v.id === currentId
                      ? 'border-border bg-accent text-foreground'
                      : 'border-transparent text-muted-foreground hover:bg-accent hover:text-foreground')}
                >
                  <span className="font-medium">v{v.version}</span>
                  {v.validated_at && (
                    <Badge variant="success" className="ml-2">{t('validated')}</Badge>
                  )}
                  <span className="block truncate text-xs text-muted-foreground">
                    {v.source_filename}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {versions.length === 0 && (
            <p className="mt-2 text-sm text-muted-foreground">{t('No protocol uploaded yet.')}</p>
          )}
        </aside>

        <section>
          {currentId !== null ? (
            <VersionEditor key={currentId} projectId={pid} protocolId={currentId}
                           isAdmin={isAdmin} />
          ) : (
            <Card className="p-6 text-sm text-muted-foreground">
              {isAdmin
                ? t('Start by uploading your protocol document.')
                : t('The project admin has not uploaded a protocol yet.')}
            </Card>
          )}
        </section>
      </div>
    </div>
  )
}

function UploadCard({ projectId, onUploaded }: {
  projectId: number
  onUploaded: (id: number) => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [error, setError] = useState('')
  const [osfUrl, setOsfUrl] = useState('')
  const [candidates, setCandidates] = useState<OsfCandidate[] | null>(null)
  const [showPaste, setShowPaste] = useState(false)
  const [pasteText, setPasteText] = useState('')
  const [pasteName, setPasteName] = useState('')

  const done = (protocol: ProtocolDetail) => {
    queryClient.invalidateQueries({ queryKey: ['protocols', projectId] })
    onUploaded(protocol.id)
    setError('')
    setCandidates(null)
    setOsfUrl('')
    setShowPaste(false)
    setPasteText('')
    setPasteName('')
  }

  const uploadFile = useMutation({
    mutationFn: (file: File) =>
      api.upload<ProtocolDetail>(`/api/projects/${projectId}/protocols/upload`, file),
    onSuccess: done,
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Upload failed')),
  })

  const pasteProtocol = useMutation({
    mutationFn: () => api.post<ProtocolDetail>(
      `/api/projects/${projectId}/protocols/paste`,
      { text: pasteText, name: pasteName.trim() || t('Pasted protocol') }),
    onSuccess: done,
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Import failed')),
  })

  const importOsf = useMutation({
    mutationFn: (pick: OsfCandidate | null) =>
      api.post<OsfImportResult>(`/api/projects/${projectId}/protocols/import-osf`,
        pick ? { url: osfUrl, pick } : { url: osfUrl }),
    onSuccess: (result) => {
      if (result.candidates) {
        setCandidates(result.candidates)
        setError('')
      } else if (result.protocol) {
        done(result.protocol)
      }
    },
    onError: (e) => {
      setCandidates(null)
      setError(e instanceof ApiError ? e.message : t('OSF import failed'))
    },
  })

  return (
    <div className="mb-4 space-y-2">
      <input
        ref={inputRef} type="file" accept=".pdf,.docx,.md,.txt" className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) uploadFile.mutate(file)
          e.target.value = ''
        }}
      />
      <Button
        className="w-full"
        onClick={() => inputRef.current?.click()}
        disabled={uploadFile.isPending}
      >
        {uploadFile.isPending ? t('Uploading…') : t('Upload new version')}
      </Button>

      <Button variant="outline" className="w-full" onClick={() => setShowPaste(true)}>
        {t('✎ Write / paste text')}
      </Button>

      <PasteModal
        open={showPaste} onOpenChange={setShowPaste}
        name={pasteName} text={pasteText}
        onName={setPasteName} onText={setPasteText}
        pending={pasteProtocol.isPending}
        onSubmit={() => { if (pasteText.trim()) pasteProtocol.mutate() }}
      />

      <form
        onSubmit={(e) => { e.preventDefault(); setCandidates(null); importOsf.mutate(null) }}
        className="flex gap-1"
      >
        <Input
          type="url" required placeholder="https://osf.io/…" value={osfUrl}
          onChange={(e) => setOsfUrl(e.target.value)}
          className="min-w-0 flex-1"
        />
        <Button
          type="submit" variant="outline"
          disabled={importOsf.isPending || !osfUrl}
        >
          {importOsf.isPending ? '…' : 'OSF'}
        </Button>
      </form>
      <p className="text-xs text-muted-foreground">
        {t('Or paste an OSF link (registration, project or file).')}
      </p>

      {candidates && (
        <div className="rounded-md border border-border bg-muted p-2">
          <p className="mb-1 text-xs font-medium text-foreground">
            {t('Several documents found — pick one:')}
          </p>
          <ul className="space-y-1">
            {candidates.map((c, i) => (
              <li key={i}>
                <button
                  onClick={() => importOsf.mutate(c)}
                  disabled={importOsf.isPending}
                  className="w-full truncate text-left text-sm text-primary hover:underline"
                  title={c.name}
                >
                  {c.kind === 'form' ? '📋 ' : '📄 '}{c.name}
                  {c.size != null && (
                    <span className="text-xs text-muted-foreground"> ({Math.round(c.size / 1024)} kB)</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  )
}

function PasteModal({ open, onOpenChange, name, text, onName, onText, pending, onSubmit }: {
  open: boolean
  onOpenChange: (v: boolean) => void
  name: string
  text: string
  onName: (v: string) => void
  onText: (v: string) => void
  pending: boolean
  onSubmit: () => void
}) {
  const { t } = useTranslation()
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('Write or paste the protocol')}</DialogTitle>
          <DialogDescription>
            {t('Paste the protocol text (objectives, question framing, eligibility criteria…). It becomes a new version you can then structure with the AI or edit by hand — exactly like an uploaded file.')}
          </DialogDescription>
        </DialogHeader>
        <Input
          value={name} onChange={(e) => onName(e.target.value)}
          placeholder={t('Version name (optional) — e.g. Registered protocol')}
        />
        <Textarea
          value={text} onChange={(e) => onText(e.target.value)}
          autoFocus placeholder={t('Paste the protocol text here…')}
          className="h-72 font-mono"
        />
        <DialogFooter className="items-center">
          <span className="mr-auto text-xs tabular-nums text-muted-foreground">
            {t('{{count}} characters', { count: text.trim().length })}
          </span>
          <Button variant="outline" onClick={() => onOpenChange(false)}>{t('Cancel')}</Button>
          <Button onClick={onSubmit} disabled={pending || !text.trim()}>
            {pending ? t('Importing…') : t('Create version')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function VersionEditor({ projectId, protocolId, isAdmin }: {
  projectId: number
  protocolId: number
  isAdmin: boolean
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const base = `/api/projects/${projectId}/protocols/${protocolId}`
  const { data: protocol } = useQuery<ProtocolDetail>({
    queryKey: ['protocol', projectId, protocolId],
    queryFn: () => api.get(base),
  })

  const [md, setMd] = useState<string | null>(null)
  const [criteria, setCriteria] = useState<Criterion[] | null>(null)
  const [tab, setTab] = useState<'edit' | 'preview'>('edit')
  const [genState, setGenState] = useState('')
  const [genCost, setGenCost] = useState<CostInfo | null>(null)
  const [error, setError] = useState('')
  const eventSourceRef = useRef<EventSource | null>(null)
  useEffect(() => () => eventSourceRef.current?.close(), [])

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['protocols', projectId] })
    queryClient.invalidateQueries({ queryKey: ['protocol', projectId, protocolId] })
  }

  const save = useMutation({
    mutationFn: () => api.put<ProtocolDetail>(base, {
      protocol_md: md ?? protocol?.protocol_md ?? '',
      criteria: criteria ?? protocol?.criteria ?? [],
    }),
    onSuccess: () => { refresh(); setMd(null); setCriteria(null); setError('') },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const act = (action: string) => api.post<ProtocolDetail>(`${base}/${action}`)
  const validate = useMutation({
    mutationFn: () => act('validate'),
    onSuccess: refresh,
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Validation failed')),
  })
  const unvalidate = useMutation({ mutationFn: () => act('unvalidate'), onSuccess: refresh })

  const generate = async () => {
    setGenState(t('Starting…'))
    setError('')
    try {
      const { job_id } = await api.post<{ job_id: number }>(`${base}/generate`, {})
      const es = new EventSource(`/api/jobs/${job_id}/stream`, { withCredentials: true })
      eventSourceRef.current = es
      es.onmessage = (event) => {
        const job = JSON.parse(event.data) as JobInfo
        if (job.status === 'running' || job.status === 'queued') {
          setGenState(job.message || t('Working…'))
        } else if (job.status === 'done') {
          setGenState('')
          es.close()
          setMd(null)
          setCriteria(null)
          refresh()
          api.get<JobInfo>(`/api/jobs/${job.id}`).then((j) =>
            setGenCost((j.result as { cost?: CostInfo })?.cost ?? null))
        } else {
          setGenState('')
          setError(job.error.split('\n')[0] || t('Generation failed'))
          es.close()
        }
      }
      es.onerror = () => { es.close(); setGenState('') }
    } catch (e) {
      setGenState('')
      setError(e instanceof ApiError ? e.message : t('Could not start generation'))
    }
  }

  if (!protocol) return <p className="text-muted-foreground">{t('Loading version…')}</p>

  const validated = protocol.validated_at !== null
  const editable = isAdmin && !validated
  const mdValue = md ?? protocol.protocol_md
  const criteriaValue = criteria ?? protocol.criteria
  const dirty = md !== null || criteria !== null

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-40 flex-1">
            <p className="text-sm font-medium text-foreground">
              v{protocol.version} — {protocol.source_filename}
              <span className="font-normal text-muted-foreground">
                {' '}{t('({{count}} chars extracted)', { count: protocol.source_text_chars.toLocaleString() })}
              </span>
            </p>
            {protocol.generated_with && (
              <p className="text-xs text-muted-foreground">
                {t('generated with {{model}}', { model: protocol.generated_with })}
                {genCost && (
                  <span title={`${genCost.tokens_in} in / ${genCost.tokens_out} out`}>
                    {' '}· {t('cost {{cost}}', { cost: genCost.cost_label })}
                  </span>
                )}
              </p>
            )}
          </div>
          {editable && (
            <Button size="sm" onClick={generate} disabled={!!genState}>
              {genState || (protocol.has_content ? t('Regenerate with AI') : t('Generate with AI'))}
            </Button>
          )}
          {editable && (
            <Button variant="outline" size="sm"
                    onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
              {t('Save changes')}
            </Button>
          )}
          {editable && protocol.has_content && (
            <Button variant="success" size="sm"
                    onClick={() => validate.mutate()} disabled={dirty || validate.isPending}
                    title={dirty ? t('Save your changes first') : ''}>
              {t('Validate')}
            </Button>
          )}
          {isAdmin && validated && (
            <Button variant="outline" size="sm" onClick={() => unvalidate.mutate()}>
              {t('Reopen for editing')}
            </Button>
          )}
        </div>
        {validated && (
          <p className="mt-2 rounded-md bg-success/10 px-3 py-2 text-sm text-success">
            {t('✓ Validated on {{date}} — this version is the context pack used by all AI modules. Editing is locked.', { date: new Date(protocol.validated_at!).toLocaleString() })}
          </p>
        )}
        {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
      </Card>

      <Card>
        <div className="flex items-center gap-2 border-b border-border px-4 py-2">
          <Segmented
            value={tab}
            onChange={setTab}
            options={[
              { value: 'edit', label: editable ? 'protocol.md' : t('protocol.md (read-only)') },
              { value: 'preview', label: t('Preview') },
            ]}
          />
        </div>
        <div className="p-4">
          {tab === 'edit' ? (
            <Textarea
              value={mdValue}
              onChange={(e) => setMd(e.target.value)}
              readOnly={!editable}
              placeholder={t('Generate with AI or write the protocol here…')}
              className="h-96 font-mono read-only:bg-muted"
            />
          ) : (
            <div className="prose prose-sm max-w-none min-h-24 text-sm text-foreground
                            [&_h1]:text-xl [&_h1]:font-bold [&_h1]:mb-3
                            [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:mt-5 [&_h2]:mb-2
                            [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5
                            [&_p]:my-2 [&_li]:my-0.5">
              <ReactMarkdown>{mdValue || t('*Nothing to preview yet.*')}</ReactMarkdown>
            </div>
          )}
        </div>
      </Card>

      <CriteriaTable
        criteria={criteriaValue}
        editable={editable}
        onChange={(next) => setCriteria(next)}
      />
    </div>
  )
}

function CriteriaTable({ criteria, editable, onChange }: {
  criteria: Criterion[]
  editable: boolean
  onChange: (next: Criterion[]) => void
}) {
  const { t } = useTranslation()
  const update = (i: number, patch: Partial<Criterion>) =>
    onChange(criteria.map((c, j) => (j === i ? { ...c, ...patch } : c)))
  const nextCode = (type: 'include' | 'exclude') => {
    const prefix = type === 'include' ? 'I' : 'E'
    const nums = criteria
      .filter((c) => c.code.toUpperCase().startsWith(prefix))
      .map((c) => parseInt(c.code.slice(1), 10) || 0)
    return `${prefix}${Math.max(0, ...nums) + 1}`
  }
  const add = (type: 'include' | 'exclude') =>
    onChange([...criteria, { code: nextCode(type), type, label: '', description: '' }])

  const cell = 'w-full rounded-md border border-input bg-transparent px-2 py-1 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] read-only:border-transparent read-only:ring-0'

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-foreground">
          {t('Screening criteria')} <span className="font-normal text-muted-foreground">
            {t('(codes used as exclusion reasons in later stages)')}</span>
        </h2>
        {editable && (
          <div className="flex gap-3">
            <button onClick={() => add('include')}
                    className="text-sm text-primary hover:underline">{t('+ inclusion')}</button>
            <button onClick={() => add('exclude')}
                    className="text-sm text-primary hover:underline">{t('+ exclusion')}</button>
          </div>
        )}
      </div>
      {criteria.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('No criteria yet.')}</p>
      ) : (
        <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="w-16 pb-1">{t('Code')}</th>
              <th className="w-24 pb-1">{t('Type')}</th>
              <th className="w-1/4 pb-1">{t('Label')}</th>
              <th className="pb-1">{t('Description')}</th>
              {editable && <th className="w-8"><span className="sr-only">{t('Actions')}</span></th>}
            </tr>
          </thead>
          <tbody>
            {criteria.map((c, i) => (
              <tr key={i} className="align-top">
                <td className="py-1 pr-2">
                  <input value={c.code} readOnly={!editable} aria-label={t('Code')}
                         className={cn(cell, 'font-mono')}
                         onChange={(e) => update(i, { code: e.target.value })} />
                </td>
                <td className="py-1 pr-2">
                  {editable ? (
                    <Select value={c.type}
                            onValueChange={(v) => update(i, { type: v as Criterion['type'] })}>
                      <SelectTrigger className="h-8 w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="include">{t('include')}</SelectItem>
                        <SelectItem value="exclude">{t('exclude')}</SelectItem>
                      </SelectContent>
                    </Select>
                  ) : (
                    <Badge variant={c.type === 'include' ? 'success' : 'destructive'}>
                      {t(c.type)}
                    </Badge>
                  )}
                </td>
                <td className="py-1 pr-2">
                  <input value={c.label} readOnly={!editable} className={cell} aria-label={t('Label')}
                         onChange={(e) => update(i, { label: e.target.value })} />
                </td>
                <td className="py-1 pr-2">
                  <textarea value={c.description} readOnly={!editable} rows={1}
                            aria-label={t('Description')} className={cn(cell, 'resize-y')}
                            onChange={(e) => update(i, { description: e.target.value })} />
                </td>
                {editable && (
                  <td className="py-1">
                    <Button variant="ghost" size="icon"
                            className="size-6 text-muted-foreground hover:text-destructive"
                            title={t('Remove')}
                            onClick={() => onChange(criteria.filter((_, j) => j !== i))}>
                      <X className="size-3.5" />
                    </Button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </Card>
  )
}
