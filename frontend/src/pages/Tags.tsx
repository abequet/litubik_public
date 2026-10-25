// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Pencil, Trash2 } from 'lucide-react'
import {
  api, ApiError, type Project, type TagInfo, type TaggedRecord,
} from '../api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

/** The tag shelf (tickets #16/#T13): every tagged paper in one list, whatever
 * its screening fate — the whole point is finding back the papers kept for
 * the intro/discussion even though they were excluded. */
export default function TagsPage() {
  const { t } = useTranslation()
  const { projectId } = useParams()
  const pid = Number(projectId)
  const base = `/api/projects/${pid}/tags`
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState<number | null>(null)
  const [error, setError] = useState('')

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'], queryFn: () => api.get('/api/projects'),
  })
  const project = projects.find((p) => p.id === pid)
  const { data: tags = [] } = useQuery<TagInfo[]>({
    queryKey: ['tags', pid], queryFn: () => api.get(base),
  })
  const { data: rows = [], isLoading } = useQuery<TaggedRecord[]>({
    queryKey: ['tagged-records', pid],
    queryFn: () => api.get(`${base}/records`),
  })
  const filterName = tags.find((tag) => tag.id === filter)?.name
  const view = filterName === undefined
    ? rows : rows.filter((r) => r.tags.includes(filterName))

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['tags', pid] })
    queryClient.invalidateQueries({ queryKey: ['tagged-records', pid] })
    queryClient.invalidateQueries({ queryKey: ['record-tags', pid] })
    setError('')
  }
  const rename = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) =>
      api.put(`${base}/${id}`, { name }),
    onSuccess: refresh,
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Rename failed')),
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.del(`${base}/${id}`),
    onSuccess: () => { setFilter(null); refresh() },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Delete failed')),
  })

  const onRename = (tag: TagInfo) => {
    const name = window.prompt(t('Rename tag “{{name}}” to:', { name: tag.name }), tag.name)
    if (name && name.trim() && name.trim() !== tag.name) {
      rename.mutate({ id: tag.id, name: name.trim() })
    }
  }
  const onDelete = (tag: TagInfo) => {
    if (window.confirm(
      t('Delete the tag “{{name}}”? It is on {{count}} paper(s); the papers themselves are untouched.',
        { name: tag.name, count: tag.n_records }))) {
      remove.mutate(tag.id)
    }
  }

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('Tagged papers')}{project ? ` — ${project.name}` : ''}
      </h1>
      <p className="mt-1 mb-4 max-w-3xl text-sm text-muted-foreground">
        {t('Every paper the team tagged, whatever its screening outcome — tags never change a vote or a PRISMA number. Typical use: shelve excluded papers that still matter for the intro or discussion.')}
      </p>

      <div className="mb-4 flex flex-wrap items-center gap-1.5">
        <FilterPill active={filter === null} onClick={() => setFilter(null)}>
          {t('All ({{count}})', { count: rows.length })}
        </FilterPill>
        {tags.map((tag) => (
          <span key={tag.id} className="inline-flex items-center">
            <FilterPill active={filter === tag.id}
                        onClick={() => setFilter(filter === tag.id ? null : tag.id)}>
              {tag.name} ({tag.n_records})
            </FilterPill>
            <button type="button" title={t('Rename')} onClick={() => onRename(tag)}
                    className="ml-0.5 p-0.5 text-muted-foreground hover:text-foreground">
              <Pencil className="size-3" />
            </button>
            <button type="button" title={t('Delete')} onClick={() => onDelete(tag)}
                    className="p-0.5 text-muted-foreground hover:text-destructive">
              <Trash2 className="size-3" />
            </button>
          </span>
        ))}
        <Button asChild variant="outline" size="sm" className="ml-auto">
          <a href={`${base}/records.csv${filter !== null ? `?tag_id=${filter}` : ''}`}>
            ⬇ CSV
          </a>
        </Button>
      </div>
      {error && <p className="mb-3 text-sm text-destructive">{error}</p>}

      {isLoading ? (
        <p className="text-muted-foreground">{t('Loading…')}</p>
      ) : view.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            {t('No tagged paper yet — add tags from the screening and full-text screening cards (the “+ Tag” chip under the title).')}
          </CardContent>
        </Card>
      ) : (
        <Card className="overflow-hidden py-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="px-4 py-2 font-medium">{t('Paper')}</th>
                <th className="px-4 py-2 font-medium">{t('Tags')}</th>
                <th className="px-4 py-2 font-medium">{t('Screening')}</th>
              </tr>
            </thead>
            <tbody>
              {view.map((r) => (
                <tr key={r.record_id} className="border-b border-border align-top last:border-0">
                  <td className="px-4 py-2.5">
                    <p className="text-foreground">{r.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {r.authors[0] ?? '?'}{r.authors.length > 1 ? ' et al.' : ''}
                      {r.year ? ` · ${r.year}` : ''}
                      {r.journal ? ` · ${r.journal}` : ''}
                      {r.doi && (
                        <>
                          {' · '}
                          <a href={`https://doi.org/${r.doi}`} target="_blank"
                             rel="noreferrer"
                             className="font-mono text-primary hover:underline">
                            {r.doi}
                          </a>
                        </>
                      )}
                    </p>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="flex flex-wrap gap-1">
                      {r.tags.map((t) => (
                        <span key={t}
                              className="rounded-full border border-border bg-muted px-2 py-0.5 text-xs">
                          {t}
                        </span>
                      ))}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-xs">
                    <span className={cn(
                      r.status.startsWith('excluded') ? 'text-destructive'
                        : r.status === 'included' ? 'text-success'
                          : 'text-muted-foreground')}>
                      {r.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}

function FilterPill({ active, onClick, children }: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button type="button" onClick={onClick}
            className={cn('rounded-full border px-2.5 py-1 text-xs transition-colors',
              active
                ? 'border-primary bg-primary text-primary-foreground'
                : 'border-border text-muted-foreground hover:text-foreground')}>
      {children}
    </button>
  )
}
