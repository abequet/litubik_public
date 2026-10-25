// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Greedy label placement for the network view: each label tries the right,
 * left, top and bottom of its node and takes the first spot that hits no
 * placed label and no obstacle (seed and cluster discs). Required labels (the
 * seeds) take the least-crowded spot when all four collide; the others are
 * dropped (their title stays one hover away). Pure. */

export interface Box { x0: number; y0: number; x1: number; y1: number }

export interface LabelRequest {
  key: string
  x: number
  y: number
  /** radius of the node the label belongs to */
  r: number
  text: string
  /** measured text width and font size */
  w: number
  h: number
  required: boolean
}

export interface PlacedLabel {
  key: string
  text: string
  /** text anchor point (baseline) */
  x: number
  y: number
  anchor: 'start' | 'end' | 'middle'
  box: Box
}

const GAP = 3

function area(a: Box, b: Box) {
  const w = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0)
  const h = Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0)
  return w > 0 && h > 0 ? w * h : 0
}

function outside(b: Box, bounds: Box | undefined) {
  if (!bounds) return 0
  const inner: Box = { x0: Math.max(b.x0, bounds.x0), y0: Math.max(b.y0, bounds.y0),
                       x1: Math.min(b.x1, bounds.x1), y1: Math.min(b.y1, bounds.y1) }
  const whole = (b.x1 - b.x0) * (b.y1 - b.y0)
  const kept = inner.x1 > inner.x0 && inner.y1 > inner.y0
    ? (inner.x1 - inner.x0) * (inner.y1 - inner.y0) : 0
  return whole - kept
}

export function placeLabels(requests: LabelRequest[], obstacles: Box[],
                            bounds?: Box): PlacedLabel[] {
  const placed: PlacedLabel[] = []
  for (const q of requests) {
    const { x, y, r, w, h } = q
    const ascent = h * 0.8
    const options: Omit<PlacedLabel, 'key' | 'text'>[] = [
      { anchor: 'start', x: x + r + GAP, y: y - h / 2 + ascent,
        box: { x0: x + r + GAP - 1, y0: y - h / 2, x1: x + r + GAP + w + 1, y1: y + h / 2 } },
      { anchor: 'end', x: x - r - GAP, y: y - h / 2 + ascent,
        box: { x0: x - r - GAP - w - 1, y0: y - h / 2, x1: x - r - GAP + 1, y1: y + h / 2 } },
      { anchor: 'middle', x, y: y - r - GAP - h + ascent,
        box: { x0: x - w / 2 - 1, y0: y - r - GAP - h, x1: x + w / 2 + 1, y1: y - r - GAP } },
      { anchor: 'middle', x, y: y + r + GAP + ascent,
        box: { x0: x - w / 2 - 1, y0: y + r + GAP, x1: x + w / 2 + 1, y1: y + r + GAP + h } },
    ]
    let best: (typeof options)[number] | null = null
    let bestScore = Infinity
    for (const o of options) {
      let score = outside(o.box, bounds) * 4
      for (const p of placed) score += area(o.box, p.box) * 3
      for (const ob of obstacles) score += area(o.box, ob)
      if (score < bestScore) { best = o; bestScore = score }
      if (score === 0) break
    }
    if (best && (bestScore === 0 || q.required))
      placed.push({ key: q.key, text: q.text, ...best })
  }
  return placed
}
