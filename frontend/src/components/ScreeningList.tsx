// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from 'react'
import {
  useInfiniteQuery, useMutation, useQueryClient,
} from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type RecordTagInfo } from '../api'
import { cn } from '@/lib/utils'
import { highlight, type HighlightFamily } from '@/lib/highlight'
import {
  TranslateControl, useRecordTranslation, type Translations,
} from './RecordTranslation'
import TagChips from './TagChips'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Segmented } from '@/components/ui/segmented'
import { Textarea } from '@/components/ui/textarea'

/** Ticket #8 — infinite-scroll list view of MY title/abstract screening
 * queue, with inline voting. Backed by GET /screening/list (keyword search
 * + offset pagination); the single-record view stays the default. */

interface ListItem {
  id: number
  doi: string | null
  title: string
  authors: string[]
  year: number | null
  journal: string
  abstract: string
  translations?: Translations
  skipped: boolean
  decision: string | null
  note: string
  locked: boolean
  tags: RecordTagInfo[]
}

const PAGE = 30

export default function ScreeningList({ projectId, round, families, query }: {
  projectId: number
  round: number
  families: HighlightFamily[]
  query: string
}) {
  const { t } = useTranslation()
  // plain browsing shows what is left to screen; a keyword search widens to
  // everything assigned to me so already-voted matches surface too
  const [status, setStatus] = useState<'pending' | 'voted' | 'all'>('pending')
  useEffect(() => { if (query.trim()) setStatus('all') }, [query])

  const {
    data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading,
  } = useInfiniteQuery<{ total: number; items: ListItem[] }>({
    queryKey: ['screening-list', projectId, round, status, query],
    queryFn: ({ pageParam }) => api.get(
      `/api/projects/${projectId}/screening/list?round=${round}`
      + `&status=${status}&offset=${pageParam}&limit=${PAGE}`
      + `&q=${encodeURIComponent(query)}`),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })
  const items = data?.pages.flatMap((p) => p.items) ?? []
  const total = data?.pages[0]?.total ?? 0

  // infinite scroll: load the next page when the sentinel becomes visible
  const sentinelRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && hasNextPage && !isFetchingNextPage) {
        fetchNextPage()
      }
    }, { rootMargin: '400px' })
    observer.observe(el)
    return () => observer.disconnect()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage, items.length])

  return (
    <div>
      <div className="mb-3 flex items-center gap-3">
        <Segmented
          value={status}
          onChange={setStatus}
          options={[
            { value: 'pending', label: t('To screen') },
            { value: 'voted', label: t('Voted') },
            { value: 'all', label: t('All') },
          ]}
        />
        <span className="text-xs tabular-nums text-muted-foreground">
          {query.trim()
            ? t('{{count}} result(s) for “{{query}}”', { count: total, query: query.trim() })
            : t('{{count}} paper(s)', { count: total })}
        </span>
      </div>
      {isLoading && <p className="text-sm text-muted-foreground">{t('Loading…')}</p>}
      {!isLoading && items.length === 0 && (
        <Card className="p-6 text-sm text-muted-foreground">
          {query.trim() ? t('No paper matches your search.')
            : status === 'pending'
              ? t('✓ Nothing left in your queue — check the Conflicts tab or the Dashboard.')
              : t('Nothing here yet.')}
        </Card>
      )}
      <ul className="space-y-3">
        {items.map((item) => (
          <ListCard key={item.id} item={item} projectId={projectId}
                    round={round} families={families} />
        ))}
      </ul>
      <div ref={sentinelRef} />
      {isFetchingNextPage && (
        <p className="py-3 text-center text-xs text-muted-foreground">{t('Loading…')}</p>
      )}
    </div>
  )
}

function ListCard({ item, projectId, round, families }: {
  item: ListItem
  projectId: number
  round: number
  families: HighlightFamily[]
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [expanded, setExpanded] = useState(false)
  // a list shows dozens of records at once: translation here is on request
  // only, expanding an abstract never fires one (cached ones show right away)
  const translation = useRecordTranslation({
    projectId, recordId: item.id, translations: item.translations,
    autoAllowed: false,
  })
  const [showNote, setShowNote] = useState(false)
  const [note, setNote] = useState(item.note)
  const [error, setError] = useState('')
  // my vote as it stands on this card — a vote keeps the card in place
  // (the list is not refetched under the reader) so it can be undone
  const [decision, setDecision] = useState(item.decision)
  const [locked, setLocked] = useState(item.locked)
  const [savedNote, setSavedNote] = useState(item.note)
  // a refetch (window focus, another tab) brings the server's word back
  useEffect(() => {
    setDecision(item.decision); setLocked(item.locked)
  }, [item.decision, item.locked])
  // what the last vote replaced, while it can still be undone
  const [undoable, setUndoable] = useState<
    { decision: string | null; note: string } | null>(null)

  const invalidate = () => {
    for (const key of ['screening-queue', 'screening-my-votes',
                       'screening-stats', 'screening-conflicts']) {
      queryClient.invalidateQueries({ queryKey: [key, projectId] })
    }
    // marked stale only: the next filter change or visit reloads it
    queryClient.invalidateQueries({ queryKey: ['screening-list', projectId],
                                    refetchType: 'none' })
  }
  const vote = useMutation({
    mutationFn: (choice: string) =>
      api.post<{ outcome: string | null }>(
        `/api/projects/${projectId}/screening/vote?round=${round}`,
        { record_id: item.id, decision: choice, justification: note }),
    onSuccess: (res, choice) => {
      setError(''); setShowNote(false)
      setUndoable({ decision, note: savedNote })
      setDecision(choice)
      setSavedNote(note)
      setLocked(res.outcome !== null)
      invalidate()
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Vote failed')),
  })
  const undo = useMutation({
    mutationFn: (previous: { decision: string | null; note: string }) =>
      api.post<{ outcome: string | null }>(
        `/api/projects/${projectId}/screening/vote/undo?round=${round}`,
        { record_id: item.id, previous_decision: previous.decision,
          previous_justification: previous.note }),
    onSuccess: (res, previous) => {
      setError('')
      setDecision(previous.decision)
      setNote(previous.note)
      setSavedNote(previous.note)
      setLocked(res.outcome !== null)
      setUndoable(null)
      invalidate()
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Undo failed')),
  })
  const skip = useMutation({
    mutationFn: () =>
      api.post(`/api/projects/${projectId}/screening/skip?round=${round}`,
        { record_id: item.id }),
    onSuccess: () => { setError(''); invalidate() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Skip failed')),
  })

  const canVote = !locked
  const busy = vote.isPending || undo.isPending
  const decisionBadge = decision && (
    <Badge
      variant={decision === 'include' ? 'success'
        : decision === 'exclude' ? 'destructive' : 'warning'}
      className="shrink-0"
    >
      {locked ? '🔒 ' : ''}{t(decision)}
    </Badge>
  )
  const undoButton = undoable && (
    <Button variant="outline" size="sm" onClick={() => undo.mutate(undoable)}
            disabled={busy}
            title={undoable.decision
              ? t('Put back your previous vote ({{decision}})', { decision: t(undoable.decision) })
              : t('Take back this vote — the paper returns to your queue')}>
      {t('↶ Undo')}
    </Button>
  )

  return (
    <li>
      <Card className="p-4">
        <div className="flex items-start justify-between gap-3">
          <h3 className="text-sm font-semibold text-foreground">
            {highlight(translation.shown?.title || item.title, families)}
          </h3>
          <span className="flex shrink-0 items-center gap-2">
            {item.skipped && decision === null && (
              <Badge variant="warning" className="shrink-0">{t('skipped')}</Badge>
            )}
            {decisionBadge}
          </span>
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {item.authors.slice(0, 6).join('; ')}{item.authors.length > 6 ? '…' : ''}
          {item.year ? ` · ${item.year}` : ''}
          {item.journal ? ` · ${item.journal}` : ''}
          {item.doi && (
            <>
              {' · '}
              <a href={`https://doi.org/${item.doi}`} target="_blank" rel="noreferrer"
                 className="font-mono text-primary hover:underline">{item.doi}</a>
            </>
          )}
        </p>
        {item.abstract && (
          <>
            {/* clicking the clamped text opens it too (a mouse shortcut: the
                button below stays the keyboard path); once open the text stays
                selectable and the button folds it back */}
            <p role="presentation"
               className={cn('mt-2 text-sm leading-relaxed text-foreground/90',
                 !expanded && 'line-clamp-3 cursor-pointer')}
               onClick={() => { if (!expanded) setExpanded(true) }}>
              {highlight(translation.shown?.abstract || item.abstract, families)}
            </p>
            <button type="button" aria-expanded={expanded}
                    onClick={() => setExpanded((v) => !v)}
                    className="mt-0.5 text-xs text-muted-foreground hover:text-foreground hover:underline">
              {expanded ? t('Show less') : t('Show the full abstract')}
            </button>
          </>
        )}
        {/* the "automatic" preference is set from the single-record view */}
        <TranslateControl control={translation.control} withAuto={false}
                          className="mt-1" />
        <TagChips projectId={projectId} recordId={item.id}
                  initialTags={item.tags} className="mt-2" />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {canVote ? (
            <>
              <Button variant="success" size="sm"
                      onClick={() => vote.mutate('include')}
                      disabled={busy}>
                {t('Include')}
              </Button>
              <Button variant="warning" size="sm"
                      onClick={() => vote.mutate('maybe')}
                      disabled={busy}>
                {t('Maybe')}
              </Button>
              <Button variant="destructive" size="sm"
                      onClick={() => vote.mutate('exclude')}
                      disabled={busy}>
                {t('Exclude')}
              </Button>
              {undoButton}
              {decision === null && (
                <Button variant="outline" size="sm"
                        onClick={() => skip.mutate()}
                        disabled={skip.isPending || busy}
                        title={t('No decision now — the record moves to the back of your queue and comes around again')}>
                  {t('⏭ Skip')}
                </Button>
              )}
              <button
                onClick={() => setShowNote((v) => !v)}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                {showNote ? t('Hide note') : note ? t('Edit note') : t('+ Note')}
              </button>
              {decision !== null && !undoable && (
                <span className="text-xs text-muted-foreground">
                  {t('Voting again replaces your vote.')}
                </span>
              )}
            </>
          ) : (
            <>
              {undoButton}
              <span className="text-xs text-muted-foreground">
                {t('Record completed — read-only')}
              </span>
            </>
          )}
        </div>
        {showNote && canVote && (
          <Textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t('Note for this vote (visible during conflict resolution)…')}
            rows={2}
            className="mt-2 text-xs"
          />
        )}
        {!showNote && note && (
          <p className="mt-2 text-xs italic text-muted-foreground">
            {t('Note')}: {note}
          </p>
        )}
        {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
      </Card>
    </li>
  )
}
