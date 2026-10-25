// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type User } from '../api'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { usd, useDemoBudget } from '@/components/DemoBanner'

interface TrustedEmailRow {
  id: number
  email: string
  registered: boolean
  source: string // "manual" | "invite" (auto-allowlisted by a project invite)
}

/** M6 demo instance — the superadmin's allowlist: these emails register as
 * full accounts (no sandbox limits, no daily wipe). */
export default function DemoAccessPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: me } = useQuery<User | null>({
    queryKey: ['me'], queryFn: () => api.get('/api/auth/me'),
  })
  const { data: entries = [] } = useQuery<TrustedEmailRow[]>({
    queryKey: ['trusted-emails'],
    queryFn: () => api.get('/api/admin/trusted-emails'),
    enabled: !!me?.is_admin,
  })
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['trusted-emails'] })
  const add = useMutation({
    mutationFn: () => api.post('/api/admin/trusted-emails', { email }),
    onSuccess: () => { setEmail(''); setError(''); invalidate() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/api/admin/trusted-emails/${id}`),
    onSuccess: invalidate,
  })
  const { data: budget } = useDemoBudget(!!me?.is_admin)
  const resetBudget = useMutation({
    mutationFn: () => api.post('/api/admin/demo-ai-budget/reset'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['demo-ai-budget'] }),
  })
  const [resetResult, setResetResult] = useState('')
  const reset = useMutation({
    mutationFn: () => api.post<{ users: number; projects: number }>(
      '/api/admin/demo-reset'),
    onSuccess: (r) => setResetResult(
      t('Purged {{users}} sandbox accounts and {{projects}} projects.',
        { users: r.users, projects: r.projects })),
    onError: (e) => setResetResult(
      e instanceof ApiError ? e.message : t('Reset failed')),
  })

  if (!me?.is_admin) {
    return <p className="text-sm text-muted-foreground">
      {t('Only an application admin manages demo access.')}
    </p>
  }

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('Demo access')}
      </h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {t('Emails allowed to register as full accounts on this demo instance: no sandbox limits, the same access as on any other instance, and their data survives the daily reset. Visitors do not register: they open a guest session from the demo address. Adding an email that already has an account promotes it immediately; removing an entry does not demote an existing account. Members invited into a project by an allowlisted account are added here automatically.')}
      </p>
      <Card className="max-w-xl p-4">
        <form className="flex gap-2"
              onSubmit={(e) => { e.preventDefault(); add.mutate() }}>
          <Input type="email" required value={email}
                 placeholder="colleague@lab.org"
                 onChange={(e) => setEmail(e.target.value)} className="flex-1" />
          <Button type="submit" disabled={add.isPending}>{t('Add')}</Button>
        </form>
        {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
        <ul className="mt-4 space-y-1">
          {entries.length === 0 && (
            <li className="text-sm text-muted-foreground">
              {t('No allowlisted email yet.')}
            </li>
          )}
          {entries.map((entry) => (
            <li key={entry.id}
                className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2">
                {entry.email}
                {entry.registered && (
                  <Badge variant="success">{t('registered')}</Badge>
                )}
                {entry.source === 'invite' && (
                  <Badge>{t('invited by a project admin')}</Badge>
                )}
              </span>
              <Button variant="ghost" size="icon"
                      className="size-6 text-muted-foreground hover:text-destructive"
                      title={t('Remove from the allowlist')}
                      onClick={() => remove.mutate(entry.id)}>
                ✕
              </Button>
            </li>
          ))}
        </ul>
      </Card>

      <Card className="mt-4 max-w-xl p-4">
        <h2 className="text-sm font-semibold text-foreground">{t('AI budget of the visitors')}</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {t('Visitors run the AI features on the app-wide key, in its bulk-tier model, within three caps: {{user}} per guest session and, for all of them together, {{day}} per day and {{month}} per calendar month. A call that could cross a cap is refused before it is sent.',
             { user: usd(budget?.user_cap_usd), day: usd(budget?.daily_cap_usd),
               month: usd(budget?.monthly_cap_usd) })}
        </p>
        {budget && (
          <p className="mt-2 text-sm tabular-nums text-foreground">
            {t('Today: {{today}} of {{dayCap}} · this month: {{spent}} of {{cap}} ({{calls}} calls) · {{visitors}} visitor sessions open',
               { today: usd(budget.day_spent_usd), dayCap: usd(budget.daily_cap_usd),
                 spent: usd(budget.month_spent_usd), cap: usd(budget.monthly_cap_usd),
                 calls: budget.month_calls ?? 0, visitors: budget.live_visitors ?? 0 })}
          </p>
        )}
        <Button variant="outline" size="sm" className="mt-3"
                disabled={resetBudget.isPending}
                onClick={() => {
                  if (confirm(t("Start this month's visitor AI spending from zero again?")))
                    resetBudget.mutate()
                }}>
          {t("Reset this month's counter")}
        </Button>
      </Card>

      <Card className="mt-4 max-w-xl border-destructive/40 p-4">
        <h2 className="text-sm font-semibold text-foreground">{t('Daily reset')}</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {t('Guest sessions and their projects are purged automatically once a day (sessions opened during the last hour wait for the next purge). This button purges them all immediately — allowlisted accounts and their data are never touched.')}
        </p>
        <div className="mt-3 flex items-center gap-3">
          <Button variant="outline" size="sm" disabled={reset.isPending}
                  className="border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive"
                  onClick={() => {
                    if (confirm(t('Purge all sandbox accounts and their projects now?')))
                      reset.mutate()
                  }}>
            {reset.isPending ? t('Purging…') : t('Reset demo data now')}
          </Button>
          {resetResult && <span className="text-xs text-muted-foreground">{resetResult}</span>}
        </div>
      </Card>
    </div>
  )
}
