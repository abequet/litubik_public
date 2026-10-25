// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, type Project } from '../api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Segmented } from '@/components/ui/segmented'

interface NoteRow {
  record_id: number
  stage: 'ta' | 'ft'
  round: number
  kind: 'vote' | 'resolution'
  author: string
  decision: string
  note: string
  at: string
  title: string
  authors: string[]
  year: number | null
}

/** T15: every note written during the screenings, in one read-only list —
 * vote justifications and conflict-resolution notes, T/A and full text. */
export default function NotesPage() {
  const { t } = useTranslation()
  const { projectId } = useParams()
  const pid = Number(projectId)
  const [stage, setStage] = useState<'all' | 'ta' | 'ft'>('all')

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'], queryFn: () => api.get('/api/projects'),
  })
  const project = projects.find((p) => p.id === pid)
  const { data: rows = [], isLoading } = useQuery<NoteRow[]>({
    queryKey: ['notes', pid],
    queryFn: () => api.get(`/api/projects/${pid}/notes`),
  })
  const view = stage === 'all' ? rows : rows.filter((r) => r.stage === stage)

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('Screening notes')}{project ? ` — ${project.name}` : ''}
      </h1>
      <p className="mt-1 mb-4 max-w-3xl text-sm text-muted-foreground">
        {t('Every note left on an article during the title/abstract and full-text screenings — vote justifications and conflict-resolution notes. Read-only; write notes from the screening screens.')}
      </p>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Segmented value={stage} onChange={setStage}
                    options={[
                      { value: 'all', label: t('All ({{count}})', { count: rows.length }) },
                      { value: 'ta', label: t('Title/abstract') },
                      { value: 'ft', label: t('Full text') },
                    ]} />
        <Button asChild variant="outline" size="sm" className="ml-auto">
          <a href={`/api/projects/${pid}/notes/export.csv`}>⬇ CSV</a>
        </Button>
      </div>

      {isLoading ? (
        <p className="text-muted-foreground">{t('Loading…')}</p>
      ) : view.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            {t('No note yet — justifications typed with a vote and conflict resolution notes will show up here.')}
          </CardContent>
        </Card>
      ) : (
        <Card className="overflow-hidden overflow-x-auto py-0">
          <table className="w-full min-w-[40rem] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="px-4 py-2 font-medium">{t('Article')}</th>
                <th className="px-4 py-2 font-medium">{t('Stage')}</th>
                <th className="px-4 py-2 font-medium">{t('Note')}</th>
                <th className="px-4 py-2 font-medium">{t('Author')}</th>
              </tr>
            </thead>
            <tbody>
              {view.map((r, i) => (
                <tr key={i} className="border-b border-border align-top last:border-0">
                  <td className="max-w-80 px-4 py-2.5">
                    <p className="text-xs leading-snug text-foreground">{r.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {r.authors[0] ?? '?'}{r.authors.length > 1 ? ' et al.' : ''}
                      {r.year ? ` · ${r.year}` : ''}
                    </p>
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-xs text-muted-foreground">
                    {r.stage === 'ta' ? t('T/A') : t('Full text')} · r{r.round}
                    <br />
                    <span className={cn('font-medium',
                      r.decision === 'include' ? 'text-success'
                        : r.decision === 'exclude' ? 'text-destructive'
                          : 'text-warning')}>
                      {t(r.decision)}
                    </span>
                    {r.kind === 'resolution' && (
                      <span className="text-muted-foreground/70"> {t('(resolution)')}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-foreground/90">{r.note}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-xs text-muted-foreground">
                    {r.author}
                    {r.at && (
                      <>
                        <br />
                        <span className="text-muted-foreground/70">
                          {new Date(r.at).toLocaleDateString()}
                        </span>
                      </>
                    )}
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
