// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, X } from 'lucide-react'
import { api, type RecordTagInfo, type TagInfo } from '../api'
import { cn } from '@/lib/utils'
import { Input } from '@/components/ui/input'

/** Tag chips for one paper + a small picker to attach existing tags or create
 * one on the fly. Tags never touch votes or PRISMA numbers — they are the
 * "keep this paper around" shelf (e.g. Intro/Discussion, ticket #16). */

// Offered as a one-click create while it does not exist yet — the canonical
// "keep even if excluded" shelf the tags feature was built for.
const SUGGESTED = 'Intro/Discussion'

export default function TagChips({ projectId, recordId, initialTags, className }: {
  projectId: number
  recordId: number
  /** tags already known (a list payload) — seeds the cache, no request */
  initialTags?: RecordTagInfo[]
  className?: string
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const base = `/api/projects/${projectId}/tags`
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const popRef = useRef<HTMLDivElement>(null)

  const { data: mine = [] } = useQuery<RecordTagInfo[]>({
    queryKey: ['record-tags', projectId, recordId],
    queryFn: () => api.get(`${base}/records/${recordId}`),
    initialData: initialTags,
    // seeded from a fresh list page: no refetch on mount
    staleTime: initialTags ? 30_000 : 0,
  })
  const { data: all = [] } = useQuery<TagInfo[]>({
    queryKey: ['tags', projectId],
    queryFn: () => api.get(base),
    enabled: open,
  })

  const refresh = (tags: RecordTagInfo[]) => {
    queryClient.setQueryData(['record-tags', projectId, recordId], tags)
    queryClient.invalidateQueries({ queryKey: ['tags', projectId] })
    queryClient.invalidateQueries({ queryKey: ['tagged-records', projectId] })
  }
  const attach = useMutation({
    mutationFn: (name: string) =>
      api.post<RecordTagInfo[]>(`${base}/records/${recordId}`, { name }),
    onSuccess: (tags) => { refresh(tags); setDraft('') },
  })
  const detach = useMutation({
    mutationFn: (tagId: number) =>
      api.del<RecordTagInfo[]>(`${base}/records/${recordId}/${tagId}`),
    onSuccess: refresh,
  })

  // close the picker on outside click
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!popRef.current?.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('mousedown', onDown)
    return () => window.removeEventListener('mousedown', onDown)
  }, [open])

  const attached = new Set(mine.map((t) => t.id))
  const available = all.filter((t) => !attached.has(t.id))
  const showSuggested = !all.some(
    (t) => t.name.toLowerCase() === SUGGESTED.toLowerCase())

  return (
    <div className={cn('relative flex flex-wrap items-center gap-1.5', className)}>
      {mine.map((tag) => (
        <span key={tag.id}
              className="inline-flex items-center gap-1 rounded-full border border-border bg-muted px-2 py-0.5 text-xs text-foreground">
          {tag.name}
          <button type="button" title={t('Remove tag “{{name}}”', { name: tag.name })}
                  onClick={() => detach.mutate(tag.id)}
                  className="text-muted-foreground hover:text-destructive">
            <X className="size-3" />
          </button>
        </span>
      ))}
      <button type="button" onClick={() => setOpen((v) => !v)}
              className="inline-flex items-center gap-0.5 rounded-full border border-dashed border-border px-2 py-0.5 text-xs text-muted-foreground transition-colors hover:border-solid hover:text-foreground">
        <Plus className="size-3" /> {t('Tag')}
      </button>

      {open && (
        <div ref={popRef}
             className="absolute left-0 top-full z-30 mt-1 w-60 rounded-lg border border-border bg-popover p-2 text-popover-foreground shadow-lg">
          <Input autoFocus value={draft}
                 onChange={(e) => setDraft(e.target.value)}
                 onKeyDown={(e) => {
                   if (e.key === 'Enter' && draft.trim()) {
                     attach.mutate(draft.trim())
                   }
                   if (e.key === 'Escape') setOpen(false)
                 }}
                 placeholder={t('Add or create a tag…')}
                 className="mb-1.5 h-7 px-2 text-xs" />
          <ul className="max-h-44 overflow-y-auto">
            {draft.trim() && !all.some((t) =>
              t.name.toLowerCase() === draft.trim().toLowerCase()) && (
              <PickRow onClick={() => attach.mutate(draft.trim())}>
                {t('+ Create “{{name}}”', { name: draft.trim() })}
              </PickRow>
            )}
            {available
              .filter((tag) =>
                tag.name.toLowerCase().includes(draft.trim().toLowerCase()))
              .map((tag) => (
                <PickRow key={tag.id} onClick={() => attach.mutate(tag.name)}>
                  {tag.name}
                  <span className="ml-1 text-muted-foreground">
                    ({tag.n_records})
                  </span>
                </PickRow>
              ))}
            {showSuggested && !draft.trim() && (
              <PickRow onClick={() => attach.mutate(SUGGESTED)}>
                + {SUGGESTED}
                <span className="ml-1 text-muted-foreground">
                  {t('— keep for the manuscript even if excluded')}
                </span>
              </PickRow>
            )}
            {!available.length && !draft.trim() && !showSuggested && (
              <li className="px-2 py-1 text-xs text-muted-foreground">
                {t('All tags are on this paper — type to create a new one.')}
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  )
}

function PickRow({ children, onClick }: {
  children: React.ReactNode
  onClick: () => void
}) {
  return (
    <li>
      <button type="button" onClick={onClick}
              className="w-full rounded px-2 py-1 text-left text-xs hover:bg-accent">
        {children}
      </button>
    </li>
  )
}
