// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { CHART_FONT } from '../results/palette'

/** Text width in px for the SVG layouts, measured on an offscreen canvas with
 * the chart font (cached); falls back to an average glyph width. */
let ctx: CanvasRenderingContext2D | null | undefined
const cache = new Map<string, number>()

export function measureText(text: string, size = 11, weight = 400): number {
  const key = `${weight}|${size}|${text}`
  const hit = cache.get(key)
  if (hit !== undefined) return hit
  if (ctx === undefined) ctx = document.createElement('canvas').getContext('2d')
  let w = text.length * size * 0.56
  if (ctx) {
    ctx.font = `${weight} ${size}px ${CHART_FONT}`
    w = ctx.measureText(text).width
  }
  cache.set(key, w)
  return w
}
