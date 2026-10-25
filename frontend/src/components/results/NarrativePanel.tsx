// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import { Sparkles } from 'lucide-react'
import { api, ApiError, type CostInfo, type NarrativeInfo } from '@/api'
import { Button } from '../ui/button'
import { Card, CardContent } from '../ui/card'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader,
  DialogTitle,
} from '../ui/dialog'

/** AI narrative synthesis tab: generate (with an up-front cost estimate on
 * hover), render the stored Markdown, regenerate behind a confirm dialog
 * (it overwrites the shared text and costs money). */
export default function NarrativePanel({ pid }: { pid: number }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const base = `/api/projects/${pid}/results/narrative`
  const [error, setError] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [wantEstimate, setWantEstimate] = useState(false)

  const { data, isLoading } = useQuery<{ narrative: NarrativeInfo | null }>({
    queryKey: ['results-narrative', pid],
    queryFn: () => api.get(base),
  })
  const { data: estimate } = useQuery<{ cost: CostInfo | null }>({
    queryKey: ['results-narrative-estimate', pid],
    queryFn: () => api.get(`${base}/estimate`),
    enabled: wantEstimate,
    staleTime: 60_000,
  })
  const generate = useMutation({
    mutationFn: () => api.post<{ narrative: NarrativeInfo }>(`${base}/generate`, {}),
    onSuccess: () => {
      setError('')
      queryClient.invalidateQueries({ queryKey: ['results-narrative', pid] })
      queryClient.invalidateQueries({ queryKey: ['project-progress', pid] })
    },
    onError: (e) =>
      setError(e instanceof ApiError ? e.message : t('Generation failed')),
  })

  if (isLoading) return <p className="text-muted-foreground">{t('Loading…')}</p>
  const narrative = data?.narrative ?? null
  const cost = estimate?.cost ?? null

  const generateButton = (label: string) => (
    <Button
      onClick={() => (narrative ? setConfirmOpen(true) : generate.mutate())}
      onMouseEnter={() => setWantEstimate(true)}
      disabled={generate.isPending}
      title={cost
        ? t('Estimated ≈ {{cost}} ({{model}})', { cost: cost.cost_label, model: cost.model })
        : t('Generate with the configured AI provider')}
      className="gap-1.5"
    >
      <Sparkles className="size-4" />
      {generate.isPending ? t('Generating…') : label}
      {cost && !generate.isPending && (
        <span className="text-xs opacity-70">≈{cost.cost_label}</span>
      )}
    </Button>
  )

  return (
    <div className="flex flex-col gap-3">
      {error && <p className="text-sm text-destructive">{error}</p>}

      {!narrative ? (
        <Card>
          <CardContent className="flex flex-col items-start gap-3 py-8">
            <p className="max-w-2xl text-sm text-muted-foreground">
              {t('The AI drafts a Results section (PRISMA 2020 style) from the computed aggregates and the consensus extraction table, grounded by the validated protocol. It is a draft to edit — the numbers it cites come from this page, and it never sees anything beyond your extraction data. Any team member can generate it; author and cost are recorded.')}
            </p>
            {generateButton(t('Generate narrative synthesis'))}
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">
              {t('AI-generated')} · {narrative.model || narrative.provider}
              {' · '}{narrative.cost.cost_label}
              {' · '}{new Date(narrative.created_at).toLocaleString()}
              {' · '}{t('by')} {narrative.generated_by_name}
            </p>
            <div className="flex gap-2">
              <Button variant="outline" size="sm"
                      onClick={() => navigator.clipboard.writeText(narrative.content_md)}>
                {t('Copy Markdown')}
              </Button>
              {generateButton(t('Regenerate'))}
            </div>
          </div>
          <Card>
            <CardContent className="prose prose-sm max-w-none text-sm text-foreground
                                    [&_h1]:text-xl [&_h1]:font-bold [&_h1]:mb-3
                                    [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:mt-5 [&_h2]:mb-2
                                    [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5
                                    [&_p]:my-2 [&_li]:my-0.5">
              <ReactMarkdown>{narrative.content_md}</ReactMarkdown>
            </CardContent>
          </Card>
        </>
      )}

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('Regenerate the narrative synthesis?')}</DialogTitle>
            <DialogDescription>
              {cost
                ? t('The current text will be overwritten for the whole team, and the call costs ≈ {{cost}}. Copy the Markdown first if you want to keep it.',
                    { cost: cost.cost_label })
                : t('The current text will be overwritten for the whole team, and the call costs money. Copy the Markdown first if you want to keep it.')}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              {t('Cancel')}
            </Button>
            <Button
              onClick={() => { setConfirmOpen(false); generate.mutate() }}
            >
              {t('Regenerate')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
