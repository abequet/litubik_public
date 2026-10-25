// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/card'
import { Button } from '../ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '../ui/dropdown-menu'
import { useVizPalette } from './palette'
import { copySvgAsPng, svgToPng, svgToSvgFile } from './exportPng'

export interface ChartTableRow {
  label: string
  value: string | number
}

/** Card wrapper every Results chart lives in: title, subtitle, n badge
 * (with the unfiltered denominator while a cross-filter is active), an
 * export menu (PNG / SVG / copy image / copy data) and an optional
 * "view the data" toggle that swaps the chart for the same aggregates as a
 * plain HTML table (screen readers + copy-paste into the manuscript). */
export default function ChartCard({ title, subtitle, n, nTotal, filename,
                                    tableData, children }: {
  title: string
  subtitle?: React.ReactNode
  n?: number
  /** unfiltered denominator, shown as `n=x / y` while filtering */
  nTotal?: number
  filename: string
  tableData?: ChartTableRow[]
  children: React.ReactNode
}) {
  const { t } = useTranslation()
  const bodyRef = useRef<HTMLDivElement>(null)
  const [showData, setShowData] = useState(false)
  const palette = useVizPalette()
  const chartSvg = () => bodyRef.current?.querySelector('svg')
  const exportPng = () => {
    const svg = chartSvg()
    if (svg) svgToPng(svg, filename, palette.card)
  }
  const exportSvg = () => {
    const svg = chartSvg()
    if (svg) svgToSvgFile(svg, filename.replace(/\.png$/, '.svg'), palette.card)
  }
  const copyImage = () => {
    const svg = chartSvg()
    if (svg) copySvgAsPng(svg, palette.card).catch(() => undefined)
  }
  const copyData = () => {
    if (!tableData) return
    const tsv = tableData.map((r) => `${r.label}\t${r.value}`).join('\n')
    navigator.clipboard.writeText(tsv).catch(() => undefined)
  }
  const filtered = nTotal !== undefined && n !== undefined && nTotal !== n
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-2">
        <div className="min-w-0">
          <CardTitle className="text-sm">
            {title}
            {n !== undefined && (
              <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-xs font-medium tabular-nums text-muted-foreground">
                {filtered ? <>n=<b className="text-foreground">{n}</b> / {nTotal}</> : <>n={n}</>}
              </span>
            )}
          </CardTitle>
          {subtitle && <CardDescription className="text-xs">{subtitle}</CardDescription>}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {tableData && tableData.length > 0 && (
            <Button variant="ghost" size="sm" aria-pressed={showData}
                    onClick={() => setShowData((v) => !v)}
                    className="text-xs text-muted-foreground"
                    title={t('Show the aggregated numbers behind this chart as a table')}>
              {showData ? t('Chart') : t('Data')}
            </Button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm"
                      className="text-xs text-muted-foreground"
                      title={t('Export this chart')}>
                ⤓ {t('Export')}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={exportPng}>{t('Download PNG')}</DropdownMenuItem>
              <DropdownMenuItem onClick={exportSvg}>{t('Download SVG')}</DropdownMenuItem>
              <DropdownMenuItem onClick={copyImage}>{t('Copy image')}</DropdownMenuItem>
              {tableData && tableData.length > 0 && (
                <DropdownMenuItem onClick={copyData}>{t('Copy data')}</DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </CardHeader>
      <CardContent ref={bodyRef} data-export-filename={filename}
                   className="pt-3">
        {/* chart stays mounted while the table shows, so the page-level
            "export all charts" sweep still finds its SVG */}
        <div className={showData ? 'hidden' : undefined}>{children}</div>
        {showData && tableData && (
          <div className="max-h-80 overflow-y-auto">
            <table className="w-full text-sm">
              <tbody>
                {tableData.map((r, i) => (
                  <tr key={i} className="border-b border-border last:border-0">
                    <td className="py-1 pr-2">{r.label}</td>
                    <td className="py-1 text-right font-medium tabular-nums">
                      {r.value}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
