// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, type DemoAiBudget, type InstanceInfo, type User } from '../api'

/** M6: public instance profile — drives the demo banner, the guest entry of
 * the sign-in page and the visibility of the superadmin's "Demo access" page.
 * Endpoint is public, so the banner also shows on the login/register screens. */
export function useInstance() {
  return useQuery<InstanceInfo>({
    queryKey: ['instance'],
    queryFn: () => api.get('/api/instance'),
    staleTime: Infinity,
  })
}

/** A visitor's sandbox account on a demo instance (a guest session, or an
 * e-mail sandbox account from before guest sessions existed). The backend
 * enforces every restriction; the interface only hides what would fail. */
export function isSandbox(user: User | null | undefined,
                          instance: InstanceInfo | undefined): boolean {
  return !!(instance?.demo && user && !user.is_admin && !user.is_trusted)
}

export function useDemoBudget(enabled: boolean) {
  return useQuery<DemoAiBudget>({
    queryKey: ['demo-ai-budget'],
    queryFn: () => api.get('/api/demo/ai-budget'),
    enabled,
    refetchInterval: 60_000,
  })
}

export const usd = (amount: number | undefined) => `$${(amount ?? 0).toFixed(2)}`

export default function DemoBanner({ user }: { user?: User | null }) {
  const { t } = useTranslation()
  const { data: instance } = useInstance()
  const sandbox = isSandbox(user, instance)
  const { data: budget } = useDemoBudget(sandbox)
  if (!instance?.demo) return null
  // full accounts, and the ordinary sign-in of the instance, get no banner
  if (user ? !sandbox : !instance.guest_entry) return null
  const hour = `${String(instance.reset_hour).padStart(2, '0')}:00`
  const daily = instance.reset_hour >= 0
  return (
    <div className="flex shrink-0 flex-wrap items-center justify-center gap-x-3 gap-y-0.5 bg-warning/15 px-4 py-1.5 text-center text-xs font-medium text-warning">
      <span>
        {sandbox
          ? (daily
              ? t('Demo session — everything you create here is deleted every day at {{hour}} UTC.', { hour })
              : t('Demo session — everything you create here is deleted regularly.'))
          : (daily
              ? t('Demo instance — try LitUbik in one click, without an account. Guest sessions are deleted every day at {{hour}} UTC.', { hour })
              : t('Demo instance — try LitUbik in one click, without an account.'))}
      </span>
      {sandbox && budget?.applies && (
        <span className="rounded-full bg-warning/15 px-2 py-0.5 tabular-nums">
          {budget.enabled
            ? t('AI budget: {{left}} left', { left: usd(budget.left_usd) })
            : t('AI features are off on this demo')}
        </span>
      )}
    </div>
  )
}
