// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import { api, type ReportKind, type ReportSectionInfo } from '@/api'
import { Button } from '../ui/button'
import { Card, CardContent } from '../ui/card'
import { Textarea } from '../ui/textarea'

/** The generated text and the author's version, side by side.
 *
 * Both are kept: the generated one is what the audit trail said at that
 * moment, the edited one is what the authors put their name to. Regenerating
 * never overwrites the edited text — that is the version they can defend. */
export default function SectionOutput({
  pid, kind, section,
}: { pid: number; kind: ReportKind; section: ReportSectionInfo }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState(section.edited_md || section.content_md)
  const [saved, setSaved] = useState(false)

  // a regeneration replaces the reference text; refresh the editor only when
  // the author has not started from the generated one yet
  useEffect(() => {
    setDraft(section.edited_md || section.content_md)
    setSaved(false)
  }, [section.content_md, section.edited_md])

  const save = useMutation({
    mutationFn: () =>
      api.put<ReportSectionInfo>(`/api/projects/${pid}/reporting/${kind}`,
                                 { edited_md: draft }),
    onSuccess: () => {
      setSaved(true)
      queryClient.invalidateQueries({ queryKey: ['reporting-sections', pid] })
      queryClient.invalidateQueries({ queryKey: ['project-progress', pid] })
    },
  })

  const dirty = draft !== (section.edited_md || section.content_md)

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-foreground">
            {t('Generated text')}
          </h3>
          <div className="flex items-center gap-2">
            <p className="text-xs text-muted-foreground">
              {section.cost.model || section.cost.provider}
              {' · '}{section.cost.cost_label}
              {' · '}{new Date(section.created_at).toLocaleString()}
              {' · '}{t('by')} {section.generated_by_name}
            </p>
            <Button variant="outline" size="sm"
                    onClick={() => navigator.clipboard.writeText(section.content_md)}>
              {t('Copy')}
            </Button>
          </div>
        </div>
        <Card>
          <CardContent className="prose prose-sm max-w-none text-sm text-foreground
                                  [&_h2]:text-base [&_h2]:font-semibold [&_h2]:mt-4 [&_h2]:mb-1.5
                                  [&_p]:my-2 [&_li]:my-0.5
                                  [&_ul]:list-disc [&_ul]:pl-5">
            <ReactMarkdown>{section.content_md}</ReactMarkdown>
          </CardContent>
        </Card>
      </div>

      <div>
        <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-foreground">
            {t('Your version')}
          </h3>
          <div className="flex items-center gap-2">
            {saved && !dirty && (
              <span className="text-xs text-success">{t('Saved')}</span>
            )}
            <Button variant="outline" size="sm"
                    onClick={() => navigator.clipboard.writeText(draft)}>
              {t('Copy')}
            </Button>
            <Button size="sm" disabled={!dirty || save.isPending}
                    onClick={() => save.mutate()}>
              {save.isPending ? t('Saving…') : t('Save my version')}
            </Button>
          </div>
        </div>
        <Textarea value={draft} rows={14}
                  onChange={(e) => { setDraft(e.target.value); setSaved(false) }}
                  className="font-mono text-xs leading-relaxed" />
        <p className="mt-1.5 text-xs text-muted-foreground">
          {t('This is the text you paste into the manuscript. Regenerating replaces the text above, never this one.')}
        </p>
      </div>
    </div>
  )
}
