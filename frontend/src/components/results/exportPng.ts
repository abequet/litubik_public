// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Chart exports (PNG download / SVG download / copy to clipboard). Works
 * because the charts carry concrete color/font attributes, never CSS classes
 * or `var(...)` — the serialized clone renders standalone. */

/** Optional last touch on the serialized clone (e.g. reveal a legend drawn
 * for exports only). */
export type PrepareClone = (clone: SVGSVGElement) => void

function standaloneSvg(svg: SVGSVGElement, background: string,
                       prepare?: PrepareClone) {
  const viewBox = svg.viewBox.baseVal
  const width = viewBox?.width || svg.clientWidth
  const height = viewBox?.height || svg.clientHeight
  const clone = svg.cloneNode(true) as SVGSVGElement
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  clone.setAttribute('width', String(width))
  clone.setAttribute('height', String(height))
  const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
  rect.setAttribute('width', '100%')
  rect.setAttribute('height', '100%')
  rect.setAttribute('fill', background)
  clone.insertBefore(rect, clone.firstChild)
  prepare?.(clone)
  return { markup: new XMLSerializer().serializeToString(clone), width, height }
}

function download(blob: Blob, filename: string) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}

/** Rasterize an inline SVG chart to a PNG blob (2x for publication). */
function svgToPngBlob(svg: SVGSVGElement, background: string,
                      scale = 2, prepare?: PrepareClone): Promise<Blob> {
  const { markup, width, height } = standaloneSvg(svg, background, prepare)
  const blob = new Blob([markup], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = Math.round(width * scale)
      canvas.height = Math.round(height * scale)
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        URL.revokeObjectURL(url)
        return reject(new Error('no 2d context'))
      }
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      URL.revokeObjectURL(url)
      canvas.toBlob((png) =>
        png ? resolve(png) : reject(new Error('toBlob failed')))
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('svg render failed'))
    }
    img.src = url
  })
}

/** Download an inline SVG chart as a PNG file. */
export function svgToPng(svg: SVGSVGElement, filename: string,
                         background: string, scale = 2,
                         prepare?: PrepareClone) {
  svgToPngBlob(svg, background, scale, prepare)
    .then((png) => download(png, filename))
    .catch(() => undefined)
}

/** Download an inline SVG chart as a standalone .svg file (vector — journals
 * increasingly ask for it). */
export function svgToSvgFile(svg: SVGSVGElement, filename: string,
                             background: string, prepare?: PrepareClone) {
  const { markup } = standaloneSvg(svg, background, prepare)
  download(new Blob([markup], { type: 'image/svg+xml;charset=utf-8' }),
           filename)
}

/** Copy an inline SVG chart to the clipboard as a PNG image. */
export function copySvgAsPng(svg: SVGSVGElement,
                             background: string, scale = 2,
                             prepare?: PrepareClone): Promise<void> {
  return svgToPngBlob(svg, background, scale, prepare).then((png) =>
    navigator.clipboard.write([new ClipboardItem({ 'image/png': png })]))
}
