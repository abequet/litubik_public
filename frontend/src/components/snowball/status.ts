// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import type { VizPalette } from '../results/palette'
import type { Status } from './types'

/** Status vocabulary shared by both snowballing views. */

export const STATUS_LABEL: Record<Status, string> = {
  seed: 'seed (crawled include)',
  included: 'included',
  excluded: 'excluded (hollow)',
  pending: 'to screen',
}

/** Short status word for tooltips and tables. */
export const STATUS_WORD: Record<Status, string> = {
  seed: 'seed', included: 'included', excluded: 'excluded', pending: 'to screen',
}

export const STATUS_ORDER: Status[] = ['seed', 'included', 'excluded', 'pending']

export function statusColor(p: VizPalette, s: Status): string {
  return s === 'seed' ? p.blue : s === 'included' ? p.teal
    : s === 'excluded' ? p.orange : p.mutedForeground
}

/** CSS-variable twin of statusColor for the HTML chips (theme-live). */
export const STATUS_VAR: Record<Status, string> = {
  seed: 'var(--viz-blue)', included: 'var(--viz-teal)',
  excluded: 'var(--viz-orange)', pending: 'var(--muted-foreground)',
}
