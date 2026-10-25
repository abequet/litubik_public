// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Undo2, X } from 'lucide-react'
import { api, ApiError } from '../api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

/** Undoing a conflict resolution (a misclick, a decision recorded on the
 * wrong card) — shared by the title/abstract and full-text Conflicts tabs.
 * The conflict goes back to "To resolve"; the reviewers' votes are untouched. */

export interface ResolvedConflict {
  id: number
  title: string
  decision: string
}

export function ReopenConflictButton({ projectId, conflictId, stage, round, onReopened }: {
  projectId: number
  conflictId: number
  stage: 'ta' | 'ft'
  round: number
  onReopened: () => void
}) {
  const { t } = useTranslation()
  const [error, setError] = useState('')
  const reopen = useMutation({
    mutationFn: () => api.post(
      `/api/projects/${projectId}/screening/conflicts/${conflictId}/reopen`
      + `?stage=${stage}&round=${round}`),
    onSuccess: () => { setError(''); onReopened() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Undo failed')),
  })
  return (
    <>
      <Button variant="outline" size="sm" className="h-7 shrink-0 gap-1 px-2 text-xs"
              onClick={() => reopen.mutate()} disabled={reopen.isPending}
              title={t('Put this conflict back in “To resolve” — the votes are kept')}>
        <Undo2 className="size-3.5" />{t('Undo resolution')}
      </Button>
      {error && <span className="text-xs text-destructive">{error}</span>}
    </>
  )
}

/** Shown above the list right after a resolution: the card has just left the
 * "To resolve" view, so this is where a slip gets caught. */
export function JustResolvedBanner({ projectId, stage, round, last, onReopened, onDismiss }: {
  projectId: number
  stage: 'ta' | 'ft'
  round: number
  last: ResolvedConflict
  onReopened: () => void
  onDismiss: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted px-3 py-2 text-xs text-muted-foreground">
      <span className="min-w-0 flex-1">
        {t('Resolved:')}{' '}
        <span className={cn('font-medium',
          last.decision === 'include' ? 'text-success' : 'text-destructive')}>
          {t(last.decision)}</span>
        {' — '}<span className="text-foreground">{last.title}</span>
      </span>
      <ReopenConflictButton projectId={projectId} conflictId={last.id}
                            stage={stage} round={round} onReopened={onReopened} />
      <button onClick={onDismiss} title={t('Close')}
              className="shrink-0 rounded p-0.5 hover:bg-background/60 hover:text-foreground">
        <X className="size-3.5" />
      </button>
    </div>
  )
}
