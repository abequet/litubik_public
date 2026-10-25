// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { Download, X } from 'lucide-react'
import { api } from '../api'
import { usePdfWindow } from './PdfWindow'
import ReplacePdfButton from './ReplacePdfButton'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Segmented } from '@/components/ui/segmented'

interface FullTextRow {
  record_id: number
  doi: string | null
  title: string
  authors: string[]
  year: number | null
  status: string
  has_file: boolean
  ft_decision: 'include' | 'exclude' | 'pending'
}

// Same colorblind-safe hues as the citation graph (reserved data-viz tokens);
// the label next to the dot spells the decision so colour is never alone.
const DECISION: Record<FullTextRow['ft_decision'], { color: string; label: string }> = {
  include: { color: 'var(--viz-teal)', label: 'included' },
  exclude: { color: 'var(--viz-orange)', label: 'excluded' },
  pending: { color: 'var(--muted-foreground)', label: 'to assess' },
}

/** Persistent right drawer listing every downloaded full text, available from
 * any pipeline step. Colour-coded by the full-text screening outcome, sortable
 * and filterable by it (so "all the included PDFs" is one click plus
 * "Select all"); each entry opens the integrated viewer. */
export default function FulltextLibrary({ projectId, onClose }: {
  projectId: number
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [sort, setSort] = useState<'author' | 'year' | 'decision'>('author')
  const [filter, setFilter] = useState<FullTextRow['ft_decision'] | 'all'>('all')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const openPdf = usePdfWindow()
  const { data: rows = [], isLoading } = useQuery<FullTextRow[]>({
    queryKey: ['fulltext-list', projectId],
    queryFn: () => api.get(`/api/projects/${projectId}/fulltext`),
  })
  const downloaded = rows.filter((r) => r.has_file)
  const visible = filter === 'all' ? downloaded
    : downloaded.filter((r) => r.ft_decision === filter)
  const countBy = (d: FullTextRow['ft_decision']) =>
    downloaded.filter((r) => r.ft_decision === d).length
  const decisionOrder = { include: 0, exclude: 1, pending: 2 }
  const sorted = [...visible].sort((a, b) => {
    if (sort === 'year') return (b.year ?? 0) - (a.year ?? 0)
    if (sort === 'decision') {
      const d = decisionOrder[a.ft_decision] - decisionOrder[b.ft_decision]
      if (d !== 0) return d
    }
    return (a.authors[0] ?? '~').localeCompare(b.authors[0] ?? '~')
  })

  // a stale id (PDF deleted since the box was ticked) must not count nor travel
  const chosen = downloaded.filter((r) => selected.has(r.record_id))
  const allChosen = downloaded.length > 0 && chosen.length === downloaded.length
  // "Select all" acts on what the filter shows: tick the included ones, switch
  // filter, tick the pending ones too — hidden ticks are kept, not discarded
  const allVisibleChosen = visible.length > 0
    && visible.every((r) => selected.has(r.record_id))
  const toggle = (recordId: number) => setSelected((prev) => {
    const next = new Set(prev)
    if (!next.delete(recordId)) next.add(recordId)
    return next
  })
  // "everything" is sent as an empty selection: the whole library in one short
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // URL, however many PDFs it holds
  const zipUrl = `/api/projects/${projectId}/fulltext/download-zip`
    + (allChosen ? '' : `?ids=${chosen.map((r) => r.record_id).join(',')}`)

  return (
    <>
      <div className="fixed inset-0 z-40">
        {/* the backdrop is a real button: click, Enter or Escape close the panel */}
        <button type="button" onClick={onClose} aria-label={t('Close')}
                className="absolute inset-0 cursor-default bg-black/50 backdrop-blur-[2px]" />
        <aside role="dialog" aria-modal="true" aria-labelledby="fulltext-library-title"
               className="absolute right-0 top-0 h-full w-96 max-w-full bg-popover shadow-2xl border-l border-border flex flex-col">
          <div className="flex items-center justify-between px-4 py-3 border-b border-border">
            <h2 id="fulltext-library-title" className="text-sm font-semibold text-foreground">
              {t('Downloaded full texts ({{count}})', { count: downloaded.length })}
            </h2>
            <Button variant="ghost" size="icon" className="size-7" onClick={onClose}>
              <X className="size-4" />
              <span className="sr-only">{t('Close')}</span>
            </Button>
          </div>
          <div className="flex items-center gap-2 px-4 py-2 border-b border-border">
            <span className="text-xs text-muted-foreground">{t('Sort by')}</span>
            <Segmented
              size="sm"
              value={sort}
              onChange={setSort}
              options={[
                { value: 'author', label: t('author') },
                { value: 'year', label: t('year') },
                { value: 'decision', label: t('decision') },
              ]}
            />
          </div>
          {downloaded.length > 0 && (
            <div className="flex items-center gap-2 px-4 py-2 border-b border-border">
              <Checkbox id="ft-lib-all" checked={allVisibleChosen}
                        disabled={visible.length === 0}
                        onCheckedChange={() => setSelected((prev) => {
                          const next = new Set(prev)
                          for (const r of visible) {
                            if (allVisibleChosen) next.delete(r.record_id)
                            else next.add(r.record_id)
                          }
                          return next
                        })} />
              <label htmlFor="ft-lib-all"
                     className="text-xs text-muted-foreground cursor-pointer">
                {filter === 'all' ? t('Select all') : t('Select all shown')}
              </label>
              <span className="ml-auto text-xs text-muted-foreground">
                {t('{{n}} of {{total}} selected',
                   { n: chosen.length, total: downloaded.length })}
              </span>
            </div>
          )}
          {/* the legend doubles as the filter: one chip per decision, with
              its count, pressed = only those entries are listed */}
          <div className="flex flex-wrap items-center gap-1 px-4 py-1.5 border-b border-border text-xs"
               role="group" aria-label={t('Filter by decision')}>
            <span className="text-muted-foreground mr-1">{t('Show')}</span>
            {(['all', ...Object.keys(DECISION)] as (FullTextRow['ft_decision'] | 'all')[]).map((d) => {
              const active = filter === d
              return (
                <button key={d} type="button" aria-pressed={active}
                        onClick={() => setFilter(d)}
                        className={'flex items-center gap-1 rounded-full border px-2 py-0.5 cursor-pointer '
                          + (active ? 'border-foreground/40 bg-accent text-foreground'
                                    : 'border-transparent text-muted-foreground hover:bg-accent')}>
                  {d !== 'all' && (
                    <span className="inline-block h-2 w-2 rounded-full"
                          style={{ background: DECISION[d].color }} />
                  )}
                  {d === 'all' ? t('All') : t(DECISION[d].label)}
                  <span className="tabular-nums opacity-70">
                    {d === 'all' ? downloaded.length : countBy(d)}
                  </span>
                </button>
              )
            })}
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {isLoading && <p className="text-xs text-muted-foreground p-2">{t('Loading…')}</p>}
            {!isLoading && downloaded.length === 0 && (
              <p className="text-xs text-muted-foreground p-2">
                {t('No full text downloaded yet — retrieve them on the FT retrieval step.')}
              </p>
            )}
            {!isLoading && downloaded.length > 0 && visible.length === 0 && (
              <p className="text-xs text-muted-foreground p-2">
                {t('No downloaded full text with this decision.')}
              </p>
            )}
            <ul className="space-y-1">
              {sorted.map((r) => (
                <li key={r.record_id}
                    className="flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-accent border border-transparent hover:border-border">
                  <Checkbox className="mt-0.5 shrink-0"
                            checked={selected.has(r.record_id)}
                            onCheckedChange={() => toggle(r.record_id)}
                            aria-label={t('Select “{{title}}”', { title: r.title })} />
                  <button onClick={() => openPdf({ projectId,
                            recordId: r.record_id, title: r.title })}
                          className="min-w-0 flex-1 text-left cursor-pointer">
                    <p className="text-xs text-foreground leading-snug flex items-start gap-1.5">
                      <span className="mt-1 inline-block h-2 w-2 shrink-0 rounded-full"
                            title={t(DECISION[r.ft_decision].label)}
                            style={{ background: DECISION[r.ft_decision].color }} />
                      <span>{r.title}</span>
                    </p>
                    <p className="text-xs text-muted-foreground pl-3.5">
                      {(r.authors[0] ?? '?')}{r.authors.length > 1 ? ' et al.' : ''}
                      {r.year ? ` · ${r.year}` : ''}
                      {' · '}{t(DECISION[r.ft_decision].label)}
                      {r.status === 'manual' ? ` · ${t('uploaded')}` : ''}
                    </p>
                  </button>
                  {/* wrong or truncated file spotted from the library: swap
                      it here, no detour through the retrieval page */}
                  <span className="mt-0.5 shrink-0">
                    <ReplacePdfButton projectId={projectId} recordId={r.record_id} />
                  </span>
                </li>
              ))}
            </ul>
          </div>
          {downloaded.length > 0 && (
            <div className="border-t border-border px-4 py-3 space-y-1.5">
              {chosen.length === 0 ? (
                <Button size="sm" className="w-full" disabled>
                  <Download className="size-4" /> {t('Download selection')}
                </Button>
              ) : (
                <Button size="sm" className="w-full" asChild>
                  <a href={zipUrl} download>
                    <Download className="size-4" />
                    {t('Download selection ({{n}})', { n: chosen.length })}
                  </a>
                </Button>
              )}
              <p className="text-xs text-muted-foreground">
                {t('A zip of the PDFs, each named author_year_first-five-title-words.pdf.')}
              </p>
            </div>
          )}
        </aside>
      </div>
    </>
  )
}
