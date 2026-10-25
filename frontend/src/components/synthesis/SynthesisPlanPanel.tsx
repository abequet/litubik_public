// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  api, ApiError, type SynthesisCatalogue, type SynthesisPlanInfo,
} from '@/api'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'

const API = (pid: number) => `/api/projects/${pid}/synthesis`

/** The SWiM items that describe the synthesis as a whole (1a, 1b, 4, 5, 7, 9).
 *
 * Free text on purpose: SWiM is a *reporting* guideline and says so — it does
 * not prescribe how a synthesis is conducted, and a structured form here would
 * quietly become a method. */
const FIELDS: { key: keyof SynthesisPlanInfo; item: string; label: string
                help: string }[] = [
  { key: 'grouping_md', item: 'SWiM 1a', label: 'How studies were grouped',
    help: 'The groups used in the synthesis — of populations, interventions, outcomes, designs — and why those. In a review without meta-analysis the groups are less visible than in a forest plot, which is why they have to be stated.' },
  { key: 'grouping_changes_md', item: 'SWiM 1b',
    label: 'What changed since the protocol, and why',
    help: 'Groups often need revising once the data is in. Reporting the change and its reason is what lets a reader judge whether the findings drove it.' },
  { key: 'prioritisation_md', item: 'SWiM 4',
    label: 'Criteria used to prioritise studies',
    help: 'If some studies carried the synthesis and others did not — by design, by risk of bias, by directness — say which criteria decided that, and pre-specify them where you can.' },
  { key: 'heterogeneity_md', item: 'SWiM 5',
    label: 'How heterogeneity was examined',
    help: 'Ordering a table by a hypothesised modifier is a method too. Say which, and note it when the investigation was not pre-planned.' },
  { key: 'presentation_md', item: 'SWiM 7', label: 'How the data is presented',
    help: 'Tables, forest plots, harvest plots, effect-direction plots — and the study characteristics used to order them, which should match the order of the text.' },
  { key: 'limitations_md', item: 'SWiM 9',
    label: 'Limitations of the synthesis',
    help: 'What the chosen metric, the chosen method and any regrouping stop this synthesis from being able to conclude.' },
]

export default function SynthesisPlanPanel({ pid, isAdmin, catalogue }: {
  pid: number
  isAdmin: boolean
  catalogue: SynthesisCatalogue | undefined
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data } = useQuery<SynthesisPlanInfo>({
    queryKey: ['synthesis-plan', pid],
    queryFn: () => api.get(`${API(pid)}/plan`),
  })
  const [form, setForm] = useState<SynthesisPlanInfo | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { if (data) setForm(data) }, [data])

  const save = useMutation({
    mutationFn: (next: SynthesisPlanInfo) => api.put(`${API(pid)}/plan`, next),
    onSuccess: () => {
      setError('')
      queryClient.invalidateQueries({ queryKey: ['synthesis-plan', pid] })
      queryClient.invalidateQueries({ queryKey: ['synthesis-outcomes', pid] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('Save failed')),
  })

  if (!form) return <p className="text-sm text-muted-foreground">{t('Loading…')}</p>
  const patch = (p: Partial<SynthesisPlanInfo>) => setForm({ ...form, ...p })

  return (
    <div className="max-w-3xl space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-semibold text-foreground">
          {t('Declare the synthesis')}
        </h2>
        <p className="mt-1 mb-3 text-sm text-muted-foreground">
          {t('Off, the review says nothing about how it synthesised its evidence — which is what editorial triage flags most often. On, these fields become part of the Methods draft and the Results narrative, and the app stops attributing to you the synthesis method typical of your review type.')}
        </p>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t('Synthesis declaration')}
            </label>
            <Select value={form.enabled ? 'on' : 'off'} disabled={!isAdmin}
                    onValueChange={(v) => patch({ enabled: v === 'on' })}>
              <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="off">{t('Off — nothing declared')}</SelectItem>
                <SelectItem value="on">{t('On — the review states how it synthesised')}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t('Certainty framework')}
            </label>
            <Select value={form.certainty_framework} disabled={!isAdmin}
                    onValueChange={(v) => patch({ certainty_framework: v })}>
              <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
              <SelectContent>
                {(catalogue?.grade.frameworks ?? []).map((f) => (
                  <SelectItem key={f.key} value={f.key}>{t(f.label)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {form.certainty_framework === 'none' && (
          <p className="mt-2 text-xs text-muted-foreground">
            {t('Rating no certainty is a defensible choice, but an unexplained one reads as an omission — say why in the synthesis limitations below.')}
          </p>
        )}
        {data?.certainty_warning && (
          <p className="mt-2 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
            {data.certainty_warning}
          </p>
        )}

        {form.enabled && (
          <div className="mt-4 space-y-4">
            {FIELDS.map((f) => (
              <div key={f.key}>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">
                  <span className="mr-1.5 rounded bg-muted px-1 py-0.5 font-mono text-xs text-foreground">
                    {f.item}
                  </span>
                  {t(f.label)}
                </label>
                <Textarea rows={3} disabled={!isAdmin}
                          value={String(form[f.key] ?? '')}
                          onChange={(e) => patch({ [f.key]: e.target.value } as Partial<SynthesisPlanInfo>)} />
                <p className="mt-1 text-xs text-muted-foreground">{t(f.help)}</p>
              </div>
            ))}
          </div>
        )}

        {isAdmin && (
          <Button className="mt-4" size="sm" disabled={save.isPending}
                  onClick={() => save.mutate(form)}>
            {save.isPending ? t('Saving…') : t('Save changes')}
          </Button>
        )}
        {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
      </Card>
    </div>
  )
}
