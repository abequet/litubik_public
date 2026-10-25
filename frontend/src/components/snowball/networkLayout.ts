// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import type { GraphModel } from './graphModel.ts'

/** Static layout of the "Network" view, computed once, synchronously:
 * retained papers and crawlers ("anchors") drawn one by one, papers shared by
 * several seeds, and one cluster per crawler standing for the papers only that
 * crawler found. Forces follow d3-force's formulas (many-body, links,
 * collision, x/y pulls) on a fixed seeded start, so the same data always gives
 * the same picture — and filtering by round later never moves anything. */

export type SimKind = 'anchor' | 'shared' | 'cluster'

export interface SimItem {
  key: string
  kind: SimKind
  /** paper id; for a cluster, the id of its crawler */
  id: number
  r: number
  x: number
  y: number
}

export interface NetworkLayout {
  items: SimItem[]
  byKey: Map<string, SimItem>
  bounds: { x0: number; y0: number; x1: number; y1: number }
}

export const ANCHOR_R = 8
export const INCLUDED_R = 6.5
export const clusterRadius = (n: number) => 5 + 0.95 * Math.sqrt(n)
export const sharedRadius = (links: number) => Math.min(14, 2.8 + 1.5 * (links - 1))
export const nodeKey = (id: number) => `n${id}`
export const clusterKey = (crawler: number) => `c${crawler}`

const ROUND_SPAN = 320

/** Small deterministic PRNG (mulberry32). */
function rng(seed: number) {
  let a = seed | 0
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

interface Body extends SimItem { vx: number; vy: number; charge: number; tx: number | null }
interface Spring { a: Body; b: Body; dist: number; strength: number; bias: number }

export function networkLayout(model: GraphModel, ticks = 300): NetworkLayout {
  const anchorRounds = [...new Set(model.anchors.map((n) => n.round || 1))].sort((a, b) => a - b)
  const multi = anchorRounds.length > 1
  const roundX = (r: number) => (anchorRounds.indexOf(r) - (anchorRounds.length - 1) / 2) * ROUND_SPAN

  const bodies: Body[] = []
  const byKey = new Map<string, Body>()
  const add = (b: Omit<Body, 'vx' | 'vy'>) => {
    const body = { ...b, vx: 0, vy: 0 }
    bodies.push(body)
    byKey.set(body.key, body)
    return body
  }

  const perRound = new Map<number, number>()
  const anchorsByRound = new Map<number, number>()
  for (const n of model.anchors) anchorsByRound.set(n.round || 1, (anchorsByRound.get(n.round || 1) ?? 0) + 1)
  for (const n of [...model.anchors].sort((a, b) => a.id - b.id)) {
    const r = n.round || 1
    const k = perRound.get(r) ?? 0
    perRound.set(r, k + 1)
    const rand = rng(n.id)
    const big = n.status === 'seed' || model.found.has(n.id)
    add({ key: nodeKey(n.id), kind: 'anchor', id: n.id, r: big ? ANCHOR_R : INCLUDED_R,
          x: roundX(r) + (rand() - 0.5) * 40,
          y: (k - ((anchorsByRound.get(r) ?? 1) - 1) / 2) * 70 + (rand() - 0.5) * 10,
          charge: -420, tx: multi ? roundX(r) : null })
  }
  for (const n of model.shared) {
    const seeds = [...(model.linkedSeeds.get(n.id)?.keys() ?? [])]
      .map((s) => byKey.get(nodeKey(s))).filter((b): b is Body => !!b)
    const rand = rng(n.id)
    const mx = seeds.length ? seeds.reduce((s, b) => s + b.x, 0) / seeds.length : 0
    const my = seeds.length ? seeds.reduce((s, b) => s + b.y, 0) / seeds.length : 0
    add({ key: nodeKey(n.id), kind: 'shared', id: n.id, r: sharedRadius(seeds.length),
          x: mx + (rand() - 0.5) * 60, y: my + (rand() - 0.5) * 60, charge: -22, tx: null })
  }
  // clusters start just outside their crawler, pointing away from the centre
  const cx0 = bodies.reduce((s, b) => s + b.x, 0) / Math.max(1, bodies.length)
  const cy0 = bodies.reduce((s, b) => s + b.y, 0) / Math.max(1, bodies.length)
  for (const [crawler, members] of model.clusters) {
    const a = byKey.get(nodeKey(crawler))
    if (!a) continue
    const r = clusterRadius(members.length)
    const rand = rng(crawler * 7 + 3)
    let ang = Math.atan2(a.y - cy0, a.x - cx0)
    if (!Number.isFinite(ang) || (a.x === cx0 && a.y === cy0)) ang = rand() * Math.PI * 2
    const d = a.r + r + 6
    add({ key: clusterKey(crawler), kind: 'cluster', id: crawler, r,
          x: a.x + Math.cos(ang) * d, y: a.y + Math.sin(ang) * d, charge: -170, tx: null })
  }

  // springs: cluster ↔ crawler short and stiff, shared paper ↔ each seed loose,
  // retained paper ↔ the crawler that found it loose
  const springs: Spring[] = []
  const degree = new Map<Body, number>()
  const link = (a: Body | undefined, b: Body | undefined, dist: number, strength: number) => {
    if (!a || !b || a === b) return
    springs.push({ a, b, dist, strength, bias: 0 })
    degree.set(a, (degree.get(a) ?? 0) + 1)
    degree.set(b, (degree.get(b) ?? 0) + 1)
  }
  for (const b of bodies) {
    if (b.kind === 'cluster') {
      const a = byKey.get(nodeKey(b.id))
      link(a, b, (a?.r ?? 0) + b.r + 6, 1)
      continue
    }
    for (const s of model.linkedSeeds.get(b.id)?.keys() ?? [])
      link(byKey.get(nodeKey(s)), b, b.kind === 'anchor' ? 90 : 70, 0.1)
  }
  for (const s of springs) s.bias = degree.get(s.a)! / (degree.get(s.a)! + degree.get(s.b)!)

  const n = bodies.length
  const steps = n > 700 ? Math.min(ticks, 150) : ticks
  const alphaMin = 0.001
  const alphaDecay = 1 - Math.pow(alphaMin, 1 / steps)
  let alpha = 1
  for (let t = 0; t < steps; t++) {
    alpha += -alpha * alphaDecay
    for (const s of springs) {
      let x = s.b.x + s.b.vx - s.a.x - s.a.vx
      let y = s.b.y + s.b.vy - s.a.y - s.a.vy
      const len = Math.sqrt(x * x + y * y) || 1e-6
      const k = ((len - s.dist) / len) * alpha * s.strength
      x *= k; y *= k
      s.b.vx -= x * s.bias; s.b.vy -= y * s.bias
      s.a.vx += x * (1 - s.bias); s.a.vy += y * (1 - s.bias)
    }
    for (let i = 0; i < n; i++) {
      const p = bodies[i]
      for (let j = i + 1; j < n; j++) {
        const q = bodies[j]
        const dx = q.x - p.x, dy = q.y - p.y
        const l = Math.max(1, dx * dx + dy * dy)
        p.vx += (dx * q.charge * alpha) / l; p.vy += (dy * q.charge * alpha) / l
        q.vx -= (dx * p.charge * alpha) / l; q.vy -= (dy * p.charge * alpha) / l
      }
    }
    for (const b of bodies) {
      if (b.tx !== null) b.vx += (b.tx - b.x) * 0.15 * alpha
      // elliptical pull (stronger in y): the card is wider than tall
      const sx = b.kind === 'anchor' ? (multi ? 0 : 0.015) : 0.008
      const sy = b.kind === 'anchor' ? 0.14 : 0.07
      b.vx += -b.x * sx * alpha
      b.vy += -b.y * sy * alpha
    }
    for (let pass = 0; pass < 2; pass++) {
      for (let i = 0; i < n; i++) {
        const p = bodies[i]
        for (let j = i + 1; j < n; j++) {
          const q = bodies[j]
          const pad = p.kind === 'shared' && q.kind === 'shared' ? 1.8 : 4
          const r = p.r + q.r + pad
          let x = p.x + p.vx - q.x - q.vx
          let y = p.y + p.vy - q.y - q.vy
          let l = x * x + y * y
          if (l >= r * r) continue
          if (l === 0) { x = (p.id % 7) - 3 || 1; y = (q.id % 5) - 2 || 1; l = x * x + y * y }
          l = Math.sqrt(l)
          const k = ((r - l) / l) * 0.9
          const pr2 = p.r * p.r, qr2 = q.r * q.r
          const w = qr2 / (pr2 + qr2)
          x *= k; y *= k
          p.vx += x * w; p.vy += y * w
          q.vx -= x * (1 - w); q.vy -= y * (1 - w)
        }
      }
    }
    for (const b of bodies) {
      b.vx *= 0.6; b.vy *= 0.6
      b.x += b.vx; b.y += b.vy
    }
  }

  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  const items: SimItem[] = bodies.map((b) => {
    x0 = Math.min(x0, b.x - b.r); x1 = Math.max(x1, b.x + b.r)
    y0 = Math.min(y0, b.y - b.r); y1 = Math.max(y1, b.y + b.r)
    return { key: b.key, kind: b.kind, id: b.id, r: b.r, x: b.x, y: b.y }
  })
  if (!items.length) { x0 = y0 = -1; x1 = y1 = 1 }
  return { items, byKey: new Map(items.map((i) => [i.key, i])), bounds: { x0, y0, x1, y1 } }
}

/** Unfolded cluster: its members on arcs centred on the crawler, fanning out
 * past the cluster disc in the crawler → cluster direction. Members are
 * spaced 2r + 1.5 apart along an arc and between arcs, so none overlap. */
export function fanLayout(seed: { x: number; y: number }, cluster: { x: number; y: number },
                          count: number, r = 3): { x: number; y: number }[] {
  const dx = cluster.x - seed.x, dy = cluster.y - seed.y
  const base = Math.hypot(dx, dy) || 24
  const theta0 = Math.atan2(dy, dx)
  const span = Math.min((200 * Math.PI) / 180, ((120 + count / 10) * Math.PI) / 180)
  const step = 2 * r + 1.5
  const out: { x: number; y: number }[] = []
  // first arc just past the cluster's fold handle (radius 6), which stays clickable
  let R = Math.max(base + 6 + r + 2, 2 * r + 12)
  while (out.length < count) {
    const cap = Math.max(1, Math.floor((span * R) / step))
    const k = Math.min(cap, count - out.length)
    const dA = step / R
    for (let i = 0; i < k; i++) {
      const a = theta0 + (i - (k - 1) / 2) * dA
      out.push({ x: seed.x + Math.cos(a) * R, y: seed.y + Math.sin(a) * R })
    }
    R += step
  }
  return out
}
