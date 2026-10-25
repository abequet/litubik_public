import type { GraphEdge, GraphNode, Status } from '../../src/components/snowball/types.ts'

/** Small snowballing history:
 * - r1: seeds S1 ("Malone, Daniel F") and S2 ("Ann B Duncliffe"), plus K, an
 *   initial-corpus paper S2's crawl finds again;
 * - r2 (crawl of S1, S2): S3 (seed later, found by S1 backward), A (shared,
 *   found by S1 and S2), B (only S1, forward), C (only S2), and a second
 *   "Duncliffe 2019" (D) shared too;
 * - r3 (crawl of S3): I4 (included, not crawled yet, found forward) and a
 *   back-link: S3's references include S1. */
export function node(id: number, status: Status, round: number, author: string,
                     year: number | null, origin: GraphNode['origin'] = 'backward'): GraphNode {
  return { id, title: `Paper ${id}`, doi: null, year, author, status, origin, round,
           has_pdf: false, reason: null, n_backward: 0, n_forward: 0 }
}

export const S1 = 1, S2 = 2, S3 = 3, I4 = 4, A = 5, B = 6, C = 7, K = 8, D = 9

export const nodes: GraphNode[] = [
  node(S1, 'seed', 1, 'Malone, Daniel F', 2024, 'both'),
  node(S2, 'seed', 1, 'Ann B Duncliffe', 2019, 'seed'),
  node(S3, 'seed', 2, 'Kahn CA', 2001),
  node(I4, 'included', 3, 'Koski Anssi', 2019, 'forward'),
  node(A, 'excluded', 2, 'Ray J', 2007),
  node(B, 'pending', 2, 'Bo Pei', 2025, 'forward'),
  node(C, 'excluded', 2, '', null),
  node(K, 'excluded', 1, 'NASA.', 2010),
  node(D, 'excluded', 2, 'Trevor Hines Duncliffe', 2019),
]

export const edges: GraphEdge[] = [
  { citing: S1, cited: S3, direction: 'backward', round: 2 },
  { citing: S1, cited: A, direction: 'backward', round: 2 },
  { citing: S2, cited: A, direction: 'backward', round: 2 },
  { citing: B, cited: S1, direction: 'forward', round: 2 },
  { citing: S2, cited: C, direction: 'backward', round: 2 },
  { citing: S2, cited: K, direction: 'backward', round: 2 },
  { citing: S1, cited: D, direction: 'backward', round: 2 },
  { citing: S2, cited: D, direction: 'backward', round: 2 },
  { citing: I4, cited: S3, direction: 'forward', round: 3 },
  { citing: S3, cited: S1, direction: 'backward', round: 3 },
]

/** A larger, seeded synthetic graph shaped like a real project: a few
 * seeds per round, hundreds of single-link finds, some shared ones. */
export function bigGraph(nSeeds = 15, perSeed = 110, rounds = 3) {
  let seed = 42
  const rand = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648 }
  const ns: GraphNode[] = []
  const es: GraphEdge[] = []
  const seedIds: number[] = []
  let id = 1
  for (let s = 0; s < nSeeds; s++) {
    const r = 1 + Math.floor((s * rounds) / nSeeds)
    ns.push(node(id, 'seed', r, `Author${s} X`, 2000 + s))
    seedIds.push(id++)
  }
  for (const sid of seedIds) {
    const r = ns[sid - 1].round + 1
    for (let k = 0; k < perSeed; k++) {
      const fid = id++
      const status: Status = rand() < 0.9 ? 'excluded' : 'pending'
      ns.push(node(fid, status, r, `Writer${fid} Y`, 1990 + Math.floor(rand() * 35)))
      const dir = rand() < 0.6 ? 'backward' : 'forward'
      es.push(dir === 'backward'
        ? { citing: sid, cited: fid, direction: 'backward', round: r }
        : { citing: fid, cited: sid, direction: 'forward', round: r })
      if (rand() < 0.1) {
        const other = seedIds[Math.floor(rand() * seedIds.length)]
        if (other !== sid) es.push({ citing: other, cited: fid, direction: 'backward', round: r })
      }
    }
  }
  return { nodes: ns, edges: es }
}
