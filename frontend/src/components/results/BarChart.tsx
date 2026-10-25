// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useTranslation } from 'react-i18next'
import { CHART_FONT, useVizPalette } from './palette'
import ChartTooltip, { useChartTooltip } from './ChartTooltip'

export interface BarItem {
  label: string
  n: number
  /** unfiltered total drawn as a recessive ghost bar behind the value */
  total?: number
  /** hover text; defaults to `label — n` (or `label — n / total`) */
  title?: string
  /** the cross-filter currently keeps exactly this bar */
  active?: boolean
  /** stable identity handed back to onSelect; bars without a key are inert */
  key?: string
}

/** Median / IQR overlay for numeric histograms, as 0–1 fractions of the
 * plot width (the honest subset of a boxplot, drawn on the distribution). */
export interface HistogramMarkers {
  median01: number
  iqr01?: [number, number]
  label: string
}

const FS = 11

/** Bar with only the data-end rounded (anchored flat on the baseline). */
function roundedBar(x: number, y: number, w: number, h: number, r: number,
                    horizontal: boolean): string {
  if (h <= 0 || w <= 0) return ''
  const rr = Math.min(r, horizontal ? w / 2 : h / 2, horizontal ? h / 2 : w / 2)
  if (horizontal) {
    // baseline on the left, rounded right end
    return `M${x},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr}` +
      ` V${y + h - rr} Q${x + w},${y + h} ${x + w - rr},${y + h} H${x} Z`
  }
  // baseline at the bottom, rounded top end
  return `M${x},${y + h} V${y + rr} Q${x},${y} ${x + rr},${y}` +
    ` H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h} Z`
}

/** Single-series SVG bar chart (vertical for time axes, horizontal for ranked
 * categories). Concrete colors/fonts only, so ChartCard can export it.
 * When a cross-filter is active the unfiltered total shows as a grey ghost
 * behind each bar (the denominator never disappears), and `onSelect` makes
 * the bars themselves the filter surface. */
export default function BarChart({ items, color, horizontal = false,
                                   width = 680, maxBars = 30,
                                   onSelect, markers, ariaLabel }: {
  items: BarItem[]
  color?: string
  horizontal?: boolean
  width?: number
  maxBars?: number
  /** click-to-filter: called with the clicked item (needs item.key) */
  onSelect?: (item: BarItem) => void
  markers?: HistogramMarkers
  ariaLabel?: string
}) {
  const { t } = useTranslation()
  const palette = useVizPalette()
  const { tip, move, hide } = useChartTooltip()
  const fill = color ?? palette.blue
  let data = items
  if (items.length > maxBars) {
    const shown = items.slice(0, maxBars - 1)
    const rest = items.slice(maxBars - 1)
    data = [...shown, {
      label: t('Other ({{count}})', { count: rest.length }),
      n: rest.reduce((s, i) => s + i.n, 0),
      total: rest.some((i) => i.total !== undefined)
        ? rest.reduce((s, i) => s + (i.total ?? i.n), 0) : undefined,
      title: rest.map((i) => `${i.label} — ${i.n}`).join('\n'),
    }]
  }
  const max = Math.max(1, ...data.map((d) => Math.max(d.n, d.total ?? 0)))
  const hoverText = (d: BarItem) =>
    d.title ?? (d.total !== undefined && d.total !== d.n
      ? `${d.label} — ${d.n} / ${d.total}`
      : `${d.label} — ${d.n}`)
  const clickable = (d: BarItem) => onSelect !== undefined && d.key !== undefined
  const handleClick = (d: BarItem) => {
    if (clickable(d)) onSelect!(d)
  }

  if (horizontal) {
    const labelW = 150
    const valueW = 34
    const rowH = 22
    const barH = 14
    const height = data.length * rowH + 8
    const plotW = width - labelW - valueW - 8
    return (
      <div className="relative">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full"
             role="img" aria-label={ariaLabel} fontFamily={CHART_FONT}>
          {data.map((d, i) => {
            const y = 4 + i * rowH
            const w = (d.n / max) * plotW
            const wTotal = d.total !== undefined ? (d.total / max) * plotW : 0
            return (
              <g key={i}
                 style={{ cursor: clickable(d) ? 'pointer' : undefined }}
                 onClick={() => handleClick(d)}
                 onMouseMove={(e) => move(e, hoverText(d))}
                 onMouseLeave={hide}>
                <title>{hoverText(d)}</title>
                {/* full-row transparent hit area (small bars stay clickable) */}
                <rect x={0} y={y - 4} width={width} height={rowH}
                      fill="transparent" />
                <text x={labelW - 6} y={y + barH - 3} textAnchor="end"
                      fontSize={FS}
                      fontWeight={d.active ? 600 : undefined}
                      fill={d.active ? palette.foreground
                                     : palette.mutedForeground}>
                  {d.label.length > 24 ? d.label.slice(0, 23) + '…' : d.label}
                </text>
                {d.total !== undefined && d.total > d.n && (
                  <path d={roundedBar(labelW, y, Math.max(wTotal, 1), barH, 4, true)}
                        fill={palette.mutedForeground} fillOpacity={0.25} />
                )}
                <path d={roundedBar(labelW, y, Math.max(w, 1), barH, 4, true)}
                      fill={fill} />
                <text x={labelW + Math.max(w, wTotal, 1) + 5} y={y + barH - 3}
                      fontSize={FS} fill={palette.foreground}
                      style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {d.n}
                </text>
              </g>
            )
          })}
        </svg>
        <ChartTooltip tip={tip} />
      </div>
    )
  }

  const height = 220
  const padL = 30
  const padB = 32
  const padT = 16
  const plotW = width - padL - 8
  const plotH = height - padT - padB
  const step = plotW / data.length
  const barW = Math.min(40, step * 0.7)
  // ~4 recessive gridlines
  const ticks = [0.25, 0.5, 0.75, 1].map((f) => Math.round(max * f))
  const labelEvery = Math.ceil((data.length * 30) / plotW)
  // selective value labels: only the peak and the last non-empty bar carry
  // their count — the rest lives in the tooltip (no second row of noise)
  const peakIdx = data.findIndex((d) => d.n === Math.max(...data.map((x) => x.n)))
  let lastIdx = -1
  for (let i = data.length - 1; i >= 0; i--) {
    if (data[i].n > 0) { lastIdx = i; break }
  }
  const showValue = (i: number) =>
    data[i].n > 0 && (i === peakIdx || i === lastIdx)
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full"
           role="img" aria-label={ariaLabel} fontFamily={CHART_FONT}>
        {[...new Set(ticks)].map((t) => {
          const y = padT + plotH - (t / max) * plotH
          return (
            <g key={t}>
              <line x1={padL} x2={width - 8} y1={y} y2={y}
                    stroke={palette.border} strokeWidth={1} />
              <text x={padL - 5} y={y + 3.5} textAnchor="end" fontSize={FS - 1}
                    fill={palette.mutedForeground}
                    style={{ fontVariantNumeric: 'tabular-nums' }}>
                {t}
              </text>
            </g>
          )
        })}
        {/* IQR band behind the bars (median line comes on top of them) */}
        {markers?.iqr01 && (
          <rect x={padL + markers.iqr01[0] * plotW} y={padT}
                width={Math.max((markers.iqr01[1] - markers.iqr01[0]) * plotW, 1)}
                height={plotH}
                fill={palette.mutedForeground} fillOpacity={0.08} />
        )}
        <line x1={padL} x2={width - 8} y1={padT + plotH} y2={padT + plotH}
              stroke={palette.border} strokeWidth={1} />
        {data.map((d, i) => {
          const h = (d.n / max) * plotH
          const hTotal = d.total !== undefined ? (d.total / max) * plotH : 0
          const x = padL + i * step + (step - barW) / 2
          const y = padT + plotH - h
          return (
            <g key={i}
               style={{ cursor: clickable(d) ? 'pointer' : undefined }}
               onClick={() => handleClick(d)}
               onMouseMove={(e) => move(e, hoverText(d))}
               onMouseLeave={hide}>
              <title>{hoverText(d)}</title>
              {/* full-column transparent hit area */}
              <rect x={padL + i * step} y={padT} width={step} height={plotH + padB}
                    fill="transparent" />
              {d.total !== undefined && d.total > d.n && (
                <path d={roundedBar(x, padT + plotH - hTotal, barW, hTotal, 4, false)}
                      fill={palette.mutedForeground} fillOpacity={0.25} />
              )}
              {d.n > 0 && <path d={roundedBar(x, y, barW, h, 4, false)} fill={fill} />}
              {showValue(i) && (
                <text x={x + barW / 2}
                      y={padT + plotH - Math.max(h, hTotal) - 4}
                      textAnchor="middle"
                      fontSize={FS - 1} fill={palette.mutedForeground}
                      style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {d.n}
                </text>
              )}
              {i % labelEvery === 0 && (
                <text x={padL + i * step + step / 2} y={padT + plotH + 14}
                      textAnchor="middle" fontSize={FS - 1}
                      fontWeight={d.active ? 600 : undefined}
                      fill={d.active ? palette.foreground
                                     : palette.mutedForeground}>
                  {d.label}
                </text>
              )}
            </g>
          )
        })}
        {markers && (
          <g>
            <line x1={padL + markers.median01 * plotW}
                  x2={padL + markers.median01 * plotW}
                  y1={padT - 2} y2={padT + plotH}
                  stroke={palette.foreground} strokeWidth={1.2}
                  strokeDasharray="4 3" />
            <text x={padL + markers.median01 * plotW + 4} y={padT + 6}
                  fontSize={FS - 2} fill={palette.mutedForeground}>
              {markers.label}
            </text>
          </g>
        )}
      </svg>
      <ChartTooltip tip={tip} />
    </div>
  )
}
