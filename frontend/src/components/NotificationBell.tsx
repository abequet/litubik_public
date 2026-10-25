// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Bell } from 'lucide-react'
import { api, type NotificationItem } from '../api'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from './ui/dropdown-menu'

/** Header bell (living review, chantier 5): the unread in-app notifications —
 * today "a search update found N new candidates" — polled every minute.
 * Opening one marks it read and goes to the project's Search page. */
export default function NotificationBell() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: items = [] } = useQuery<NotificationItem[]>({
    queryKey: ['notifications'],
    queryFn: () => api.get('/api/notifications?unread=true&limit=20'),
    refetchInterval: 60_000,
  })
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['notifications'] })
    queryClient.invalidateQueries({ queryKey: ['notifications-summary'] })
  }
  const markRead = useMutation({
    mutationFn: (id: number) => api.post(`/api/notifications/${id}/read`),
    onSuccess: invalidate,
  })
  const markAll = useMutation({
    mutationFn: () => api.post('/api/notifications/read-all'),
    onSuccess: invalidate,
  })
  const unread = items.length

  const describe = (n: NotificationItem): string => {
    const p = n.payload
    if (n.kind === 'search_update') {
      const name = String(p.project_name ?? '')
      const count = Number(p.n_new_unique ?? 0)
      return count > 0
        ? t('{{name}}: search update found {{count}} new candidates to screen', { name, count })
        : t('{{name}}: search update found nothing new', { name })
    }
    return n.kind
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="relative inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground outline-none focus-visible:ring-ring/50 focus-visible:ring-[3px]"
        title={t('Notifications')}
        aria-label={unread
          ? t('Notifications ({{count}} unread)', { count: unread })
          : t('Notifications')}
      >
        <Bell className="size-4" aria-hidden />
        {unread > 0 && (
          <span aria-hidden
                className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-primary px-1 text-center text-[0.625rem] font-semibold leading-4 text-primary-foreground">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel className="flex items-center justify-between">
          {t('Notifications')}
          {unread > 0 && (
            <button type="button" onClick={() => markAll.mutate()}
                    className="text-xs font-normal text-muted-foreground hover:text-foreground hover:underline">
              {t('Mark all read')}
            </button>
          )}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {items.length === 0 && (
          <p className="px-2 py-3 text-xs text-muted-foreground">{t('Nothing new.')}</p>
        )}
        {items.map((n) => (
          <DropdownMenuItem key={n.id} asChild className="whitespace-normal">
            <Link to={n.project_id ? `/projects/${n.project_id}/search` : '/'}
                  onClick={() => markRead.mutate(n.id)}
                  className="flex flex-col items-start gap-0.5">
              <span className="text-xs text-foreground">{describe(n)}</span>
              <span className="text-xs text-muted-foreground">
                {new Date(n.created_at).toLocaleString()}
              </span>
            </Link>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
