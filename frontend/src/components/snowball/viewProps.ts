// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import type { VizPalette } from '../results/palette'
import type { GraphModel } from './graphModel'
import type { GraphNode } from './types'

/** What the shell hands to each snowballing view. */
export interface ViewProps {
  model: GraphModel
  palette: VizPalette
  /** card height outside fullscreen */
  height: number
  isFs: boolean
  selectedId: number | null
  /** search hit to reveal (seq changes on every pick) */
  focus: { id: number; seq: number } | null
  onSelect: (id: number, clientX: number, clientY: number) => void
  onClearSelection: () => void
  onOpenCard?: (n: GraphNode) => void
}
