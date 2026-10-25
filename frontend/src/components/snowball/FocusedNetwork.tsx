// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Segmented } from '@/components/ui/segmented'
import { CHART_FONT } from '../results/palette'
import { isVisible, neighbours, type Filters } from './graphModel'
import {
  clusterKey, clusterRadius, fanLayout, networkLayout, nodeKey, type SimItem,
} from './networkLayout'
import { placeLabels, type Box, type LabelRequest } from './labelPlacement'
import { HoverCard, NodeTooltipBody, StatusDot } from './GraphOverlays'
import { STATUS_LABEL, STATUS_ORDER, statusColor } from './status'
import { measureText } from './svgText'
import type { Direction, GraphNode, Status } from './types'
import type { ViewProps } from './viewProps'

const FAN_R = 3
const SHARED_LABEL_LINKS = 5

interface View { x: number; y: number; k: number }

interface ClusterScene {
  item: SimItem
  members: GraphNode[]
  counts: Record<Status, number>
  r: number
  open: boolean
  fan: { x: number; y: number }[]
}

/** SVG ring slice (or full ring) centred on 0,0, angles from 12 o'clock. */
function ringPath(r0: number, r1: number, a0: number, a1: number): string {
  const p = (r: number, a: number) => `${(r * Math.sin(a)).toFixed(2)} ${(-r * Math.cos(a)).toFixed(2)}`
  if (a1 - a0 >= Math.PI * 2 - 1e-6)
    return `M${p(r1, 0)} A${r1} ${r1} 0 1 1 ${p(r1, Math.PI)} A${r1} ${r1} 0 1 1 ${p(r1, 0)} `
      + `M${p(r0, 0)} A${r0} ${r0} 0 1 0 ${p(r0, Math.PI)} A${r0} ${r0} 0 1 0 ${p(r0, 0)} Z`
  const large = a1 - a0 > Math.PI ? 1 : 0
  return `M${p(r1, a0)} A${r1} ${r1} 0 ${large} 1 ${p(r1, a1)} L${p(r0, a1)} `
    + `A${r0} ${r0} 0 ${large} 0 ${p(r0, a0)} Z`
}

/** "Network" view: retained papers, papers shared by several seeds, and one
 * ring per seed for the papers only that seed found (click to fan them out).
 * The layout is computed once; the round filter, the status / direction
 * chips and unfolding never move what is already drawn. */
export default function FocusedNetwork({ model, palette, height, isFs, selectedId, focus,
                                         onSelect, onClearSelection }: ViewProps) {
  const { t, i18n } = useTranslation()
  const nf = useMemo(() => new Intl.NumberFormat(i18n.language), [i18n.language])
  const layout = useMemo(() => networkLayout(model), [model])

  const wrapRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const [size, setSize] = useState({ w: 900, h: height })
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const update = () => setSize({ w: Math.max(200, el.clientWidth), h: Math.max(200, el.clientHeight) })
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const fit = useMemo<View>(() => {
    const b = layout.bounds
    const pad = 40
    const k = Math.min((size.w - 2 * pad) / Math.max(1, b.x1 - b.x0),
                       (size.h - 2 * pad) / Math.max(1, b.y1 - b.y0), 2)
    return { k, x: size.w / 2 - (k * (b.x0 + b.x1)) / 2, y: size.h / 2 - (k * (b.y0 + b.y1)) / 2 }
  }, [layout, size])
  const [userView, setUserView] = useState<View | null>(null)
  const v = userView ?? fit
  const viewRef = useRef(v)
  useEffect(() => { viewRef.current = v })
  const setView = (next: View) => { viewRef.current = next; setUserView(next) }

  const lastRound = model.rounds[model.rounds.length - 1] ?? 1
  const [maxRound, setMaxRound] = useState(lastRound)
  const [hiddenStatus, setHiddenStatus] = useState<Set<Status>>(() => new Set())
  const [hiddenDir, setHiddenDir] = useState<Set<Direction>>(() => new Set())
  const [unfolded, setUnfolded] = useState<Set<number>>(() => new Set())
  const [hover, setHover] = useState<{ key: string; x: number; y: number } | null>(null)

  const filters = useMemo<Filters>(() => ({ hiddenStatus, hiddenDir, maxRound }),
    [hiddenStatus, hiddenDir, maxRound])

  const scene = useMemo(() => {
    const shown = (id: number) => {
      const n = model.byId.get(id)
      return !!n && isVisible(n, filters)
    }
    const anchors: SimItem[] = []
    const shared: SimItem[] = []
    const clusters: ClusterScene[] = []
    for (const it of layout.items) {
      if (!shown(it.id)) continue
      if (it.kind === 'anchor') anchors.push(it)
      else if (it.kind === 'shared') shared.push(it)
      else {
        const members = (model.clusters.get(it.id) ?? [])
          .map((id) => model.byId.get(id)!).filter((n) => isVisible(n, filters))
        if (!members.length) continue
        const counts: Record<Status, number> = { seed: 0, included: 0, excluded: 0, pending: 0 }
        for (const m of members) counts[m.status]++
        const open = unfolded.has(it.id)
        const anchor = layout.byKey.get(nodeKey(it.id))!
        clusters.push({ item: it, members, counts, r: clusterRadius(members.length), open,
                        fan: open ? fanLayout(anchor, it, members.length, FAN_R) : [] })
      }
    }
    const drawn = new Set([...anchors, ...shared].map((i) => i.key))
    const edges: { a: SimItem; b: SimItem; dir: Direction | 'both' | 'cluster' }[] = []
    for (const it of [...anchors, ...shared]) {
      for (const [s, dirs] of model.linkedSeeds.get(it.id) ?? []) {
        const a = layout.byKey.get(nodeKey(s))
        if (!a || !drawn.has(a.key)) continue
        const kept = [...dirs].filter((d) => !hiddenDir.has(d))
        if (!kept.length) continue
        edges.push({ a, b: it, dir: kept.length > 1 ? 'both' : kept[0] })
      }
    }
    for (const c of clusters) edges.push({ a: layout.byKey.get(nodeKey(c.item.id))!, b: c.item, dir: 'cluster' })
    return { anchors, shared, clusters, edges }
  }, [layout, model, filters, hiddenDir, unfolded])

  // hover (or selection) isolates a neighbourhood
  const lit = useMemo(() => {
    const k = hover?.key ?? (selectedId !== null ? nodeKey(selectedId) : null)
    if (!k) return null
    const id = Number(k.slice(1))
    const out = new Set<string>([nodeKey(id), clusterKey(id)])
    if (k[0] === 'c') {
      // an unfolded cluster lights its fan
      if (unfolded.has(id)) for (const m of model.clusters.get(id) ?? []) out.add(nodeKey(m))
      return out
    }
    for (const x of neighbours(model, id)) out.add(nodeKey(x))
    return out
  }, [hover, selectedId, model, unfolded])
  const dim = (key: string) => (lit && !lit.has(key) ? 0.12 : 1)

  // labels in screen space: they keep their size when zooming
  const labels = useMemo(() => {
    const sx = (x: number) => v.x + v.k * x
    const sy = (y: number) => v.y + v.k * y
    const obstacles: Box[] = []
    for (const it of scene.anchors) {
      const r = (it.r + 3) * v.k
      obstacles.push({ x0: sx(it.x) - r, y0: sy(it.y) - r, x1: sx(it.x) + r, y1: sy(it.y) + r })
    }
    for (const c of scene.clusters) {
      const r = c.r * v.k
      const cx = sx(c.item.x), cy = sy(c.item.y)
      obstacles.push({ x0: cx - r, y0: cy - r, x1: cx + r, y1: cy + r })
      // a small ring writes its count beside it
      if (!c.open && r < 14)
        obstacles.push({ x0: cx + r, y0: cy - 6, x1: cx + r + 4 + measureText(nf.format(c.members.length), 9.5), y1: cy + 6 })
    }
    const reqs: LabelRequest[] = scene.anchors.map((it) => {
      const text = model.labels.get(it.id) ?? ''
      return { key: it.key, x: sx(it.x), y: sy(it.y), r: (it.r + 3) * v.k, text,
               w: measureText(text, 11.5, 600), h: 11.5, required: true }
    })
    const links = (it: SimItem) => model.linkedSeeds.get(it.id)?.size ?? 0
    for (const it of [...scene.shared].sort((a, b) => links(b) - links(a))) {
      if (links(it) < SHARED_LABEL_LINKS && v.k < 1.6) continue
      const text = model.labels.get(it.id) ?? ''
      reqs.push({ key: it.key, x: sx(it.x), y: sy(it.y), r: it.r * v.k, text,
                  w: measureText(text, 10.5), h: 10.5, required: false })
    }
    return placeLabels(reqs, obstacles, { x0: 0, y0: 0, x1: size.w, y1: size.h })
  }, [scene, v, size, model, nf])

  // wheel zoom anchored at the cursor (native listener: React's is passive)
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const rect = svg.getBoundingClientRect()
      const mx = e.clientX - rect.left, my = e.clientY - rect.top
      const cur = viewRef.current
      const k = Math.min(8, Math.max(0.15, cur.k * (e.deltaY < 0 ? 1.15 : 1 / 1.15)))
      const f = k / cur.k
      setView({ k, x: mx - (mx - cur.x) * f, y: my - (my - cur.y) * f })
    }
    svg.addEventListener('wheel', onWheel, { passive: false })
    return () => svg.removeEventListener('wheel', onWheel)
  }, [])

  // a search pick: reveal the paper (filters off, its cluster unfolded), centre it
  useEffect(() => {
    if (!focus) return
    const id = focus.id
    setHiddenStatus(new Set())
    setHiddenDir(new Set())
    setMaxRound(lastRound)
    let pos: { x: number; y: number } | undefined = layout.byKey.get(nodeKey(id))
    if (!pos) {
      for (const [crawler, members] of model.clusters) {
        const idx = members.indexOf(id)
        if (idx < 0) continue
        setUnfolded((prev) => new Set(prev).add(crawler))
        const a = layout.byKey.get(nodeKey(crawler)), c = layout.byKey.get(clusterKey(crawler))
        if (a && c) pos = fanLayout(a, c, members.length, FAN_R)[idx]
        break
      }
    }
    if (!pos) return
    const k = Math.max(viewRef.current.k, 1.4)
    setView({ k, x: size.w / 2 - k * pos.x, y: size.h / 2 - k * pos.y })
    const rect = wrapRef.current?.getBoundingClientRect()
    if (rect) onSelect(id, rect.left + size.w / 2, rect.top + size.h / 2)
  }, [focus])  // eslint-disable-line

  const keyOf = (e: React.PointerEvent) =>
    (e.target as Element).closest?.('[data-k]')?.getAttribute('data-k') ?? null
  const drag = useRef<{ key: string | null; x0: number; y0: number; lx: number; ly: number } | null>(null)
  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    const key = keyOf(e)
    drag.current = { key, x0: e.clientX, y0: e.clientY, lx: e.clientX, ly: e.clientY }
    if (!key) e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const d = drag.current
    if (d && !d.key) {
      const cur = viewRef.current
      setView({ ...cur, x: cur.x + e.clientX - d.lx, y: cur.y + e.clientY - d.ly })
      d.lx = e.clientX
      d.ly = e.clientY
      setHover(null)
      return
    }
    const k = keyOf(e)
    setHover(k ? { key: k, x: e.clientX, y: e.clientY } : null)
  }
  const onPointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    const d = drag.current
    drag.current = null
    if (!d || Math.hypot(e.clientX - d.x0, e.clientY - d.y0) > 4) return
    const k = keyOf(e)
    if (k !== d.key) return
    if (!k) { onClearSelection(); return }
    const id = Number(k.slice(1))
    if (k[0] === 'c') {
      setUnfolded((prev) => {
        const next = new Set(prev)
        if (next.has(id)) next.delete(id); else next.add(id)
        return next
      })
    } else onSelect(id, e.clientX, e.clientY)
  }

  const toggle = <T,>(set: (f: (prev: Set<T>) => Set<T>) => void, x: T) =>
    set((prev) => {
      const next = new Set(prev)
      if (next.has(x)) next.delete(x); else next.add(x)
      return next
    })

  const roundOptions = model.rounds.filter((r) => r >= 2)
    .map((r) => ({ value: r, label: `r1–r${r}` }))

  const nodeShape = (n: GraphNode, x: number, y: number, r: number, key: string) => {
    const c = statusColor(palette, n.status)
    const op = dim(key)
    return (
      <g key={key} data-k={key} opacity={op} style={{ cursor: 'pointer' }}>
        {n.status === 'excluded'
          ? <circle cx={x} cy={y} r={r} fill={palette.card} stroke={c} strokeWidth={1.5}
                    vectorEffect="non-scaling-stroke" />
          : <circle cx={x} cy={y} r={r} fill={c} fillOpacity={n.status === 'pending' ? 0.8 : 1} />}
        {n.status === 'seed' && (
          <circle cx={x} cy={y} r={r + 3} fill="none" stroke={c} strokeWidth={1.4}
                  vectorEffect="non-scaling-stroke" />
        )}
        {selectedId === n.id && (
          <circle cx={x} cy={y} r={r + 6} fill="none" stroke={palette.foreground} strokeWidth={1.2}
                  strokeDasharray="3 2" vectorEffect="non-scaling-stroke" />
        )}
      </g>
    )
  }

  // export-only legend (top left of the exported view)
  const legendItems: { key: string; label: string; mark: React.ReactNode }[] = [
    { key: 'seed', label: t(STATUS_LABEL.seed), mark: (
      <><circle cx={5} cy={0} r={4} fill={palette.blue} />
        <circle cx={5} cy={0} r={6.5} fill="none" stroke={palette.blue} /></>) },
    { key: 'included', label: t(STATUS_LABEL.included),
      mark: <circle cx={5} cy={0} r={4} fill={palette.teal} /> },
    { key: 'excluded', label: t(STATUS_LABEL.excluded),
      mark: <circle cx={5} cy={0} r={4} fill={palette.card} stroke={palette.orange} strokeWidth={1.5} /> },
    { key: 'pending', label: t(STATUS_LABEL.pending),
      mark: <circle cx={5} cy={0} r={4} fill={palette.mutedForeground} /> },
    { key: 'cluster', label: t('one-seed cluster'),
      mark: <path transform="translate(5,0)" d={ringPath(3.5, 6.5, 0, Math.PI * 2)}
                  fill={palette.orange} fillRule="evenodd" /> },
    { key: 'back', label: t('backward (refs, solid)'),
      mark: <line x1={0} x2={16} y1={0} y2={0} stroke={palette.mutedForeground} strokeWidth={1.4} /> },
    { key: 'fwd', label: t('forward (citing, dashed)'),
      mark: <line x1={0} x2={16} y1={0} y2={0} stroke={palette.blue} strokeWidth={1.4} strokeDasharray="4 3" /> },
  ]
  // the exported legend names only what the exported view draws
  const drawn = new Set<string>()
  for (const it of [...scene.anchors, ...scene.shared]) drawn.add(model.byId.get(it.id)!.status)
  for (const c of scene.clusters) {
    drawn.add('cluster')
    if (c.open) for (const m of c.members) drawn.add(m.status)
  }
  for (const e of scene.edges) {
    if (e.dir === 'backward' || e.dir === 'both') drawn.add('back')
    if (e.dir === 'forward' || e.dir === 'both') drawn.add('fwd')
  }
  let lx = 12
  let ly = 18
  const legend = legendItems.filter((it) => drawn.has(it.key)).map((it) => {
    const markW = it.key === 'back' || it.key === 'fwd' ? 22 : 16
    const w = markW + measureText(it.label, 11) + 16
    if (lx + w > size.w - 8 && lx > 12) { lx = 12; ly += 18 }
    const pos = { ...it, x: lx, y: ly, markW }
    lx += w
    return pos
  })

  const hoverCard = (() => {
    if (!hover || selectedId !== null) return null
    const id = Number(hover.key.slice(1))
    if (hover.key[0] === 'c') {
      const c = scene.clusters.find((x) => x.item.id === id)
      if (!c) return null
      return (
        <HoverCard x={hover.x} y={hover.y}>
          <p className="font-medium text-foreground">
            {t('Found by this seed only: {{count}} papers', { count: nf.format(c.members.length) })}
          </p>
          <p className="text-muted-foreground">{model.labels.get(id)}</p>
          <p className="text-muted-foreground">
            {t('excluded {{excluded}} · to screen {{pending}}',
               { excluded: nf.format(c.counts.excluded), pending: nf.format(c.counts.pending) })}
          </p>
          <p className="text-muted-foreground">{c.open ? t('Click to fold') : t('Click to unfold')}</p>
        </HoverCard>
      )
    }
    const n = model.byId.get(id)
    return n ? <HoverCard x={hover.x} y={hover.y}><NodeTooltipBody node={n} model={model} /></HoverCard> : null
  })()

  return (
    <div className={cn('flex flex-col gap-2', isFs && 'min-h-0 flex-1')}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted-foreground">
        {roundOptions.length > 1 && (
          <span className="flex items-center gap-1.5">
            {t('Iterations shown')}
            <Segmented size="sm" value={maxRound} onChange={setMaxRound} options={roundOptions} />
          </span>
        )}
        <span className="flex flex-wrap items-center gap-x-1 gap-y-1">
          {STATUS_ORDER.map((s) => (
            <button key={s} onClick={() => toggle(setHiddenStatus, s)} aria-pressed={!hiddenStatus.has(s)}
                    title={hiddenStatus.has(s) ? t('Show these papers') : t('Hide these papers')}
                    className={cn('flex items-center gap-1 rounded px-1 hover:bg-accent',
                                  hiddenStatus.has(s) && 'line-through opacity-40')}>
              <StatusDot status={s} />{t(STATUS_LABEL[s])}
            </button>
          ))}
          <span className="text-border">|</span>
          <button onClick={() => toggle(setHiddenDir, 'backward' as Direction)}
                  aria-pressed={!hiddenDir.has('backward')}
                  title={hiddenDir.has('backward')
                    ? t('Show backward papers & links') : t('Hide backward papers & links')}
                  className={cn('flex items-center gap-1 rounded px-1 hover:bg-accent',
                                hiddenDir.has('backward') && 'line-through opacity-40')}>
            <span className="inline-block w-4 border-t-2 border-muted-foreground" />
            {t('backward (refs, solid)')}
          </button>
          <button onClick={() => toggle(setHiddenDir, 'forward' as Direction)}
                  aria-pressed={!hiddenDir.has('forward')}
                  title={hiddenDir.has('forward')
                    ? t('Show forward papers & links') : t('Hide forward papers & links')}
                  className={cn('flex items-center gap-1 rounded px-1 hover:bg-accent',
                                hiddenDir.has('forward') && 'line-through opacity-40')}>
            <span className="inline-block w-4 border-t-2 border-dashed"
                  style={{ borderColor: 'var(--viz-blue)' }} />
            {t('forward (citing, dashed)')}
          </button>
          <span className="flex items-center gap-1 px-1">
            <span aria-hidden className="inline-block h-3 w-3 rounded-full border-[3px]"
                  style={{ borderColor: 'var(--viz-orange)' }} />
            {t('one-seed cluster')}
          </span>
        </span>
        <span className="flex-1" />
        <Button variant="ghost" size="sm" className="h-7 text-xs" disabled={!userView}
                onClick={() => { viewRef.current = fit; setUserView(null) }}>
          {t('Reset view')}
        </Button>
      </div>

      <div ref={wrapRef}
           className={cn('relative overflow-hidden rounded-lg border border-border bg-card',
                         isFs && 'min-h-0 flex-1')}
           style={isFs ? undefined : { height }}>
        <svg ref={svgRef} data-export width={size.w} height={size.h}
             viewBox={`0 0 ${size.w} ${size.h}`} role="img" fontFamily={CHART_FONT}
             aria-label={t('Citation network of {{count}} papers — use the Data button for a table',
                           { count: model.byId.size })}
             className="block h-full w-full touch-none cursor-grab"
             onPointerDown={onPointerDown} onPointerMove={onPointerMove}
             onPointerUp={onPointerUp} onPointerLeave={() => setHover(null)}>
          <g transform={`translate(${v.x.toFixed(2)} ${v.y.toFixed(2)}) scale(${v.k.toFixed(4)})`}>
            <g>
              {scene.edges.map(({ a, b, dir }) => {
                const on = !lit || (lit.has(a.key) && lit.has(b.key))
                return (
                  <line key={`${a.key}-${b.key}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                        vectorEffect="non-scaling-stroke"
                        stroke={dir === 'forward' ? palette.blue
                          : dir === 'cluster' ? palette.border : palette.mutedForeground}
                        strokeWidth={dir === 'cluster' ? 1.5 : lit && on ? 1.4 : 0.9}
                        strokeDasharray={dir === 'forward' ? '4 3' : undefined}
                        opacity={lit ? (on ? 0.9 : 0.05) : dir === 'cluster' ? 1 : 0.32} />
                )
              })}
            </g>
            <g>
              {scene.clusters.map((c) => {
                const total = c.members.length
                let a = 0
                const parts = STATUS_ORDER.filter((s) => c.counts[s] > 0).map((s) => {
                  const a0 = a
                  a += (Math.PI * 2 * c.counts[s]) / total
                  return { s, a0, a1: a }
                })
                const inner = c.r * 0.6
                const screenR = c.r * v.k
                return (
                  <g key={c.item.key} data-k={c.item.key} opacity={dim(c.item.key)}
                     transform={`translate(${c.item.x},${c.item.y})`} style={{ cursor: 'pointer' }}>
                    {c.open ? (
                      <>
                        <circle r={6} fill={palette.card} stroke={palette.mutedForeground}
                                strokeDasharray="2 2" vectorEffect="non-scaling-stroke" />
                        <line x1={-3} x2={3} y1={0} y2={0} stroke={palette.mutedForeground}
                              strokeWidth={1.4} vectorEffect="non-scaling-stroke" />
                      </>
                    ) : (
                      <>
                        <circle r={c.r} fill={palette.card} />
                        {parts.map((p) => (
                          <path key={p.s} d={ringPath(inner, c.r, p.a0, p.a1)} fillRule="evenodd"
                                fill={statusColor(palette, p.s)}
                                stroke={parts.length > 1 ? palette.card : 'none'}
                                strokeWidth={1} vectorEffect="non-scaling-stroke" />
                        ))}
                        {screenR >= 14 ? (
                          <text textAnchor="middle" y={3.6 / v.k} fontSize={10.5 / v.k} fontWeight={600}
                                fill={palette.foreground}>{nf.format(total)}</text>
                        ) : (
                          <text x={c.r + 2 / v.k} y={3.4 / v.k} fontSize={9.5 / v.k}
                                fill={palette.mutedForeground}>{nf.format(total)}</text>
                        )}
                      </>
                    )}
                  </g>
                )
              })}
            </g>
            <g>
              {scene.shared.map((it) => nodeShape(model.byId.get(it.id)!, it.x, it.y, it.r, it.key))}
            </g>
            <g>
              {scene.anchors.map((it) => nodeShape(model.byId.get(it.id)!, it.x, it.y, it.r, it.key))}
            </g>
            <g>
              {scene.clusters.filter((c) => c.open).map((c) =>
                c.members.map((m, i) => nodeShape(m, c.fan[i].x, c.fan[i].y, FAN_R, nodeKey(m.id))))}
            </g>
          </g>
          <g>
            {labels.map((l) => {
              const anchor = l.key[0] === 'n' && layout.byKey.get(l.key)?.kind === 'anchor'
              return (
                <text key={l.key} x={l.x.toFixed(1)} y={l.y.toFixed(1)} textAnchor={l.anchor}
                      fontSize={anchor ? 11.5 : 10.5} fontWeight={anchor ? 600 : 400}
                      fill={anchor ? palette.foreground : palette.mutedForeground}
                      stroke={palette.card} strokeWidth={3} strokeLinejoin="round" paintOrder="stroke"
                      opacity={dim(l.key)} style={{ pointerEvents: 'none' }}>
                  {l.text}
                </text>
              )
            })}
          </g>
          <g data-export-only="" display="none">
            {legend.map((it) => (
              <g key={it.key} transform={`translate(${it.x},${it.y})`}>
                {it.mark}
                <text x={it.markW} y={4} fontSize={11} fill={palette.mutedForeground}>{it.label}</text>
              </g>
            ))}
          </g>
        </svg>
      </div>
      <p className="text-xs text-muted-foreground">
        {t('· hover = neighbours · click a cluster to unfold it · drag = pan · wheel = zoom')}
      </p>
      {hoverCard}
    </div>
  )
}
