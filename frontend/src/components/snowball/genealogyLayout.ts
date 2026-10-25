// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import type { GraphModel, RoundStats } from './graphModel.ts'
import type { Direction } from './types.ts'

/** Geometry of the "Iterations" view: one column per round, the retained
 * papers as pills stacked without overlap, each placed level with the seeds
 * that found it, curves from a seed's crawl bar to what it led to. Pure: the
 * text width is measured by the caller (canvas in the browser, a stub in the
 * tests). */

export const PILL_H = 24
export const ROW_H = 34
const PAD_X = 10
const BAR_GAP = 6
const BAR_MAX = 56
const CURVE_GUTTER = 44
const LABEL_LEFT = 22
const LABEL_RIGHT = 10
const MIN_EMPTY_COL_W = 140

export interface SeedBar {
  x: number
  w: number
  /** backward share of w */
  wb: number
  nb: number
  nf: number
}

export interface PillGeom {
  id: number
  x: number
  y: number
  w: number
  label: string
  bar: SeedBar | null
  /** where the curves to its children start */
  port: [number, number]
}

export interface ColumnGeom {
  round: number
  x: number
  w: number
  stats: RoundStats
}

export interface CurveGeom {
  from: number
  to: number
  dir: Direction | 'both'
  d: string
}

export interface GenealogyLayout {
  width: number
  height: number
  columns: ColumnGeom[]
  pills: PillGeom[]
  curves: CurveGeom[]
  /** top of the pill area */
  bodyTop: number
  /** top of the per-column footers */
  footerTop: number
}

export interface GenealogyOptions {
  measure: (text: string) => number
  /** room the header texts of a round need */
  minColW?: (round: number) => number
  headerH?: number
  footerH?: number
}

/** Least-squares placement of ordered rows at their ideal y with a minimum
 * gap (pool-adjacent-violators on y_i − i·gap): no overlap, curves stay flat. */
export function packRows(ideal: number[], gap: number, top: number): number[] {
  const w = ideal.map((y, i) => y - i * gap)
  const vals: number[] = []
  const cnt: number[] = []
  for (const x of w) {
    vals.push(x); cnt.push(1)
    while (vals.length > 1 && vals[vals.length - 2] > vals[vals.length - 1]) {
      const c = cnt[cnt.length - 2] + cnt[cnt.length - 1]
      const v = (vals[vals.length - 2] * cnt[cnt.length - 2]
        + vals[vals.length - 1] * cnt[cnt.length - 1]) / c
      vals.splice(-2, 2, v)
      cnt.splice(-2, 2, c)
    }
  }
  const out: number[] = []
  vals.forEach((v, i) => { for (let k = 0; k < cnt[i]; k++) out.push(Math.max(top, v) + out.length * gap) })
  return out
}

export function genealogyLayout(model: GraphModel, opts: GenealogyOptions): GenealogyLayout {
  const headerH = opts.headerH ?? 64
  const footerH = opts.footerH ?? 58
  const bodyTop = headerH
  const maxLabel = Math.max(40, ...model.retained.map((n) => opts.measure(model.labels.get(n.id) ?? '')))
  const pillW = Math.min(150, Math.ceil(maxLabel) + LABEL_LEFT + LABEL_RIGHT)
  const pillColW = pillW + BAR_GAP + BAR_MAX + CURVE_GUTTER
  // a round that retained nothing only needs room for its header and footer
  const colW = (round: number) => Math.max(opts.minColW?.(round) ?? 0,
    model.roundStats.get(round)!.retained > 0 ? pillColW : MIN_EMPTY_COL_W)
  // a label too long for the pill loses letters of the name, never the year
  const room = pillW - LABEL_LEFT - LABEL_RIGHT
  const fitLabel = (label: string) => {
    if (opts.measure(label) <= room) return label
    const m = /^(.*?)( \d{4}[a-z]?)$/.exec(label)
    let head = m ? m[1] : label
    const tail = m ? m[2] : ''
    while (head.length > 2 && opts.measure(`${head}…${tail}`) > room) head = head.slice(0, -1)
    return `${head}…${tail}`
  }

  const maxCrawl = Math.max(1, ...model.retained.map((n) => {
    const f = model.found.get(n.id)
    return f ? f.backward.length + f.forward.length : 0
  }))

  let nextX = PAD_X
  const columns: ColumnGeom[] = model.rounds.map((round) => {
    const w = colW(round)
    const col = { round, x: nextX, w, stats: model.roundStats.get(round)! }
    nextX += w
    return col
  })
  const pills = new Map<number, PillGeom>()

  for (const col of columns) {
    const list = model.retained.filter((n) => (n.round || 1) === col.round)
    const ideal = new Map<number, number>()
    for (const n of list) {
      const ys = (model.parents.get(n.id) ?? []).map((p) => pills.get(p)?.y)
        .filter((y): y is number => y !== undefined)
      if (ys.length) ideal.set(n.id, ys.reduce((s, y) => s + y, 0) / ys.length)
    }
    // parentless papers (initial corpus, manual additions) go below, by year
    list.sort((a, b) => {
      const ia = ideal.get(a.id) ?? Infinity, ib = ideal.get(b.id) ?? Infinity
      return (ia === ib ? 0 : ia - ib) || (a.year ?? 0) - (b.year ?? 0)
        || (model.labels.get(a.id) ?? '').localeCompare(model.labels.get(b.id) ?? '')
    })
    const finite = list.map((n) => ideal.get(n.id)).filter((y): y is number => y !== undefined)
    let next = finite.length ? Math.max(...finite) + ROW_H : bodyTop
    const wanted = list.map((n) => {
      const y = ideal.get(n.id)
      if (y !== undefined) return y
      next += ROW_H
      return next - ROW_H
    })
    const ys = packRows(wanted, ROW_H, bodyTop)
    list.forEach((n, i) => {
      const x = col.x
      const y = ys[i]
      const f = model.found.get(n.id)
      const nb = f?.backward.length ?? 0, nf = f?.forward.length ?? 0
      let bar: SeedBar | null = null
      let port: [number, number] = [x + pillW, y + PILL_H / 2]
      if (nb + nf > 0) {
        const w = Math.max(3, BAR_MAX * Math.sqrt((nb + nf) / maxCrawl))
        bar = { x: x + pillW + BAR_GAP, w, wb: w * nb / (nb + nf), nb, nf }
        port = [bar.x + w + 3, y + 7.5]
      }
      pills.set(n.id, { id: n.id, x, y, w: pillW, label: fitLabel(model.labels.get(n.id) ?? ''),
                        bar, port })
    })
  }

  const curves: CurveGeom[] = []
  for (const [child, ps] of model.parents) {
    const c = pills.get(child)
    if (!c) continue
    for (const p of ps) {
      const s = pills.get(p)
      if (!s) continue
      const dirs = model.linkedSeeds.get(child)?.get(p)
      const dir: CurveGeom['dir'] = dirs && dirs.size > 1 ? 'both'
        : dirs?.has('forward') ? 'forward' : 'backward'
      const [sx, sy] = s.port
      const ex = c.x, ey = c.y + PILL_H / 2
      const dx = Math.max(24, (ex - sx) / 2)
      curves.push({ from: p, to: child, dir,
        d: `M${sx.toFixed(1)} ${sy.toFixed(1)} C${(sx + dx).toFixed(1)} ${sy.toFixed(1)} `
          + `${(ex - dx).toFixed(1)} ${ey.toFixed(1)} ${ex.toFixed(1)} ${ey.toFixed(1)}` })
    }
  }

  const bottom = Math.max(bodyTop + PILL_H, ...[...pills.values()].map((p) => p.y + PILL_H))
  const footerTop = bottom + 18
  const lastCol = columns[columns.length - 1]
  return {
    width: (lastCol ? lastCol.x + lastCol.w : PAD_X) + PAD_X,
    height: footerTop + footerH,
    columns, pills: [...pills.values()], curves, bodyTop, footerTop,
  }
}
