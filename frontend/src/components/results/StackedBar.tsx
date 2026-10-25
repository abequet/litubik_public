// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId } from 'react'
import { CHART_FONT, useVizPalette } from './palette'
import ChartTooltip, { useChartTooltip } from './ChartTooltip'

export interface StackedRow {
  label: string
  /** segment values in the fixed segment order passed to the chart */
  values: number[]
}

export interface StackedSegment {
  label: string
  color: string
  /** identity carried by shape, not color alone: 'hatch' = diagonal stripes
   * (unclear), 'hollow' = dashed outline, no fill (n/a) — both survive dark
   * theme, B&W print and every CVD type */
  pattern?: 'hatch' | 'hollow'
}

/** Horizontal 100% stacked bars (JBI yes/no/unclear/na per study). Fixed
 * segment order + 2px surface gaps + spelled-out tooltips keep identity
 * readable without relying on color alone; the legend is drawn inside the
 * SVG so the PNG export carries it. A thicker `pooled` row on top answers
 * the overall question before the per-study detail, and 0/25/50/75/100%
 * gridlines make mid-bar comparisons readable. */
export default function StackedBar({ rows, segments, pooled, width = 680,
                                     ariaLabel }: {
  rows: StackedRow[]
  segments: StackedSegment[]
  /** summary row (all studies pooled) drawn first, thicker */
  pooled?: StackedRow
  width?: number
  ariaLabel?: string
}) {
  const palette = useVizPalette()
  const { tip, move, hide } = useChartTooltip()
  // useId can contain ':' which breaks url(#…) references — strip it
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const hatchId = `${uid}-hatch`
  const FS = 11
  const labelW = 150
  const rowH = 22
  const barH = 14
  const legendH = 22
  const pooledBarH = 18
  const pooledH = pooled ? rowH + 8 : 0
  const axisH = 18
  const gap = 2 // surface gap between segments
  const plotW = width - labelW - 24
  const barsBottom = legendH + pooledH + rows.length * rowH
  const height = barsBottom + axisH + 2

  const segFill = (seg: StackedSegment) =>
    seg.pattern === 'hatch' ? `url(#${hatchId})`
      : seg.pattern === 'hollow' ? palette.card
      : seg.color

  const segmentRects = (row: StackedRow, y: number, h: number) => {
    const total = row.values.reduce((a, b) => a + b, 0) || 1
    let x = labelW
    return row.values.map((v, si) => {
      const seg = segments[si]
      const w = (v / total) * plotW
      const text = `${row.label} — ${seg.label}: ${v}/${total}` +
        ` (${Math.round((v / total) * 100)}%)`
      const node = (
        <g key={si} onMouseMove={(e) => move(e, text)} onMouseLeave={hide}>
          <title>{text}</title>
          {v > 0 && (
            <rect x={x} y={y} width={Math.max(w - gap, 1)} height={h}
                  rx={2} fill={segFill(seg)}
                  stroke={seg.pattern === 'hollow'
                    ? palette.mutedForeground : undefined}
                  strokeWidth={seg.pattern === 'hollow' ? 1 : undefined}
                  strokeDasharray={seg.pattern === 'hollow' ? '3 2' : undefined} />
          )}
        </g>
      )
      x += w
      return node
    })
  }

  const legendSwatch = (seg: StackedSegment) => (
    <rect width={10} height={10} rx={2} fill={segFill(seg)}
          stroke={seg.pattern === 'hollow' ? palette.mutedForeground : undefined}
          strokeWidth={seg.pattern === 'hollow' ? 1 : undefined}
          strokeDasharray={seg.pattern === 'hollow' ? '3 2' : undefined} />
  )

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full"
           role="img" aria-label={ariaLabel} fontFamily={CHART_FONT}>
        <defs>
          {/* diagonal stripes for 'unclear' — reads in dark theme and in B&W
              print, and serializes as-is into the PNG/SVG exports */}
          <pattern id={hatchId} patternUnits="userSpaceOnUse"
                   width={5} height={5} patternTransform="rotate(45)">
            <rect width={5} height={5} fill={palette.card} />
            <line x1={0} y1={0} x2={0} y2={5}
                  stroke={palette.mutedForeground} strokeWidth={2.2} />
          </pattern>
        </defs>
        {/* legend (in-SVG so exports keep it) */}
        {segments.map((s, i) => (
          <g key={s.label} transform={`translate(${labelW + i * 90}, 4)`}>
            {legendSwatch(s)}
            <text x={14} y={9} fontSize={FS - 1} fill={palette.mutedForeground}>
              {s.label}
            </text>
          </g>
        ))}
        {/* % gridlines behind the bars */}
        {[0, 0.25, 0.5, 0.75, 1].map((f) => {
          const x = labelW + f * plotW
          return (
            <g key={f}>
              <line x1={x} x2={x} y1={legendH + 2} y2={barsBottom}
                    stroke={palette.border} strokeWidth={1} />
              <text x={x} y={barsBottom + 12} textAnchor="middle"
                    fontSize={FS - 2} fill={palette.mutedForeground}
                    style={{ fontVariantNumeric: 'tabular-nums' }}>
                {Math.round(f * 100)}%
              </text>
            </g>
          )
        })}
        {pooled && (
          <g>
            <text x={labelW - 6} y={legendH + pooledBarH - 4} textAnchor="end"
                  fontSize={FS} fontWeight={600} fill={palette.foreground}>
              {pooled.label.length > 24
                ? pooled.label.slice(0, 23) + '…' : pooled.label}
            </text>
            {segmentRects(pooled, legendH + 2, pooledBarH)}
            <line x1={labelW} x2={labelW + plotW}
                  y1={legendH + pooledH - 3} y2={legendH + pooledH - 3}
                  stroke={palette.border} strokeWidth={1} />
          </g>
        )}
        {rows.map((row, ri) => {
          const y = legendH + pooledH + ri * rowH
          return (
            <g key={ri}>
              <text x={labelW - 6} y={y + barH - 3} textAnchor="end"
                    fontSize={FS} fill={palette.mutedForeground}>
                {row.label.length > 24 ? row.label.slice(0, 23) + '…' : row.label}
              </text>
              {segmentRects(row, y, barH)}
            </g>
          )
        })}
      </svg>
      <ChartTooltip tip={tip} />
    </div>
  )
}
