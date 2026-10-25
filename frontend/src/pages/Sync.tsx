// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import {
  ArrowDownToLine, ArrowUpFromLine, Download, FolderOpen, FolderSync,
  Globe, KeyRound, RefreshCw, Satellite, Trash2, Upload,
} from 'lucide-react'
import {
  api, ApiError, type ContribImportReport, type FolderScanSummary,
  type FolderState, type JobInfo, type Project, type SharedKey,
  type SyncEventInfo, type SyncImportReport, type SyncInfo,
} from '../api'
import { useJobWatcher } from '../useJob'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'

/** Page Synchronisation : instantanés (coordinateur → satellites, phase 1)
 * et paquets de contributions (satellite → coordinateur, phase 2), plus le
 * journal des échanges. */
export default function SyncPage() {
  const { t } = useTranslation()
  const { projectId } = useParams()
  const pid = Number(projectId)
  const queryClient = useQueryClient()

  const { data: info } = useQuery<SyncInfo>({
    queryKey: ['sync', pid],
    queryFn: () => api.get(`/api/projects/${pid}/sync`),
  })
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: () => api.get('/api/projects'),
  })
  const isAdmin = projects.find((p) => p.id === pid)?.my_role === 'admin'
  const isSatellite = info?.sync_role === 'satellite'

  // ---- export d'instantané ----
  const [includePdfs, setIncludePdfs] = useState(true)
  const exportJobRef = useRef<number | null>(null)
  const [download, setDownload] = useState<{ jobId: number; filename: string;
    sizeKb: number } | null>(null)
  const exportWatcher = useJobWatcher(async () => {
    if (exportJobRef.current === null) return
    const job = await api.get<JobInfo>(`/api/jobs/${exportJobRef.current}`)
    if (job.status === 'done') {
      setDownload({
        jobId: job.id,
        filename: String(job.result.filename ?? 'snapshot.zip'),
        sizeKb: Number(job.result.size_kb ?? 0),
      })
      queryClient.invalidateQueries({ queryKey: ['sync', pid] })
    }
  })
  const startExport = async () => {
    setDownload(null)
    const { job_id } = await api.post<{ job_id: number }>(
      `/api/projects/${pid}/sync/export-snapshot`,
      { include_pdfs: includePdfs })
    exportJobRef.current = job_id
    exportWatcher.watch(job_id)
  }

  // ---- archive de réplication publique (sans contenus sous droits) ----
  const [pseudonymize, setPseudonymize] = useState(false)
  const publicJobRef = useRef<number | null>(null)
  const [publicDownload, setPublicDownload] = useState<{ jobId: number;
    filename: string; sizeKb: number } | null>(null)
  const publicWatcher = useJobWatcher(async () => {
    if (publicJobRef.current === null) return
    const job = await api.get<JobInfo>(`/api/jobs/${publicJobRef.current}`)
    if (job.status === 'done') {
      setPublicDownload({
        jobId: job.id,
        filename: String(job.result.filename ?? 'replication.zip'),
        sizeKb: Number(job.result.size_kb ?? 0),
      })
    }
  })
  const startPublicExport = async () => {
    setPublicDownload(null)
    const { job_id } = await api.post<{ job_id: number }>(
      `/api/projects/${pid}/sync/export-snapshot`,
      { public: true, pseudonymize })
    publicJobRef.current = job_id
    publicWatcher.watch(job_id)
  }

  // ---- import / mise à jour d'instantané ----
  const fileInputRef = useRef<HTMLInputElement>(null)
  const importJobRef = useRef<number | null>(null)
  const [report, setReport] = useState<SyncImportReport | null>(null)
  const importWatcher = useJobWatcher(async () => {
    if (importJobRef.current === null) return
    const job = await api.get<JobInfo>(`/api/jobs/${importJobRef.current}`)
    if (job.status === 'done') {
      setReport(job.result as unknown as SyncImportReport)
      queryClient.invalidateQueries({ queryKey: ['sync', pid] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      // the sidebar stays mounted: without this the pipeline position keeps
      // showing the pre-import state until the window regains focus
      queryClient.invalidateQueries({ queryKey: ['project-progress'] })
    }
  })
  const startImport = async (file: File, restore = false) => {
    setReport(null)
    const { job_id } = await api.upload<{ job_id: number }>(
      '/api/sync/import-snapshot', file,
      restore ? { restore: 'true' } : undefined)
    importJobRef.current = job_id
    importWatcher.watch(job_id)
  }
  const restoreFileRef = useRef<HTMLInputElement>(null)

  // ---- contributions (phase 2) ----
  const [contribBusy, setContribBusy] = useState(false)
  const [contribError, setContribError] = useState('')
  const [contribReport, setContribReport] = useState<ContribImportReport | null>(null)
  const contribFileRef = useRef<HTMLInputElement>(null)
  const { data: events = [] } = useQuery<SyncEventInfo[]>({
    queryKey: ['sync-events', pid],
    queryFn: () => api.get(`/api/projects/${pid}/sync/events`),
  })

  const exportContributions = async () => {
    setContribError('')
    setContribBusy(true)
    try {
      const res = await fetch(`/api/projects/${pid}/sync/export-contributions`,
        { method: 'POST', credentials: 'include' })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new ApiError(res.status, data.detail ?? res.statusText)
      }
      const blob = await res.blob()
      const cd = res.headers.get('Content-Disposition') ?? ''
      const filename = /filename="([^"]+)"/.exec(cd)?.[1]
        ?? 'contributions.litubik-contrib.json'
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
      queryClient.invalidateQueries({ queryKey: ['sync-events', pid] })
    } catch (e) {
      setContribError(e instanceof Error ? e.message : String(e))
    } finally {
      setContribBusy(false)
    }
  }

  const importContributions = async (file: File) => {
    setContribError('')
    setContribReport(null)
    setContribBusy(true)
    try {
      const report = await api.upload<ContribImportReport>(
        `/api/projects/${pid}/sync/import-contributions`, file)
      setContribReport(report)
      queryClient.invalidateQueries({ queryKey: ['sync-events', pid] })
      queryClient.invalidateQueries({ queryKey: ['project-progress'] })
      queryClient.invalidateQueries({ queryKey: ['tags', pid] })
      queryClient.invalidateQueries({ queryKey: ['tagged-records', pid] })
    } catch (e) {
      setContribError(e instanceof Error ? e.message : String(e))
    } finally {
      setContribBusy(false)
    }
  }

  // shared between the coordinator card and the satellite "advanced" fold
  const snapshotExportControls = (
    <>
      <label className="mb-3 flex items-center gap-2 text-sm">
        <input
          type="checkbox" checked={includePdfs}
          onChange={(e) => setIncludePdfs(e.target.checked)}
        />
        {t('Include PDFs (heavier archive, but a complete copy)')}
      </label>
      <div className="flex items-center gap-3">
        <Button onClick={startExport} disabled={!!exportWatcher.state}>
          <Upload className="size-4" /> {t('Export snapshot')}
        </Button>
        {exportWatcher.state && (
          <span className="text-sm text-muted-foreground">{exportWatcher.state}</span>
        )}
        {download && (
          <Button asChild variant="secondary">
            <a href={`/api/projects/${pid}/sync/snapshot-download?job_id=${download.jobId}`}>
              <Download className="size-4" /> {download.filename}
              {download.sizeKb > 0 && ` (${Math.max(1, Math.round(download.sizeKb / 1024))} Mo)`}
            </a>
          </Button>
        )}
      </div>
      {exportWatcher.error && (
        <p className="mt-2 text-sm text-destructive">{exportWatcher.error}</p>
      )}
    </>
  )

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <FolderSync className="size-5 text-muted-foreground" />
        <h1 className="text-xl font-semibold tracking-tight">{t('Synchronisation')}</h1>
        {info && (
          <Badge variant={isSatellite ? 'warning' : 'outline'}>
            {isSatellite ? t('satellite') : t('coordinator')}
          </Badge>
        )}
      </div>

      {info && (
        <Card className="p-4 text-sm">
          {isSatellite ? (
            <p className="flex items-start gap-2">
              <Satellite className="mt-0.5 size-4 shrink-0 text-warning" />
              <span>
                {t('Satellite copy of the project — the structural state (imports, dedup, protocol, configurations, conflict resolution…) is managed by the coordinator')}
                {info.coordinator_email && <> (<b>{info.coordinator_email}</b>)</>}.
                {' '}{t('You can vote, extract and annotate; apply received snapshots here to stay up to date.')}
              </span>
            </p>
          ) : (
            <p className="text-muted-foreground">
              {t("This instance is the project's reference. Export a snapshot so a co-reviewer on another instance can create or update their satellite copy.")}
            </p>
          )}
          <p className="mt-2 text-xs text-muted-foreground">
            {t('Snapshot version:')} <b>v{info.snapshot_version}</b>
            <span className="ml-3 select-all font-mono">{info.uuid}</span>
          </p>
        </Card>
      )}

      {/* Order and emphasis follow the role. Satellite: the everyday action
          is SENDING your contributions; the full snapshot only serves to
          receive updates (or, advanced, to duplicate the copy — never to send
          back, the coordinator would refuse it). Coordinator: the reverse. */}

      {!isSatellite && isAdmin && (
        <Card className="p-4">
          <h2 className="mb-1 font-medium">
            {t('Export snapshot — for your co-reviewers')}
          </h2>
          <p className="mb-3 text-sm text-muted-foreground">
            {t('Complete project archive (data, raw RIS files, protocol{{pdfs}}). On a co-reviewer\'s machine it creates their satellite copy ("Import a project" on their Projects page), then keeps it up to date. It holds content you may not redistribute: to publish the review, use the public replication archive below.',
               { pdfs: includePdfs ? t(', PDFs') : '' })}
          </p>
          {snapshotExportControls}
        </Card>
      )}

      {!isSatellite && isAdmin && (
        <Card className="p-4">
          <h2 className="mb-1 flex items-center gap-2 font-medium">
            <Globe className="size-4 text-muted-foreground" />
            {t('Public replication archive — to publish with a paper')}
          </h2>
          <p className="mb-2 text-sm text-muted-foreground">
            {t('What you may share publicly (OSF, Zenodo, supplementary material): bibliographic metadata, equations and counts, deduplication, votes, conflicts and reasons, appraisal, extraction, the AI-use journal and the deviations. Re-imported into LitUbik, it reproduces the PRISMA counts and the agreement statistics.')}
          </p>
          <p className="mb-3 text-sm text-muted-foreground">
            {t('Left out because they belong to publishers or database vendors: full-text PDFs, abstracts and their translations, raw database exports, passages quoted by PDF annotations. Also left out: shared API keys, pending invitations, reviewers\' work sessions, retrieval diagnostics and the name of the institution whose access fetched a paper. Whoever replicates the review fetches the full texts with their own access.')}
          </p>
          <label className="mb-1 flex items-center gap-2 text-sm">
            <input
              type="checkbox" checked={pseudonymize}
              onChange={(e) => setPseudonymize(e.target.checked)}
            />
            {t('Pseudonymise the reviewers (Reviewer 1, Reviewer 2…), for journals that ask for a blinded package')}
          </label>
          <p className="mb-3 ml-6 text-xs text-muted-foreground">
            {t('Every e-mail address is replaced. Names typed by hand in free-text notes (resolution notes, deviations, comments) are not detected: reread them before publishing.')}
          </p>
          <div className="flex items-center gap-3">
            <Button onClick={startPublicExport} disabled={!!publicWatcher.state}>
              <Upload className="size-4" /> {t('Export public archive')}
            </Button>
            {publicWatcher.state && (
              <span className="text-sm text-muted-foreground">{publicWatcher.state}</span>
            )}
            {publicDownload && (
              <Button asChild variant="secondary">
                <a href={`/api/projects/${pid}/sync/snapshot-download?job_id=${publicDownload.jobId}`}>
                  <Download className="size-4" /> {publicDownload.filename}
                  {publicDownload.sizeKb > 0 && ` (${Math.max(1, Math.round(publicDownload.sizeKb / 1024))} Mo)`}
                </a>
              </Button>
            )}
          </div>
          {publicWatcher.error && (
            <p className="mt-2 text-sm text-destructive">{publicWatcher.error}</p>
          )}
        </Card>
      )}

      <Card className="p-4">
        {isSatellite ? (
          <>
            <h2 className="mb-1 font-medium">
              {t('My contributions — the file to send to the coordinator')}
            </h2>
            <p className="mb-3 text-sm text-muted-foreground">
              {t('After a work session, this is the file (lightweight JSON: your votes, JBI appraisals, extractions, annotations and your support tickets — nothing else) you send to the coordinator. Complete and safe: sent twice or late, it can never overwrite anything newer.')}
            </p>
          </>
        ) : (
          <>
            <h2 className="mb-1 font-medium">{t("Co-reviewers' contributions")}</h2>
            <p className="mb-3 text-sm text-muted-foreground">
              {t('Import here the "my contributions" (.json) files your co-reviewers send you: their votes merge and the conflicts/kappa recompute. (Your own export mostly serves when another admin centralises in your place.)')}
            </p>
          </>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button variant={isSatellite ? 'default' : 'outline'}
                  onClick={exportContributions} disabled={contribBusy}>
            <ArrowUpFromLine className="size-4" /> {t('Export my contributions')}
          </Button>
          {isAdmin && (
            <>
              <input
                ref={contribFileRef} type="file" accept=".json" className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) importContributions(file)
                  e.target.value = ''
                }}
              />
              <Button variant={isSatellite ? 'secondary' : 'default'}
                      disabled={contribBusy}
                      onClick={() => contribFileRef.current?.click()}>
                <ArrowDownToLine className="size-4" />
                {t("Import a co-reviewer's contributions…")}
              </Button>
            </>
          )}
        </div>
        {contribError && (
          <p className="mt-2 text-sm text-destructive">{contribError}</p>
        )}
        {contribReport && <ContribReportView report={contribReport} />}
      </Card>

      {isSatellite && (
        <Card className="p-4">
          <h2 className="mb-1 font-medium">{t('Apply a received snapshot')}</h2>
          <p className="mb-3 text-sm text-muted-foreground">
            {t('When the coordinator sends a new version of the project (.zip archive), apply it here: your copy updates and your local votes, extractions and annotations are kept (the most recent version wins).')}
          </p>
          <input
            ref={fileInputRef} type="file" accept=".zip" className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) startImport(file)
              e.target.value = ''
            }}
          />
          <div className="flex items-center gap-3">
            <Button
              onClick={() => fileInputRef.current?.click()}
              disabled={!!importWatcher.state}
            >
              <Download className="size-4" /> {t('Choose the received archive (.zip)…')}
            </Button>
            {importWatcher.state && (
              <span className="text-sm text-muted-foreground">{importWatcher.state}</span>
            )}
          </div>
          {importWatcher.error && (
            <p className="mt-2 text-sm text-destructive">{importWatcher.error}</p>
          )}
          {report && <ImportReportView report={report} />}
        </Card>
      )}

      {!isSatellite && isAdmin && (
        <Card className="p-4">
          <h2 className="mb-1 font-medium">{t('Restore from a snapshot (backup)')}</h2>
          <p className="mb-3 text-sm text-muted-foreground">
            {t("Replace the WHOLE project with the content of a snapshot archive previously exported from it: everything done since that export (votes, resolutions, extractions, imports…) is lost. The project stays the reference (coordinator) instance. This is for recovering from a mistake or a crash — to receive a co-reviewer's work, use the contributions import above instead.")}
          </p>
          <input
            ref={restoreFileRef} type="file" accept=".zip" className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file && confirm(t('Replace the entire project with this archive? Everything done since that snapshot was exported will be lost.')))
                startImport(file, true)
              e.target.value = ''
            }}
          />
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              className="border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive"
              onClick={() => restoreFileRef.current?.click()}
              disabled={!!importWatcher.state}
            >
              <Download className="size-4" /> {t('Restore an archive (.zip)…')}
            </Button>
            {importWatcher.state && (
              <span className="text-sm text-muted-foreground">{importWatcher.state}</span>
            )}
          </div>
          {importWatcher.error && (
            <p className="mt-2 text-sm text-destructive">{importWatcher.error}</p>
          )}
          {report && <ImportReportView report={report} />}
        </Card>
      )}

      <FolderCard pid={pid} info={info} isAdmin={isAdmin} />

      <SharedKeysCard pid={pid} info={info} isAdmin={isAdmin} />

      {isSatellite && isAdmin && (
        <details className="rounded-xl border border-border bg-card p-4">
          <summary className="cursor-pointer text-sm font-medium">
            {t('Advanced — export a full copy of this project (snapshot)')}
          </summary>
          <p className="mb-3 mt-2 text-sm text-muted-foreground">
            {t('Do NOT send it to the coordinator: their instance would refuse it (the project\'s reference state cannot be overwritten) — to send them your work, use "Export my contributions" above. This full copy serves to: back up your instance, move to another machine, or create another co-reviewer\'s satellite copy without going through the coordinator.')}
          </p>
          {snapshotExportControls}
        </details>
      )}

      {events.length > 0 && (
        <Card className="p-4">
          <h2 className="mb-2 font-medium">{t('Exchange log')}</h2>
          <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="py-1 pr-3">{t('Date')}</th>
                <th className="py-1 pr-3">{t('Exchange')}</th>
                <th className="py-1 pr-3">{t('Author')}</th>
                <th className="py-1 pr-3">{t('Summary')}</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev) => (
                <tr key={ev.id} className="border-b border-border/50 align-top">
                  <td className="whitespace-nowrap py-1.5 pr-3 tabular-nums text-muted-foreground">
                    {new Date(ev.created_at).toLocaleString()}
                  </td>
                  <td className="whitespace-nowrap py-1.5 pr-3">
                    {ev.direction === 'export' ? '↑ export' : '↓ import'}{' '}
                    {ev.kind === 'snapshot' ? t('snapshot') : t('contributions')}
                    {ev.kind === 'snapshot' ? ` v${ev.seq}` : ` #${ev.seq}`}
                  </td>
                  <td className="py-1.5 pr-3">{ev.author_email}</td>
                  <td className="py-1.5 pr-3 text-muted-foreground">
                    {summarizeEvent(ev)}
                    {ev.warnings.length > 0 && (
                      <span className="ml-1 text-warning" title={ev.warnings.join('\n')}>
                        ⚠ {ev.warnings.length}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </Card>
      )}
    </div>
  )
}

/** Sync phase 4: shared-folder transport. Link the project to a locally
 * synced Nextcloud/Drive/OneDrive folder; the background loop (5 min) then
 * exchanges packages automatically — this card configures it, shows its
 * state, and offers manual scan / publish / apply actions. */
function FolderCard({ pid, info, isAdmin }: {
  pid: number; info: SyncInfo | undefined; isAdmin: boolean
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [path, setPath] = useState<string | null>(null)
  const [autoPublish, setAutoPublish] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [scan, setScan] = useState<FolderScanSummary | null>(null)
  const jobRef = useRef<number | null>(null)

  const { data: state } = useQuery<FolderState>({
    queryKey: ['sync-folder', pid],
    queryFn: () => api.get(`/api/projects/${pid}/sync/folder`),
    refetchInterval: 60_000,
  })
  const isSatellite = info?.sync_role === 'satellite'
  const shownPath = path ?? state?.path ?? ''
  const shownAuto = autoPublish ?? state?.auto_publish ?? false

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['sync-folder', pid] })
    queryClient.invalidateQueries({ queryKey: ['sync-events', pid] })
    queryClient.invalidateQueries({ queryKey: ['sync', pid] })
    queryClient.invalidateQueries({ queryKey: ['project-progress'] })
  }
  const watcher = useJobWatcher(async () => {
    refresh()
    setBusy(false)
  })
  const run = async (fn: () => Promise<unknown>) => {
    setError('')
    setBusy(true)
    try {
      await fn()
      refresh()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="p-4">
      <h2 className="mb-1 flex items-center gap-2 font-medium">
        <FolderOpen className="size-4" /> {t('Shared folder (automatic sync)')}
      </h2>
      <p className="mb-3 text-sm text-muted-foreground">
        {t('Point every instance of the project to the SAME synced folder (Nextcloud, OneDrive, Google Drive…): contribution packages then exchange themselves (every 5 min, or via "Sync now"). Your machine\'s sync client moves the files.')}
      </p>

      {isAdmin && (
        <form
          className="mb-3 flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            run(() => api.post(`/api/projects/${pid}/sync/folder`,
              { path: shownPath, auto_publish: shownAuto }))
          }}
        >
          <Input
            value={shownPath} onChange={(e) => setPath(e.target.value)}
            placeholder={t('C:\\Users\\me\\Nextcloud\\SLRproject')}
            className="min-w-72 flex-1"
          />
          {!isSatellite && (
            <label className="flex items-center gap-1.5 text-sm">
              <input
                type="checkbox" checked={shownAuto}
                onChange={(e) => setAutoPublish(e.target.checked)}
              />
              {t('auto-publish the snapshot')}
            </label>
          )}
          <Button type="submit" variant="secondary" disabled={busy}>
            {t('Save')}
          </Button>
        </form>
      )}

      {state?.configured && (
        <div className="mb-3 text-sm">
          {state.ok === false ? (
            <p className="text-destructive">{state.error}</p>
          ) : (
            <p className="text-muted-foreground">
              {t('Folder linked · snapshot v{{version}} in the folder', { version: state.latest_snapshot_version ?? 0 })}
              {(state.pending_contributions?.length ?? 0) > 0 && (
                <span className="ml-2 text-warning">
                  {state.pending_contributions!
                    .map((p) => t('{{count}} package(s) from {{author}}', { count: p.n_new, author: p.author }))
                    .join(', ')} {t('pending')}
                </span>
              )}
            </p>
          )}
          {state.update_available && (
            <p className="mt-1 font-medium text-warning">
              {t('A newer snapshot is available in the folder.')}
              {isAdmin && (
                <Button
                  size="sm" className="ml-2" disabled={busy}
                  onClick={() => run(async () => {
                    const { job_id } = await api.post<{ job_id: number }>(
                      `/api/projects/${pid}/sync/folder/apply-snapshot`)
                    jobRef.current = job_id
                    setBusy(true)
                    watcher.watch(job_id)
                  })}
                >
                  {t('Apply the update')}
                </Button>
              )}
            </p>
          )}
          {state.snapshot_behind && !state.auto_publish && (
            <p className="mt-1 text-warning">
              {t("The folder's snapshot is behind this instance — remember to publish.")}
            </p>
          )}
        </div>
      )}

      {state?.configured && state.ok !== false && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary" disabled={busy}
            onClick={() => run(async () => {
              const summary = await api.post<FolderScanSummary>(
                `/api/projects/${pid}/sync/folder/scan`)
              setScan(summary)
            })}
          >
            <RefreshCw className="size-4" /> {t('Sync now')}
          </Button>
          {isAdmin && !isSatellite && (
            <Button
              variant="outline" disabled={busy}
              onClick={() => run(async () => {
                const { job_id } = await api.post<{ job_id: number }>(
                  `/api/projects/${pid}/sync/folder/publish`,
                  { include_pdfs: true })
                jobRef.current = job_id
                setBusy(true)
                watcher.watch(job_id)
              })}
            >
              <Upload className="size-4" /> {t('Publish the snapshot into the folder')}
            </Button>
          )}
          {watcher.state && (
            <span className="text-sm text-muted-foreground">{watcher.state}</span>
          )}
        </div>
      )}

      {scan && (
        <div className="mt-3 rounded-md border border-border bg-muted/40 p-3 text-sm">
          <p className="text-muted-foreground">
            {scan.imported.length > 0
              && t('Imported: {{list}}', { list: scan.imported.map((i) =>
                `${i.author} #${i.seq}`).join(', ') })
              + (scan.imported.some((i) => i.conflicts_created > 0)
                ? ` ${t('({{count}} conflict(s))', { count: scan.imported.reduce((n, i) => n + i.conflicts_created, 0) })}`
                : '')}
            {scan.imported.length === 0 && scan.pushed.length === 0
              && !scan.published && t('Nothing new on either side.')}
          </p>
          {scan.pushed.length > 0 && (
            <p className="text-muted-foreground">
              {t('Pushed: {{list}}', { list: scan.pushed.map((p) => `${p.author} #${p.seq}`).join(', ') })}
            </p>
          )}
          {scan.published && (
            <p className="text-muted-foreground">{t('Snapshot v{{version}} published.', { version: scan.published })}</p>
          )}
          {scan.warnings.map((w) => (
            <p key={w} className="text-warning">{w}</p>
          ))}
        </div>
      )}
      {(error || watcher.error) && (
        <p className="mt-2 text-sm text-destructive">{error || watcher.error}</p>
      )}
    </Card>
  )
}

/** Sync phase 3: the project passphrase + the project-scoped API keys and
 * their sharing toggles. Only shared PROJECT keys travel (encrypted with the
 * passphrase); instance-global keys and EZProxy logins never do. */
function SharedKeysCard({ pid, info, isAdmin }: {
  pid: number; info: SyncInfo | undefined; isAdmin: boolean
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [passphrase, setPassphrase] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [dbProvider, setDbProvider] = useState<string>('scopus')
  // the keyed providers come from the server (chantier 6b added four)
  const { data: keyProviders = [] } = useQuery<{ provider: string; label: string }[]>({
    queryKey: ['db-key-providers', pid],
    queryFn: () => api.get(`/api/database-credentials?project_id=${pid}`),
  })
  const [dbKey, setDbKey] = useState('')

  const { data: keys = [] } = useQuery<SharedKey[]>({
    queryKey: ['shared-keys', pid],
    queryFn: () => api.get(`/api/projects/${pid}/sync/shared-keys`),
  })
  const { data: globalProviders = [] } = useQuery<string[]>({
    queryKey: ['global-llm-providers', pid],
    queryFn: () => api.get(`/api/projects/${pid}/sync/global-llm-providers`),
  })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['shared-keys', pid] })
    queryClient.invalidateQueries({ queryKey: ['global-llm-providers', pid] })
    queryClient.invalidateQueries({ queryKey: ['sync', pid] })
  }
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setError('')
    setMessage('')
    try {
      await fn()
      setMessage(ok)
      refresh()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    }
  }

  return (
    <Card className="p-4">
      <h2 className="mb-1 flex items-center gap-2 font-medium">
        <KeyRound className="size-4" /> {t('Shared API keys')}
      </h2>
      <p className="mb-3 text-sm text-muted-foreground">
        {t('Each member chooses, key by key, to keep their API keys to themselves or share them with the project: shared keys travel ENCRYPTED in the snapshots and contribution packages, and become usable by the jobs (AI, searches, counts) of the other instances. Personal EZProxy/CAS institutional logins are never shared.')}
      </p>

      <div className="mb-3 rounded-md border border-border bg-muted/30 p-3">
        <p className="text-sm font-medium">
          {t('Project passphrase:')}{' '}
          {info?.has_passphrase
            ? <span className="text-success">{t('set ✓')}</span>
            : <span className="text-warning">{t('not set — shared keys will not travel')}</span>}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {t('The same phrase must be entered on every instance of the project (share it by voice or a separate channel, never with the file).')}
        </p>
        {isAdmin && (
          <form
            className="mt-2 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              run(() => api.post(`/api/projects/${pid}/sync/passphrase`,
                { passphrase }), passphrase
                ? t('Passphrase saved')
                : t('Passphrase cleared'))
              setPassphrase('')
            }}
          >
            <Input
              type="password" value={passphrase} className="max-w-xs"
              placeholder={t('New phrase (empty to clear)')}
              onChange={(e) => setPassphrase(e.target.value)}
            />
            <Button type="submit" variant="secondary">{t('Save')}</Button>
          </form>
        )}
      </div>

      {keys.length > 0 && (
        <ul className="mb-3 space-y-1.5">
          {keys.map((k) => (
            <li key={`${k.kind}-${k.id}`}
                className="flex items-center gap-2 text-sm">
              <Badge variant="outline" className="w-16 justify-center">
                {k.kind === 'llm' ? t('AI') : t('database')}
              </Badge>
              <span className="font-medium">{k.provider}</span>
              {k.default_model && (
                <span className="text-xs text-muted-foreground">{k.default_model}</span>
              )}
              <span className="text-xs text-muted-foreground">
                {k.is_mine ? t('mine') : k.owner_email
                  ? t('shared by {{email}}', { email: k.owner_email }) : ''}
              </span>
              <label className="ml-auto flex items-center gap-1.5 text-xs">
                <input
                  type="checkbox" checked={k.shared}
                  disabled={!k.is_mine && !isAdmin}
                  onChange={(e) => run(
                    () => api.post(
                      `/api/projects/${pid}/sync/shared-keys/${k.kind}/${k.id}/share`,
                      { shared: e.target.checked }),
                    e.target.checked
                      ? t('Key shared with the project')
                      : t('Sharing revoked — the key will disappear on the other instances at the next exchange'))}
                />
                {t('share')}
              </label>
              {(k.is_mine || isAdmin) && (
                <Button
                  variant="ghost" size="icon"
                  className="size-6 text-muted-foreground hover:text-destructive"
                  title={t('Remove this key from the project')}
                  onClick={() => run(
                    () => api.del(
                      `/api/projects/${pid}/sync/shared-keys/${k.kind}/${k.id}`),
                    t('Key removed'))}
                >
                  <Trash2 className="size-3.5" />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}

      {globalProviders.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">
            {t('Your global AI keys (not attached to the project, hence absent from the snapshots):')}
          </span>
          {globalProviders.map((provider) => (
            <Button
              key={provider} variant="outline" size="sm"
              title={t('Copies the global key as a shared project key — it will travel encrypted in the snapshots and packages')}
              onClick={() => run(
                () => api.post(
                  `/api/projects/${pid}/sync/shared-keys/adopt-global`,
                  { provider }),
                t('{{provider}} key attached to the project and shared', { provider }))}
            >
              <KeyRound className="size-3.5" /> {t('Share my {{provider}} key', { provider })}
            </Button>
          ))}
        </div>
      )}

      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          run(() => api.put(`/api/projects/${pid}/sync/database-keys`,
            { provider: dbProvider, api_key: dbKey, shared: true }),
            t('Key added to the project (shared)'))
          setDbKey('')
        }}
      >
        <select
          value={dbProvider}
          onChange={(e) => setDbProvider(e.target.value)}
          aria-label={t('Database provider')}
          className="h-9 rounded-md border border-border bg-background px-2 text-sm"
        >
          {keyProviders.map((k) => (
            <option key={k.provider} value={k.provider}>{k.label}</option>
          ))}
        </select>
        <Input
          value={dbKey} onChange={(e) => setDbKey(e.target.value)}
          placeholder={t('My institutional API key…')} className="max-w-xs"
          required minLength={6}
        />
        <Button type="submit" variant="secondary">{t('Add to the project')}</Button>
        <span className="text-xs text-muted-foreground">
          {t('(AI keys: project Settings page, AI keys tab)')}
        </span>
      </form>

      {message && <p className="mt-2 text-sm text-success">{message}</p>}
      {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
    </Card>
  )
}

function summarizeEvent(ev: SyncEventInfo): string {
  const c = ev.counts as Record<string, unknown>
  const parts: string[] = []
  if (ev.kind === 'snapshot') {
    if (c.records !== undefined) parts.push(i18n.t('{{count}} rec.', { count: c.records }))
    if (c.votes !== undefined) parts.push(`${c.votes} votes`)
    if (c.size_kb !== undefined) {
      const kb = Number(c.size_kb)
      parts.push(kb >= 1024 ? `${Math.round(kb / 1024)} ${i18n.t('MB')}` : `${kb} ${i18n.t('kB')}`)
    }
  } else {
    for (const key of ['votes', 'jbi', 'values', 'annotations', 'skips']) {
      const v = c[key]
      if (typeof v === 'number' && v > 0) parts.push(`${v} ${key}`)
      else if (v && typeof v === 'object') {
        const cc = v as { new?: number; updated?: number }
        const n = (cc.new ?? 0) + (cc.updated ?? 0)
        if (n > 0) parts.push(`${n} ${key}`)
      }
    }
    const conflicts = c.conflicts_created
    if (typeof conflicts === 'number' && conflicts > 0) {
      parts.push(i18n.t('{{count}} conflict(s) created', { count: conflicts }))
    }
  }
  return parts.join(' · ') || '—'
}

function ContribReportView({ report }: { report: ContribImportReport }) {
  const { t } = useTranslation()
  const merged = report.votes.new + report.votes.updated
  return (
    <div className="mt-3 rounded-md border border-border bg-muted/40 p-3 text-sm">
      <p className="font-medium">
        {t('Contributions from {{author}} (package #{{seq}}) imported.', { author: report.author, seq: report.seq })}
      </p>
      <p className="mt-1 text-muted-foreground">
        {t('Votes: {{new}} new, {{updated}} updated, {{unchanged}} unchanged', { new: report.votes.new, updated: report.votes.updated, unchanged: report.votes.unchanged })}
        {report.ai_votes.added > 0 && ` · ${t('{{count}} AI votes added', { count: report.ai_votes.added })}`}
        {report.ai_votes.skipped > 0
          && ` · ${t('{{count}} AI votes skipped (already present)', { count: report.ai_votes.skipped })}`}
      </p>
      {(report.jbi.new + report.jbi.updated + report.values.new
        + report.values.updated + report.annotations + report.skips) > 0 && (
        <p className="mt-1 text-muted-foreground">
          {t('JBI: {{jbi}} · extractions: {{values}} · annotations: {{annotations}} · skips: {{skips}}',
             { jbi: report.jbi.new + report.jbi.updated,
               values: report.values.new + report.values.updated,
               annotations: report.annotations, skips: report.skips })}
        </p>
      )}
      {report.conflicts_created > 0 && (
        <p className="mt-1 font-medium text-warning">
          {t('{{count}} new conflict(s) detected — see the screening Conflicts tab.', { count: report.conflicts_created })}
        </p>
      )}
      {report.tags
        && (report.tags.attached + report.tags.removed) > 0 && (
        <p className="mt-1 text-muted-foreground">
          {t('Tags: {{attached}} attached', { attached: report.tags.attached })}
          {report.tags.removed > 0 && `, ${t('{{count}} removed', { count: report.tags.removed })}`}
        </p>
      )}
      {report.tickets
        && (report.tickets.new + report.tickets.updated
            + (report.ticket_comments ?? 0)) > 0 && (
        <p className="mt-1 text-muted-foreground">
          {t('Tickets: {{new}} new, {{updated}} updated', { new: report.tickets.new, updated: report.tickets.updated })}
          {(report.ticket_comments ?? 0) > 0
            && ` · ${t('{{count}} comment(s)', { count: report.ticket_comments })}`}{' '}
          {t('— see the Tickets page.')}
        </p>
      )}
      {report.credentials
        && (report.credentials.applied + report.credentials.removed) > 0 && (
        <p className="mt-1 text-muted-foreground">
          {t('Shared API keys: {{applied}} applied', { applied: report.credentials.applied })}
          {report.credentials.removed > 0
            && `, ${t('{{count}} removed', { count: report.credentials.removed })}`}
        </p>
      )}
      {merged === 0 && report.conflicts_created === 0 && (
        <p className="mt-1 text-muted-foreground">
          {t('Nothing new (package already imported?).')}
        </p>
      )}
      {report.quarantined_count > 0 && (
        <p className="mt-1 text-warning">
          {t('{{count}} row(s) quarantined (record absent from this project).', { count: report.quarantined_count })}
        </p>
      )}
      {report.warnings.map((w) => (
        <p key={w} className="mt-1 text-warning">{w}</p>
      ))}
    </div>
  )
}

export function ImportReportView({ report }: { report: SyncImportReport }) {
  const { t } = useTranslation()
  const kept = Object.entries(report.kept_local ?? {}).filter(([, n]) => n > 0)
  return (
    <div className="mt-3 rounded-md border border-border bg-muted/40 p-3 text-sm">
      <p className="font-medium">
        {report.mode === 'create'
          ? t('Project “{{name}}” imported (satellite copy, v{{version}}).', { name: report.project_name, version: report.snapshot_version })
          : t('Project “{{name}}” updated (v{{version}}).', { name: report.project_name, version: report.snapshot_version })}
      </p>
      <p className="mt-1 text-muted-foreground">
        {t('{{records}} records · {{votes}} votes · {{rounds}} screening round(s)',
           { records: report.counts.records ?? 0, votes: report.n_votes,
             rounds: report.counts.screening_configs ?? 0 })}
      </p>
      {kept.length > 0 && (
        <p className="mt-1 text-muted-foreground">
          {t('Local contributions kept: {{list}}', { list: kept.map(([k, n]) => `${k} ${n}`).join(', ') })}
        </p>
      )}
      {report.shadow_users.length > 0 && (
        <p className="mt-1 text-muted-foreground">
          {t('Accounts created for the remote members: {{list}} (they cannot log in here; registering with that email claims the account)', { list: report.shadow_users.join(', ') })}
        </p>
      )}
      {report.pdfs_missing > 0 && (
        <p className="mt-1 text-warning">
          {t('{{count}} PDFs absent from the archive — status reset to "pending", retrievable again from FT retrieval on the coordinator side.', { count: report.pdfs_missing })}
        </p>
      )}
      {report.quarantined_count > 0 && (
        <p className="mt-1 text-warning">
          {t("{{count}} local contribution(s) quarantined (their record no longer exists in the snapshot).", { count: report.quarantined_count })}
        </p>
      )}
      {report.folder_linked && (
        <p className="mt-1 text-success">
          {t('Shared folder linked ({{path}}) — synchronisation is now automatic.', { path: report.folder_linked })}
        </p>
      )}
      {report.warnings.map((w) => (
        <p key={w} className="mt-1 text-warning">{w}</p>
      ))}
    </div>
  )
}
