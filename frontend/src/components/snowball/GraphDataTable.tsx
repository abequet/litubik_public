// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import type { GraphModel } from './graphModel'
import type { GraphNode, Status } from './types'
import { StatusDot } from './GraphOverlays'
import { STATUS_WORD } from './status'

const ORDER: Record<Status, number> = { seed: 0, included: 1, pending: 2, excluded: 3 }

/** Text alternative of both views (WCAG 1.1.1): every paper of the network,
 * retained first, then the most-linked; a title opens the paper card. */
export default function GraphDataTable({ model, maxHeight, onOpenCard }: {
  model: GraphModel
  maxHeight?: number
  onOpenCard?: (n: GraphNode) => void
}) {
  const { t } = useTranslation()
  const rows = useMemo(() => [...model.byId.values()].sort((a, b) =>
    (a.round || 1) - (b.round || 1) || ORDER[a.status] - ORDER[b.status]
    || (model.linkedSeeds.get(b.id)?.size ?? 0) - (model.linkedSeeds.get(a.id)?.size ?? 0)
    || a.id - b.id), [model])
  return (
    <div className="overflow-auto rounded-lg border border-border bg-card"
         style={maxHeight ? { maxHeight } : undefined}>
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-card text-left text-muted-foreground">
          <tr>
            <th className="px-2 py-1.5 font-medium">{t('Paper')}</th>
            <th className="px-2 py-1.5 font-medium">{t('Status')}</th>
            <th className="px-2 py-1.5 font-medium">{t('Round')}</th>
            <th className="px-2 py-1.5 text-right font-medium">{t('Linked seeds')}</th>
            <th className="px-2 py-1.5 text-right font-medium">{t('Cites')}</th>
            <th className="px-2 py-1.5 text-right font-medium">{t('Cited by')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((n) => (
            <tr key={n.id} className="border-t border-border align-top">
              <td className="px-2 py-1">
                {onOpenCard ? (
                  <button onClick={() => onOpenCard(n)}
                          className="text-left text-foreground hover:underline">
                    {n.title}
                  </button>
                ) : <span className="text-foreground">{n.title}</span>}
                <span className="block text-muted-foreground">
                  {n.author}{n.year ? ` · ${n.year}` : ''}
                </span>
              </td>
              <td className="whitespace-nowrap px-2 py-1">
                <span className="inline-flex items-center gap-1.5">
                  <StatusDot status={n.status} />{t(STATUS_WORD[n.status])}
                </span>
              </td>
              <td className="px-2 py-1 tabular-nums">r{n.round || 1}</td>
              <td className="px-2 py-1 text-right tabular-nums">
                {model.linkedSeeds.get(n.id)?.size ?? 0}
              </td>
              <td className="px-2 py-1 text-right tabular-nums">{model.cites.get(n.id) ?? 0}</td>
              <td className="px-2 py-1 text-right tabular-nums">{model.citedBy.get(n.id) ?? 0}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
