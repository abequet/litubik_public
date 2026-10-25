// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import type { GraphModel } from './graphModel'
import type { GraphNode, Status } from './types'
import { STATUS_VAR, STATUS_WORD } from './status'

/** Pieces both snowballing views share: status colours and labels, the hover
 * card and the click popover. Status is never colour-alone: excluded papers
 * are hollow, seeds carry a ring, and the tooltip spells the status. */

export function StatusDot({ status, className }: { status: Status; className?: string }) {
  return (
    <span aria-hidden
          className={cn('inline-block h-2.5 w-2.5 shrink-0 rounded-full',
                        status === 'excluded' && 'border-2 bg-card', className)}
          style={status === 'excluded'
            ? { borderColor: STATUS_VAR[status] }
            : { background: STATUS_VAR[status] }} />
  )
}

/** Hover card, fixed to the viewport next to the pointer. */
export function HoverCard({ x, y, children }: { x: number; y: number; children: React.ReactNode }) {
  return (
    <div className="pointer-events-none fixed z-40 max-w-xs rounded-md border border-border bg-popover px-3 py-2 text-xs shadow-lg"
         style={{ left: Math.max(8, Math.min(x + 12, window.innerWidth - 330)),
                  top: Math.min(y + 12, window.innerHeight - 140) }}>
      {children}
    </div>
  )
}

export function NodeTooltipBody({ node, model }: { node: GraphNode; model: GraphModel }) {
  const { t } = useTranslation()
  const seeds = model.linkedSeeds.get(node.id)
  const crawl = model.found.get(node.id)
  return (
    <>
      <p className="font-medium leading-snug text-foreground">{node.title}</p>
      <p className="mt-0.5 text-muted-foreground">
        {node.author}{node.year ? ` · ${node.year}` : ''}
        {' · '}{t(STATUS_WORD[node.status])}
        {node.reason ? ` (${node.reason.code} ${node.reason.label})` : ''}
      </p>
      <p className="text-muted-foreground">
        {crawl
          ? t('crawl: {{backward}} backward · {{forward}} forward',
              { backward: crawl.backward.length, forward: crawl.forward.length })
          : node.origin === 'both' ? t('reference + citing')
            : node.origin === 'forward' ? t('citing article (forward)')
              : t('reference (backward)')}
        {' · '}r{node.round || 1}
        {node.has_pdf ? ' · PDF ✓' : ''}
      </p>
      {seeds && seeds.size > 0 && (
        <p className="text-muted-foreground">
          {t('Linked to {{count}} seed(s): {{seeds}}', {
            count: seeds.size,
            seeds: [...seeds.keys()].slice(0, 6).map((s) => model.labels.get(s)).join(', ')
              + (seeds.size > 6 ? '…' : ''),
          })}
        </p>
      )}
    </>
  )
}

/** Action popover of a clicked paper: details card, PDF, DOI. */
export function NodePopover({ node, px, py, maxX, maxY, onClose, onOpenCard, onOpenPdf }: {
  node: GraphNode
  px: number
  py: number
  maxX: number
  maxY: number
  onClose: () => void
  onOpenCard?: (n: GraphNode) => void
  onOpenPdf?: (n: GraphNode) => void
}) {
  const { t } = useTranslation()
  return (
    <div className="absolute z-40 w-72 rounded-lg border border-border bg-popover p-3 text-xs shadow-xl"
         style={{ left: Math.max(4, Math.min(px + 10, maxX - 296)),
                  top: Math.max(4, Math.min(py + 10, maxY - 150)) }}>
      <div className="flex items-start justify-between gap-2">
        <p className="font-medium leading-snug text-foreground">{node.title}</p>
        <button onClick={onClose} aria-label={t('Close')}
                className="shrink-0 text-muted-foreground hover:text-foreground">×</button>
      </div>
      <p className="mt-0.5 text-muted-foreground">
        {node.author}{node.year ? ` · ${node.year}` : ''} · {t(STATUS_WORD[node.status])}
        {node.reason ? ` — ${node.reason.code} ${node.reason.label}` : ''}
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        {onOpenCard && (
          <Button variant="outline" size="sm"
                  onClick={() => { onOpenCard(node); onClose() }}
                  title={t('Metadata, screening outcomes and snowballing story')}>
            {t('ℹ Details')}
          </Button>
        )}
        {node.has_pdf && onOpenPdf && (
          <Button size="sm" onClick={() => { onOpenPdf(node); onClose() }}>
            {t('📄 Open PDF')}
          </Button>
        )}
        {node.doi && (
          <Button variant="outline" size="sm" asChild>
            <a href={`https://doi.org/${node.doi}`} target="_blank" rel="noreferrer">
              {t('DOI ↗ publisher')}
            </a>
          </Button>
        )}
        {!node.has_pdf && !node.doi && (
          <span className="italic text-muted-foreground">{t('No PDF stored, no DOI.')}</span>
        )}
      </div>
    </div>
  )
}
