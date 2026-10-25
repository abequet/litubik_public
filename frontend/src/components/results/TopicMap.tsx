// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TopicCluster, TopicPoint } from '../../api'
import { Button } from '@/components/ui/button'
import { clusterColor, readVizPalette } from './palette'

const MARGIN = 36          // px kept free around the fitted extent
const HALO_PAD = 14        // px of halo around a cluster's convex hull
const LABEL_FONT = '600 11.5px system-ui, sans-serif'
const LABEL_MAX_CHARS = 36

/** Dot radius: smaller as the corpus grows so 1,000 dots stay distinct. */
const baseRadius = (n: number) =>
  n > 2000 ? 2.4 : n > 800 ? 3 : n > 300 ? 3.6 : n > 100 ? 4.2 : 5

type XY = { x: number; y: number }

/** Convex hull (Andrew's monotone chain), counter-clockwise. */
function convexHull(pts: XY[]): XY[] {
  if (pts.length < 3) return pts.slice()
  const p = [...pts].sort((a, b) => a.x - b.x || a.y - b.y)
  const cross = (o: XY, a: XY, b: XY) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)
  const lower: XY[] = []
  for (const q of p) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], q) <= 0) lower.pop()
    lower.push(q)
  }
  const upper: XY[] = []
  for (let i = p.length - 1; i >= 0; i--) {
    const q = p[i]
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], q) <= 0) upper.pop()
    upper.push(q)
  }
  lower.pop(); upper.pop()
  return lower.concat(upper)
}

type Box = { x: number; y: number; w: number; h: number; text: string; cid: number }

/** Push overlapping label boxes apart (a few relaxation passes), then keep
 * them inside the canvas. */
function spreadLabels(boxes: Box[], w: number, h: number) {
  for (let pass = 0; pass < 60; pass++) {
    let moved = false
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i], b = boxes[j]
        const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x) + 4
        const oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y) + 4
        if (ox <= 0 || oy <= 0) continue
        moved = true
        // labels are wide and short: separate vertically unless the
        // horizontal overlap is tiny
        if (oy < ox * 0.6 || ox < 16) {
          const s = (a.y + a.h / 2 <= b.y + b.h / 2 ? -1 : 1) * oy / 2
          a.y += s; b.y -= s
        } else {
          const s = (a.x + a.w / 2 <= b.x + b.w / 2 ? -1 : 1) * ox / 2
          a.x += s; b.x -= s
        }
      }
    }
    if (!moved) break
  }
  for (const b of boxes) {
    b.x = Math.max(4, Math.min(w - b.w - 4, b.x))
    b.y = Math.max(4, Math.min(h - b.h - 4, b.y))
  }
}

/** 2-D scatter of the corpus (one dot per record, colour = cluster, marker =
 * screening decision: filled = included, ring = excluded, faint = undecided).
 * Each cluster gets a translucent halo (padded convex hull) and one label
 * at its median, labels pushed apart so they stay readable; `highlight`
 * (from the legend) dims every other cluster. The view fits the extent of
 * the visible dots. Plain canvas, same interaction patterns as
 * CitationGraph: hover tooltip, drag to pan, wheel to zoom, click to open
 * the paper card. */
export default function TopicMap({ points, clusters, hidden, highlight = null, height = 560,
                                   onOpenCard, filename }: {
  points: TopicPoint[]
  clusters: TopicCluster[]
  hidden: Set<number>
  highlight?: number | null
  height?: number
  onOpenCard: (recordId: number) => void
  filename: string
}) {
  const { t } = useTranslation()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef({ x: 0, y: 0, k: 1 })
  const fitRef = useRef({ cx: 0, cy: 0, s: 1 })
  const dragRef = useRef<{ startX: number; startY: number; moved: number } | null>(null)
  const drawRef = useRef<(() => void) | null>(null)
  const [hover, setHover] = useState<{ p: TopicPoint; px: number; py: number } | null>(null)

  const labelOf = (c: TopicCluster | undefined) =>
    c ? (c.label || c.terms.slice(0, 3).join(', ')) : ''

  // fit the visible extent into the canvas (recomputed when clusters are
  // hidden, so what remains fills the map)
  const fitTo = (visible: TopicPoint[], w: number, h: number) => {
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity
    for (const p of visible) {
      if (p.x < x0) x0 = p.x; if (p.x > x1) x1 = p.x
      if (p.y < y0) y0 = p.y; if (p.y > y1) y1 = p.y
    }
    if (!visible.length) { x0 = y0 = -1; x1 = y1 = 1 }
    const rx = Math.max(x1 - x0, 0.05), ry = Math.max(y1 - y0, 0.05)
    fitRef.current = {
      cx: (x0 + x1) / 2, cy: (y0 + y1) / 2,
      s: Math.min((w - 2 * MARGIN) / rx, (h - 2 * MARGIN) / ry),
    }
  }

  // screen position of a data point for the current view
  const place = (x: number, y: number, w: number, h: number) => {
    const view = viewRef.current, fit = fitRef.current
    return { sx: w / 2 + view.x + (x - fit.cx) * fit.s * view.k,
             sy: h / 2 + view.y - (y - fit.cy) * fit.s * view.k }
  }

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const visible = points.filter((p) => !hidden.has(p.cluster))
    const members = new Map<number, TopicPoint[]>()
    for (const p of visible) {
      const list = members.get(p.cluster)
      if (list) list.push(p); else members.set(p.cluster, [p])
    }

    const paint = (target: CanvasRenderingContext2D, w: number, h: number,
                   scale: number, background: string | null) => {
      const pal = readVizPalette()
      fitTo(visible, w, h)
      target.setTransform(scale, 0, 0, scale, 0, 0)
      target.clearRect(0, 0, w, h)
      if (background) {
        target.fillStyle = background
        target.fillRect(0, 0, w, h)
      }
      const zoom = Math.min(1.8, Math.max(0.7, viewRef.current.k))
      const r0 = baseRadius(visible.length) * zoom
      const dimOf = (cid: number) => (highlight !== null && cid !== highlight ? 0.15 : 1)

      // halos: the padded convex hull of each cluster, drawn first
      for (const c of clusters) {
        const list = members.get(c.id)
        if (!list || dimOf(c.id) < 1) continue
        const hull = convexHull(list.map((p) => { const s = place(p.x, p.y, w, h); return { x: s.sx, y: s.sy } }))
        if (!hull.length) continue
        target.beginPath()
        hull.forEach((q, i) => (i ? target.lineTo(q.x, q.y) : target.moveTo(q.x, q.y)))
        target.closePath()
        target.lineJoin = 'round'; target.lineCap = 'round'
        target.lineWidth = HALO_PAD * 2 * zoom
        target.strokeStyle = clusterColor(c.id); target.fillStyle = clusterColor(c.id)
        target.globalAlpha = highlight === c.id ? 0.16 : 0.09
        target.stroke(); target.fill()
        target.globalAlpha = 1
      }
      // dots, a thin contour in the card colour so neighbours stay apart
      for (const p of visible) {
        const { sx, sy } = place(p.x, p.y, w, h)
        const color = clusterColor(p.cluster)
        const dim = dimOf(p.cluster)
        const r = p.status === 'undecided' ? r0 * 0.85 : r0
        target.beginPath()
        target.arc(sx, sy, r, 0, Math.PI * 2)
        if (p.status === 'exclude') {
          target.globalAlpha = dim
          target.fillStyle = pal.card
          target.fill()
          target.strokeStyle = color
          target.lineWidth = Math.max(1.2, r * 0.45)
          target.stroke()
        } else {
          target.globalAlpha = (p.status === 'undecided' ? 0.5 : 0.95) * dim
          target.fillStyle = color
          target.fill()
          if (p.status === 'include') {
            target.strokeStyle = pal.card
            target.lineWidth = 0.8
            target.stroke()
          }
        }
        target.globalAlpha = 1
      }
      // one label per cluster at the median of its members, pushed apart
      target.font = LABEL_FONT
      target.textAlign = 'left'
      target.textBaseline = 'middle'
      const boxes: Box[] = []
      for (const c of clusters) {
        const list = members.get(c.id)
        if (!list) continue
        const xs = list.map((p) => p.x).sort((a, b) => a - b)
        const ys = list.map((p) => p.y).sort((a, b) => a - b)
        const { sx, sy } = place(xs[xs.length >> 1], ys[ys.length >> 1], w, h)
        let text = `${c.id + 1} · ${labelOf(c)}`
        if (text.length > LABEL_MAX_CHARS) text = text.slice(0, LABEL_MAX_CHARS - 1) + '…'
        const tw = target.measureText(text).width
        boxes.push({ x: sx - tw / 2 - 6, y: sy - 10, w: tw + 12, h: 20, text, cid: c.id })
      }
      spreadLabels(boxes, w, h)
      for (const b of boxes) {
        target.globalAlpha = highlight !== null && b.cid !== highlight ? 0.35 : 1
        target.fillStyle = pal.card
        target.fillRect(b.x, b.y, b.w, b.h)
        target.strokeStyle = clusterColor(b.cid)
        target.lineWidth = 1.5
        target.strokeRect(b.x, b.y, b.w, b.h)
        target.fillStyle = pal.foreground
        target.fillText(b.text, b.x + 6, b.y + b.h / 2)
        target.globalAlpha = 1
      }
    }

    const draw = () => {
      const dpr = window.devicePixelRatio || 1
      const w = canvas.clientWidth, h = canvas.clientHeight
      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr; canvas.height = h * dpr
      }
      paint(ctx, w, h, dpr, null)
    }
    drawRef.current = draw
    draw()
    window.addEventListener('resize', draw)
    const obs = new MutationObserver(draw)
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme'] })
    // PNG export paints the same scene on an offscreen canvas at 2x
    ;(canvas as HTMLCanvasElement & { __exportPng?: () => void }).__exportPng = () => {
      const w = canvas.clientWidth, h = canvas.clientHeight
      const off = document.createElement('canvas')
      off.width = w * 2; off.height = h * 2
      const octx = off.getContext('2d')
      if (!octx) return
      paint(octx, w, h, 2, readVizPalette().card)
      off.toBlob((blob) => {
        if (!blob) return
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = filename
        a.click()
        URL.revokeObjectURL(a.href)
      }, 'image/png')
    }
    return () => { window.removeEventListener('resize', draw); obs.disconnect() }
  }, [points, clusters, hidden, highlight, filename])  // eslint-disable-line react-hooks/exhaustive-deps

  const pointAt = (clientX: number, clientY: number): TopicPoint | undefined => {
    const canvas = canvasRef.current
    if (!canvas) return undefined
    const rect = canvas.getBoundingClientRect()
    const cx = clientX - rect.left, cy = clientY - rect.top
    let best: { p: TopicPoint; d: number } | undefined
    for (const p of points) {
      if (hidden.has(p.cluster)) continue
      const { sx, sy } = place(p.x, p.y, rect.width, rect.height)
      const d = (cx - sx) ** 2 + (cy - sy) ** 2
      if (d <= 64 && (!best || d < best.d)) best = { p, d }
    }
    return best?.p
  }

  const onPointerDown = (e: React.PointerEvent) => {
    dragRef.current = { startX: e.clientX, startY: e.clientY, moved: 0 }
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const drag = dragRef.current
    if (!drag) {
      const p = pointAt(e.clientX, e.clientY)
      const rect = wrapRef.current?.getBoundingClientRect()
      setHover(p && rect ? { p, px: e.clientX - rect.left, py: e.clientY - rect.top } : null)
      return
    }
    const dx = e.clientX - drag.startX, dy = e.clientY - drag.startY
    drag.startX = e.clientX; drag.startY = e.clientY
    drag.moved += Math.abs(dx) + Math.abs(dy)
    viewRef.current.x += dx
    viewRef.current.y += dy
    drawRef.current?.()
  }
  const onPointerUp = (e: React.PointerEvent) => {
    const drag = dragRef.current
    dragRef.current = null
    if (drag && drag.moved < 4) {
      const p = pointAt(e.clientX, e.clientY)
      if (p) { setHover(null); onOpenCard(p.record_id) }
    }
  }
  const onWheel = (e: React.WheelEvent) => {
    // zoom around the cursor so the region under it stays put
    const canvas = canvasRef.current
    const view = viewRef.current
    const next = Math.min(6, Math.max(0.4, view.k * (e.deltaY < 0 ? 1.12 : 0.89)))
    if (canvas) {
      const rect = canvas.getBoundingClientRect()
      const mx = e.clientX - rect.left - rect.width / 2, my = e.clientY - rect.top - rect.height / 2
      const f = next / view.k
      view.x = mx - (mx - view.x) * f
      view.y = my - (my - view.y) * f
    }
    view.k = next
    drawRef.current?.()
  }
  const reset = () => { viewRef.current = { x: 0, y: 0, k: 1 }; drawRef.current?.() }
  const exportPng = () =>
    (canvasRef.current as (HTMLCanvasElement & { __exportPng?: () => void }) | null)?.__exportPng?.()

  const hoverCluster = hover ? clusters.find((c) => c.id === hover.p.cluster) : undefined
  return (
    <div ref={wrapRef} className="relative" style={{ height }}>
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={t('Thematic map: one dot per record, coloured by cluster. The table below lists the same assignment.')}
        className="h-full w-full cursor-grab rounded-md border bg-card touch-none"
        onPointerDown={onPointerDown} onPointerMove={onPointerMove}
        onPointerUp={onPointerUp} onPointerLeave={() => setHover(null)}
        onWheel={onWheel}
      />
      <div className="absolute top-2 right-2 flex gap-1">
        <Button variant="outline" size="sm" onClick={reset}>{t('Reset view')}</Button>
        <Button variant="outline" size="sm" onClick={exportPng}>⤓ PNG</Button>
      </div>
      <p className="absolute bottom-2 left-2 rounded bg-card/80 px-1 text-[11px] text-muted-foreground">
        {t('Filled = included · ring = excluded · faint = undecided · drag to pan, wheel to zoom, click a dot for the paper card, point at a cluster in the legend to highlight it')}
      </p>
      {hover && (
        <div className="pointer-events-none absolute z-10 max-w-xs rounded-md border bg-popover p-2 text-xs shadow"
             style={{ left: hover.px + 12, top: hover.py + 12 }}>
          <p className="font-medium text-foreground">{hover.p.title}</p>
          <p className="text-muted-foreground">
            {hover.p.author}{hover.p.year ? ` · ${hover.p.year}` : ''}
          </p>
          <p className="mt-1" style={{ color: clusterColor(hover.p.cluster) }}>
            {hover.p.cluster + 1} · {labelOf(hoverCluster)}
          </p>
        </div>
      )}
    </div>
  )
}
