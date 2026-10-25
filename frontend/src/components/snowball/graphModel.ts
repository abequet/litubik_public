// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Direction, GraphEdge, GraphNode, Status } from './types.ts'

/** What the two snowballing views derive from the graph payload. Citation
 * edges only ever join a crawled seed (the "crawler": the citing paper of a
 * backward edge, the cited one of a forward edge) to a paper its crawl found,
 * so the graph is a union of stars around the seeds: the structure worth
 * drawing is the lineage between retained papers and the few candidates
 * several seeds share; the rest folds into one cluster per seed. Pure (no
 * React, no DOM) so it is unit-tested with `node --test`. */

export interface RoundStats {
  round: number
  /** papers of this round in the graph */
  candidates: number
  retained: number
  /** of the non-retained ones */
  excluded: number
  pending: number
}

export interface GraphModel {
  byId: Map<number, GraphNode>
  /** found paper → crawler → the directions that link them */
  linkedSeeds: Map<number, Map<number, Set<Direction>>>
  /** crawler → distinct papers its crawl found, per direction */
  found: Map<number, { backward: number[]; forward: number[] }>
  /** seeds + included papers (the ones the review kept) */
  retained: GraphNode[]
  /** rounds present in the graph, ascending */
  rounds: number[]
  /** retained paper → the retained crawlers of an earlier round that found it */
  parents: Map<number, number[]>
  children: Map<number, number[]>
  roundStats: Map<number, RoundStats>
  /** nodes drawn individually in the network: retained papers + crawlers */
  anchors: GraphNode[]
  /** non-anchor papers linked to two seeds or more */
  shared: GraphNode[]
  /** crawler → the non-anchor papers linked to that crawler only */
  clusters: Map<number, number[]>
  cites: Map<number, number>
  citedBy: Map<number, number>
  /** "Surname Year", made unique with a/b suffixes */
  labels: Map<number, string>
}

export const isRetained = (n: GraphNode) => n.status === 'seed' || n.status === 'included'

export const crawlerOf = (e: GraphEdge) => (e.direction === 'backward' ? e.citing : e.cited)
export const foundOf = (e: GraphEdge) => (e.direction === 'backward' ? e.cited : e.citing)

const RETAINED_FIRST: Record<Status, number> = { seed: 0, included: 1, pending: 2, excluded: 3 }

/** Family name of the first author, whatever the source format:
 * "Malone, Daniel F" → Malone, "Daniel F Malone" → Malone,
 * "Malone DF" → Malone (initials last), "" → "?". */
export function surname(author: string): string {
  const a = (author || '').trim()
  if (!a) return '?'
  if (a.includes(',')) return a.split(',')[0].trim() || '?'
  const parts = a.split(/\s+/)
  if (parts.length === 1) return parts[0]
  const last = parts[parts.length - 1]
  if (/^[A-Z][A-Z.-]{0,3}$/.test(last) && last.replace(/[.-]/g, '').length <= 3) return parts[0]
  return last
}

export function shortLabel(n: GraphNode): string {
  const s = surname(n.author)
  return n.year ? `${s} ${n.year}` : s
}

export function buildGraphModel(nodes: GraphNode[], edges: GraphEdge[]): GraphModel {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const linkedSeeds = new Map<number, Map<number, Set<Direction>>>()
  const found = new Map<number, { backward: number[]; forward: number[] }>()
  const foundSets = new Map<number, { backward: Set<number>; forward: Set<number> }>()
  const crawlers = new Set<number>()
  const cites = new Map<number, number>()
  const citedBy = new Map<number, number>()
  for (const e of edges) {
    if (!byId.has(e.citing) || !byId.has(e.cited)) continue
    cites.set(e.citing, (cites.get(e.citing) ?? 0) + 1)
    citedBy.set(e.cited, (citedBy.get(e.cited) ?? 0) + 1)
    const c = crawlerOf(e), f = foundOf(e)
    crawlers.add(c)
    let byCrawler = linkedSeeds.get(f)
    if (!byCrawler) linkedSeeds.set(f, (byCrawler = new Map()))
    let dirs = byCrawler.get(c)
    if (!dirs) byCrawler.set(c, (dirs = new Set()))
    dirs.add(e.direction)
    let fs = foundSets.get(c)
    if (!fs) foundSets.set(c, (fs = { backward: new Set(), forward: new Set() }))
    fs[e.direction].add(f)
  }
  for (const [c, fs] of foundSets)
    found.set(c, { backward: [...fs.backward], forward: [...fs.forward] })

  const retained = nodes.filter(isRetained)
  const rounds = [...new Set(nodes.map((n) => n.round || 1))].sort((a, b) => a - b)

  // lineage: only a crawler of an EARLIER round is a parent, so a later seed
  // that cites an early one (a "re-discovery" back-link) is not drawn upward
  const parents = new Map<number, number[]>()
  const children = new Map<number, number[]>()
  for (const n of retained) {
    const ps = [...(linkedSeeds.get(n.id)?.keys() ?? [])].filter((p) => {
      const pn = byId.get(p)
      return !!pn && isRetained(pn) && (pn.round || 1) < (n.round || 1)
    }).sort((a, b) => a - b)
    parents.set(n.id, ps)
    for (const p of ps) {
      const list = children.get(p) ?? []
      list.push(n.id)
      children.set(p, list)
    }
  }

  const roundStats = new Map<number, RoundStats>()
  for (const r of rounds)
    roundStats.set(r, { round: r, candidates: 0, retained: 0, excluded: 0, pending: 0 })
  for (const n of nodes) {
    const s = roundStats.get(n.round || 1)!
    s.candidates++
    if (isRetained(n)) s.retained++
    else if (n.status === 'excluded') s.excluded++
    else s.pending++
  }

  const anchorIds = new Set<number>([...retained.map((n) => n.id), ...crawlers])
  const anchors = nodes.filter((n) => anchorIds.has(n.id))
  const shared: GraphNode[] = []
  const clusters = new Map<number, number[]>()
  for (const n of nodes) {
    if (anchorIds.has(n.id)) continue
    const seeds = linkedSeeds.get(n.id)
    if (!seeds || seeds.size === 0) continue
    if (seeds.size >= 2) { shared.push(n); continue }
    const [only] = seeds.keys()
    const list = clusters.get(only) ?? []
    list.push(n.id)
    clusters.set(only, list)
  }
  // members: retained / to screen first, then by year (fan order)
  for (const list of clusters.values())
    list.sort((a, b) => {
      const na = byId.get(a)!, nb = byId.get(b)!
      return RETAINED_FIRST[na.status] - RETAINED_FIRST[nb.status]
        || (nb.year ?? 0) - (na.year ?? 0) || a - b
    })

  // a/b suffixes only among the papers drawn individually by default, so a
  // seed is not "Custalow 2004b" because of a hidden namesake
  const labels = new Map<number, string>()
  const byLabel = new Map<string, number[]>()
  const drawn = new Set<number>([...anchorIds, ...shared.map((n) => n.id)])
  for (const n of [...nodes].sort((a, b) => a.id - b.id)) {
    const l = shortLabel(n)
    if (!drawn.has(n.id)) { labels.set(n.id, l); continue }
    const list = byLabel.get(l) ?? []
    list.push(n.id)
    byLabel.set(l, list)
  }
  for (const [l, ids] of byLabel) {
    if (ids.length === 1 || !/\d$/.test(l)) { for (const id of ids) labels.set(id, l); continue }
    ids.forEach((id, i) => labels.set(id, l + (i < 26 ? String.fromCharCode(97 + i) : `-${i + 1}`)))
  }

  return { byId, linkedSeeds, found, retained, rounds, parents, children, roundStats,
           anchors, shared, clusters, cites, citedBy, labels }
}

/** A paper and every retained paper above (the seeds that led to it) and
 * below it (what its crawl led to). */
export function lineage(model: GraphModel, id: number): Set<number> {
  const out = new Set<number>([id])
  const walk = (from: number, next: Map<number, number[]>) => {
    for (const x of next.get(from) ?? []) if (!out.has(x)) { out.add(x); walk(x, next) }
  }
  walk(id, model.parents)
  walk(id, model.children)
  return out
}

export interface Filters {
  hiddenStatus: ReadonlySet<Status>
  hiddenDir: ReadonlySet<Direction>
  /** papers of a later round are hidden */
  maxRound: number
}

/** Status / direction / round filter. A paper found both ways disappears only
 * when both directions are hidden. */
export function isVisible(n: GraphNode, f: Filters): boolean {
  if (f.hiddenStatus.has(n.status)) return false
  if ((n.round || 1) > f.maxRound) return false
  if (n.origin === 'backward' && f.hiddenDir.has('backward')) return false
  if (n.origin === 'forward' && f.hiddenDir.has('forward')) return false
  if (n.origin === 'both' && f.hiddenDir.has('backward') && f.hiddenDir.has('forward')) return false
  return true
}

/** Neighbours in the network: a paper's linked crawlers, a crawler's finds. */
export function neighbours(model: GraphModel, id: number): Set<number> {
  const out = new Set<number>([id])
  for (const s of model.linkedSeeds.get(id)?.keys() ?? []) out.add(s)
  const f = model.found.get(id)
  if (f) for (const x of [...f.backward, ...f.forward]) out.add(x)
  return out
}

/** Non-retained papers of a round, the most-linked first. */
export function notRetainedOfRound(model: GraphModel, round: number): GraphNode[] {
  return [...model.byId.values()]
    .filter((n) => (n.round || 1) === round && !isRetained(n))
    .sort((a, b) => (model.linkedSeeds.get(b.id)?.size ?? 0) - (model.linkedSeeds.get(a.id)?.size ?? 0)
      || RETAINED_FIRST[a.status] - RETAINED_FIRST[b.status]
      || (b.year ?? 0) - (a.year ?? 0) || a.id - b.id)
}
