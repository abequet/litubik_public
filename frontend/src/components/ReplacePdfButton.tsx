// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../api'
import { Button } from '@/components/ui/button'

/** "Replace PDF" / "Upload PDF" (tickets #T17/#23): (re-)upload a record's
 * full text from wherever the PDF is being read or listed — FT screening,
 * floating viewer, PDF library — instead of going back to the retrieval page.
 * Open to every project member: a reviewer who finds the file missing or
 * wrong mid-screening fixes it on the spot. On success every fulltext
 * listing is refreshed and the caller can reload its viewer. */
export default function ReplacePdfButton({ projectId, recordId, hasPdf = true,
                                           onReplaced }: {
  projectId: number
  recordId: number
  /** false → the button reads "Upload PDF" (nothing stored yet) */
  hasPdf?: boolean
  onReplaced?: () => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState('')

  const upload = async (file: File) => {
    setBusy(t('Uploading…'))
    const form = new FormData()
    form.append('file', file)
    try {
      const res = await fetch(
        `/api/projects/${projectId}/fulltext/records/${recordId}/upload`,
        { method: 'POST', credentials: 'include', body: form })
      if (!res.ok) throw new ApiError(res.status, (await res.json()).detail)
      queryClient.invalidateQueries({ queryKey: ['fulltext', projectId] })
      queryClient.invalidateQueries({ queryKey: ['fulltext-list', projectId] })
      queryClient.invalidateQueries({ queryKey: ['ftscreen-queue', projectId] })
      setBusy('')
      onReplaced?.()
    } catch (e) {
      setBusy(e instanceof ApiError ? `✗ ${e.message}` : t('✗ Upload failed'))
    }
  }

  return (
    <span className="inline-flex items-center gap-1.5">
      <input ref={inputRef} type="file" accept=".pdf,application/pdf"
             className="hidden"
             onChange={(e) => {
               const f = e.target.files?.[0]
               if (f) upload(f)
               e.target.value = ''
             }} />
      <Button variant="outline" size="sm" className="h-6 px-2 text-xs"
              title={hasPdf
                ? t('Replace the stored PDF (wrong or truncated file)')
                : t('Upload the PDF of this report from your computer')}
              onClick={() => inputRef.current?.click()}>
        {hasPdf ? t('Replace PDF') : t('Upload PDF')}
      </Button>
      {busy && (
        <span className="text-xs text-muted-foreground">{busy}</span>
      )}
    </span>
  )
}
