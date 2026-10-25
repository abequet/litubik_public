// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { api } from '../api'
import { useMe } from '../App'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Segmented } from '@/components/ui/segmented'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from '@/components/ui/dialog'

interface TicketRow {
  id: number
  title: string
  body: string
  kind: 'bug' | 'feedback' | 'feature'
  severity: 'minor' | 'major' | 'blocking'
  page: string
  status: 'open' | 'in_progress' | 'resolved' | 'closed'
  project_id: number | null
  project_name: string | null
  author: string
  created_at: string
  updated_at: string
  n_comments: number
}

interface TicketComment {
  id: number
  author: string
  body: string
  created_at: string
  mine: boolean
}

interface TicketDetail extends TicketRow {
  comments: TicketComment[]
}

// Ticket status is a STATE, so it earns the semantic vote colours. open needs
// triage (warning), resolved is done (success); in_progress is active but not a
// success/danger signal (neutral graphite), closed is de-emphasised (outline).
const STATUS_BADGE: Record<TicketRow['status'],
  'default' | 'outline' | 'success' | 'warning'> = {
  open: 'warning',
  in_progress: 'default',
  resolved: 'success',
  closed: 'outline',
}

// Same mapping for the highlighted (current) status pill in the modal, using the
// Button variants — closed maps to secondary (Button has no outline-with-fill).
const STATUS_BUTTON: Record<TicketRow['status'],
  'default' | 'secondary' | 'success' | 'warning'> = {
  open: 'warning',
  in_progress: 'default',
  resolved: 'success',
  closed: 'secondary',
}

const KIND_ICON: Record<TicketRow['kind'], string> = {
  bug: '🐞', feedback: '💬', feature: '✨',
}

const STATUS_FILTERS = [
  { value: '', label: 'all' },
  { value: 'open', label: 'open' },
  { value: 'in_progress', label: 'in progress' },
  { value: 'resolved', label: 'resolved' },
  { value: 'closed', label: 'closed' },
]

function since(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return i18n.t('just now')
  if (mins < 60) return i18n.t('{{count}} min ago', { count: mins })
  const hours = Math.round(mins / 60)
  if (hours < 24) return i18n.t('{{count}} h ago', { count: hours })
  return i18n.t('{{count}} d ago', { count: Math.round(hours / 24) })
}

/** Ticket triage board: reviewers see their reports; the app admin sees and
 * triages everything. Polls so new tickets show up while you work. */
export default function TicketsPage() {
  const { t } = useTranslation()
  const { data: me } = useMe()
  const [statusFilter, setStatusFilter] = useState('')
  const [openId, setOpenId] = useState<number | null>(null)
  const { data: tickets = [] } = useQuery<TicketRow[]>({
    queryKey: ['tickets', statusFilter],
    queryFn: () => api.get(`/api/tickets${statusFilter ? `?status=${statusFilter}` : ''}`),
    refetchInterval: 30_000,
  })

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">{t('Tickets')}</h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {me?.is_admin
          ? t('Every bug report and piece of feedback sent by the users (auto-refreshes).')
          : t('Your bug reports and feedback — the admin sees them in real time.')}
      </p>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Segmented
          value={statusFilter}
          onChange={setStatusFilter}
          options={STATUS_FILTERS.map((o) => ({ ...o, label: t(o.label) }))}
        />
        {me?.is_admin && (
          <Button asChild variant="outline" size="sm" className="ml-auto">
            <a href={`/api/tickets/export.csv${statusFilter ? `?status=${statusFilter}` : ''}`}>
              ⬇ CSV
            </a>
          </Button>
        )}
      </div>
      {tickets.length === 0 ? (
        <Card className="p-8 text-center text-sm text-muted-foreground">
          {statusFilter
            ? t('No ticket with status "{{status}}" — use the 🐞 Report button in the header to send one.', { status: t(statusFilter.replace('_', ' ')) })
            : t('No ticket yet — use the 🐞 Report button in the header to send one.')}
        </Card>
      ) : (
        <ul className="space-y-2">
          {tickets.map((tk) => (
            <li key={tk.id}>
              <button onClick={() => setOpenId(tk.id)} aria-labelledby={`ticket-${tk.id}-title`}
                      className="block w-full text-left outline-none">
                <Card className="p-4 transition-colors hover:bg-accent">
                  <div className="flex items-center gap-2">
                    <span>{KIND_ICON[tk.kind]}</span>
                    <span id={`ticket-${tk.id}-title`} className="flex-1 text-sm font-medium text-foreground">
                      <span className="font-mono text-muted-foreground">#{tk.id}</span>{' '}
                      {tk.title}
                    </span>
                    {tk.kind === 'bug' && tk.severity !== 'minor' && (
                      <Badge variant={tk.severity === 'blocking' ? 'destructive' : 'warning'}>
                        {t(tk.severity)}
                      </Badge>
                    )}
                    <Badge variant={STATUS_BADGE[tk.status]}>
                      {t(tk.status.replace('_', ' '))}
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {tk.author} · {since(tk.created_at)}
                    {tk.project_name ? ` · ${tk.project_name}` : ''}
                    {tk.page ? ` · ${tk.page}` : ''}
                    {tk.n_comments ? ` · 💬 ${tk.n_comments}` : ''}
                  </p>
                </Card>
              </button>
            </li>
          ))}
        </ul>
      )}
      {openId !== null && (
        <TicketModal ticketId={openId} isAdmin={!!me?.is_admin}
                     onClose={() => setOpenId(null)} />
      )}
    </div>
  )
}

function TicketModal({ ticketId, isAdmin, onClose }: {
  ticketId: number
  isAdmin: boolean
  onClose: () => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [comment, setComment] = useState('')
  const { data: ticket } = useQuery<TicketDetail>({
    queryKey: ['ticket', ticketId],
    queryFn: () => api.get(`/api/tickets/${ticketId}`),
    refetchInterval: 15_000,
  })
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['ticket', ticketId] })
    queryClient.invalidateQueries({ queryKey: ['tickets'] })
    queryClient.invalidateQueries({ queryKey: ['tickets-summary'] })
  }
  const setStatus = useMutation({
    mutationFn: (status: string) =>
      api.put(`/api/tickets/${ticketId}/status`, { status }),
    onSuccess: invalidate,
  })
  const addComment = useMutation({
    mutationFn: () => api.post(`/api/tickets/${ticketId}/comments`, { body: comment }),
    onSuccess: () => { setComment(''); invalidate() },
  })
  if (!ticket) return null
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="flex max-h-[85vh] max-w-lg flex-col gap-3">
        <DialogHeader>
          <DialogTitle className="pr-6 text-sm">
            {KIND_ICON[ticket.kind]} <span className="font-mono text-muted-foreground">#{ticket.id}</span>{' '}
            {ticket.title}
          </DialogTitle>
          <DialogDescription className="text-xs">
            {ticket.author} · {since(ticket.created_at)}
            {ticket.project_name ? ` · ${ticket.project_name}` : ''}
            {ticket.page ? ` · ${ticket.page}` : ''}
            {ticket.kind === 'bug' ? ` · ${t(ticket.severity)}` : ''}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap items-center gap-1.5">
          {(['open', 'in_progress', 'resolved', 'closed'] as const).map((s) => {
            const current = ticket.status === s
            const locked = !isAdmin && s !== 'closed'
            return (
              <Button
                key={s}
                size="sm"
                variant={current ? STATUS_BUTTON[s] : 'outline'}
                aria-pressed={current}
                disabled={locked && !current}
                onClick={() => { if (!current) setStatus.mutate(s) }}
                className={cn('rounded-full', current && 'pointer-events-none')}
              >
                {t(s.replace('_', ' '))}
              </Button>
            )
          })}
        </div>
        {ticket.body && (
          <p className="whitespace-pre-wrap rounded-md bg-muted px-3 py-2 text-sm text-foreground">
            {ticket.body}
          </p>
        )}
        <div className="flex-1 space-y-2 overflow-y-auto">
          {ticket.comments.map((c) => (
            <div key={c.id} className={cn(
              'rounded-md px-3 py-2 text-xs text-foreground',
              c.mine ? 'border-l-2 border-l-primary bg-accent' : 'bg-muted')}>
              <span className="font-medium">{c.author}</span>
              <span className="text-muted-foreground"> · {since(c.created_at)}</span>
              <p className="mt-0.5 whitespace-pre-wrap">{c.body}</p>
            </div>
          ))}
        </div>
        <div className="flex gap-2">
          <Input value={comment} onChange={(e) => setComment(e.target.value)}
                 onKeyDown={(e) => {
                   if (e.key === 'Enter' && comment.trim()) addComment.mutate()
                 }}
                 placeholder={t('Add a comment…')} />
          <Button onClick={() => addComment.mutate()}
                  disabled={addComment.isPending || !comment.trim()}>
            {t('Send')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
