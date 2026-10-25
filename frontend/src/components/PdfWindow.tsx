// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { createContext, useContext, useState, type ReactNode } from 'react'
import RecordPdfModal from './RecordPdfModal'

/** App-level floating PDF window: any page opens a record's PDF via
 * usePdfWindow() and the window survives navigation between pages
 * (it lives in the provider, not in the page that opened it). */

export interface PdfTarget {
  projectId: number
  recordId: number
  title: string
}

const PdfWindowContext = createContext<(target: PdfTarget) => void>(() => {})

export const usePdfWindow = () => useContext(PdfWindowContext)

export function PdfWindowProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<PdfTarget | null>(null)
  return (
    <PdfWindowContext.Provider value={setTarget}>
      {children}
      {target && (
        <RecordPdfModal
          key={`${target.projectId}:${target.recordId}`}
          projectId={target.projectId}
          recordId={target.recordId}
          title={target.title}
          onClose={() => setTarget(null)}
        />
      )}
    </PdfWindowContext.Provider>
  )
}
