// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { CountryCount } from '@/api'
import { CHART_FONT, useVizPalette } from './palette'
import worldPaths from './world-paths.json'

/** Choropleth of studies per country: pre-projected Natural Earth 110m
 * outlines (static asset, no geo dependency), sequential single-hue fill
 * (opacity ramp of --viz-blue), zero-count countries in the neutral muted
 * surface. Micro-states absent from the 110m base map are covered by the
 * exact-count list next to the map. With `onSelect` each country is a
 * click-to-filter target; selected countries get an ink outline. */
export default function WorldMap({ counts, onSelect, selected = [],
                                   ariaLabel }: {
  counts: CountryCount[]
  /** click-to-filter: toggles this ISO3 in the country cross-filter */
  onSelect?: (iso3: string) => void
  selected?: string[]
  ariaLabel?: string
}) {
  const { t } = useTranslation()
  const palette = useVizPalette()
  const [hover, setHover] = useState<{ text: string; x: number; y: number } | null>(null)
  const byIso = new Map(counts.map((c) => [c.iso3, c]))
  const max = Math.max(1, ...counts.map((c) => c.n))
  const opacity = (n: number) => 0.25 + 0.75 * (n / max)
  const legendSteps = max === 1 ? [1] :
    [...new Set([1, Math.round(max / 3), Math.round((2 * max) / 3), max])]
  const selectedSet = new Set(selected)
  return (
    <div className="relative">
      <svg viewBox="0 0 960 520" className="w-full" role="img"
           aria-label={ariaLabel} fontFamily={CHART_FONT}
           onMouseLeave={() => setHover(null)}>
        {worldPaths.map((c, i) => {
          const hit = c.iso3 ? byIso.get(c.iso3) : undefined
          const name = hit?.name ?? c.name
          const n = hit?.n ?? 0
          return (
            <path
              key={c.iso3 ?? `x${i}`}
              d={c.d}
              fill={n > 0 ? palette.blue : palette.muted}
              fillOpacity={n > 0 ? opacity(n) : 1}
              stroke={palette.card}
              strokeWidth={0.6}
              style={{ cursor: onSelect && c.iso3 ? 'pointer' : undefined }}
              onClick={() => {
                if (onSelect && c.iso3) onSelect(c.iso3)
              }}
              onMouseMove={(e) => {
                const box = e.currentTarget.ownerSVGElement!.getBoundingClientRect()
                setHover({
                  text: `${name} — ${n} ${n === 1 ? t('study') : t('studies')}`,
                  x: e.clientX - box.left, y: e.clientY - box.top,
                })
              }}
            >
              <title>{`${name} — ${n} ${n === 1 ? t('study') : t('studies')}`}</title>
            </path>
          )
        })}
        {/* ink outline over the selected countries (drawn last so neighbours
            never overpaint it) */}
        {selectedSet.size > 0 && worldPaths
          .filter((c) => c.iso3 && selectedSet.has(c.iso3))
          .map((c) => (
            <path key={`sel-${c.iso3}`} d={c.d} fill="none"
                  stroke={palette.foreground} strokeWidth={1.2}
                  pointerEvents="none" />
          ))}
        {/* discrete opacity legend (in-SVG so the PNG keeps it) */}
        <g transform="translate(12, 495)">
          <text x={0} y={9} fontSize={10} fill={palette.mutedForeground}>
            {t('studies')}
          </text>
          {legendSteps.map((s, i) => (
            <g key={s} transform={`translate(${52 + i * 44}, 0)`}>
              <rect width={14} height={11} rx={2} fill={palette.blue}
                    fillOpacity={opacity(s)} />
              <text x={18} y={9} fontSize={10} fill={palette.mutedForeground}
                    style={{ fontVariantNumeric: 'tabular-nums' }}>
                {s}
              </text>
            </g>
          ))}
          <g transform={`translate(${52 + legendSteps.length * 44 + 12}, 0)`}>
            <rect width={14} height={11} rx={2} fill={palette.muted} />
            <text x={18} y={9} fontSize={10} fill={palette.mutedForeground}>
              0
            </text>
          </g>
        </g>
      </svg>
      {hover && (
        <div
          className="pointer-events-none absolute z-10 rounded-md border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-md"
          style={{ left: hover.x + 12, top: hover.y + 12 }}
        >
          {hover.text}
        </div>
      )}
    </div>
  )
}
