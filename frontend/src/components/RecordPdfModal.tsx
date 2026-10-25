// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Annotation } from '../api'
import PdfViewer, { type NewAnnotation } from './PdfViewer'
import ReplacePdfButton from './ReplacePdfButton'

/** Floating window showing a record's stored PDF with the shared highlight
 * annotations. Draggable by its title bar, resizable by the corner handle,
 * no backdrop — the page behind stays usable, and mounted through
 * PdfWindowProvider it survives navigating between project pages. */
export default function RecordPdfModal({ projectId, recordId, title, onClose }: {
  projectId: number
  recordId: number
  title: string
  onClose: () => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const base = `/api/projects/${projectId}/records/${recordId}/annotations`
  const { data: annotations = [] } = useQuery<Annotation[]>({
    queryKey: ['annotations', projectId, recordId],
    queryFn: () => api.get(base),
  })
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['annotations', projectId, recordId] })
  const create = useMutation({
    mutationFn: (a: NewAnnotation) => api.post(base, a),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.del(`${base}/${id}`),
    onSuccess: invalidate,
  })

  // bumped when the PDF is replaced so the viewer reloads the new file
  const [pdfVersion, setPdfVersion] = useState(0)

  const [box, setBox] = useState(() => {
    const w = Math.min(880, window.innerWidth - 48)
    const h = Math.min(Math.max(480, window.innerHeight - 96), window.innerHeight - 24)
    return { x: Math.max((window.innerWidth - w) / 2, 12), y: 48, w, h }
  })

  const startDrag = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest('button')) return
    e.preventDefault()
    const offX = e.clientX - box.x
    const offY = e.clientY - box.y
    const move = (ev: PointerEvent) => setBox((b) => ({
      ...b,
      x: Math.min(Math.max(ev.clientX - offX, 80 - b.w), window.innerWidth - 80),
      y: Math.min(Math.max(ev.clientY - offY, 0), window.innerHeight - 48),
    }))
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  const startResize = (e: React.PointerEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const startW = box.w, startH = box.h
    const fromX = e.clientX, fromY = e.clientY
    const move = (ev: PointerEvent) => setBox((b) => ({
      ...b,
      w: Math.max(360, startW + ev.clientX - fromX),
      h: Math.max(280, startH + ev.clientY - fromY),
    }))
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  return (
    <div className="fixed z-50 bg-popover rounded-xl shadow-2xl border border-border flex flex-col overflow-hidden"
         style={{ left: box.x, top: box.y, width: box.w, height: box.h,
                  maxWidth: 'calc(100vw - 8px)', maxHeight: 'calc(100vh - 8px)' }}>
      <div onPointerDown={startDrag}
           title={t('Drag to move')}
           className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-muted cursor-move select-none touch-none">
        <p className="text-sm font-medium text-foreground truncate pr-4">{title}</p>
        <div className="flex shrink-0 items-center gap-2">
          <ReplacePdfButton projectId={projectId} recordId={recordId}
                            onReplaced={() => setPdfVersion((v) => v + 1)} />
          <button onClick={onClose} title={t('Close')}
                  className="text-muted-foreground hover:text-foreground text-lg">×</button>
        </div>
      </div>
      <div className="flex-1 p-2 min-h-0 min-w-0">
        <PdfViewer
          fileUrl={`/api/projects/${projectId}/fulltext/records/${recordId}/file`
            + (pdfVersion ? `?v=${pdfVersion}` : '')}
          annotations={annotations}
          onCreate={(a) => create.mutate(a)}
          onDelete={(id) => remove.mutate(id)} />
      </div>
      <div onPointerDown={startResize}
           title={t('Drag to resize')}
           className="absolute bottom-0 right-0 h-5 w-5 cursor-nwse-resize touch-none text-muted-foreground/50 hover:text-muted-foreground">
        <svg viewBox="0 0 20 20" className="h-full w-full" fill="currentColor">
          <path d="M18 18h-2v-2h2v2zm0-5h-2v-2h2v2zm-5 5h-2v-2h2v2z" />
        </svg>
      </div>
    </div>
  )
}
