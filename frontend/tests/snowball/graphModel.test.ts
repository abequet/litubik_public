import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  buildGraphModel, isVisible, lineage, notRetainedOfRound, surname,
} from '../../src/components/snowball/graphModel.ts'
import { A, B, C, D, I4, K, S1, S2, S3, edges, nodes } from './fixture.ts'

const model = buildGraphModel(nodes, edges)

test('parents come from earlier-round crawlers only (no back-link upward)', () => {
  assert.deepEqual(model.parents.get(S3), [S1])
  assert.deepEqual(model.parents.get(I4), [S3])
  assert.deepEqual(model.parents.get(S1), [])   // S3 cites S1, but S3 is later
  assert.deepEqual(model.children.get(S1), [S3])
})

test('shared papers and one-seed clusters', () => {
  assert.deepEqual(model.shared.map((n) => n.id).sort(), [A, D])
  assert.deepEqual(model.clusters.get(S1), [B])
  // excluded members by year, the year-less one last
  assert.deepEqual(model.clusters.get(S2), [K, C])
  assert.ok(!model.clusters.has(S3))            // I4 is retained: drawn, not folded
  assert.deepEqual(model.anchors.map((n) => n.id).sort(), [S1, S2, S3, I4])
})

test('round statistics', () => {
  assert.deepEqual(model.rounds, [1, 2, 3])
  assert.deepEqual(model.roundStats.get(2),
    { round: 2, candidates: 5, retained: 1, excluded: 3, pending: 1 })
  assert.deepEqual(model.roundStats.get(1),
    { round: 1, candidates: 3, retained: 2, excluded: 1, pending: 0 })
})

test('crawl counts per direction', () => {
  assert.deepEqual(model.found.get(S1), { backward: [S3, A, D], forward: [B] })
  assert.equal(model.found.get(S3)?.backward.length, 1)
  assert.equal(model.found.get(S3)?.forward.length, 1)
})

test('surname whatever the author format', () => {
  assert.equal(surname('Malone, Daniel F'), 'Malone')
  assert.equal(surname('Daniel F Malone'), 'Malone')
  assert.equal(surname('Malone DF'), 'Malone')
  assert.equal(surname('NASA.'), 'NASA.')
  assert.equal(surname(''), '?')
  assert.equal(surname('Md Mahmud Hossain'), 'Hossain')
})

test('labels: namesakes among drawn papers get a/b, the others stay plain', () => {
  assert.equal(model.labels.get(S1), 'Malone 2024')
  assert.equal(model.labels.get(S2), 'Duncliffe 2019a')
  assert.equal(model.labels.get(D), 'Duncliffe 2019b')
  assert.equal(model.labels.get(C), '?')
  assert.equal(model.labels.get(S3), 'Kahn 2001')
})

test('lineage walks up and down the retained papers', () => {
  assert.deepEqual([...lineage(model, S1)].sort(), [S1, S3, I4])
  assert.deepEqual([...lineage(model, I4)].sort(), [S1, S3, I4])
  assert.deepEqual([...lineage(model, S2)], [S2])
})

test('visibility: status, round, and "both" needs both directions hidden', () => {
  const none = { hiddenStatus: new Set<never>(), hiddenDir: new Set<never>(), maxRound: 9 }
  const byId = model.byId
  assert.ok(isVisible(byId.get(A)!, none))
  assert.ok(!isVisible(byId.get(A)!, { ...none, hiddenStatus: new Set(['excluded'] as const) }))
  assert.ok(!isVisible(byId.get(I4)!, { ...none, maxRound: 2 }))
  assert.ok(isVisible(byId.get(S1)!, { ...none, hiddenDir: new Set(['backward'] as const) }))
  assert.ok(!isVisible(byId.get(S1)!, { ...none, hiddenDir: new Set(['backward', 'forward'] as const) }))
})

test('not-retained list of a round, most-linked first', () => {
  const list = notRetainedOfRound(model, 2).map((n) => n.id)
  assert.deepEqual(list.slice(0, 2).sort(), [A, D])
  assert.deepEqual(list.slice(2).sort(), [B, C])
  assert.ok(!list.includes(S3))
})
