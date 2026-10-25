// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Archive, FolderOpen, FolderSync, Settings, X } from 'lucide-react'
import {
  api, ApiError, type JobInfo, type Member, type Project,
  type SyncImportReport, type User,
} from '../api'
import { useJobWatcher } from '../useJob'
import { ImportReportView } from './Sync'
import { cn } from '@/lib/utils'
import { fmtDuration } from '@/lib/duration'
import { STEPS } from '@/components/AppSidebar'
import { isSandbox, useInstance } from '@/components/DemoBanner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Segmented } from '@/components/ui/segmented'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'

// The pills below and the sidebar show the same pipeline, so they read the
// same list: a hand-copied duplicate of STEPS is how a new step ends up
// visible in one place and missing in the other.
const PIPELINE_STEPS = STEPS.filter((s) => s.path)

export default function Projects() {
  const { t } = useTranslation()
  // living review: unread "new candidates" notices per project
  const { data: notices } = useQuery<{ unread: number; by_project: Record<string, number> }>({
    queryKey: ['notifications-summary'],
    queryFn: () => api.get('/api/notifications/summary'),
    refetchInterval: 60_000,
  })
  const queryClient = useQueryClient()
  const [view, setView] = useState<'active' | 'archived'>('active')
  const { data: projects = [], isLoading } = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: () => api.get('/api/projects'),
  })
  const { data: archived = [] } = useQuery<Project[]>({
    queryKey: ['projects', 'archived'],
    queryFn: () => api.get('/api/projects?archived=true'),
  })
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [openProject, setOpenProject] = useState<Project | null>(null)
  // demo visitors: no members, no shared folders, no project imports (the
  // backend refuses them), and no access setup to walk through
  const { data: me } = useQuery<User | null>({
    queryKey: ['me'], queryFn: () => api.get('/api/auth/me'),
  })
  const { data: instance } = useInstance()
  const sandbox = isSandbox(me, instance)

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['projects'] })
    queryClient.invalidateQueries({ queryKey: ['projects', 'archived'] })
  }
  const navigate = useNavigate()
  const createProject = useMutation({
    mutationFn: () => api.post<Project>('/api/projects', { name, description }),
    onSuccess: (p) => {
      invalidate()
      setShowForm(false)
      setName('')
      setDescription('')
      // M4b: walk the creator through the access setup (institution, database
      // keys, AI keys) — every step skippable. A demo visitor has none to set.
      navigate(sandbox ? `/projects/${p.id}/protocol`
                       : `/projects/${p.id}/settings?setup=1`)
    },
  })
  const archiveProject = useMutation({
    mutationFn: (id: number) => api.post(`/api/projects/${id}/archive`),
    onSuccess: invalidate,
  })
  const unarchiveProject = useMutation({
    mutationFn: (id: number) => api.post(`/api/projects/${id}/unarchive`),
    onSuccess: invalidate,
  })
  const deleteProject = useMutation({
    mutationFn: (id: number) => api.del(`/api/projects/${id}`),
    onSuccess: invalidate,
  })

  if (isLoading) return <p className="text-muted-foreground">{t('Loading projects…')}</p>

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight text-foreground">{t('Projects')}</h1>
          <Segmented
            value={view}
            onChange={setView}
            options={[
              { value: 'active', label: t('Active') },
              { value: 'archived', label: t('Archived ({{count}})', { count: archived.length }) },
            ]}
          />
        </div>
        {view === 'active' && (
          <div className="flex items-center gap-2">
            {!sandbox && <JoinFolderButton />}
            {!sandbox && <ImportSnapshotButton />}
            <Button data-tour="new-project" onClick={() => setShowForm((v) => !v)}>{t('New project')}</Button>
          </div>
        )}
      </div>

      {view === 'archived' && (
        <div className="grid gap-4 sm:grid-cols-2">
          {archived.length === 0 && (
            <p className="text-sm text-muted-foreground">{t('No archived projects.')}</p>
          )}
          {archived.map((p) => (
            <Card key={p.id} className="p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h2 className="font-semibold text-foreground">{p.name}</h2>
                  {p.archived_at && (
                    <p className="text-xs text-muted-foreground">
                      {t('Archived {{date}}', { date: new Date(p.archived_at).toLocaleDateString() })}
                    </p>
                  )}
                </div>
                <Badge variant="outline" className="shrink-0">{t(p.my_role)}</Badge>
              </div>
              {p.description && (
                <p className="mt-1 text-sm text-muted-foreground">{p.description}</p>
              )}
              {p.my_role === 'admin' && (
                <div className="mt-3 flex gap-2">
                  <Button variant="outline" size="sm"
                          onClick={() => unarchiveProject.mutate(p.id)}
                          disabled={unarchiveProject.isPending}>
                    {t('Restore')}
                  </Button>
                  <Button
                    variant="outline" size="sm"
                    className="border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive"
                    onClick={() => {
                      if (confirm(t('Permanently delete “{{name}}” and all its data (records, votes, PDFs, PRISMA…)? This cannot be undone.', { name: p.name })))
                        deleteProject.mutate(p.id)
                    }}
                    disabled={deleteProject.isPending}>
                    {t('Delete permanently')}
                  </Button>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      {view === 'active' && <>

      {showForm && (
        <Card className="mb-6 max-w-xl p-4">
          <form
            onSubmit={(e) => { e.preventDefault(); createProject.mutate() }}
            className="flex flex-col gap-3"
          >
            <Input
              required placeholder={t('Project name')} value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <Textarea
              placeholder={t('Description (optional)')} value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <div className="flex gap-2">
              <Button type="submit" disabled={createProject.isPending}>{t('Create')}</Button>
              <Button type="button" variant="outline" onClick={() => setShowForm(false)}>
                {t('Cancel')}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {projects.length === 0 && !showForm && (
        <p className="text-sm text-muted-foreground">
          {t('No projects yet. Create your first systematic review project.')}
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {projects.map((p) => (
          <Card key={p.id} className="p-4">
            <div className="flex items-start justify-between gap-2">
              <h2 className="font-semibold text-foreground">{p.name}</h2>
              <span className="flex shrink-0 items-center gap-2">
                {p.sync_role === 'satellite' && (
                  <Badge
                    variant="warning"
                    title={t('Satellite copy — structural state managed by the coordinator')}
                  >
                    {t('satellite')}
                  </Badge>
                )}
                {(notices?.by_project[String(p.id)] ?? 0) > 0 && (
                  <Badge asChild variant="default"
                         title={t('New candidates found by a search update — open the Search page')}>
                    <Link to={`/projects/${p.id}/search`}>
                      {t('{{count}} new', { count: notices!.by_project[String(p.id)] })}
                    </Link>
                  </Badge>
                )}
                <Badge variant="outline">{t(p.my_role)}</Badge>
                {p.my_role === 'admin' && (
                  <>
                    <Button
                      asChild variant="ghost" size="icon"
                      className="size-7 text-muted-foreground hover:text-foreground"
                      title={t('Project settings (keys, members, highlights…)')}
                    >
                      <Link to={`/projects/${p.id}/settings`}>
                        <Settings className="size-4" />
                      </Link>
                    </Button>
                    <Button
                      variant="ghost" size="icon"
                      className="size-7 text-muted-foreground hover:text-foreground"
                      title={t('Archive project (reversible)')}
                      disabled={archiveProject.isPending}
                      onClick={() => archiveProject.mutate(p.id)}
                    >
                      <Archive className="size-4" />
                    </Button>
                  </>
                )}
              </span>
            </div>
            {p.description && (
              <p className="mt-1 text-sm text-muted-foreground">{p.description}</p>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-1">
              <PipelinePills project={p} />
              {!sandbox && (
                <button
                  onClick={() => setOpenProject(openProject?.id === p.id ? null : p)}
                  className="ml-2 text-xs text-primary hover:underline"
                >
                  {openProject?.id === p.id ? t('Hide members') : t('Members')}
                </button>
              )}
            </div>
            {openProject?.id === p.id && <MembersPanel project={p} />}
          </Card>
        ))}
      </div>
      </>}
    </div>
  )
}

/** One-step join for a co-reviewer: point at the shared folder the
 * coordinator publishes into — the latest snapshot there is imported and the
 * project is linked to the folder (all later exchanges become automatic). */
function JoinFolderButton() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [path, setPath] = useState('')
  const jobRef = useRef<number | null>(null)
  const [report, setReport] = useState<SyncImportReport | null>(null)
  const watcher = useJobWatcher(async () => {
    if (jobRef.current === null) return
    const job = await api.get<JobInfo>(`/api/jobs/${jobRef.current}`)
    if (job.status === 'done') {
      setReport(job.result as unknown as SyncImportReport)
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      queryClient.invalidateQueries({ queryKey: ['project-progress'] })
    }
  })
  const join = async () => {
    setReport(null)
    try {
      const { job_id } = await api.post<{ job_id: number }>(
        '/api/sync/join-folder', { path })
      jobRef.current = job_id
      watcher.watch(job_id)
      setOpen(false)
    } catch (e) {
      watcher.setError(e instanceof ApiError ? e.message : String(e))
    }
  }
  return (
    <>
      {open ? (
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => { e.preventDefault(); join() }}
        >
          <Input
            autoFocus required value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder={t('C:\\Users\\me\\Nextcloud\\SLRproject')}
            className="w-72"
          />
          <Button type="submit" disabled={!!watcher.state}>{t('Join')}</Button>
          <Button type="button" variant="ghost"
                  onClick={() => setOpen(false)}>
            {t('Cancel')}
          </Button>
        </form>
      ) : (
        <Button variant="outline" onClick={() => setOpen(true)}
                disabled={!!watcher.state}
                title={t('The coordinator publishes into a shared folder (Nextcloud/Drive…) that you sync? Paste its local path: the project is imported and linked to the folder in one step.')}>
          <FolderOpen className="size-4" />
          {watcher.state ? watcher.state : t('Join via a shared folder')}
        </Button>
      )}
      {(watcher.error || report) && (
        <div className="fixed bottom-4 right-4 z-50 max-w-md rounded-md border border-border bg-background p-3 shadow-lg">
          {watcher.error && <p className="text-sm text-destructive">{watcher.error}</p>}
          {report && <ImportReportView report={report} />}
          <button
            className="mt-2 text-xs text-muted-foreground hover:text-foreground"
            onClick={() => { setReport(null); watcher.setError('') }}
          >
            {t('Close')}
          </button>
        </div>
      )}
    </>
  )
}

/** Import a snapshot archive received from another LitUbik instance: creates
 * (or updates) the local satellite copy of the project. */
function ImportSnapshotButton() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const jobRef = useRef<number | null>(null)
  const [report, setReport] = useState<SyncImportReport | null>(null)
  const watcher = useJobWatcher(async () => {
    if (jobRef.current === null) return
    const job = await api.get<JobInfo>(`/api/jobs/${jobRef.current}`)
    if (job.status === 'done') {
      setReport(job.result as unknown as SyncImportReport)
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      queryClient.invalidateQueries({ queryKey: ['project-progress'] })
    }
  })
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const start = async (file: File, restore = false) => {
    setReport(null)
    const { job_id } = await api.upload<{ job_id: number }>(
      '/api/sync/import-snapshot', file,
      restore ? { restore: 'true' } : undefined)
    jobRef.current = job_id
    watcher.watch(job_id)
  }
  return (
    <>
      <input
        ref={fileInputRef} type="file" accept=".zip" className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) setPendingFile(file)
          e.target.value = ''
        }}
      />
      <Button variant="outline" onClick={() => fileInputRef.current?.click()}
              disabled={!!watcher.state}
              title={t('Create the local copy of a project received from another LitUbik instance, or restore one of your own backups (.zip)')}>
        <FolderSync className="size-4" />
        {watcher.state ? watcher.state : t('Import a project')}
      </Button>
      <Dialog open={!!pendingFile}
              onOpenChange={(o) => { if (!o) setPendingFile(null) }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('What is this archive?')}</DialogTitle>
            <DialogDescription>{pendingFile?.name}</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Button
              onClick={() => { start(pendingFile!); setPendingFile(null) }}
            >
              {t("A coordinator's snapshot — create/update my satellite copy")}
            </Button>
            <p className="text-xs text-muted-foreground">
              {t('The usual case: a co-reviewer sent you their project. Your copy stays linked to theirs; you vote and send contributions back.')}
            </p>
            <Button
              variant="outline"
              className="border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive"
              onClick={() => {
                if (confirm(t('Restore this backup? If the project already exists here, its current state is entirely replaced by the archive — everything done since that export is lost.'))) {
                  start(pendingFile!, true)
                  setPendingFile(null)
                }
              }}
            >
              {t('My own backup — restore it (this instance is the reference)')}
            </Button>
            <p className="text-xs text-muted-foreground">
              {t('For a snapshot exported from YOUR OWN project: recover after a mistake or a crash, or rebuild on a fresh instance. The project is (or becomes) coordinator here.')}
            </p>
          </div>
        </DialogContent>
      </Dialog>
      {(watcher.error || report) && (
        <div className="fixed bottom-4 right-4 z-50 max-w-md rounded-md border border-border bg-background p-3 shadow-lg">
          {watcher.error && <p className="text-sm text-destructive">{watcher.error}</p>}
          {report && <ImportReportView report={report} />}
          <button
            className="mt-2 text-xs text-muted-foreground hover:text-foreground"
            onClick={() => { setReport(null); watcher.setError('') }}
          >
            {t('Close')}
          </button>
        </div>
      )}
    </>
  )
}

/** Pipeline pills with live progress (#9): the current step is highlighted
 * right on the projects page, completed steps get a check. Shares the
 * sidebar's ['project-progress'] cache entry. */
function PipelinePills({ project }: { project: Project }) {
  const { t } = useTranslation()
  const { data: progress } = useQuery<{ current: string; done: string[] }>({
    queryKey: ['project-progress', project.id],
    queryFn: () => api.get(`/api/projects/${project.id}/progress`),
    staleTime: 15_000,
  })
  return (
    <>
      {PIPELINE_STEPS.map(({ id, label, path }, i) => {
        const isCurrent = progress?.current === id
        const isDone = progress?.done.includes(id)
        return (
          <Link
            key={id}
            to={`/projects/${project.id}/${path}`}
            title={isCurrent ? t('You are here — current step')
              : isDone ? t('Step completed') : undefined}
            className={cn(
              'rounded-full px-2.5 py-1 text-xs font-medium transition-colors',
              isCurrent
                ? 'bg-primary text-primary-foreground shadow-sm hover:bg-primary/90'
                : isDone
                  ? 'bg-muted text-foreground hover:bg-accent'
                  : 'bg-muted text-muted-foreground hover:bg-accent hover:text-foreground',
            )}
          >
            {isDone ? '✓ ' : ''}{i + 1}. {t(label)}
          </Link>
        )
      })}
    </>
  )
}

/** Work time (chantier 14) is personal data: every member is told that it
 * is measured, what is measured, who sees the detail — and sees their own
 * total here. */
function WorkTimeNotice({ project }: { project: Project }) {
  const { t } = useTranslation()
  const { data } = useQuery<{ total_seconds: number }>({
    queryKey: ['worktime-me', project.id],
    queryFn: () => api.get(`/api/projects/${project.id}/worktime/me`),
  })
  return (
    <p className="mb-3 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
      {t('Active work time is measured on the screening, dedup, extraction and appraisal pages — per stage only, never per reference. The project admin sees the detail per reviewer.')}
      {data && <> {t('Your total on this project: {{time}}.', { time: fmtDuration(data.total_seconds) })}</>}
      {project.my_role === 'admin' && (
        <> <Link to={`/projects/${project.id}/worktime`} className="underline hover:text-foreground">
          {t('See the detail')}
        </Link></>
      )}
    </p>
  )
}

export function MembersPanel({ project }: { project: Project }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: members = [] } = useQuery<Member[]>({
    queryKey: ['members', project.id],
    queryFn: () => api.get(`/api/projects/${project.id}/members`),
  })
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<'reviewer' | 'admin'>('reviewer')
  const [error, setError] = useState('')

  const addMember = useMutation({
    mutationFn: () => api.post(`/api/projects/${project.id}/members`, { email, role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['members', project.id] })
      setEmail('')
      setError('')
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Failed to add member')),
  })

  return (
    <div className="mt-3 border-t border-border pt-3">
      <WorkTimeNotice project={project} />
      <ul className="mb-3 space-y-1">
        {members.map((m) => (
          <li key={m.email} className="flex items-center justify-between text-sm text-muted-foreground">
            <span>
              {m.status === 'invited'
                ? <span className="italic text-muted-foreground/70">{m.email}</span>
                : <>{m.display_name} <span className="text-muted-foreground">({m.email})</span></>}
              {m.status === 'invited' && (
                <Badge variant="warning" className="ml-2">
                  {t('invited — becomes a member once registered')}
                </Badge>
              )}
              {m.status === 'awaiting' && (
                <Badge
                  variant="warning" className="ml-2"
                  title={t('Already usable everywhere (reviewer, assignments, snapshots) — the person claims this account by registering with this email')}
                >
                  {t('awaiting registration')}
                </Badge>
              )}
            </span>
            <span className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground/70">{t(m.role)}</span>
              {m.status === 'invited' && project.my_role === 'admin' && (
                <Button
                  variant="ghost" size="icon"
                  className="size-6 text-muted-foreground hover:text-destructive"
                  title={t('Revoke invitation')}
                  onClick={() =>
                    api.del(`/api/projects/${project.id}/invitations?email=${encodeURIComponent(m.email)}`)
                      .then(() => queryClient.invalidateQueries(
                        { queryKey: ['members', project.id] }))}
                >
                  <X className="size-3.5" />
                </Button>
              )}
            </span>
          </li>
        ))}
      </ul>
      {project.my_role === 'admin' && (
        <form
          onSubmit={(e) => { e.preventDefault(); addMember.mutate() }}
          className="flex gap-2"
        >
          <Input
            type="email" required placeholder="colleague@lab.org" value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="flex-1"
          />
          <Select value={role} onValueChange={(v) => setRole(v as 'reviewer' | 'admin')}>
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="reviewer">{t('reviewer')}</SelectItem>
              <SelectItem value="admin">{t('admin')}</SelectItem>
            </SelectContent>
          </Select>
          <Button type="submit" variant="secondary">{t('Add')}</Button>
        </form>
      )}
      {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
    </div>
  )
}
