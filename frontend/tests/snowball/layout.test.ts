import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildGraphModel } from '../../src/components/snowball/graphModel.ts'
import { genealogyLayout, packRows, ROW_H } from '../../src/components/snowball/genealogyLayout.ts'
import { fanLayout, networkLayout } from '../../src/components/snowball/networkLayout.ts'
import { placeLabels, type LabelRequest } from '../../src/components/snowball/labelPlacement.ts'
import { I4, S1, S2, S3, bigGraph, edges, nodes } from './fixture.ts'

const measure = (s: string) => s.length * 6.5

test('packRows keeps the gap and stays as close as it can to the ideal rows', () => {
  const ys = packRows([100, 100, 100, 300], 34, 64)
  for (let i = 1; i < ys.length; i++) assert.ok(ys[i] - ys[i - 1] >= 34 - 1e-9)
  assert.equal(ys[3], 300)
  assert.ok(Math.abs((ys[0] + ys[1] + ys[2]) / 3 - 100) < 1e-9)   // centred on the ideal
  assert.deepEqual(packRows([0, 0], 34, 64), [64, 98])          // never above the top
})

test('genealogy: no overlapping pills, curves only between retained papers', () => {
  const model = buildGraphModel(nodes, edges)
  const g = genealogyLayout(model, { measure })
  assert.equal(g.columns.length, 3)
  const byCol = new Map<number, number[]>()
  for (const p of g.pills) byCol.set(p.x, [...(byCol.get(p.x) ?? []), p.y])
  for (const ys of byCol.values()) {
    ys.sort((a, b) => a - b)
    for (let i = 1; i < ys.length; i++) assert.ok(ys[i] - ys[i - 1] >= ROW_H - 1e-9)
  }
  const pairs = g.curves.map((c) => `${c.from}>${c.to}`).sort()
  assert.deepEqual(pairs, [`${S1}>${S3}`, `${S3}>${I4}`])
  assert.equal(g.curves.find((c) => c.to === I4)?.dir, 'forward')
  // first column ordered by year
  const first = g.pills.filter((p) => p.x === g.columns[0].x).sort((a, b) => a.y - b.y)
  assert.deepEqual(first.map((p) => p.id), [S2, S1])
  // a seed's crawl bar, none for a paper not crawled yet
  assert.ok(g.pills.find((p) => p.id === S1)?.bar)
  assert.equal(g.pills.find((p) => p.id === I4)?.bar, null)
})

test('genealogy: a label too long for the pill keeps its year', () => {
  const long = nodes.map((n) => (n.id === S1 ? { ...n, author: 'Wolfeschlegelsteinhausenbergerdorff' } : n))
  const g = genealogyLayout(buildGraphModel(long, edges), { measure })
  const label = g.pills.find((p) => p.id === S1)!.label
  assert.match(label, /… 2024$/)
})

test('network: deterministic, finite, no overlapping discs', () => {
  const { nodes: ns, edges: es } = bigGraph()
  const model = buildGraphModel(ns, es)
  const t0 = performance.now()
  const a = networkLayout(model)
  const ms = performance.now() - t0
  const b = networkLayout(model)
  assert.deepEqual(a.items, b.items)
  for (const it of a.items) assert.ok(Number.isFinite(it.x) && Number.isFinite(it.y))
  for (let i = 0; i < a.items.length; i++)
    for (let j = i + 1; j < a.items.length; j++) {
      const p = a.items[i], q = a.items[j]
      if (p.kind === 'shared' && q.kind === 'shared') continue
      assert.ok(Math.hypot(p.x - q.x, p.y - q.y) >= p.r + q.r - 0.5,
                `${p.key} overlaps ${q.key}`)
    }
  // seeds drift left to right with their round
  const meanX = (r: number) => {
    const xs = model.anchors.filter((n) => n.round === r).map((n) => a.byKey.get(`n${n.id}`)!.x)
    return xs.reduce((s, x) => s + x, 0) / xs.length
  }
  assert.ok(meanX(1) < meanX(2) && meanX(2) < meanX(3))
  assert.ok(ms < 2000, `layout took ${ms.toFixed(0)} ms`)
})

test('fan of a large cluster: no two members overlap', () => {
  const r = 3
  const pts = fanLayout({ x: 0, y: 0 }, { x: 40, y: 10 }, 815, r)
  assert.equal(pts.length, 815)
  for (let i = 0; i < pts.length; i++)
    for (let j = i + 1; j < pts.length; j++)
      assert.ok(Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y) >= 2 * r)
})

test('labels: no two placed labels intersect, required ones always placed', () => {
  const reqs: LabelRequest[] = []
  for (let i = 0; i < 40; i++)
    reqs.push({ key: `k${i}`, x: 100 + (i % 8) * 30, y: 100 + Math.floor(i / 8) * 12, r: 4,
                text: `Label ${i}`, w: 48, h: 11, required: i < 5 })
  const placed = placeLabels(reqs, [], { x0: 0, y0: 0, x1: 600, y1: 400 })
  for (let i = 0; i < 5; i++) assert.ok(placed.some((p) => p.key === `k${i}`))
  const free = placed.filter((p) => !['k0', 'k1', 'k2', 'k3', 'k4'].includes(p.key))
  for (let i = 0; i < free.length; i++)
    for (let j = 0; j < placed.length; j++) {
      if (free[i].key === placed[j].key) continue
      const a = free[i].box, b = placed[j].box
      const hit = Math.min(a.x1, b.x1) > Math.max(a.x0, b.x0) && Math.min(a.y1, b.y1) > Math.max(a.y0, b.y0)
      assert.ok(!hit, `${free[i].key} hits ${placed[j].key}`)
    }
})
