// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bug } from 'lucide-react'
import { api, ApiError } from '../api'
import { Button } from './ui/button'
import { Input } from './ui/input'
import { Textarea } from './ui/textarea'
import { Segmented } from './ui/segmented'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from './ui/dialog'
import { Tooltip, TooltipContent, TooltipTrigger } from './ui/tooltip'

/** Header button opening a quick bug/feedback form. The current route is
 * captured automatically so the admin knows where the problem happened. */
export default function FeedbackButton() {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [kind, setKind] = useState<'bug' | 'feedback' | 'feature'>('bug')
  const [severity, setSeverity] = useState<'minor' | 'major' | 'blocking'>('minor')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')
  const location = useLocation()
  const queryClient = useQueryClient()

  const projectMatch = location.pathname.match(/^\/projects\/(\d+)/)

  const create = useMutation({
    mutationFn: () => api.post('/api/tickets', {
      title, body, kind, severity,
      page: location.pathname,
      project_id: projectMatch ? Number(projectMatch[1]) : null,
    }),
    onSuccess: () => {
      setSent(true)
      setTitle(''); setBody(''); setError('')
      queryClient.invalidateQueries({ queryKey: ['tickets'] })
      queryClient.invalidateQueries({ queryKey: ['tickets-summary'] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Failed to send')),
  })

  const onOpenChange = (v: boolean) => {
    setOpen(v)
    if (!v) { setSent(false); setError('') }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <Tooltip>
        <TooltipTrigger asChild>
          <DialogTrigger asChild>
            <Button variant="ghost" size="icon" aria-label={t('Report a bug or send feedback')}>
              <Bug className="size-4" />
            </Button>
          </DialogTrigger>
        </TooltipTrigger>
        <TooltipContent>{t('Report a bug / feedback')}</TooltipContent>
      </Tooltip>

      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('Report a bug / send feedback')}</DialogTitle>
        </DialogHeader>

        {sent ? (
          <div className="rounded-md bg-success/10 px-3 py-4 text-center text-sm text-success">
            {t('✓ Ticket sent — thanks! The admin sees it immediately.')}
            <div className="mt-3">
              <Button variant="outline" size="sm" onClick={() => setSent(false)}>
                {t('Send another')}
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <Segmented
              value={kind}
              onChange={setKind}
              options={[
                { value: 'bug', label: '🐞 bug' },
                { value: 'feedback', label: '💬 feedback' },
                { value: 'feature', label: '✨ feature' },
              ]}
            />
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t('Short title (the problem / your idea)')}
            />
            <Textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={4}
              placeholder={t('Details: what you did, what you expected, what happened…')}
            />
            {kind === 'bug' && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                {t('Severity:')}
                <Segmented
                  size="sm"
                  value={severity}
                  onChange={setSeverity}
                  options={[
                    { value: 'minor', label: 'minor' },
                    { value: 'major', label: 'major' },
                    { value: 'blocking', label: 'blocking' },
                  ]}
                />
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              {t('Reported from')} <code className="font-mono text-foreground">{location.pathname}</code> {t('— attached automatically.')}
            </p>
            {error && <p className="text-xs text-destructive">{error}</p>}
            <Button
              onClick={() => create.mutate()}
              disabled={create.isPending || title.trim().length < 3}
            >
              {t('Send the ticket')}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
