// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type User } from '../api'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

interface AdminUser {
  id: number
  email: string
  display_name: string
  is_admin: boolean
  can_download_papers: boolean
  created_at: string
}

interface DownloadUser {
  id: number | null  // null: the account has since been deleted
  email: string
  display_name: string
  is_admin: boolean
  runs: number
  requested: number
  retrieved: number
  last_at: string | null
}

interface DownloadRun {
  id: number
  status: string
  created_at: string
  finished_at: string | null
  requested: number
  retrieved: number
  items: {
    doi: string
    title: string
    status: 'retrieved' | 'not_found'
    via: string
    filename: string
    error: string
  }[]
}

/** Registered users (Administration). The superadmin ticks who may use the
 * standalone Download papers module — off for everyone by default — and sees
 * what each user fetched with it. */
export default function UsersAdminPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: me } = useQuery<User>({
    queryKey: ['me'], queryFn: () => api.get('/api/auth/me'),
  })
  const isAppAdmin = !!me?.is_admin
  const { data: users = [], isLoading } = useQuery<AdminUser[]>({
    queryKey: ['admin-users'],
    queryFn: () => api.get('/api/admin/users'),
    enabled: isAppAdmin,
  })
  const [error, setError] = useState('')
  const { data: downloaders = [] } = useQuery<DownloadUser[]>({
    queryKey: ['admin-paper-downloads'],
    queryFn: () => api.get('/api/admin/users/paper-downloads'),
    enabled: isAppAdmin,
  })
  const [openUser, setOpenUser] = useState<number | null>(null)

  const grant = useMutation({
    mutationFn: ({ id, allowed }: { id: number; allowed: boolean }) =>
      api.patch(`/api/admin/users/${id}`, { can_download_papers: allowed }),
    onSuccess: () => {
      setError('')
      queryClient.invalidateQueries({ queryKey: ['admin-users'] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('Users')}
      </h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {t('Everyone registered on this instance. Tick “Download papers” to open the standalone download module to a user — it is closed by default, and limited to 5 papers per hour for everyone but application admins.')}
        {!isAppAdmin && ' ' + t('Only an application admin can change them.')}
      </p>
      {error && <p className="mb-2 text-sm text-destructive">{error}</p>}
      {isAppAdmin && (
        <Card className="max-w-3xl overflow-hidden overflow-x-auto">
          <table className="w-full min-w-[32rem] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="p-3">{t('Name')}</th>
                <th className="p-3">{t('Email')}</th>
                <th className="p-3">{t('Registered')}</th>
                <th className="p-3 text-center">{t('Download papers')}</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-border last:border-0">
                  <td className="p-3">
                    {u.display_name}
                    {u.is_admin && (
                      <Badge className="ml-2">{t('app admin')}</Badge>
                    )}
                  </td>
                  <td className="p-3 text-muted-foreground">{u.email}</td>
                  <td className="p-3 tabular-nums text-muted-foreground">
                    {new Date(u.created_at).toLocaleDateString()}
                  </td>
                  <td className="p-3 text-center">
                    <input
                      type="checkbox"
                      className="size-4 accent-primary"
                      aria-label={t('Allow {{name}} to download papers', { name: u.display_name })}
                      title={u.is_admin ? t('Application admins always have this module') : undefined}
                      checked={u.is_admin || u.can_download_papers}
                      disabled={u.is_admin || grant.isPending}
                      onChange={(e) => grant.mutate({ id: u.id, allowed: e.target.checked })}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {isLoading && (
            <p className="p-6 text-sm text-muted-foreground">{t('Loading…')}</p>
          )}
        </Card>
      )}

      {isAppAdmin && (
        <>
          <h2 className="mt-8 text-base font-semibold text-foreground">
            {t('Downloaded papers')}
          </h2>
          <p className="mt-1 mb-3 max-w-2xl text-sm text-muted-foreground">
            {t('What each user fetched with the Download papers module: every run, with the papers requested and whether a PDF was retrieved. Click a user to see the details.')}
          </p>
          <Card className="max-w-3xl overflow-hidden overflow-x-auto">
            {downloaders.length === 0 ? (
              <p className="p-6 text-sm text-muted-foreground">
                {t('Nobody has used the module yet.')}
              </p>
            ) : (
              <table className="w-full min-w-[32rem] text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="p-3">{t('Name')}</th>
                    <th className="p-3 text-right">{t('Runs')}</th>
                    <th className="p-3 text-right">{t('PDFs retrieved')}</th>
                    <th className="p-3">{t('Last run')}</th>
                  </tr>
                </thead>
                <tbody>
                  {downloaders.map((u) => {
                    const key = u.id ?? 0
                    const open = openUser === key
                    return (
                      <DownloadUserRows key={key} user={u} open={open}
                        onToggle={() => setOpenUser(open ? null : key)} />
                    )
                  })}
                </tbody>
              </table>
            )}
          </Card>
        </>
      )}
    </div>
  )
}

function DownloadUserRows({ user, open, onToggle }: {
  user: DownloadUser; open: boolean; onToggle: () => void
}) {
  const { t } = useTranslation()
  const key = user.id ?? 0
  const { data: runs = [], isLoading } = useQuery<DownloadRun[]>({
    queryKey: ['admin-paper-downloads', key],
    queryFn: () => api.get(`/api/admin/users/paper-downloads/${key}`),
    enabled: open,
  })
  const statusLabel = (status: string) => ({
    done: t('done'), failed: t('failed'), cancelled: t('cancelled'),
    running: t('running'), queued: t('queued'),
  }[status] ?? status)
  return (
    <>
      <tr className="cursor-pointer border-b border-border hover:bg-muted/50"
          onClick={onToggle}>
        <td className="p-3">
          <span className="inline-flex items-center gap-1">
            {open ? <ChevronDown className="size-4 text-muted-foreground" />
              : <ChevronRight className="size-4 text-muted-foreground" />}
            {user.id === null ? (
              <span className="italic text-muted-foreground">{t('Deleted account')}</span>
            ) : user.display_name}
            {user.is_admin && <Badge className="ml-2">{t('app admin')}</Badge>}
          </span>
          {user.email && (
            <span className="ml-2 text-xs text-muted-foreground">{user.email}</span>
          )}
        </td>
        <td className="p-3 text-right tabular-nums">{user.runs}</td>
        <td className="p-3 text-right tabular-nums">
          {user.retrieved} / {user.requested}
        </td>
        <td className="p-3 tabular-nums text-muted-foreground">
          {user.last_at ? new Date(user.last_at).toLocaleString() : '—'}
        </td>
      </tr>
      {open && (
        <tr className="border-b border-border last:border-0">
          <td colSpan={4} className="bg-muted/30 p-0">
            {isLoading && (
              <p className="p-4 text-sm text-muted-foreground">{t('Loading…')}</p>
            )}
            {runs.map((run) => (
              <div key={run.id} className="border-b border-border p-3 last:border-0">
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span className="tabular-nums">
                    {new Date(run.created_at).toLocaleString()}
                  </span>
                  <Badge variant={run.status === 'done' ? 'default'
                    : run.status === 'failed' ? 'destructive' : 'outline'}>
                    {statusLabel(run.status)}
                  </Badge>
                  <span>
                    {t('{{retrieved}} of {{total}} PDF(s) retrieved',
                      { retrieved: run.retrieved, total: run.requested })}
                  </span>
                </div>
                <ul className="mt-2 space-y-1 text-sm">
                  {run.items.map((item) => (
                    <li key={item.doi} className="flex items-start gap-2">
                      <Badge variant={item.status === 'retrieved' ? 'success' : 'warning'}>
                        {item.status === 'retrieved' ? t('PDF retrieved') : t('No PDF')}
                      </Badge>
                      <div className="min-w-0 flex-1">
                        <p className="truncate">{item.title || item.doi}</p>
                        <p className="truncate text-xs text-muted-foreground">
                          {item.doi}
                          {item.status === 'retrieved'
                            && ` · ${item.filename} · ${t('via {{source}}', { source: item.via || '?' })}`}
                          {item.status === 'not_found' && item.error && ` · ${item.error}`}
                        </p>
                      </div>
                    </li>
                  ))}
                  {run.items.length === 0 && (
                    <li className="text-xs text-muted-foreground">
                      {t('No result recorded for this run.')}
                    </li>
                  )}
                </ul>
              </div>
            ))}
          </td>
        </tr>
      )}
    </>
  )
}
