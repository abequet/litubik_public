// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { CHART_FONT } from '../results/palette'
import { lineage, notRetainedOfRound } from './graphModel'
import { genealogyLayout, PILL_H } from './genealogyLayout'
import { HoverCard, NodeTooltipBody, StatusDot } from './GraphOverlays'
import { STATUS_LABEL, statusColor } from './status'
import { measureText } from './svgText'
import type { ViewProps } from './viewProps'

const LEGEND_ROW = 18
const PAGE = 200

/** "Iterations" view: the provenance of every retained paper. One column per
 * round, retained papers only, a curve from the seed whose crawl found each
 * one; a seed's bar sums up what its crawl brought (backward / forward), and
 * each column ends with its yield and the count of what was not retained —
 * which also reads as the saturation of the snowballing. */
export default function GenealogyView({ model, palette, height, isFs, selectedId, focus,
                                        onSelect, onClearSelection, onOpenCard }: ViewProps) {
  const { t, i18n } = useTranslation()
  const nf = useMemo(() => new Intl.NumberFormat(i18n.language), [i18n.language])
  const pf = useMemo(() => new Intl.NumberFormat(i18n.language,
    { minimumFractionDigits: 1, maximumFractionDigits: 1 }), [i18n.language])

  const columnTitle = (r: number) => (r === 1 ? t('Initial corpus') : t('Iteration r{{round}}', { round: r }))
  const columnSub = (r: number) => {
    const s = model.roundStats.get(r)!
    return r === 1 ? t('Retained: {{count}}', { count: s.retained })
      : t('{{candidates}} candidates → {{retained}} retained',
          { candidates: nf.format(s.candidates), retained: s.retained })
  }
  const layout = useMemo(() => {
    const headerW = new Map(model.rounds.map((r) => [r, Math.max(
      measureText(columnTitle(r), 13, 600), measureText(columnSub(r), 11.5)) + 28]))
    return genealogyLayout(model, { measure: (s) => measureText(s, 12, 500),
                                    minColW: (r) => headerW.get(r) ?? 0 })
  }, [model, i18n.language])  // eslint-disable-line

  const [hover, setHover] = useState<{ key: string; x: number; y: number } | null>(null)
  const [panelRound, setPanelRound] = useState<number | null>(null)
  const [limit, setLimit] = useState(PAGE)
  const svgRef = useRef<SVGSVGElement>(null)
  const down = useRef<{ key: string | null; x: number; y: number } | null>(null)

  const lit = useMemo(() => {
    const k = hover?.key
    if (k && k[0] === 'n') return lineage(model, Number(k.slice(1)))
    if (selectedId !== null && model.parents.has(selectedId)) return lineage(model, selectedId)
    return null
  }, [hover, selectedId, model])

  // a search pick lands here: select the pill (the shell opens its popover)
  useEffect(() => {
    if (!focus) return
    const el = svgRef.current?.querySelector(`[data-k="n${focus.id}"]`)
    if (!el) return
    el.scrollIntoView({ block: 'nearest', inline: 'nearest' })
    const r = el.getBoundingClientRect()
    onSelect(focus.id, r.right, r.top + r.height / 2)
  }, [focus])  // eslint-disable-line

  const keyOf = (e: React.PointerEvent) =>
    (e.target as Element).closest?.('[data-k]')?.getAttribute('data-k') ?? null
  const openPanel = (r: number) => {
    setPanelRound((p) => (p === r ? null : r))
    setLimit(PAGE)
  }
  const onPointerUp = (e: React.PointerEvent) => {
    const d = down.current
    down.current = null
    if (!d || Math.hypot(e.clientX - d.x, e.clientY - d.y) > 4) return
    const k = keyOf(e)
    if (k !== d.key) return
    if (!k) onClearSelection()
    else if (k[0] === 'n') onSelect(Number(k.slice(1)), e.clientX, e.clientY)
    else if (k[0] === 'f') openPanel(Number(k.slice(1)))
  }

  const W = layout.width
  const roundsWithRest = model.rounds.filter((r) => {
    const s = model.roundStats.get(r)!
    return r > 1 && s.candidates > s.retained
  })
  const panelList = useMemo(() => (panelRound === null ? [] : notRetainedOfRound(model, panelRound)),
    [model, panelRound])

  // legend drawn inside the SVG so the exported figure carries it
  const legendItems: { key: string; label: string; mark: React.ReactNode }[] = [
    { key: 'seed', label: t(STATUS_LABEL.seed),
      mark: <circle cx={5} cy={0} r={4.5} fill={palette.blue} /> },
    { key: 'included', label: t('included'),
      mark: <circle cx={5} cy={0} r={4.5} fill={palette.teal} /> },
    { key: 'back', label: t('backward (refs, solid)'),
      mark: <line x1={0} x2={16} y1={0} y2={0} stroke={palette.mutedForeground} strokeWidth={1.6} /> },
    { key: 'fwd', label: t('forward (citing, dashed)'),
      mark: <line x1={0} x2={16} y1={0} y2={0} stroke={palette.blue} strokeWidth={1.6} strokeDasharray="5 3" /> },
  ]
  // only what is drawn, wrapped to the figure width (a two-round view is narrow)
  const drawn = new Set<string>(layout.pills.map((p) => model.byId.get(p.id)!.status))
  for (const c of layout.curves) {
    if (c.dir !== 'forward') drawn.add('back')
    if (c.dir !== 'backward') drawn.add('fwd')
  }
  let lx = 10
  let ly = 0
  const legend = legendItems.filter((it) => drawn.has(it.key)).map((it) => {
    const markW = it.key === 'back' || it.key === 'fwd' ? 22 : 14
    const w = markW + measureText(it.label, 11) + 18
    if (lx + w > W - 4 && lx > 10) { lx = 10; ly += LEGEND_ROW }
    const pos = { ...it, x: lx, y: ly, w: markW }
    lx += w
    return pos
  })
  const H = layout.height + 22 + ly + 8

  const hoverCard = (() => {
    if (!hover || selectedId !== null) return null
    if (hover.key[0] === 'n') {
      const n = model.byId.get(Number(hover.key.slice(1)))
      return n ? <HoverCard x={hover.x} y={hover.y}><NodeTooltipBody node={n} model={model} /></HoverCard> : null
    }
    const s = model.roundStats.get(Number(hover.key.slice(1)))
    if (!s) return null
    return (
      <HoverCard x={hover.x} y={hover.y}>
        <p className="font-medium text-foreground">
          {t('Not retained: {{count}}', { count: nf.format(s.candidates - s.retained) })}
        </p>
        <p className="text-muted-foreground">
          {t('excluded {{excluded}} · to screen {{pending}}',
             { excluded: nf.format(s.excluded), pending: nf.format(s.pending) })}
        </p>
        <p className="text-muted-foreground">{t('Click to list them')}</p>
      </HoverCard>
    )
  })()

  return (
    <div className={isFs ? 'flex min-h-0 flex-1 flex-col' : undefined}>
      <div className={isFs ? 'min-h-0 flex-1 overflow-auto rounded-lg border border-border bg-card'
                           : 'overflow-auto rounded-lg border border-border bg-card'}
           style={isFs ? undefined : { maxHeight: height }}>
        <svg ref={svgRef} data-export width={W} height={H} viewBox={`0 0 ${W} ${H}`}
             role="img" fontFamily={CHART_FONT} className="block"
             aria-label={t('Snowballing genealogy: {{count}} retained papers over {{rounds}} rounds — use the Data button for a table',
                           { count: model.retained.length, rounds: model.rounds.length })}
             onPointerDown={(e) => { down.current = { key: keyOf(e), x: e.clientX, y: e.clientY } }}
             onPointerMove={(e) => {
               const k = keyOf(e)
               setHover(k ? { key: k, x: e.clientX, y: e.clientY } : null)
             }}
             onPointerUp={onPointerUp}
             onPointerLeave={() => setHover(null)}>
          {layout.columns.map((c, i) => {
            const s = c.stats
            const r = c.round
            const rest = s.candidates - s.retained
            const fy = layout.footerTop
            const bw = c.w - 44
            const we = rest ? (bw * s.excluded) / rest : 0
            return (
              <g key={r}>
                {i > 0 && <line x1={c.x - 6} x2={c.x - 6} y1={8} y2={fy + 44}
                                stroke={palette.border} />}
                <text x={c.x} y={22} fontSize={13} fontWeight={600} fill={palette.foreground}>
                  {columnTitle(r)}
                </text>
                <text x={c.x} y={40} fontSize={11.5} fill={palette.mutedForeground}>{columnSub(r)}</text>
                {r > 1 && s.candidates > 0 && (
                  <text x={c.x} y={55} fontSize={10.5} fill={palette.mutedForeground}>
                    {t('yield {{pct}} %', { pct: pf.format((100 * s.retained) / s.candidates) })}
                  </text>
                )}
                {s.retained === 0 && (
                  <text x={c.x} y={layout.bodyTop + 16} fontSize={12} fontStyle="italic"
                        fill={palette.mutedForeground}>{t('No paper retained')}</text>
                )}
                {r > 1 && rest > 0 && (
                  <g data-k={`f${r}`} style={{ cursor: 'pointer' }}>
                    <rect x={c.x - 4} y={fy - 4} width={c.w - 28} height={48} rx={6}
                          fill={panelRound === r ? palette.muted : palette.card} />
                    <text x={c.x} y={fy + 10} fontSize={11.5} fontWeight={500} fill={palette.foreground}>
                      {t('Not retained: {{count}}', { count: nf.format(rest) })}
                    </text>
                    {s.excluded > 0 && (
                      <rect x={c.x} y={fy + 17} height={7} rx={2} fill={palette.orange} fillOpacity={0.8}
                            width={Math.max(1.5, we - (s.pending ? 1 : 0))} />
                    )}
                    {s.pending > 0 && (
                      <rect x={c.x + we + (s.excluded ? 1 : 0)} y={fy + 17} height={7} rx={2}
                            fill={palette.mutedForeground}
                            width={Math.max(2, bw - we - (s.excluded ? 1 : 0))} />
                    )}
                    <text x={c.x} y={fy + 37} fontSize={11} fill={palette.mutedForeground}>
                      {t('excluded {{excluded}} · to screen {{pending}}',
                         { excluded: nf.format(s.excluded), pending: nf.format(s.pending) })}
                    </text>
                  </g>
                )}
              </g>
            )
          })}
          <g fill="none">
            {layout.curves.map((cv) => {
              const on = !lit || (lit.has(cv.from) && lit.has(cv.to))
              return (
                <path key={`${cv.from}-${cv.to}`} d={cv.d} strokeLinecap="round"
                      stroke={cv.dir === 'forward' ? palette.blue : palette.mutedForeground}
                      strokeWidth={lit && on ? 2 : 1.4}
                      strokeDasharray={cv.dir === 'forward' ? '5 3' : undefined}
                      opacity={on ? 0.85 : 0.08} />
              )
            })}
          </g>
          {layout.pills.map((p) => {
            const n = model.byId.get(p.id)!
            const c = statusColor(palette, n.status)
            const on = !lit || lit.has(p.id)
            return (
              <g key={p.id} data-k={`n${p.id}`} transform={`translate(${p.x},${p.y})`}
                 opacity={on ? 1 : 0.2} style={{ cursor: 'pointer' }}>
                <rect width={p.w} height={PILL_H} rx={PILL_H / 2} fill={palette.card} />
                <rect width={p.w} height={PILL_H} rx={PILL_H / 2} fill={c} fillOpacity={0.1}
                      stroke={c} strokeWidth={1.5} />
                {selectedId === p.id && (
                  <rect x={-3.5} y={-3.5} width={p.w + 7} height={PILL_H + 7} rx={PILL_H / 2 + 3.5}
                        fill="none" stroke={palette.foreground} strokeWidth={1.2} strokeDasharray="3 2" />
                )}
                <circle cx={12} cy={PILL_H / 2} r={4.5} fill={c} />
                <text x={22} y={16.5} fontSize={12} fontWeight={500} fill={palette.foreground}>
                  {p.label}
                </text>
                {p.bar && (
                  <g transform={`translate(${p.bar.x - p.x},0)`}>
                    {p.bar.nb > 0 && (
                      <rect x={0} y={4} height={7} rx={2} fill={palette.mutedForeground} fillOpacity={0.45}
                            width={Math.max(1.5, p.bar.wb - (p.bar.nf ? 1 : 0))} />
                    )}
                    {p.bar.nf > 0 && (
                      <rect x={p.bar.wb + (p.bar.nb ? 1 : 0)} y={4} height={7} rx={2}
                            fill={palette.blue} fillOpacity={0.6}
                            width={Math.max(1.5, p.bar.w - p.bar.wb - (p.bar.nb ? 1 : 0))} />
                    )}
                    <text x={0} y={22} fontSize={9.5} fill={palette.mutedForeground}
                          stroke={palette.card} strokeWidth={3} strokeLinejoin="round"
                          paintOrder="stroke">
                      {`◀${p.bar.nb}  ▶${p.bar.nf}`}
                    </text>
                  </g>
                )}
              </g>
            )
          })}
          <g transform={`translate(0,${layout.height + 14})`}>
            {legend.map((it) => (
              <g key={it.key} transform={`translate(${it.x},${it.y})`}>
                {it.mark}
                <text x={it.w} y={4} fontSize={11} fill={palette.mutedForeground}>{it.label}</text>
              </g>
            ))}
          </g>
        </svg>
      </div>

      {roundsWithRest.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          <span>{t('Papers not retained, per round:')}</span>
          {roundsWithRest.map((r) => {
            const s = model.roundStats.get(r)!
            return (
              <Button key={r} size="sm" variant={panelRound === r ? 'default' : 'outline'}
                      className="h-6 px-2 text-xs" aria-pressed={panelRound === r}
                      onClick={() => openPanel(r)}>
                r{r} · {nf.format(s.candidates - s.retained)}
              </Button>
            )
          })}
          <span className="ml-auto">{t('· hover = lineage · click = details')}</span>
        </div>
      )}
      {panelRound !== null && (
        <div className="mt-2 rounded-md border border-border bg-card">
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-1.5 text-xs">
            <span className="font-medium text-foreground">
              {t('Not retained in r{{round}} ({{count}}), most-linked first',
                 { round: panelRound, count: nf.format(panelList.length) })}
            </span>
            <button onClick={() => setPanelRound(null)} aria-label={t('Close')}
                    className="text-muted-foreground hover:text-foreground">×</button>
          </div>
          <ul className="max-h-64 overflow-auto text-xs">
            {panelList.slice(0, limit).map((n) => (
              <li key={n.id}>
                <button onClick={() => onOpenCard?.(n)} disabled={!onOpenCard}
                        className="flex w-full items-center gap-2 px-3 py-1 text-left hover:bg-accent">
                  <StatusDot status={n.status} />
                  <span className="w-8 shrink-0 tabular-nums text-muted-foreground"
                        title={t('Linked seeds')}>
                    {model.linkedSeeds.get(n.id)?.size ?? 0}×
                  </span>
                  <span className="min-w-0 flex-1 truncate text-foreground">{n.title}</span>
                  <span className="shrink-0 text-muted-foreground">{model.labels.get(n.id)}</span>
                </button>
              </li>
            ))}
          </ul>
          {panelList.length > limit && (
            <button onClick={() => setLimit((l) => l + PAGE)}
                    className="w-full border-t border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent">
              {t('Show {{count}} more', { count: Math.min(PAGE, panelList.length - limit) })}
            </button>
          )}
        </div>
      )}
      {hoverCard}
    </div>
  )
}
