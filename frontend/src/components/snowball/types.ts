// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Payload of `GET /api/projects/{pid}/snowballing/graph` (see
 * `graph_data()` in backend/app/services/snowballing/service.py). */

export type Status = 'seed' | 'included' | 'excluded' | 'pending'
export type Direction = 'backward' | 'forward'

export interface GraphNode {
  id: number
  title: string
  doi: string | null
  year: number | null
  author: string
  status: Status
  /** how the paper was discovered (spelled out in the tooltip) */
  origin: 'seed' | 'backward' | 'forward' | 'both'
  /** corpus round: 1 = initial corpus, N = discovered by the round-N crawl */
  round: number
  has_pdf: boolean
  reason: { code: string; label: string } | null
  /** seed contribution counts (0 for non-seeds) */
  n_backward: number
  n_forward: number
}

export interface GraphEdge {
  citing: number
  cited: number
  direction: Direction
  round: number
}
