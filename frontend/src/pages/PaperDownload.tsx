// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Download } from 'lucide-react'
import { api, ApiError, type JobInfo, type User } from '../api'
import { useJobWatcher } from '../useJob'
import { institutionsForRetrieve } from '@/components/InstitutionAccess'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

interface DownloadItem {
  doi: string
  title: string
  status: 'retrieved' | 'not_found'
  via: string
  filename: string
  oa_url: string
  error: string
}

interface Quota {
  limit: number | null
  used: number
  remaining: number | null
  resets_at: string | null
}

const DOI_RE = /10\.\d{4,9}\/[^\s,;"'<>]+/gi

/** Standalone module (workspace, outside any project): paste DOIs, get the
 * PDF — or a zip when there are several — through the browser. Same source
 * cascade and file naming as a project's batch retrieval; nothing is stored
 * in a project. */
export default function PaperDownloadPage() {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  const [finished, setFinished] = useState<JobInfo | null>(null)
  const jobIdRef = useRef<number | null>(null)
  // only a run started from this page visit downloads by itself — coming back
  // to an older finished run must not push a file at the user
  const autoDownloadRef = useRef(false)

  const { data: me } = useQuery<User>({
    queryKey: ['me'], queryFn: () => api.get('/api/auth/me'),
  })
  const myInstitutions = me ? institutionsForRetrieve(me.id) : []
  // opt-in module: the superadmin ticks who gets it (Administration → Users)
  const allowed = !!me && (me.is_admin || me.can_download_papers)
  // everyone but the superadmin: 5 papers per sliding hour (limit null = none)
  const { data: quota, refetch: refetchQuota } = useQuery<Quota>({
    queryKey: ['paper-download-quota'],
    queryFn: () => api.get('/api/paper-download/quota'),
    enabled: allowed,
    refetchOnMount: 'always',
  })

  const fileUrl = (jobId: number) => `/api/paper-download/${jobId}/file`

  const job = useJobWatcher(async () => {
    const id = jobIdRef.current
    if (id === null) return
    const info = await api.get<JobInfo>(`/api/jobs/${id}`)
    setFinished(info)
    refetchQuota()
    if (autoDownloadRef.current && info.status === 'done'
        && Number(info.result.retrieved) > 0) {
      window.location.assign(fileUrl(id))
    }
    autoDownloadRef.current = false
  })

  // The run lives on the server: re-attach to it (or show its outcome) when
  // coming back to the page.
  const { data: recent = [] } = useQuery<JobInfo[]>({
    queryKey: ['paper-download-jobs'],
    queryFn: () => api.get('/api/jobs?limit=50'),
    enabled: allowed,
    refetchOnMount: 'always',
  })
  const last = recent.find((j) => j.type === 'paper_download'
    && j.project_id === null)
  useEffect(() => {
    if (!last || job.state || jobIdRef.current !== null) return
    jobIdRef.current = last.id
    if (last.status === 'queued' || last.status === 'running') job.watch(last.id)
    else if (last.status === 'done') setFinished(last)
  }, [last?.id])  // eslint-disable-line

  const count = new Set((text.match(DOI_RE) ?? []).map((d) => d.toLowerCase())).size

  const start = async () => {
    setError('')
    setFinished(null)
    try {
      const { job_id } = await api.post<{ job_id: number }>(
        '/api/paper-download',
        { text, institutions: me ? institutionsForRetrieve(me.id) : [] })
      jobIdRef.current = job_id
      autoDownloadRef.current = true
      job.watch(job_id)
      refetchQuota()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('Could not start the download'))
    }
  }

  const items = (finished?.result.items ?? []) as DownloadItem[]
  const retrieved = items.filter((i) => i.status === 'retrieved').length
  const remaining = quota?.remaining ?? null
  const overQuota = remaining !== null && count > remaining

  if (me && !allowed) {
    return (
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          {t('Download papers')}
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          {t('This module is not enabled for your account. An application admin can open it for you from Administration → Users.')}
        </p>
      </div>
    )
  }

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('Download papers')}
      </h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {t('Paste DOIs and get the PDFs straight from your browser — the PDF itself for a single paper, a zip for several. Files are named Author_Year_first_title_words.pdf, like a project’s batch retrieval. Nothing is added to any project.')}
      </p>

      <Card className="mb-6 max-w-3xl p-4">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={8}
          spellCheck={false}
          placeholder={t('One DOI per line (or separated by commas or spaces) — doi.org links work too')}
          className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button onClick={start} disabled={!!job.state || count === 0 || overQuota}>
            <Download className="size-4" />
            {job.state || t('Download {{count}} paper(s)', { count })}
          </Button>
          {job.state && jobIdRef.current !== null && (
            <Button variant="outline"
                    onClick={() => api.post(`/api/jobs/${jobIdRef.current}/cancel`)}>
              {t('Cancel')}
            </Button>
          )}
          <Link to="/settings/institutions" className="text-xs text-primary hover:underline">
            {myInstitutions.length > 0
              ? t('My institutional access ({{count}} ready) — also tried for paywalled papers', { count: myInstitutions.length })
              : t('Add my institutional access (EZproxy/OpenAthens) to fetch paywalled PDFs')}
          </Link>
        </div>
        {quota && quota.limit !== null && (
          <p className={`mt-2 text-xs ${overQuota || remaining === 0 ? 'text-warning' : 'text-muted-foreground'}`}>
            {t('Limit: {{limit}} papers per hour — {{remaining}} left.',
              { limit: quota.limit, remaining })}
            {quota.resets_at && remaining !== null && remaining < quota.limit && ' '
              + t('Next slot frees up at {{time}}.', {
                time: new Date(quota.resets_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
              })}
            {overQuota && ' ' + t('Remove some DOIs to fit the limit.')}
          </p>
        )}
        {(error || job.error) && (
          <p className="mt-2 text-sm text-destructive">{error || job.error}</p>
        )}
        {job.state && (
          <p className="mt-2 text-xs text-muted-foreground">
            {t('Downloads run on the server (4 papers at a time, each trying its sources in parallel) — you can navigate away and come back for the files.')}
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
      </Card>

      {finished && finished.status === 'done' && (
        <Card className="max-w-3xl overflow-hidden">
          <div className="flex flex-wrap items-center gap-3 border-b border-border p-3">
            <span className="text-sm font-medium">
              {t('{{retrieved}} of {{total}} PDF(s) retrieved',
                { retrieved, total: items.length })}
            </span>
            <span className="flex-1" />
            {retrieved > 0 && (
              <Button asChild variant="outline" size="sm">
                <a href={fileUrl(finished.id)}>
                  <Download className="size-4" />
                  {retrieved === 1 ? t('Download the PDF') : t('Download the zip')}
                </a>
              </Button>
            )}
          </div>
          <ul className="divide-y divide-border text-sm">
            {items.map((item) => (
              <li key={item.doi} className="flex items-start gap-3 p-3">
                <Badge variant={item.status === 'retrieved' ? 'success' : 'warning'}>
                  {item.status === 'retrieved' ? t('PDF retrieved') : t('No PDF')}
                </Badge>
                <div className="min-w-0 flex-1">
                  <p className="truncate">{item.title || item.doi}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {item.doi}
                    {item.status === 'retrieved'
                      && ` · ${item.filename} · ${t('via {{source}}', { source: item.via || '?' })}`}
                  </p>
                  {item.status === 'not_found' && (
                    <p className="text-xs text-warning">
                      {item.error}
                      {item.oa_url && (
                        <>
                          {' · '}
                          <a href={item.oa_url} target="_blank" rel="noreferrer"
                             className="text-primary hover:underline">
                            {t('Open the publisher page')}
                          </a>
                        </>
                      )}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ul>
          <p className="border-t border-border p-3 text-xs text-muted-foreground">
            {t('The files stay available for 24 hours.')}
          </p>
        </Card>
      )}
    </div>
  )
}
