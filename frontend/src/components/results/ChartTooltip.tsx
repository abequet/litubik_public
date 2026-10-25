// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'

export interface ChartTip {
  text: string
  x: number
  y: number
}

/** Instant HTML tooltip shared by every Results chart (same pattern WorldMap
 * pioneered): positioned on mousemove relative to the chart's wrapping
 * `relative` div, no hover delay, works on touch-tap. The native SVG <title>
 * stays underneath as the accessibility fallback. */
export function useChartTooltip() {
  const [tip, setTip] = useState<ChartTip | null>(null)
  const move = (e: React.MouseEvent<Element>, text: string) => {
    const svg = (e.currentTarget as Element).closest('svg')
    const host = svg?.parentElement
    if (!host) return
    const box = host.getBoundingClientRect()
    setTip({ text, x: e.clientX - box.left, y: e.clientY - box.top })
  }
  const hide = () => setTip(null)
  return { tip, move, hide }
}

export default function ChartTooltip({ tip }: { tip: ChartTip | null }) {
  if (!tip) return null
  return (
    <div
      className="pointer-events-none absolute z-10 whitespace-pre rounded-md border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-md"
      style={{ left: tip.x + 12, top: tip.y + 12 }}
    >
      {tip.text}
    </div>
  )
}
