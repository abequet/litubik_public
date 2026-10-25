// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useRef } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, type Project } from '../api'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import ReviewerSummary from '@/components/ReviewerSummary'
import PrismaDiagram from '@/components/prisma/PrismaDiagram'
import type { PrismaCounts, RoundCounts } from '@/components/prisma/types'
import { useVizPalette } from '@/components/results/palette'
import { copySvgAsPng, svgToPng, svgToSvgFile } from '@/components/results/exportPng'

export default function PrismaPage() {
  const { t } = useTranslation()
  const { projectId } = useParams()
  const pid = Number(projectId)
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'], queryFn: () => api.get('/api/projects'),
  })
  const project = projects.find((p) => p.id === pid)
  const { data: c } = useQuery<PrismaCounts>({
    queryKey: ['prisma', pid],
    queryFn: () => api.get(`/api/projects/${pid}/prisma`),
    refetchOnMount: 'always',
    // counts are computed live server-side; keep the page current while
    // screening/snowballing jobs run elsewhere
    refetchInterval: 15_000,
  })
  const palette = useVizPalette()
  const svgRef = useRef<SVGSVGElement>(null)
  const filename = `prisma-${(project?.name ?? 'review').toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'review'}`

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('PRISMA 2020 flow')}{project ? ` — ${project.name}` : ''}
      </h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {t('Every number is computed live from the pipeline tables — nothing is typed in. Dashed boxes fill in as the next modules (screening, full text) are used. Export the figure as PNG or SVG for the manuscript.')}
      </p>
      {!c ? <p className="text-muted-foreground">{t('Loading…')}</p> : (
        <>
          {c.rounds.length > 1 && !c.final_total_ready && (
            <div className="max-w-3xl mb-4 rounded-lg border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning">
              {t('⏳ A later round is in progress (snowballing iteration or search update) — the totals below are provisional. The final "studies included" tally only stands once every round has finished full-text screening.')}
            </div>
          )}
          <Card className="max-w-6xl p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-foreground">{t('Flow diagram')}</h2>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="sm"
                          className="text-xs text-muted-foreground"
                          title={t('Export the diagram')}>
                    ⤓ {t('Export')}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => {
                    if (svgRef.current) svgToPng(svgRef.current, `${filename}.png`, palette.card, 3)
                  }}>{t('Download PNG')}</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => {
                    if (svgRef.current) svgToSvgFile(svgRef.current, `${filename}.svg`, palette.card)
                  }}>{t('Download SVG')}</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => {
                    if (svgRef.current) copySvgAsPng(svgRef.current, palette.card, 3).catch(() => undefined)
                  }}>{t('Copy image')}</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            <div className="overflow-x-auto">
              <PrismaDiagram counts={c} palette={palette} svgRef={svgRef} />
            </div>
            <DiagramNotes c={c} />
          </Card>
          {c.rounds.length > 1 && <RoundsDetail rounds={c.rounds} />}
          <ReviewerSummary projectId={pid} />
        </>
      )}
    </div>
  )
}

/** Live caveats kept out of the exported figure. */
function DiagramNotes({ c }: { c: PrismaCounts }) {
  const { t } = useTranslation()
  const notes: string[] = []
  if (c.dedup_unresolved)
    notes.push(t('{{count}} record(s) not deduplicated yet — run/finish deduplication', { count: c.dedup_unresolved }))
  if (c.rounds.length > 1)
    notes.push(t('Studies included: sum of the initial search + every snowballing iteration and search update')
      + (c.final_total_ready ? '' : t(' (provisional)')))
  if (c.records_excluded_auto)
    notes.push(t('"By automation tools": titles excluded through the AI title triage, each list validated by a reviewer (PRISMA 2020 item 16a).'))
  if (notes.length === 0) return null
  return (
    <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
      {notes.map((n) => <li key={n}>· {n}</li>)}
    </ul>
  )
}

/** A round is labelled by what created it (living review: an update pass
 * keeps its own column next to the snowballing iterations). */
function roundLabel(t: (k: string, o?: Record<string, unknown>) => string, r: RoundCounts): string {
  if (r.kind === 'initial') return t('Initial search')
  if (r.kind === 'update') return t('Search update {{n}}', { n: r.n ?? r.round })
  if (r.kind === 'snowballing') return t('Snowballing iteration {{n}}', { n: r.n ?? r.round - 1 })
  return r.label
}

/** Per-iteration breakdown: the initial search, each snowballing iteration
 * and each search-update pass keep their own auditable mini-flow; the
 * diagram above shows the union. */
function RoundsDetail({ rounds }: { rounds: RoundCounts[] }) {
  const { t } = useTranslation()
  const fmt = (v: number | null) => (v === null || v === undefined ? '—' : v)
  return (
    <div className="max-w-3xl mt-8">
      <h2 className="text-sm font-semibold text-foreground mb-1">
        {t('Detail per round — initial search, snowballing iterations, search updates')}
      </h2>
      <p className="text-xs text-muted-foreground mb-3">
        {t("Each snowballing iteration and each search-update pass runs its own screening; the diagram above aggregates them. Reading a column top to bottom follows that round's records through the pipeline.")}
      </p>
      <Card className="p-4 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-muted-foreground">
              <td className="py-1 pr-3" aria-hidden />
              {rounds.map((r) => (
                <th key={r.round} className="py-1 pr-3 font-medium">
                  {roundLabel(t, r)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="text-foreground">
            {([
              ['Records identified', (r: RoundCounts) => fmt(r.identified)],
              ['Duplicates removed', (r: RoundCounts) => fmt(r.duplicates_removed)],
              ['Records screened (T/A)', (r: RoundCounts) => fmt(r.records_screened)],
              ['Excluded at title/abstract', (r: RoundCounts) => fmt(r.records_excluded)],
              ['… of which by automation tools (title basis, checked by reviewers)',
               (r: RoundCounts) => fmt(r.records_excluded_auto)],
              ['Reports sought', (r: RoundCounts) => fmt(r.reports_sought)],
              ['Not retrieved', (r: RoundCounts) => fmt(r.reports_not_retrieved)],
              ['Assessed (full text)', (r: RoundCounts) => fmt(r.reports_assessed)],
              ['Excluded (full text)', (r: RoundCounts) => fmt(r.reports_excluded)],
            ] as const).map(([label, get]) => (
              <tr key={label} className="border-t border-border">
                <td className="py-1.5 pr-3 text-muted-foreground">{t(label)}</td>
                {rounds.map((r) => (
                  <td key={r.round} className="py-1.5 pr-3 tabular-nums">{get(r)}</td>
                ))}
              </tr>
            ))}
            <tr className="border-t border-border font-medium text-foreground">
              <td className="py-1.5 pr-3">{t('Studies included')}</td>
              {rounds.map((r) => (
                <td key={r.round} className="py-1.5 pr-3 tabular-nums">
                  {fmt(r.studies_included)}
                </td>
              ))}
            </tr>
            <tr className="text-muted-foreground">
              <td className="py-1 pr-3">{t('Excluded by reason')}</td>
              {rounds.map((r) => (
                <td key={r.round} className="py-1 pr-3">
                  {r.reports_excluded_by_reason.length
                    ? r.reports_excluded_by_reason.map((x) =>
                        `${x.code} (${x.n})`).join(' · ')
                    : '—'}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </Card>
    </div>
  )
}
