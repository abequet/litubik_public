// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  api, ApiError, type JobInfo, type Project, type ZoteroCollection, type ZoteroStatus,
} from '../api'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Segmented } from '@/components/ui/segmented'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import LiveStatus from './LiveStatus'

type Scope = 'all' | 'included' | 'excluded' | 'undecided'
const NEW_COLLECTION = '__new__'

/** Export the project's references at any stage of the review: scope
 * (all / included / excluded / undecided so far, from the current screening
 * state — full-text decisions override title/abstract ones) and destination:
 * a file (RIS, BibTeX, CSV — a plain authenticated GET) or the member's own
 * Zotero library (background job; items sent before are updated in place). */
export default function ExportReferencesDialog({ projectId, open, onOpenChange }: {
  projectId: number
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation()
  const [scope, setScope] = useState<Scope>('all')
  const [dest, setDest] = useState<'file' | 'zotero'>('file')
  const [fmt, setFmt] = useState<'ris' | 'bibtex' | 'csv'>('ris')
  const { data: summary } = useQuery<{
    all: number; included: number; excluded: number; undecided: number
  }>({
    queryKey: ['export-summary', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/export/references/summary`),
    enabled: open,
  })

  const count = summary?.[scope]
  const url = `/api/projects/${projectId}/export/references?scope=${scope}&fmt=${fmt}`

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('Export references')}</DialogTitle>
          <DialogDescription>
            {t('Download the project references at their current screening state (full-text decisions override title/abstract ones). Works at any stage of the review.')}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">{t('References')}</p>
            <Segmented
              value={scope}
              onChange={setScope}
              options={[
                { value: 'all', label: t('All references ({{count}})', { count: summary?.all ?? '…' }) },
                { value: 'included', label: t('Included ({{count}})', { count: summary?.included ?? '…' }) },
                { value: 'excluded', label: t('Excluded ({{count}})', { count: summary?.excluded ?? '…' }) },
                { value: 'undecided', label: t('Undecided ({{count}})', { count: summary?.undecided ?? '…' }) },
              ]}
            />
          </div>
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">{t('Destination')}</p>
            <Segmented
              value={dest}
              onChange={setDest}
              options={[
                { value: 'file', label: t('File') },
                { value: 'zotero', label: 'Zotero' },
              ]}
            />
          </div>
          {dest === 'file' ? (
            <>
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">{t('Format')}</p>
                <Segmented
                  value={fmt}
                  onChange={setFmt}
                  options={[
                    { value: 'ris', label: 'RIS' },
                    { value: 'bibtex', label: 'BibTeX' },
                    { value: 'csv', label: 'CSV' },
                  ]}
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  {fmt === 'csv'
                    ? t('CSV includes a screening_status column (include / exclude / undecided).')
                    : t('RIS and BibTeX re-import cleanly into Zotero, EndNote or another LitUbik project.')}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {count === 0 ? (
                  <>
                    <Button disabled>{t('Download')}</Button>
                    <span className="text-xs text-muted-foreground">
                      {t('Nothing in this scope yet.')}
                    </span>
                  </>
                ) : (
                  <Button asChild>
                    <a href={url} download onClick={() => onOpenChange(false)}>
                      {t('Download')}
                    </a>
                  </Button>
                )}
              </div>
            </>
          ) : (
            <ZoteroDestination projectId={projectId} scope={scope} count={count}
                               enabled={open} />
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function ZoteroDestination({ projectId, scope, count, enabled }: {
  projectId: number
  scope: Scope
  count: number | undefined
  enabled: boolean
}) {
  const { t } = useTranslation()
  const { data: status } = useQuery<ZoteroStatus>({
    queryKey: ['zotero-status'], queryFn: () => api.get('/api/integrations/zotero'),
    enabled,
  })
  const configured = !!status?.configured
  const { data: collections = [], isError: collectionsFailed } = useQuery<ZoteroCollection[]>({
    queryKey: ['zotero-collections'],
    queryFn: () => api.get('/api/integrations/zotero/collections'),
    enabled: enabled && configured,
    staleTime: 60_000,
  })
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'], queryFn: () => api.get('/api/projects'),
  })
  const projectName = projects.find((p) => p.id === projectId)?.name ?? ''
  const [collection, setCollection] = useState<string>(NEW_COLLECTION)
  const [result, setResult] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const send = useMutation({
    mutationFn: () => api.post<{ job_id: number }>(`/api/projects/${projectId}/zotero/export`, {
      scope, collection_key: collection === NEW_COLLECTION ? null : collection,
    }),
    onSuccess: ({ job_id }) => {
      setResult(''); setError(''); setBusy(true)
      watchResult(job_id)
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Export failed')),
  })

  // follow the job, then read its result once for the summary line
  const watchResult = (jobId: number) => {
    const es = new EventSource(`/api/jobs/${jobId}/stream`, { withCredentials: true })
    es.onmessage = (event) => {
      const job = JSON.parse(event.data)
      if (job.status === 'running' || job.status === 'queued') {
        setResult(job.message || t('Working…'))
        return
      }
      es.close()
      setBusy(false)
      if (job.status === 'done') {
        // the stream carries progress only — the result lives on the job row
        api.get<JobInfo>(`/api/jobs/${jobId}`).then((done) => {
          const r = done.result ?? {}
          setResult(t('{{created}} created, {{updated}} updated, {{failed}} failed in collection “{{collection}}”.', {
            created: r.created ?? 0, updated: r.updated ?? 0, failed: r.failed ?? 0,
            collection: r.collection_name ?? '' }))
        }).catch(() => setResult(t('Sent to Zotero.')))
      } else {
        setResult('')
        setError(String(job.error ?? '').split('\n')[0] || t('Export failed'))
      }
    }
    es.onerror = () => { es.close(); setBusy(false) }
  }

  if (status && !configured) {
    return (
      <p className="text-sm text-muted-foreground">
        {t('No Zotero library connected yet.')}{' '}
        <Link to="/settings/integrations" className="text-primary hover:underline">
          {t('Connect it in My integrations.')}
        </Link>
      </p>
    )
  }
  if (status && !status.write) {
    return (
      <p className="text-sm text-muted-foreground">
        {t('Your Zotero key is read-only: create one with “Allow write access” in')}{' '}
        <Link to="/settings/integrations" className="text-primary hover:underline">
          {t('My integrations')}
        </Link>.
      </p>
    )
  }
  const newName = t('New collection “LitUbik – {{project}}”', { project: projectName })
  return (
    <div className="space-y-3">
      <div>
        <p className="mb-1 text-xs font-medium text-muted-foreground">
          {t('Collection in {{library}}', {
            library: status?.library_type === 'user' ? t('My library')
                                                     : (status?.library_name ?? 'Zotero') })}
        </p>
        <Select value={collection} onValueChange={setCollection}>
          <SelectTrigger className="h-8 w-full text-sm" aria-label={t('Zotero collection')}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NEW_COLLECTION}>{newName}</SelectItem>
            {collections.map((c) => (
              <SelectItem key={c.key} value={c.key}>
                {' '.repeat(c.depth * 3)}{c.name} ({c.n_items})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {collectionsFailed && (
          <p className="mt-1 text-xs text-destructive">{t('Could not list your Zotero collections.')}</p>
        )}
        <p className="mt-1 text-xs text-muted-foreground">
          {t('Each reference becomes a Zotero item tagged litubik:included / excluded / undecided plus its LitUbik tags; a reference sent before is updated in place, not duplicated. PDFs are not sent.')}
        </p>
      </div>
      <div className="flex items-center gap-2">
        <Button onClick={() => send.mutate()}
                disabled={count === 0 || send.isPending || busy}>
          {t('Send to Zotero')}
        </Button>
        {count === 0 && (
          <span className="text-xs text-muted-foreground">{t('Nothing in this scope yet.')}</span>
        )}
      </div>
      <LiveStatus tone="error" className="text-xs">{error}</LiveStatus>
      <LiveStatus tone="info" className="text-xs">{result}</LiveStatus>
    </div>
  )
}
