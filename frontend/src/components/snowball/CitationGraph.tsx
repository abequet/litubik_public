// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Segmented } from '@/components/ui/segmented'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useVizPalette } from '../results/palette'
import { copySvgAsPng, svgToPng, svgToSvgFile, type PrepareClone } from '../results/exportPng'
import { buildGraphModel, isRetained } from './graphModel'
import GenealogyView from './GenealogyView'
import FocusedNetwork from './FocusedNetwork'
import GraphDataTable from './GraphDataTable'
import { NodePopover } from './GraphOverlays'
import type { GraphEdge, GraphNode } from './types'

export type { GraphEdge, GraphNode } from './types'

type ViewMode = 'iterations' | 'network'

/** reveal the legend drawn for exports only */
const revealExportOnly: PrepareClone = (clone) => {
  clone.querySelectorAll('[data-export-only]').forEach((el) => el.removeAttribute('display'))
}

/** Citation network of the snowballing crawls, two SVG views:
 * - Iterations (default): the provenance of the retained papers, one column
 *   per round — what a systematic review reports and how saturation reads;
 * - Network: retained papers, the papers several seeds share, one folded
 *   cluster per seed for the rest.
 * Shared: search, paper popover (details / PDF / DOI), table view, PNG/SVG
 * export, fullscreen. */
export default function CitationGraph({ nodes, edges, height = 520, onOpenPdf, onOpenCard }: {
  nodes: GraphNode[]
  edges: GraphEdge[]
  height?: number
  onOpenPdf?: (node: GraphNode) => void
  onOpenCard?: (node: GraphNode) => void
}) {
  const { t } = useTranslation()
  const model = useMemo(() => buildGraphModel(nodes, edges), [nodes, edges])
  const palette = useVizPalette()
  const rootRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const [view, setView] = useState<ViewMode>('iterations')
  const [showTable, setShowTable] = useState(false)
  const [query, setQuery] = useState('')
  const [isFs, setIsFs] = useState(false)
  const [selected, setSelected] = useState<{ id: number; px: number; py: number } | null>(null)
  const [focus, setFocus] = useState<{ id: number; seq: number } | null>(null)

  useEffect(() => {
    const onChange = () => setIsFs(document.fullscreenElement === rootRef.current)
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [])
  const toggleFs = () => {
    if (document.fullscreenElement) void document.exitFullscreen()
    else void rootRef.current?.requestFullscreen()
  }

  const select = (id: number, clientX: number, clientY: number) => {
    const rect = bodyRef.current?.getBoundingClientRect()
    setSelected({ id, px: clientX - (rect?.left ?? 0), py: clientY - (rect?.top ?? 0) })
    setFocus(null)  // a search pick is consumed once (views remount on switch)
  }
  const switchView = (v: ViewMode) => { setSelected(null); setFocus(null); setView(v) }

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (q.length < 2) return []
    return nodes.filter((n) => n.title.toLowerCase().includes(q)
      || n.author.toLowerCase().includes(q)).slice(0, 6)
  }, [query, nodes])
  const pick = (id: number) => {
    setQuery('')
    setShowTable(false)
    setSelected(null)
    const n = model.byId.get(id)
    // a paper the review did not keep is only drawn in the network view
    if (view === 'iterations' && n && !isRetained(n)) setView('network')
    setFocus({ id, seq: Date.now() })
  }

  const chartSvg = () => bodyRef.current?.querySelector<SVGSVGElement>('svg[data-export]') ?? null
  const filename = view === 'iterations' ? 'snowballing-iterations' : 'snowballing-network'
  const exportPng = () => {
    const svg = chartSvg()
    if (svg) svgToPng(svg, `${filename}.png`, palette.card, 2, revealExportOnly)
  }
  const exportSvg = () => {
    const svg = chartSvg()
    if (svg) svgToSvgFile(svg, `${filename}.svg`, palette.card, revealExportOnly)
  }
  const copyImage = () => {
    const svg = chartSvg()
    if (svg) copySvgAsPng(svg, palette.card, 2, revealExportOnly).catch(() => undefined)
  }

  const sel = selected ? model.byId.get(selected.id) : undefined
  const viewProps = {
    model, palette, height, isFs, focus,
    selectedId: selected?.id ?? null,
    onSelect: select,
    onClearSelection: () => setSelected(null),
    onOpenCard,
  }
  return (
    <div ref={rootRef}
         className={isFs ? 'flex h-full flex-col overflow-hidden bg-background p-4' : ''}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Segmented
          value={view}
          onChange={switchView}
          options={[
            { value: 'iterations' as ViewMode, label: t('Iterations'),
              title: t('Retained papers per round and the seed that found each of them') },
            { value: 'network' as ViewMode, label: t('Network'),
              title: t('Retained papers, papers shared by several seeds, one cluster per seed for the rest') },
          ]}
        />
        <span className="flex-1" />
        <span className="relative">
          <Input value={query} onChange={(e) => setQuery(e.target.value)}
                 placeholder={t('Find a paper (title / author)…')}
                 className="h-8 w-56 text-xs" />
          {matches.length > 0 && (
            <ul className="absolute right-0 top-full z-50 mt-1 w-80 overflow-hidden rounded-md border border-border bg-popover shadow-lg">
              {matches.map((n) => (
                <li key={n.id}>
                  <button onClick={() => pick(n.id)}
                          className="block w-full px-3 py-1.5 text-left text-xs hover:bg-accent">
                    <span className="text-foreground">{n.title.slice(0, 60)}
                      {n.title.length > 60 ? '…' : ''}</span>
                    <span className="text-muted-foreground">
                      {' — '}{n.author}{n.year ? ` ${n.year}` : ''}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </span>
        <Button variant="outline" size="sm" aria-pressed={showTable}
                onClick={() => { setSelected(null); setShowTable((v) => !v) }}
                title={t('Show the papers of this network as a table')}>
          {showTable ? t('Graph') : t('Data')}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" disabled={showTable} title={t('Export this chart')}>
              ⤓ {t('Export')}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={exportPng}>{t('Download PNG')}</DropdownMenuItem>
            <DropdownMenuItem onClick={exportSvg}>{t('Download SVG')}</DropdownMenuItem>
            <DropdownMenuItem onClick={copyImage}>{t('Copy image')}</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Button variant="outline" size="sm" onClick={toggleFs}
                title={isFs ? t('Exit fullscreen (Esc)') : t('Fullscreen')}>
          {isFs ? t('🗗 Exit') : t('⛶ Fullscreen')}
        </Button>
      </div>

      <div ref={bodyRef} className={isFs ? 'relative flex min-h-0 flex-1 flex-col' : 'relative'}>
        {showTable ? (
          <GraphDataTable model={model} maxHeight={isFs ? undefined : height}
                          onOpenCard={onOpenCard} />
        ) : view === 'iterations' ? (
          <GenealogyView {...viewProps} />
        ) : (
          <FocusedNetwork {...viewProps} />
        )}
        {sel && selected && !showTable && (
          <NodePopover node={sel} px={selected.px} py={selected.py}
                       maxX={bodyRef.current?.clientWidth ?? 600}
                       maxY={bodyRef.current?.clientHeight ?? height}
                       onClose={() => setSelected(null)}
                       onOpenCard={onOpenCard} onOpenPdf={onOpenPdf} />
        )}
      </div>
    </div>
  )
}
