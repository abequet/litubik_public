// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'

/** Concrete color strings for SVG charts (SVG attributes exported to PNG
 * can't carry `var(...)`). Same live-token pattern as CitationGraph. */
export interface VizPalette {
  blue: string
  teal: string
  orange: string
  card: string
  border: string
  muted: string
  foreground: string
  mutedForeground: string
}

export function readVizPalette(): VizPalette {
  const s = getComputedStyle(document.documentElement)
  const g = (n: string, fallback: string) => s.getPropertyValue(n).trim() || fallback
  return {
    blue: g('--viz-blue', '#0072b2'),
    teal: g('--viz-teal', '#009e73'),
    orange: g('--viz-orange', '#d55e00'),
    card: g('--card', '#ffffff'),
    border: g('--border', '#e4e4e7'),
    muted: g('--muted', '#f4f4f5'),
    foreground: g('--foreground', '#18181b'),
    mutedForeground: g('--muted-foreground', '#71717a'),
  }
}

/** Live token palette, refreshed when the theme class flips. */
export function useVizPalette(): VizPalette {
  const [palette, setPalette] = useState(readVizPalette)
  useEffect(() => {
    const update = () => setPalette(readVizPalette())
    const obs = new MutationObserver(update)
    obs.observe(document.documentElement, {
      attributes: true, attributeFilter: ['class', 'data-theme', 'style'],
    })
    return () => obs.disconnect()
  }, [])
  return palette
}

export const CHART_FONT =
  'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'

/** Colour per cluster of the thematic map: Okabe–Ito (8, colour-blind
 * safe) extended with four further distinct hues; past twelve, hues cycle
 * and the legend's number keeps clusters apart. */
export const CLUSTER_COLORS = [
  '#0072b2', '#e69f00', '#009e73', '#d55e00', '#cc79a7', '#56b4e9',
  '#f0e442', '#000000', '#8c564b', '#7f7f7f', '#17becf', '#9467bd',
]

export const clusterColor = (id: number) => CLUSTER_COLORS[id % CLUSTER_COLORS.length]
