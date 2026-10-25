// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '../../i18n'
import { CHART_FONT, type VizPalette } from '../results/palette'
import type { ColumnFlow, PrismaCounts } from './types'

/** PRISMA 2020 flow diagram as one inline SVG, laid out here from the live
 * counts: the three stage bands on the left (Identification / Screening /
 * Included), a main column per identification route with its exclusion
 * boxes to the right, vertical arrows down the main column and horizontal
 * arrows into every exclusion box, and the single "included" box both routes
 * merge into. Every colour is a concrete value from the live palette (no CSS
 * classes, no var()), so exportPng.ts can serialise the node as is.
 *
 * Boxes whose stage has not been reached yet are drawn dashed with "n = —".
 * Live warnings (unfinished deduplication, provisional totals) belong to the
 * page, not to the figure, so an export stays clean. */

const FONT_SIZE = 11
const LINE = 14
const PAD = 8
const BOX_W = 226
const H_GAP = 44           // room for the horizontal arrow
const V_GAP = 30           // room for the vertical arrow
const BAND_W = 30
const BAND_GAP = 14
const HEADER_H = 26
const HEADER_GAP = 12
const COL_GAP = 48         // between the two identification routes
const MARGIN = 8
const CHAR_W = FONT_SIZE * 0.55

interface BoxSpec {
  title: string
  n: number | null | undefined
  lines?: string[]
}

interface Placed extends BoxSpec {
  x: number
  y: number
  w: number
  h: number
  titleLines: string[]
  bodyLines: string[]
  pending: boolean
}

/** Keep every "(n = 12)" group on one line: non-breaking spaces inside it,
 * and the wrapper only breaks on plain spaces. */
const glueN = (text: string) => text.replace(/\(n = ([^)]*)\)/g, '(n\u00a0=\u00a0$1)')

function wrap(text: string, maxChars: number): string[] {
  const words = glueN(text).split(/ +/).filter(Boolean)
  const lines: string[] = []
  let cur = ''
  for (const w of words) {
    const next = cur ? `${cur} ${w}` : w
    if (next.length > maxChars && cur) {
      lines.push(cur)
      cur = w
    } else {
      cur = next
    }
  }
  if (cur) lines.push(cur)
  return lines.length ? lines : ['']
}

function measure(spec: BoxSpec, w: number): Omit<Placed, 'x' | 'y'> {
  const maxChars = Math.floor((w - 2 * PAD) / CHAR_W)
  const pending = spec.n === null || spec.n === undefined
  const titleLines = wrap(`${spec.title} (n = ${pending ? '—' : spec.n})`, maxChars)
  const bodyLines = (spec.lines ?? []).flatMap((l) => wrap(l, maxChars))
  const h = 2 * PAD + (titleLines.length + bodyLines.length) * LINE
  return { ...spec, w, h, titleLines, bodyLines, pending }
}

/** PRISMA 2020 wording for validated AI title exclusions — only when
 * automation excluded anything. */
export const excludedTaLines = (total: number | null, auto: number | null) =>
  auto && total !== null
    ? [i18n.t('by the reviewers (n = {{n}})', { n: total - auto }),
       i18n.t('by automation tools on the title basis (manually checked by the reviewers) (n = {{n}})', { n: auto })]
    : undefined

const SOURCE_TYPE_LABEL: Record<string, string> = {
  snowballing: 'citation searching',
  manual: 'manual addition',
}
const sourceTypeLabel = (type: string) =>
  SOURCE_TYPE_LABEL[type] ? i18n.t(SOURCE_TYPE_LABEL[type]) : ''

interface Route {
  header: string | null
  identified: BoxSpec
  duplicates: BoxSpec
  screened: BoxSpec
  excluded: BoxSpec
  sought: BoxSpec
  notRetrieved: BoxSpec
  assessed: BoxSpec
  excludedFt: BoxSpec
}

function routeSpecs(t: (k: string, o?: Record<string, unknown>) => string,
                    flow: ColumnFlow, kind: 'databases' | 'other',
                    header: string | null): Route {
  const sourceLines = (flow.sources ?? []).map((s) =>
    `${s.source}${kind === 'other' && sourceTypeLabel(s.type)
      ? ` — ${sourceTypeLabel(s.type)}` : ''} (n = ${s.n})`)
  return {
    header,
    identified: {
      title: kind === 'databases'
        ? t('Records identified from databases')
        : t('Records identified from other methods'),
      n: flow.identified,
      lines: sourceLines.length ? sourceLines
        : kind === 'databases' ? [t('no database search yet')] : [],
    },
    duplicates: { title: t('Records removed before screening: duplicates'),
                  n: flow.duplicates_removed },
    screened: { title: t('Records screened'), n: flow.records_screened },
    excluded: { title: t('Records excluded (title/abstract)'), n: flow.records_excluded,
                lines: excludedTaLines(flow.records_excluded, flow.records_excluded_auto) },
    sought: { title: t('Reports sought for retrieval'), n: flow.reports_sought },
    notRetrieved: { title: t('Reports not retrieved'), n: flow.reports_not_retrieved },
    assessed: { title: t('Reports assessed for eligibility'), n: flow.reports_assessed },
    excludedFt: { title: t('Reports excluded, by reason'), n: flow.reports_excluded,
                  lines: (flow.reports_excluded_by_reason || []).map(
                    (r) => `${r.code} ${r.label} (n = ${r.n})`) },
  }
}

interface Layout {
  width: number
  height: number
  boxes: Placed[]
  headers: { x: number; w: number; label: string }[]
  bands: { y: number; h: number; label: string }[]
  vArrows: { x: number; y1: number; y2: number }[]
  hArrows: { x1: number; x2: number; y: number }[]
  mergePath: string | null
}

const ROW_KEYS = [
  ['identified', 'duplicates'],
  ['screened', 'excluded'],
  ['sought', 'notRetrieved'],
  ['assessed', 'excludedFt'],
] as const

function layout(t: (k: string, o?: Record<string, unknown>) => string,
                routes: Route[], included: BoxSpec): Layout {
  const dual = routes.length > 1
  const x0 = MARGIN + BAND_W + BAND_GAP
  const routeW = BOX_W * 2 + H_GAP
  const routeX = routes.map((_, i) => x0 + i * (routeW + COL_GAP))
  const width = x0 + routes.length * routeW + (routes.length - 1) * COL_GAP + MARGIN

  let y = MARGIN + (dual ? HEADER_H + HEADER_GAP : 0)
  const boxes: Placed[] = []
  const vArrows: Layout['vArrows'] = []
  const hArrows: Layout['hArrows'] = []
  const bands: Layout['bands'] = []
  const rowTops: number[] = []
  const rowBottoms: number[] = []
  // main column boxes per route, in row order (to draw the vertical arrows)
  const mains: Placed[][] = routes.map(() => [])

  for (const [mainKey, exclKey] of ROW_KEYS) {
    const measured = routes.map((r) => [measure(r[mainKey], BOX_W),
                                        measure(r[exclKey], BOX_W)] as const)
    const rowH = Math.max(...measured.flatMap(([m, e]) => [m.h, e.h]))
    rowTops.push(y)
    measured.forEach(([m, e], i) => {
      const main: Placed = { ...m, x: routeX[i], y }
      const excl: Placed = { ...e, x: routeX[i] + BOX_W + H_GAP, y }
      boxes.push(main, excl)
      mains[i].push(main)
      hArrows.push({ x1: main.x + main.w, x2: excl.x, y: y + PAD + LINE / 2 })
    })
    y += rowH
    rowBottoms.push(y)
    y += V_GAP
  }

  // included: under the first route's main column; the second route merges in
  const inc = measure(included, BOX_W)
  const incBox: Placed = { ...inc, x: routeX[0], y }
  boxes.push(incBox)
  rowTops.push(y)
  y += inc.h
  rowBottoms.push(y)
  const height = y + MARGIN

  mains.forEach((col, i) => {
    col.forEach((b, r) => {
      const next = r + 1 < col.length ? col[r + 1] : (i === 0 ? incBox : null)
      if (next) vArrows.push({ x: b.x + b.w / 2, y1: b.y + b.h, y2: next.y })
    })
  })
  let mergePath: string | null = null
  if (dual) {
    const last = mains[1][mains[1].length - 1]
    const sx = last.x + last.w / 2
    const my = incBox.y + incBox.h / 2
    mergePath = `M ${sx} ${last.y + last.h} V ${my} H ${incBox.x + incBox.w}`
  }

  const bandSpan = (from: number, to: number, label: string) => ({
    y: rowTops[from], h: rowBottoms[to] - rowTops[from], label,
  })
  bands.push(bandSpan(0, 0, t('Identification')),
             bandSpan(1, 3, t('Screening')),
             bandSpan(4, 4, t('Included')))

  const headers = dual
    ? routes.map((r, i) => ({ x: routeX[i], w: routeW, label: r.header ?? '' }))
    : []
  return { width, height, boxes, headers, bands, vArrows, hArrows, mergePath }
}

export default function PrismaDiagram({ counts, palette, svgRef }: {
  counts: PrismaCounts
  palette: VizPalette
  svgRef?: React.Ref<SVGSVGElement>
}) {
  const { t } = useTranslation()
  const lay = useMemo(() => {
    const dual = !!counts.via_other && counts.via_other.identified > 0
    // the per-database breakdown lives in identified_databases, not in the flow
    const dbFlow: ColumnFlow = {
      ...counts.via_databases,
      sources: counts.identified_databases.map((d) => ({ ...d, type: 'database' })),
    }
    const routes: Route[] = [
      routeSpecs(t, dbFlow, 'databases',
                 dual ? t('Identification of studies via databases and registers') : null),
    ]
    if (dual) {
      routes.push(routeSpecs(t, counts.via_other, 'other',
                             t('Identification of studies via other methods')))
    }
    const includedLines: string[] = []
    if (counts.reports_included !== null && counts.reports_included !== undefined)
      includedLines.push(t('Reports of included studies (n = {{n}})', { n: counts.reports_included }))
    if (dual)
      includedLines.push(t('via databases (n = {{db}}) · via other methods (n = {{other}})',
                           { db: counts.via_databases.studies_included ?? '—',
                             other: counts.via_other.studies_included ?? '—' }))
    return layout(t, routes, { title: t('Studies included in the review'),
                               n: counts.studies_included, lines: includedLines })
  }, [counts, t])

  const stroke = palette.foreground
  return (
    <svg ref={svgRef} viewBox={`0 0 ${lay.width} ${lay.height}`}
         width="100%" style={{ maxWidth: lay.width, height: 'auto', display: 'block' }}
         role="img" aria-label={t('PRISMA 2020 flow diagram')}
         fontFamily={CHART_FONT} fontSize={FONT_SIZE}>
      <title>{t('PRISMA 2020 flow diagram')}</title>
      <defs>
        <marker id="prisma-arrow" viewBox="0 0 10 10" refX="9" refY="5"
                markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill={stroke} />
        </marker>
      </defs>

      {lay.headers.map((h) => (
        <g key={h.label}>
          <rect x={h.x} y={MARGIN} width={h.w} height={HEADER_H} rx={3}
                fill={palette.muted} stroke="none" />
          <text x={h.x + h.w / 2} y={MARGIN + HEADER_H / 2} textAnchor="middle"
                dominantBaseline="central" fontWeight={600} fill={palette.foreground}>
            {h.label}
          </text>
        </g>
      ))}

      {lay.bands.map((b) => (
        <g key={b.label}>
          <rect x={MARGIN} y={b.y} width={BAND_W} height={b.h} rx={3} fill={palette.blue} />
          <text transform={`translate(${MARGIN + BAND_W / 2} ${b.y + b.h / 2}) rotate(-90)`}
                textAnchor="middle" dominantBaseline="central" fontWeight={600}
                fill="#ffffff" letterSpacing={0.4}>
            {b.label}
          </text>
        </g>
      ))}

      {lay.vArrows.map((a, i) => (
        <line key={`v${i}`} x1={a.x} y1={a.y1} x2={a.x} y2={a.y2}
              stroke={stroke} strokeWidth={1.2} markerEnd="url(#prisma-arrow)" />
      ))}
      {lay.hArrows.map((a, i) => (
        <line key={`h${i}`} x1={a.x1} y1={a.y} x2={a.x2} y2={a.y}
              stroke={stroke} strokeWidth={1.2} markerEnd="url(#prisma-arrow)" />
      ))}
      {lay.mergePath && (
        <path d={lay.mergePath} fill="none" stroke={stroke} strokeWidth={1.2}
              markerEnd="url(#prisma-arrow)" />
      )}

      {lay.boxes.map((b, i) => (
        <g key={i}>
          <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={3}
                fill={b.pending ? palette.muted : palette.card}
                stroke={b.pending ? palette.mutedForeground : stroke}
                strokeWidth={1} strokeDasharray={b.pending ? '4 3' : undefined} />
          <text x={b.x + PAD} y={b.y + PAD + LINE / 2} dominantBaseline="central"
                fill={b.pending ? palette.mutedForeground : palette.foreground}>
            {b.titleLines.map((line, j) => (
              <tspan key={`t${j}`} x={b.x + PAD} dy={j === 0 ? 0 : LINE} fontWeight={600}>
                {line}
              </tspan>
            ))}
            {b.bodyLines.map((line, j) => (
              <tspan key={`b${j}`} x={b.x + PAD} dy={LINE}>{line}</tspan>
            ))}
          </text>
        </g>
      ))}
    </svg>
  )
}
